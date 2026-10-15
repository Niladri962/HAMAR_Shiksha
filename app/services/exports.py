"""Tabular export to CSV, XLSX and PDF.

Every export carries a header block: title, scope, generation time, the
requesting role, data-status notes and a confidentiality marking.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from openpyxl import Workbook
from openpyxl.styles import Font

MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list]
    notes: list[str] = field(default_factory=list)
    classification: str = "OFFICIAL - for authorised education administration use only"


def _cell(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.1%}" if 0 <= v <= 1 else f"{v:.2f}"
    return str(v)


def _csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection in exported text."""
    s = _cell(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and s != "-" else s


def to_csv(t: Table) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([t.title])
    for n in [t.classification, *t.notes]:
        w.writerow([n])
    w.writerow([])
    w.writerow(t.columns)
    for r in t.rows:
        w.writerow([_csv_safe(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel reads Devanagari correctly


def to_xlsx(t: Table) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.append([t.title])
    ws["A1"].font = Font(bold=True, size=14)
    for n in [t.classification, *t.notes]:
        ws.append([n])
    ws.append([])
    ws.append(t.columns)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for r in t.rows:
        ws.append([_csv_safe(v) if isinstance(v, str) else v for v in r])
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col[len(t.notes) + 3:] if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(48, max(10, width + 2))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --------------------------------------------------------------- tiny PDF ----

def _pdf_text(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def to_pdf(t: Table) -> bytes:
    """Minimal multi-page PDF (A4 landscape, Helvetica). Devanagari text is
    not representable in the base-14 fonts; use XLSX/CSV for Hindi content."""
    W, H, margin, lh = 842, 595, 36, 13
    usable = W - 2 * margin
    ncol = max(1, len(t.columns))
    col_w = usable / ncol
    max_chars = max(4, int(col_w / 5.2))

    def fit(s: str) -> str:
        s = _cell(s) if not isinstance(s, str) else s
        return s if len(s) <= max_chars else s[: max_chars - 1] + "~"

    header_lines = [(t.title, 13, True), (t.classification, 8, False)] + [(n, 8, False) for n in t.notes]
    pages: list[list[str]] = []
    ops: list[str] = []
    y = H - margin

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops, y = [], H - margin

    def text(x, y_, s, size=9, bold=False):
        ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {x:.1f} {y_:.1f} Td ({_pdf_text(s)}) Tj ET")

    def table_header():
        nonlocal y
        for i, c in enumerate(t.columns):
            text(margin + i * col_w, y, fit(c), 9, True)
        y -= 4
        ops.append(f"{margin} {y:.1f} m {W - margin} {y:.1f} l S")
        y -= lh

    for s, size, bold in header_lines:
        text(margin, y, s, size, bold)
        y -= size + 5
    y -= 6
    table_header()
    for r in t.rows:
        if y < margin + lh:
            new_page()
            table_header()
        for i, v in enumerate(r):
            text(margin + i * col_w, y, fit(_cell(v)), 8)
        y -= lh
    new_page()

    objs: list[bytes] = []
    n_pages = len(pages)
    # 1 catalog, 2 pages, 3 F1, 4 F2, then (page, content) pairs
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    for i, page_ops in enumerate(pages):
        footer = f"BT /F1 7 Tf {margin} 20 Td (HAMAR SHIKSHA - page {i + 1} of {n_pages}) Tj ET"
        stream = ("0.5 w\n" + "\n".join(page_ops + [footer])).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def render(t: Table, fmt: str) -> bytes:
    return {"csv": to_csv, "xlsx": to_xlsx, "pdf": to_pdf}[fmt](t)
