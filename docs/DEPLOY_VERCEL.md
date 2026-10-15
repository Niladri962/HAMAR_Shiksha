# Deploying the demo on Vercel

The repository is ready for Vercel: `api/index.py` is the Python function, `vercel.json` sends every
request to it, and `deploy/demo.db.gz` is a compact demonstration database (33 districts, 57
schools, ~1,000 students; generated data only, no SCERT textbook text).

## 1. Import the project

1. Sign in at <https://vercel.com> with GitHub and choose **Add New… → Project**.
2. Import **Niladri962/HAMAR_Shiksha**. Framework preset: **Other**. Leave build and output
   settings empty (Vercel installs `requirements.txt` for the Python function).
3. **Environment variables** (Settings → Environment Variables) — all optional for a first look:

| Variable | Value | Why |
|---|---|---|
| `HS_SECRET_KEY` | a long random string (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) | good practice; never reuse the development value |
| `HS_DATABASE_URL` or a Neon integration (`DATABASE_URL`) | your PostgreSQL URL | shared, persistent data (see step 2) |
| `HS_SLM_URL` | `https://…` of an Ollama server you run | enables the Gyan SLM; without it AI answers fall back to textbook passages |

4. **Deploy**. Open the URL; sign in with the demo accounts in [DEMO_ACCOUNTS.md](DEMO_ACCOUNTS.md)
   (e.g. `state.admin` / `Demo@State2026`, `DEMO-T-001` / `Demo@Teacher2026`, `st-demo01` / `Demo@Student26`).

## 2. Use a hosted database (recommended for a client demo)

Without a database URL each serverless instance unpacks its own copy of the demo database in
`/tmp`: it works for a quick look, but sign-ins can be lost when Vercel starts another instance,
and changes disappear. For a stable demonstration:

1. In the Vercel project: **Storage → Create → Neon (Postgres)** and connect it to the project.
   Vercel adds `DATABASE_URL`; `api/index.py` converts it for SQLAlchemy automatically.
2. Seed it once from your own computer (copy the URL from Neon; keep `?sslmode=require`):

```bash
pip install -r requirements.txt
HS_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require" \
HS_DEMO_SCALE=compact HS_EMBEDDING_MODEL="" python -m app.cli seed-demo
```

   (`HS_DEMO_SCALE=full` creates ~3,600 students; it takes a few minutes over the network.)
3. Optional: load the SCERT textbooks into **your** database (the PDFs are not in the repository):

```bash
python scripts/download_scert_books.py && python scripts/add_scert_books.py
HS_DATABASE_URL="postgresql+psycopg://…" HS_EMBEDDING_MODEL="" \
python -m app.cli ingest-curriculum data/scert_cg/manifest.json
```

4. Redeploy.

## What does not run on Vercel (and why)

| Feature | On Vercel | To enable |
|---|---|---|
| Gyan SLM (llama3.2:3b via Ollama) | Off: answers show the matching textbook passages, labelled as not AI | Run Ollama on a server/GPU you control and set `HS_SLM_URL` (protect it; do not expose it publicly without authentication) |
| Vector retrieval (bge-m3) | Keyword (BM25) retrieval only | Needs the embedding model; use the Docker/VM deployment |
| Voice input (Whisper) | Off (model too large for a function) | Docker/VM deployment with `requirements-voice.txt` |
| Uploading textbooks in the admin portal | Works with PostgreSQL; files are processed in the request (60 s limit) | Large books: ingest from your computer as above |

Vercel is suitable for showing the platform. A state rollout should use the Docker deployment on
approved government infrastructure (see [TECHNICAL.md](TECHNICAL.md)), where the SLM, vectors and voice
run locally and `HS_ENVIRONMENT=production` enforces the production checks.

## Refreshing the bundled demo database

The demo data is dated relative to the day it was built; after about a month schools start to show
as "stale". Rebuild before a demonstration and push:

```bash
python scripts/build_vercel_demo_db.py
```

## Troubleshooting

- **"This page is unavailable / 500 FUNCTION_INVOCATION_FAILED"**: redeploy the latest commit.
  Start-up problems are now shown on the page itself (HTTP 503 with the reason, passwords redacted)
  and in Vercel → Project → **Logs**. Send that text to the developer.
- The serverless set-up (`app/serverless.py`) runs whether Vercel starts `api/index.py` or detects
  FastAPI in `app/main.py`, so both entry points use `/tmp` for the demo database.
- Python is pinned to 3.12 (`.python-version`).
- Do **not** set `HS_ENVIRONMENT=production` on Vercel with the bundled demo database: production mode
  refuses demo data and SQLite by design.
