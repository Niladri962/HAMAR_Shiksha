"""Official school-code registry: search, validation, onboarding workflow."""
import io

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, School
from app.registry import format_problems, is_demo_code


def test_search_valid_code_returns_the_registered_school(as_):
    r = as_("state").get("/api/admin/search/schools", params={"code": "2291 0100 101"})
    assert r.status_code == 200
    [row] = r.json()
    assert row["official_code"] == "22910100101"
    assert row["district"] == "Raipur"


def test_code_format_rules():
    assert format_problems("2291010010") == ["School code must be exactly 11 digits (UDISE+ format)"]
    assert format_problems("2291010010A")
    assert format_problems("27010100101") == ["School code does not belong to Chhattisgarh (state code 22)"]
    assert format_problems("22010100101") == []
    assert is_demo_code("22910100101") and not is_demo_code("22050100101")


@pytest.mark.parametrize("code,status,fragment", [
    ("12345", 422, "11 digits"),
    ("27010100101", 422, "Chhattisgarh"),
    ("22910100177", 422, "not found in the official registry"),
    ("22910100199", 422, "closed"),
    ("22910100101", 409, "already registered"),
])
def test_invalid_and_duplicate_codes_are_rejected(as_, db, code, status, fragment):
    r = as_("state").post("/api/admin/schools", json={"official_code": code})
    assert r.status_code == status, r.text
    assert fragment in r.json()["detail"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "school.register_rejected")) is not None


def test_registration_outside_scope_is_refused(as_):
    r = as_("district_south").post("/api/admin/schools", json={"official_code": "22910200108"})
    assert r.status_code == 403


def test_onboarding_workflow_with_maker_checker(as_, db):
    district = as_("district_north")
    r = district.post("/api/admin/schools", json={"official_code": "22910100108", "lowest_class": 1, "highest_class": 5})
    assert r.status_code == 201
    school_id = r.json()["id"]
    assert r.json()["status"] == "pending"
    # The same district admin cannot activate their own registration.
    assert district.post(f"/api/admin/schools/{school_id}/activate").status_code == 403
    # Block admins cannot activate at all.
    assert as_("block_amla").post(f"/api/admin/schools/{school_id}/activate").status_code == 403
    assert as_("state").post(f"/api/admin/schools/{school_id}/activate").status_code == 200
    school = db.get(School, school_id)
    db.refresh(school)
    assert school.status == "active" and school.name.endswith("(Demo)")
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == str(school_id))))
    assert {"school.registered", "school.activated"} <= actions
    # A second registration of the same code is a duplicate.
    assert district.post("/api/admin/schools", json={"official_code": "22910100108"}).status_code == 409


def test_demo_codes_rejected_when_demo_data_disabled(as_):
    s = get_settings()
    s.allow_demo_data = False
    try:
        r = as_("state").post("/api/admin/schools", json={"official_code": "22910100109"})
        assert r.status_code == 422 and "Demonstration" in r.json()["detail"]
    finally:
        s.allow_demo_data = True


def test_registry_import_validates_rows_and_is_state_only(as_, db):
    csv_text = (
        "udise_code,school_name,district_code,district_name,block_code,block_name,status\n"
        "22050100101,Govt. Primary School Example,2205,Example District,220501,Example Block,active\n"
        "22050100101,Duplicate row,2205,Example District,220501,Example Block,active\n"
        "22060100101,Prefix mismatch,2205,Example District,220501,Example Block,active\n"
        "22910100150,Demo-range code,2291,Raipur,229101,Dharsiwa,active\n"
        "123,Too short,2205,Example District,220501,Example Block,active\n"
    )
    files = {"file": ("udise.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    data = {"source": "Test extract", "source_reference": "TEST/2026/001"}
    assert as_("district_north").post("/api/admin/registry/import", files=files, data=data).status_code == 403
    files = {"file": ("udise.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    r = as_("state").post("/api/admin/registry/import", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    reasons = {x["line"]: " ".join(x["reasons"]) for x in body["rejected"]}
    assert "duplicate" in reasons[3]
    assert "prefix" in reasons[4]
    assert "demo-range" in reasons[5]
    assert "11 digits" in reasons[6]
    log = db.scalar(select(AuditLog).where(AuditLog.action == "registry.imported"))
    assert log.details["source_reference"] == "TEST/2026/001"
    # Lookup of the imported (not yet registered) code
    entry = as_("state").get("/api/admin/registry/22050100101").json()
    assert entry["source"] == "Test extract" and entry["registered_school_id"] is None
