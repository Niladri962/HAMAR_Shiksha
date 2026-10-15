"""Add the downloaded Hindi-medium SCERT Chhattisgarh books (classes 1-8) to
data/scert_cg/manifest.json.

Reads data/scert_cg/books_hi_medium.tsv (grade, subject, file, source name),
checks each PDF opens and has a text layer, detects Kruti Dev encoding, and
records the SHA-256 so scripts/fetch_scert_cg.py can verify later downloads.

    python scripts/add_scert_books.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.kb.legacy_fonts import devanagari_share  # noqa: E402

DIR = ROOT / "data" / "scert_cg"
BASE = "https://scert.cg.gov.in/pdf/textbook-2024-25/"
SUBJECT_HI = {"HIN": "हिंदी", "ENG": "English", "MATH": "गणित", "EVS": "पर्यावरण अध्ययन", "SCI": "विज्ञान एवं प्रौद्योगिकी",
              "SST": "सामाजिक विज्ञान", "SAN": "संस्कृत"}
SPECIAL = {"hindi-cg": "हिंदी-छत्तीसगढ़ी", "bhugol": "सामाजिक विज्ञान (भूगोल)",
           "itihas": "सामाजिक विज्ञान (इतिहास व नागरिक शास्त्र)", "sahayak-vachan": "हिंदी सहायक वाचन"}


def sample_text(path: Path) -> tuple[str, int]:
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        if n == 0:
            raise ValueError("no pages (truncated download)")
        idx = range(min(8, n), min(n, 28))
        return " ".join((pdf.pages[i].extract_text() or "") for i in idx), n


def converts(path: Path) -> bool:
    """True if Kruti Dev conversion of sample pages yields mostly Devanagari text."""
    from app.kb.legacy_fonts import pdf_page_text

    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        text = " ".join(pdf_page_text(pdf.pages[i]) for i in range(min(8, n), min(n, 16)))
    return devanagari_share(text) >= 0.3


def main() -> int:
    manifest_path = DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    have = {d["file"] for d in manifest["documents"]}
    added, skipped = [], []
    for line in (DIR / "books_hi_medium.tsv").read_text(encoding="utf-8").splitlines():
        grade, subject, file, source = line.split("\t")
        path = DIR / file
        if file in have:
            continue
        if not path.exists():
            skipped.append((file, "not downloaded"))
            continue
        try:
            text, pages = sample_text(path)
        except Exception as exc:  # noqa: BLE001 - truncated/corrupt download
            skipped.append((file, f"cannot open ({type(exc).__name__}); re-download"))
            continue
        letters = sum(c.isalpha() for c in text)
        if letters < 1500:
            skipped.append((file, "no text layer (scanned images); needs OCR"))
            continue
        english = subject == "ENG"
        legacy = None if english or devanagari_share(text) >= 0.3 else "krutidev"
        if legacy and not converts(path):
            skipped.append((file, "legacy font other than Kruti Dev (e.g. Shree-Lipi); not supported"))
            continue
        key = next((v for k, v in SPECIAL.items() if k in file), SUBJECT_HI[subject])
        title = (f"English Class {grade} (SCERT CG)" if english
                 else f"{key} कक्षा {grade} (एससीईआरटी छ.ग., हिंदी माध्यम)")
        entry = {"file": file, "title": title, "doc_type": "textbook", "subject": subject, "grade": int(grade),
                 "language": "en" if english else "hi", "curriculum_version": "SCERT-CG 2024-25",
                 "publisher": "SCERT Chhattisgarh, Raipur"}
        if legacy:
            entry["legacy_font"] = legacy
        entry["url"] = BASE + urllib.parse.quote(source)
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["documents"].append(entry)
        added.append((file, pages, legacy or "unicode"))
    manifest["documents"].sort(key=lambda d: (d["grade"], d["subject"] or "", d["language"], d["file"]))
    lines = ["{", f'  "note": {json.dumps(manifest["note"], ensure_ascii=False)},', '  "documents": [']
    lines += ["    " + json.dumps(d, ensure_ascii=False) + ("," if i < len(manifest["documents"]) - 1 else "")
              for i, d in enumerate(manifest["documents"])]
    manifest_path.write_text("\n".join(lines + ["  ]", "}", ""]), encoding="utf-8")
    for f, p, enc in added:
        print(f"added    {f} ({p} pages, {enc})")
    for f, why in skipped:
        print(f"skipped  {f}: {why}")
    if "--warm" in sys.argv:  # pre-extract every PDF in parallel so ingestion is fast
        from app.kb.ingest import warm_page_cache

        warm_page_cache([(DIR / d["file"], d.get("legacy_font")) for d in manifest["documents"]
                         if (DIR / d["file"]).exists()], workers=4)
        print("page cache ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
