"""Download the SCERT Chhattisgarh books listed in data/scert_cg/books_hi_medium.tsv.

The SCERT server often closes connections early while still reporting
success, so each file is checked against the server's Content-Length and
resumed with HTTP Range requests until complete. Files that already match the
expected size are skipped. After downloading, run scripts/add_scert_books.py
to record checksums in the manifest.

    python scripts/download_scert_books.py [--workers 4]
"""
from __future__ import annotations

import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

DIR = Path(__file__).resolve().parent.parent / "data" / "scert_cg"
BASE = "https://scert.cg.gov.in/pdf/textbook-2024-25/"


def fetch(client: httpx.Client, file: str, source: str, attempts: int = 40) -> str:
    url = BASE + urllib.parse.quote(source)
    target, part = DIR / file, DIR / (file + ".part")
    total = int(client.head(url).headers["content-length"])
    if target.exists() and target.stat().st_size == total:
        return f"ok        {file}"
    if target.exists():
        target.replace(part)  # an earlier truncated copy: resume from it
    for _ in range(attempts):
        have = part.stat().st_size if part.exists() else 0
        if have >= total:
            break
        try:
            with client.stream("GET", url, headers={"Range": f"bytes={have}-"} if have else {}) as r:
                if have and r.status_code != 206:  # server ignored the range: start again
                    part.unlink(missing_ok=True)
                    continue
                with part.open("ab") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
        except httpx.HTTPError:
            time.sleep(2)
    size = part.stat().st_size if part.exists() else 0
    if size != total:
        return f"INCOMPLETE {file}: {size}/{total} bytes"
    part.replace(target)
    return f"fetched   {file} ({total // 1_000_000} MB)"


def main() -> int:
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
    rows = [line.split("\t") for line in (DIR / "books_hi_medium.tsv").read_text(encoding="utf-8").splitlines() if line]
    with httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=True) as client, \
            ThreadPoolExecutor(workers) as pool:
        for msg in pool.map(lambda r: fetch(client, r[2], r[3]), rows):
            print(msg, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
