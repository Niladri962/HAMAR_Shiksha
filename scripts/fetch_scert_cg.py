"""Download the SCERT Chhattisgarh textbooks listed in data/scert_cg/manifest.json.

Each file is checked against the SHA-256 recorded in the manifest, so a
changed or tampered download is refused. Existing files with the right hash
are skipped.

    python scripts/fetch_scert_cg.py
    python -m app.cli ingest-curriculum data/scert_cg/manifest.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import httpx

MANIFEST = Path(__file__).resolve().parent.parent / "data" / "scert_cg" / "manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    docs = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]
    failed = 0
    with httpx.Client(timeout=httpx.Timeout(30, read=600), follow_redirects=True) as client:
        for d in docs:
            target = MANIFEST.parent / d["file"]
            if target.exists() and sha256(target) == d["sha256"]:
                print(f"ok        {d['file']}")
                continue
            tmp = target.with_suffix(".part")
            with client.stream("GET", d["url"]) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            if sha256(tmp) != d["sha256"]:
                tmp.unlink()
                print(f"MISMATCH  {d['file']} - the published file has changed; review it before updating the manifest")
                failed += 1
                continue
            tmp.replace(target)
            print(f"fetched   {d['file']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
