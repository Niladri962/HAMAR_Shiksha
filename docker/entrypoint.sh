#!/bin/sh
# Apply database migrations, optionally load demo data, then start the server.
set -e
python - <<'PY'
from app import database
database.init_db()
print("database migrated")
PY
if [ "${HS_SEED_DEMO:-0}" = "1" ]; then
  python -m app.cli seed-demo
fi
exec "$@"
