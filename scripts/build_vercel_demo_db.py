"""Build deploy/demo.db.gz: the compact demonstration database bundled with
the Vercel deployment when no hosted database is configured.

Contains only generated demo data and the demo curriculum primers (no SCERT
textbook text, which is not redistributed in this repository). Dates are
relative to the day it is built, so rebuild it before a demonstration:

    python scripts/build_vercel_demo_db.py
"""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="hs-vercel-"))
    db = tmp / "demo.db"
    env = {**os.environ, "HS_DATABASE_URL": f"sqlite:///{db.as_posix()}", "HS_KB_DIR": str(tmp / "kb"),
           "HS_EMBEDDING_MODEL": "", "HS_DEMO_SCALE": "compact", "HS_ENVIRONMENT": "test",
           "HS_SLM_RUNTIME": "none", "USE_TF": "0"}
    subprocess.run([sys.executable, "-m", "app.cli", "seed-demo"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('VACUUM'); c.close()",
                    str(db)], check=True)
    out = ROOT / "deploy" / "demo.db.gz"
    out.parent.mkdir(exist_ok=True)
    with open(db, "rb") as src, gzip.open(out, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB (database {db.stat().st_size / 1e6:.1f} MB)")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
