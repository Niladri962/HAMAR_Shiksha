"""Reports respect scope, are audited, and exports are safe."""
import csv
import io

from sqlalchemy import select

from app.models import AuditLog, ClassSection, School
from app.services.exports import Table, to_csv


def _rows(text):
    lines = text.lstrip("﻿").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("UDISE code"))
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def test_reports_respect_admin_scope(as_):
    north = _rows(as_("district_north").get("/api/admin/reports/coverage", params={"format": "csv"}).text)
    assert north and all(r["District"] == "Raipur" for r in north)
    block = _rows(as_("block_amla").get("/api/admin/reports/coverage").text)
    assert block and all(r["Block"] == "Dharsiwa" for r in block)
    state = _rows(as_("state").get("/api/admin/reports/coverage").text)
    assert len(state) > len(north) > len(block)


def test_report_header_marks_demo_data_and_scope(as_):
    text = as_("state").get("/api/admin/reports/performance").text
    assert "DEMONSTRATION DATA" in text and "Scope: Chhattisgarh" in text


def test_all_formats_render(as_):
    a = as_("state")
    for kind in ("coverage", "performance", "district-summary", "interventions", "data-quality"):
        for fmt, magic in (("csv", None), ("xlsx", b"PK"), ("pdf", b"%PDF")):
            r = a.get(f"/api/admin/reports/{kind}", params={"format": fmt})
            assert r.status_code == 200, (kind, fmt)
            assert r.headers["cache-control"] == "no-store"
            if magic:
                assert r.content.startswith(magic)
    assert a.get("/api/admin/reports/students").status_code == 404


def test_exports_are_audited(as_, db):
    as_("district_north").get("/api/admin/reports/data-quality", params={"format": "xlsx"})
    log = db.scalars(select(AuditLog).where(AuditLog.action == "report.exported", AuditLog.entity_id == "data-quality")).all()
    assert log and log[-1].details["format"] == "xlsx"


def test_teacher_class_export_only_for_own_class(as_, db):
    showcase = db.scalar(select(ClassSection).join(School).where(School.official_code == "22910100101",
                                                                 ClassSection.grade == 5))
    r = as_("math_teacher").get(f"/api/teacher/classes/{showcase.id}/export", params={"format": "csv"})
    assert r.status_code == 200 and "CONFIDENTIAL" in r.text
    assert as_("other_teacher").get(f"/api/teacher/classes/{showcase.id}/export").status_code == 404
    assert as_("student5").get(f"/api/teacher/classes/{showcase.id}/export").status_code == 403


def test_csv_neutralises_formula_injection():
    out = to_csv(Table("t", ["a"], [["=HYPERLINK(\"http://x\")"], ["+1"], ["@SUM(A1)"], ["normal"]])).decode("utf-8-sig")
    assert "'=HYPERLINK" in out and "'+1" in out and "'@SUM" in out and "\nnormal" in out


def test_teacher_report_reaches_scoped_admins(as_):
    t = as_("head_teacher")
    r = t.post("/api/teacher/reports", json={"period": "2026-10", "title": "October report",
                                             "body": "Attendance improved after SMC meeting."})
    assert r.status_code == 201
    titles = [x["title"] for x in as_("block_amla").get("/api/admin/school-reports").json()]
    assert "October report" in titles
    assert "October report" not in [x["title"] for x in as_("district_south").get("/api/admin/school-reports").json()]
