"""Curriculum ingestion: extract -> clean -> segment -> store -> index.

Supported inputs: PDF (text layer, one page per PDF page) and UTF-8 text /
Markdown where pages are separated by form feeds or lines like
"=== PAGE 12 ===". Chapter headings ("## ...", "Chapter 3 ...",
"अध्याय 3 ...") are tracked so every chunk carries class, subject, chapter,
page, language, curriculum version and source document.

Only authorised material may be ingested; the document's publisher and
approval status are recorded and shown in every citation.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CurriculumChunk, CurriculumDocument, Subject

PAGE_MARK = re.compile(r"^\s*=+\s*PAGE\s+(\d+)\s*=+\s*$", re.I | re.M)
CHAPTER_RE = re.compile(r"^\s*(?:#{1,3}\s+(.+)|((?:chapter|unit|lesson|अध्याय|पाठ|इकाई)\s*[-–.:]?\s*[\d०-९]+.*))$", re.I)
MIN_DEVANAGARI_SHARE = 0.6  # a converted legacy-font Hindi document below this is rejected
TARGET_WORDS, MAX_WORDS = 120, 200


@dataclass
class DocMeta:
    title: str
    doc_type: str
    subject_code: str | None
    grade: int | None
    language: str
    curriculum_version: str
    publisher: str
    approval_status: str = "approved"
    is_demo: bool = False
    legacy_font: str | None = None  # "krutidev" for Kruti Dev / DevLys Hindi PDFs


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("­", "").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line breaks
    return re.sub(r"\n{3,}", "\n\n", text).strip()


EXTRACTOR_VERSION = "3"  # bump when PDF extraction changes, to invalidate cached pages


def _page_cache(path: Path, legacy_font: str | None) -> Path:
    from app.config import get_settings

    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    d = Path(get_settings().kb_dir) / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{digest}-{legacy_font or 'plain'}-v{EXTRACTOR_VERSION}.json"


def read_pages(path: Path, legacy_font: str | None = None) -> list[tuple[int, str]]:
    """Page texts of a document. PDF extraction (slow for legacy fonts) is cached
    per file content, so re-ingesting or rebuilding a database is fast."""
    if path.suffix.lower() == ".pdf":
        cache = _page_cache(path, legacy_font)
        if cache.exists():
            return [tuple(p) for p in json.loads(cache.read_text(encoding="utf-8"))]
        pages = _read_pdf(path, legacy_font)
        cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        return pages
    raw = path.read_text(encoding="utf-8-sig")
    if PAGE_MARK.search(raw):
        parts = PAGE_MARK.split(raw)
        # split -> [pre, num, text, num, text, ...]
        return [(int(parts[i]), clean(parts[i + 1])) for i in range(1, len(parts) - 1, 2)]
    return [(i + 1, clean(p)) for i, p in enumerate(raw.split("\f"))]


def warm_page_cache(items: list[tuple[Path, str | None]], workers: int = 4) -> None:
    """Extract several PDFs in parallel processes (fills the page cache)."""
    from concurrent.futures import ProcessPoolExecutor

    todo = [(p, lf) for p, lf in items if p.suffix.lower() == ".pdf" and not _page_cache(p, lf).exists()]
    if not todo:
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_warm_one, todo))


def _warm_one(item: tuple[Path, str | None]) -> None:
    read_pages(*item)


def _read_pdf(path: Path, legacy_font: str | None) -> list[tuple[int, str]]:
    import pdfplumber

    from app.kb.legacy_fonts import pdf_page_text

    if legacy_font not in (None, "krutidev"):
        raise ValueError(f"Unsupported legacy font {legacy_font!r}")
    with pdfplumber.open(path) as pdf:
        pages = []
        for i, p in enumerate(pdf.pages):
            p = p.dedupe_chars()  # "fake bold" headings draw every glyph several times
            pages.append((i + 1, clean(pdf_page_text(p) if legacy_font else (p.extract_text() or ""))))
        return pages


SENTENCE_END = re.compile(r"[.?!।|]['\"’”)]*\s*$")
BARE_CHAPTER = re.compile(r"(?:chapter|unit|lesson|अध्याय|पाठ|इकाई)\s*[-–.:]?\s*[\d०-९]+\s*[-–.:]?", re.I)


def segment(pages: list[tuple[int, str]]) -> list[dict]:
    """Chunks of ~120 words (max 200) that never cross a page. They break at
    paragraph gaps or sentence ends; chapter headings are detected on any line
    (textbook PDFs often have no blank lines between paragraphs)."""
    chunks, chapter = [], None
    for page_no, text in pages:
        buf: list[str] = []
        words = 0
        expect_title = False
        top = [l.strip() for l in text.split("\n") if l.strip()][:2]
        # Chapter opening page: a bare chapter number, then an upper-case title ("3" / "AIR").
        if len(top) == 2 and re.fullmatch(r"\d{1,2}", top[0]) and top[1].isupper() and len(top[1]) > 2:
            chapter = f"{top[0]}. {top[1].title()}"[:200]
            text = text.replace(top[0], "", 1).replace(top[1], "", 1)

        def flush():
            nonlocal words
            if buf:
                body = "\n".join(buf).strip()
                if len(body.split()) >= 5:
                    chunks.append({"page": page_no, "chapter": chapter, "text": body})
                buf.clear()
            words = 0

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                if words >= TARGET_WORDS:
                    flush()
                continue
            m = CHAPTER_RE.match(line)
            if m:
                flush()
                chapter = (m.group(1) or m.group(2)).strip()[:200]
                # "CHAPTER- 1" alone on its line: the title is on the next line
                expect_title = bool(m.group(2)) and bool(BARE_CHAPTER.fullmatch(chapter))
                continue
            if expect_title:
                expect_title = False
                if len(line.split()) <= 12:
                    chapter = f"{chapter}: {line}"[:200]
                    continue
            n = len(line.split())
            if words + n > MAX_WORDS:
                flush()
            buf.append(line)
            words += n
            if words >= TARGET_WORDS and SENTENCE_END.search(line):
                flush()
        flush()
    if chunks and sum(c["chapter"] is None for c in chunks) > 0.9 * len(chunks):
        _chapters_from_running_headers(pages, chunks)
    return chunks


def _chapters_from_running_headers(pages: list[tuple[int, str]], chunks: list[dict]) -> None:
    """Fallback for books without "Chapter N" headings: textbooks print the
    chapter name at the top of (odd) pages and the book title on the others.
    A first line repeated on several pages, other than the most common one,
    is taken as the chapter name."""
    from collections import Counter

    def head(text: str) -> str | None:
        for line in text.split("\n"):
            line = re.sub(r"^\d{1,3}\s+|\s+\d{1,3}$", "", line.strip()).strip()
            if line:
                return line if 2 <= len(line.split()) <= 10 or len(line) >= 4 else None
        return None

    heads = {no: head(t) for no, t in pages}
    counts = Counter(h for h in heads.values() if h)
    if not counts:
        return
    book_title = counts.most_common(1)[0][0]
    current, by_page = None, {}
    for no, _ in pages:
        h = heads[no]
        if h and h != book_title and counts[h] >= 2:
            current = h[:200]
        by_page[no] = current
    for c in chunks:
        c["chapter"] = c["chapter"] or by_page.get(c["page"])


def ingest_file(db: Session, path: Path, meta: DocMeta, *, approved_by: int | None = None) -> tuple[CurriculumDocument, bool]:
    """Returns (document, created). Identical files (same checksum) are skipped."""
    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(CurriculumDocument).where(CurriculumDocument.checksum == checksum))
    if existing is not None:
        return existing, False
    subject = None
    if meta.subject_code:
        subject = db.scalar(select(Subject).where(Subject.code == meta.subject_code))
        if subject is None:
            raise ValueError(f"Unknown subject code {meta.subject_code}")
    pages = read_pages(path, meta.legacy_font)
    if meta.legacy_font:
        from app.kb.legacy_fonts import devanagari_share

        share = devanagari_share(" ".join(t for _, t in pages))
        if share < MIN_DEVANAGARI_SHARE:
            raise ValueError(f"{path.name}: legacy-font conversion produced only {share:.0%} Devanagari text; "
                             "check the font or use a Unicode edition")
    doc = CurriculumDocument(title=meta.title, doc_type=meta.doc_type, subject_id=subject.id if subject else None,
                             grade=meta.grade, language=meta.language, curriculum_version=meta.curriculum_version,
                             publisher=meta.publisher, source_file=path.name, checksum=checksum,
                             approval_status=meta.approval_status, approved_by=approved_by, pages=len(pages),
                             is_demo=meta.is_demo)
    db.add(doc)
    db.flush()
    for seq, c in enumerate(segment(pages)):
        db.add(CurriculumChunk(document_id=doc.id, seq=seq, text=c["text"], page=c["page"], chapter=c["chapter"],
                               grade=meta.grade, subject_id=doc.subject_id, language=meta.language))
    db.flush()
    return doc, True


def ingest_manifest(db: Session, manifest_path: Path, *, approved_by: int | None = None,
                    workers: int = 1) -> list[dict]:
    """Manifest JSON: {"documents": [{"file": ..., "title": ..., "doc_type": ..., "subject": "MATH",
    "grade": 5, "language": "hi", "curriculum_version": ..., "publisher": ..., "is_demo": false}]}"""
    spec = json.loads(manifest_path.read_text(encoding="utf-8"))
    if workers > 1:
        warm_page_cache([(manifest_path.parent / d["file"], d.get("legacy_font")) for d in spec["documents"]
                         if (manifest_path.parent / d["file"]).exists()], workers)
    out = []
    for d in spec["documents"]:
        meta = DocMeta(title=d["title"], doc_type=d.get("doc_type", "textbook"), subject_code=d.get("subject"),
                       grade=d.get("grade"), language=d.get("language", "hi"),
                       curriculum_version=d["curriculum_version"], publisher=d["publisher"],
                       approval_status=d.get("approval_status", "approved"), is_demo=bool(d.get("is_demo")),
                       legacy_font=d.get("legacy_font"))
        doc, created = ingest_file(db, manifest_path.parent / d["file"], meta, approved_by=approved_by)
        out.append({"title": doc.title, "document_id": doc.id, "created": created})
    return out
