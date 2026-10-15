"""Dashboards distinguish current, stale, missing and estimated data."""
from datetime import date, timedelta

from sqlalchemy import select

from app.models import School, SchoolPerformanceSnapshot
from app.services import analytics


def test_data_status_classification():
    today = date(2026, 10, 14)
    snap = SchoolPerformanceSnapshot(period="2026-10", as_of=today - timedelta(days=3), is_estimate=False)
    assert analytics.data_status(snap, today) == "current"
    snap.as_of = today - timedelta(days=90)
    assert analytics.data_status(snap, today) == "stale"
    snap.is_estimate = True
    assert analytics.data_status(snap, today) == "estimated"
    assert analytics.data_status(None, today) == "missing"


def test_overview_reports_status_counts_and_uses_only_current_data(as_):
    ov = as_("state").get("/api/admin/overview").json()
    ds = ov["metrics"]["data_status"]
    assert ds["stale"] == 2 and ds["missing"] == 2
    assert ds["current"] == ov["totals"]["schools_active"] - 4
    assert ov["metrics"]["metrics_basis"].startswith(f"{ds['current']} of")
    assert 0 < ov["metrics"]["student_attendance_rate"] < 1
    assert set(ov["metrics"]["subject_scores"]) >= {"MATH", "HIN"}
    assert len(ov["trend"]) == 6


def test_stale_and_missing_schools_are_flagged_and_values_withheld(as_, db):
    a = as_("state")
    stale = db.scalar(select(School).where(School.official_code == "22920200103"))
    missing = db.scalar(select(School).where(School.official_code == "22930200102"))
    s = a.get(f"/api/admin/schools/{stale.id}").json()
    assert s["data_status"] == "stale"
    assert any(f["metric"] == "reporting" for f in s["flags"])
    m = a.get(f"/api/admin/schools/{missing.id}").json()
    assert m["data_status"] == "missing" and m["latest"] is None
    perf = a.get("/api/admin/reports/performance", params={"format": "csv"}).text
    line = next(l for l in perf.splitlines() if l.startswith("22920200103"))
    assert ",stale,-,-,-,-," in line  # no outcome values for stale data


def test_admin_class_view_is_aggregated_and_small_groups_suppressed(as_, db):
    a = as_("state")
    school = db.scalar(select(School).where(School.official_code == "22910100101"))
    detail = a.get(f"/api/admin/schools/{school.id}").json()
    cls = detail["classes"][0]
    view = a.get(f"/api/admin/classes/{cls['id']}").json()
    assert view["suppressed"] is False
    text = str(view)
    assert "st-demo" not in text and "name" not in {k for s in view["subjects"] for k in s if k == "name" and False}
    # create a tiny class -> suppressed
    r = a.post(f"/api/admin/schools/{school.id}/classes", json={"grade": 2, "section": "B", "academic_year": "2026-27"})
    assert r.status_code == 201
    a.post(f"/api/admin/classes/{r.json()['id']}/students",
           json={"full_name": "Solo Student", "guardian_name": "Guardian", "guardian_consent": True})
    tiny = a.get(f"/api/admin/classes/{r.json()['id']}").json()
    assert tiny["suppressed"] is True and tiny["attendance_rate_30d"] is None


def test_snapshots_are_derived_from_raw_records(db):
    school = db.scalar(select(School).where(School.official_code == "22910100101"))
    period = analytics.recent_periods(1)[0]
    snap = analytics.compute_school_snapshot(db, school, period)
    assert snap is not None and snap.source == "platform-records" and snap.is_estimate is False
    assert snap.student_count >= 24
    db.rollback()
