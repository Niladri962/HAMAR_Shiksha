"""Curriculum knowledge base + Gyan SLM status + platform configuration."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.database import get_db
from app.deps import Principal, get_principal, require_admin
from app.kb import retrieval
from app.kb.ingest import DocMeta, ingest_file
from app.models import STATE_ADMIN, CurriculumChunk, CurriculumDocument
from app.scope import not_found
from app.slm import gyan

router = APIRouter(tags=["knowledge-base"])


@router.get("/api/platform")
def platform():
    """Public: module names, enabled languages, demo flag."""
    s = get_settings()
    return {"modules": s.module_names, "languages": sorted(gyan.SUPPORTED_LANGUAGES),
            "roadmap_languages": {"cg": "Chhattisgarhi", "gon": "Gondi", "hlb": "Halbi"},
            "demo_mode": s.allow_demo_data, "voice": {"speech_to_text": bool(s.stt_model)}}


@router.get("/api/kb/status")
def kb_status(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    docs = db.scalar(select(func.count(CurriculumDocument.id)).where(CurriculumDocument.approval_status == "approved"))
    chunks = db.scalar(select(func.count(CurriculumChunk.id)))
    return {"slm": gyan.status(), "documents": docs, "chunks": chunks}


@router.get("/api/kb/documents")
def documents(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if p.portal == "student":
        raise HTTPException(403, "Not available")
    rows = db.scalars(select(CurriculumDocument).order_by(CurriculumDocument.grade, CurriculumDocument.title)).all()
    counts = dict(db.execute(select(CurriculumChunk.document_id, func.count()).group_by(CurriculumChunk.document_id)).all())
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "subject": d.subject.name if d.subject else None,
             "grade": d.grade, "language": d.language, "curriculum_version": d.curriculum_version,
             "publisher": d.publisher, "pages": d.pages, "chunks": counts.get(d.id, 0),
             "approval_status": d.approval_status, "is_demo": d.is_demo, "ingested_at": d.ingested_at.isoformat()}
            for d in rows]


@router.get("/api/kb/search")
def search(q: str, grade: int | None = None, subject_id: int | None = None, p: Principal = Depends(get_principal),
           db: Session = Depends(get_db)):
    if p.portal == "student":
        raise HTTPException(403, "Not available")
    hits, supported = retrieval.search(db, q[:300], grade=grade, subject_id=subject_id, k=6)
    return {"supported": supported, "hits": [{"citation": retrieval.format_citation(h.citation), **h.citation,
                                              "text": h.text, "score": h.score, "bm25": h.bm25, "vector": h.vector}
                                             for h in hits]}


ALLOWED_SUFFIX = {".pdf", ".txt", ".md"}


@router.post("/api/kb/documents", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), title: str = Form(..., min_length=3, max_length=250),
                 doc_type: Literal["textbook", "syllabus", "lo_framework", "lesson_material", "question_paper",
                                   "training"] = Form("textbook"),
                 subject: str | None = Form(None), grade: int | None = Form(None),
                 language: Literal["hi", "en"] = Form("hi"), curriculum_version: str = Form(..., min_length=2),
                 publisher: str = Form(..., min_length=3),
                 legacy_font: Literal["none", "krutidev"] = Form("none"),
                 p: Principal = Depends(require_admin(STATE_ADMIN)), db: Session = Depends(get_db)):
    """State administrators ingest authorised material (validated upload)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(422, "Only PDF, TXT or MD files are accepted")
    data = await file.read(50_000_001)
    if len(data) > 50_000_000:
        raise HTTPException(413, "File too large (max 50 MB)")
    if suffix == ".pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(422, "File is not a valid PDF")
    if publisher.strip().upper() == "DEMO":
        raise HTTPException(422, "Demo material is loaded only by the demo seed")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            doc, created = ingest_file(db, path, DocMeta(title=title, doc_type=doc_type, subject_code=subject, grade=grade,
                                                         language=language, curriculum_version=curriculum_version,
                                                         publisher=publisher,
                                                         legacy_font=None if legacy_font == "none" else legacy_font),
                                       approved_by=p.user.id)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    doc.source_file = file.filename or doc.source_file
    audit(db, "kb.document_ingested", principal=p, request=request, entity_type="curriculum_document",
          entity_id=doc.id, created=created, title=title)
    db.commit()
    return {"id": doc.id, "created": created,
            "chunks": db.scalar(select(func.count(CurriculumChunk.id)).where(CurriculumChunk.document_id == doc.id))}


@router.post("/api/kb/documents/{doc_id}/withdraw")
def withdraw(doc_id: int, request: Request, p: Principal = Depends(require_admin(STATE_ADMIN)),
             db: Session = Depends(get_db)):
    d = db.get(CurriculumDocument, doc_id)
    if d is None:
        raise not_found("Document")
    d.approval_status = "withdrawn"
    audit(db, "kb.document_withdrawn", principal=p, request=request, entity_type="curriculum_document", entity_id=d.id)
    db.commit()
    return {"ok": True}
