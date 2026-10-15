"""Official school-code registry.

The platform never invents school codes. Codes enter `school_code_registry`
only through an authorised import of a government extract (UDISE+), and a
school can be registered only for a code that is present, active and not
already registered.

UDISE+ school codes are 11 digits: state(2) district(2) block(2) cluster/
village(3) school(2). Chhattisgarh's state code is 22. District codes 60-99 (far beyond
the state's 33 real districts) are reserved by this platform for demonstration
rows ("2260..." - "2299..."), which are refused whenever demo data is disabled.
Districts are linked to their revenue division by name (app/geo.py).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.config import get_settings
from app.models import Block, District, School, SchoolCodeRegistry, utcnow

STATE_CODE = "22"  # Chhattisgarh
DEMO_DISTRICT_MIN = "60"  # district digits 60-99 are reserved for demo data
CODE_RE = re.compile(r"^\d{11}$")


class CodeError(HTTPException):
    def __init__(self, message: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY):
        super().__init__(code, message)


def normalise_code(raw: str) -> str:
    return re.sub(r"\s+", "", raw or "")


def format_problems(code: str) -> list[str]:
    if not CODE_RE.match(code):
        return ["School code must be exactly 11 digits (UDISE+ format)"]
    if not code.startswith(STATE_CODE):
        return ["School code does not belong to Chhattisgarh (state code 22)"]
    return []


def is_demo_code(code: str) -> bool:
    return code[2:4] >= DEMO_DISTRICT_MIN


def validate_for_registration(db: Session, raw_code: str) -> SchoolCodeRegistry:
    """Return the registry entry if `raw_code` may be registered, else raise."""
    code = normalise_code(raw_code)
    problems = format_problems(code)
    if problems:
        raise CodeError(problems[0])
    entry = db.get(SchoolCodeRegistry, code)
    if entry is None:
        raise CodeError("School code not found in the official registry")
    if (entry.is_demo or is_demo_code(code)) and not get_settings().allow_demo_data:
        raise CodeError("Demonstration codes are not accepted in this environment")
    if entry.registry_status != "active":
        raise CodeError(f"School code is marked '{entry.registry_status}' in the official registry")
    if db.scalar(select(School.id).where(School.official_code == code)) is not None:
        raise CodeError("A school with this official code is already registered",
                        status.HTTP_409_CONFLICT)
    return entry


def resolve_geography(db: Session, entry: SchoolCodeRegistry) -> tuple[District, Block]:
    district = db.scalar(select(District).where(District.code == entry.district_code))
    block = db.scalar(select(Block).where(Block.code == entry.block_code))
    if district is None or block is None or block.district_id != district.id:
        raise CodeError("District/block for this code is not configured; import the registry first")
    return district, block


# ----------------------------------------------------------------- import ----

REQUIRED_COLUMNS = {"udise_code", "school_name", "district_code", "district_name",
                    "block_code", "block_name"}


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    rejected: list[dict] = field(default_factory=list)


def import_registry_csv(db: Session, text: str, *, source: str, source_reference: str,
                        imported_by: int | None, demo: bool = False) -> ImportResult:
    """Upsert registry rows from a government CSV extract.

    Columns: udise_code, school_name, district_code, district_name, block_code,
    block_name and optionally district_name_hi, block_name_hi, locality,
    category, management, status (active|closed|merged).
    """
    settings = get_settings()
    if demo and not settings.allow_demo_data:
        raise CodeError("Demo data is disabled in this environment", status.HTTP_403_FORBIDDEN)
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise CodeError("Missing columns: " + ", ".join(sorted(missing)))

    result = ImportResult()
    seen: set[str] = set()
    for line_no, row in enumerate(reader, start=2):
        row = {k: (v or "").strip() for k, v in row.items() if k}
        code = normalise_code(row["udise_code"])
        d_code, b_code = row["district_code"], row["block_code"]
        reasons = format_problems(code)
        if not reasons:
            if code in seen:
                reasons.append("duplicate code within file")
            elif code[:4] != d_code or code[:6] != b_code:
                reasons.append("district/block code does not match the school code prefix")
            elif is_demo_code(code) != demo:
                reasons.append("demo-range code in a non-demo import" if not demo
                               else "non-demo code in a demo import")
            elif not row["school_name"]:
                reasons.append("school_name is empty")
        status_value = (row.get("status") or "active").lower()
        if status_value not in ("active", "closed", "merged"):
            reasons.append(f"unknown status '{status_value}'")
        if reasons:
            result.rejected.append({"line": line_no, "code": code, "reasons": reasons})
            continue
        seen.add(code)

        district = db.scalar(select(District).where(District.code == d_code))
        if district is None:
            district = District(code=d_code, name=row["district_name"],
                                name_hi=row.get("district_name_hi", ""), is_demo=demo)
            geo.assign_division(db, district)
            db.add(district)
            db.flush()
        block = db.scalar(select(Block).where(Block.code == b_code))
        if block is None:
            block = Block(code=b_code, district_id=district.id, name=row["block_name"],
                          name_hi=row.get("block_name_hi", ""), is_demo=demo)
            db.add(block)
            db.flush()

        entry = db.get(SchoolCodeRegistry, code)
        values = dict(school_name=row["school_name"], district_code=d_code, block_code=b_code,
                      locality=row.get("locality", ""), category=row.get("category", ""),
                      management=row.get("management", ""), registry_status=status_value,
                      source=source, source_reference=source_reference,
                      imported_at=utcnow(), imported_by=imported_by, is_demo=demo)
        if entry is None:
            db.add(SchoolCodeRegistry(code=code, **values))
            result.created += 1
        else:
            for k, v in values.items():
                setattr(entry, k, v)
            result.updated += 1
            # A closed/merged registry code suspends the platform school.
            school = db.scalar(select(School).where(School.official_code == code))
            if school and status_value != "active" and school.status == "active":
                school.status = "closed"
    db.flush()
    return result
