"""Chhattisgarh administrative geography: 5 revenue divisions and 33 districts.

This is public reference data (district names and the division each belongs
to), not statistics. District *codes* used by the demo dataset are in the
reserved demo range (see app/registry.py); real UDISE+ codes come only from an
official registry import, which is matched to these districts by name.

Map shapes: `map_shape` names the polygon in web/static/data/cg-districts.geojson
(geoBoundaries 2021, ODbL). Five districts created in September 2022 have no
separate polygon in that source; they are drawn inside the district they were
carved from (`map_shape` = parent) and the map says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

DIVISIONS = [
    ("RPR", "Raipur", "रायपुर"),
    ("DRG", "Durg", "दुर्ग"),
    ("BSP", "Bilaspur", "बिलासपुर"),
    ("SRG", "Surguja", "सरगुजा"),
    ("BST", "Bastar", "बस्तर"),
]


@dataclass(frozen=True)
class DistrictInfo:
    name: str
    name_hi: str
    division: str          # division code
    map_shape: str         # polygon name in the 2021 boundary file
    created_2022: bool = False


DISTRICTS: list[DistrictInfo] = [
    # Raipur division
    DistrictInfo("Raipur", "रायपुर", "RPR", "Raipur"),
    DistrictInfo("Balodabazar-Bhatapara", "बलौदाबाजार-भाटापारा", "RPR", "Baloda Bazar"),
    DistrictInfo("Gariaband", "गरियाबंद", "RPR", "Gariaband"),
    DistrictInfo("Mahasamund", "महासमुंद", "RPR", "Mahasamund"),
    DistrictInfo("Dhamtari", "धमतरी", "RPR", "Dhamtari"),
    # Durg division
    DistrictInfo("Durg", "दुर्ग", "DRG", "Durg"),
    DistrictInfo("Balod", "बालोद", "DRG", "Balod"),
    DistrictInfo("Bemetara", "बेमेतरा", "DRG", "Bemetra"),
    DistrictInfo("Rajnandgaon", "राजनांदगांव", "DRG", "Rajnandgaon"),
    DistrictInfo("Kabirdham", "कबीरधाम", "DRG", "Kabeerdham"),
    DistrictInfo("Khairagarh-Chhuikhadan-Gandai", "खैरागढ़-छुईखदान-गंडई", "DRG", "Rajnandgaon", True),
    DistrictInfo("Mohla-Manpur-Ambagarh Chowki", "मोहला-मानपुर-अंबागढ़ चौकी", "DRG", "Rajnandgaon", True),
    # Bilaspur division
    DistrictInfo("Bilaspur", "बिलासपुर", "BSP", "Bilaspur"),
    DistrictInfo("Mungeli", "मुंगेली", "BSP", "Mungeli"),
    DistrictInfo("Korba", "कोरबा", "BSP", "Korba"),
    DistrictInfo("Janjgir-Champa", "जांजगीर-चांपा", "BSP", "Janjgir-Champa"),
    DistrictInfo("Raigarh", "रायगढ़", "BSP", "Raigarh"),
    DistrictInfo("Gaurela-Pendra-Marwahi", "गौरेला-पेंड्रा-मरवाही", "BSP", "Gaurella Pendra Marwahi"),
    DistrictInfo("Sakti", "सक्ती", "BSP", "Janjgir-Champa", True),
    DistrictInfo("Sarangarh-Bilaigarh", "सारंगढ़-बिलाईगढ़", "BSP", "Raigarh", True),
    # Surguja division
    DistrictInfo("Surguja", "सरगुजा", "SRG", "Surguja"),
    DistrictInfo("Surajpur", "सूरजपुर", "SRG", "Surajpur"),
    DistrictInfo("Balrampur-Ramanujganj", "बलरामपुर-रामानुजगंज", "SRG", "Balrampur"),
    DistrictInfo("Koriya", "कोरिया", "SRG", "Koriya"),
    DistrictInfo("Jashpur", "जशपुर", "SRG", "Jashpur"),
    DistrictInfo("Manendragarh-Chirmiri-Bharatpur", "मनेंद्रगढ़-चिरमिरी-भरतपुर", "SRG", "Koriya", True),
    # Bastar division
    DistrictInfo("Bastar", "बस्तर", "BST", "Bastar"),
    DistrictInfo("Kondagaon", "कोंडागांव", "BST", "Kondagaon"),
    DistrictInfo("Narayanpur", "नारायणपुर", "BST", "Narayanpur"),
    DistrictInfo("Uttar Bastar Kanker", "उत्तर बस्तर कांकेर", "BST", "Uttar Bastar Kanker"),
    DistrictInfo("Dakshin Bastar Dantewada", "दक्षिण बस्तर दंतेवाड़ा", "BST", "Dakshin Bastar Dantewada"),
    DistrictInfo("Sukma", "सुकमा", "BST", "Sukma"),
    DistrictInfo("Bijapur", "बीजापुर", "BST", "Bijapur"),
]

# Spellings found in official extracts -> canonical name
ALIASES = {
    "balodabazar": "Balodabazar-Bhatapara", "baloda bazar": "Balodabazar-Bhatapara",
    "bemetra": "Bemetara", "kawardha": "Kabirdham", "kabeerdham": "Kabirdham",
    "janjgir champa": "Janjgir-Champa", "kanker": "Uttar Bastar Kanker", "dantewada": "Dakshin Bastar Dantewada",
    "balrampur": "Balrampur-Ramanujganj", "korea": "Koriya", "gaurella pendra marwahi": "Gaurela-Pendra-Marwahi",
    "sarguja": "Surguja", "ambikapur": "Surguja", "jagdalpur": "Bastar",
}


def _key(name: str) -> str:
    return re.sub(r"[^a-z ]+", " ", name.lower()).strip()


_BY_KEY = {_key(d.name): d for d in DISTRICTS}
for alias, canonical in ALIASES.items():
    _BY_KEY[_key(alias)] = next(d for d in DISTRICTS if d.name == canonical)


def lookup(name: str) -> DistrictInfo | None:
    k = _key(re.sub(r"\(.*?\)", "", name))
    return _BY_KEY.get(re.sub(r"\s+", " ", k))


def ensure_divisions(db: Session) -> dict[str, int]:
    from app.models import Division

    have = {d.code: d for d in db.scalars(select(Division))}
    for code, name, name_hi in DIVISIONS:
        if code not in have:
            have[code] = Division(code=code, name=name, name_hi=name_hi)
            db.add(have[code])
    db.flush()
    return {c: d.id for c, d in have.items()}


def assign_division(db: Session, district) -> None:
    """Attach a district to its division by name (no-op if unknown)."""
    info = lookup(district.name)
    if info is None:
        return
    ids = ensure_divisions(db)
    district.division_id = ids[info.division]
    if not district.name_hi:
        district.name_hi = info.name_hi
