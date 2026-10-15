# HAMAR SHIKSHA — Technical Guide

For engineers who set up, deploy, operate and extend the platform. Architecture diagrams:
[ARCHITECTURE.md](ARCHITECTURE.md). Security: [SECURITY_PRIVACY.md](SECURITY_PRIVACY.md).
Model choice and benchmarks: [MODEL_SELECTION.md](MODEL_SELECTION.md). API: [API.md](API.md).
What is not done: [LIMITATIONS.md](LIMITATIONS.md).

## 1. Local development

Requirements: Python 3.10+, [Ollama](https://ollama.com) (for the SLM), ~6 GB disk for one model.

```bash
python -m venv .venv && .venv\Scripts\activate          # Windows (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
ollama pull llama3.2:3b                                  # default; gemma2:2b for CPU-only PCs (MODEL_SELECTION.md)
python -m app.cli seed-demo                              # migrations + clearly-labelled demo data
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 (demo accounts are printed by `seed-demo` and listed in README.md).

Optional hybrid retrieval (Hindi↔English, better recall):
```bash
pip install -r requirements-embeddings.txt
set HS_EMBEDDING_MODEL=BAAI/bge-m3                      # first use downloads ~2.3 GB, then works offline
```

Without Ollama the platform still runs: the tutor shows labelled textbook excerpts and Saathi
returns labelled templates (`HS_SLM_RUNTIME=none`).

## 2. Configuration (`HS_*` environment variables)

See `.env.example`. Key settings:

| Variable | Default | Meaning |
|---|---|---|
| `HS_SLM_RUNTIME` | `ollama` | `ollama`, `llamacpp` (llama.cpp `llama-server`, OpenAI-compatible), `none`, or `anthropic` (optional central cloud inference, explicit opt-in only) |
| `HS_SLM_URL` / `HS_SLM_MODEL` | `http://127.0.0.1:11434` / `llama3.2:3b` | Runtime endpoint and model tag; set the model chosen in MODEL_SELECTION.md |
| `HS_EMBEDDING_MODEL` | empty | Empty = BM25 keyword retrieval; `BAAI/bge-m3` = hybrid |
| `HS_RETRIEVAL_MIN_VECTOR_SCORE` | `0.45` | Cosine threshold for "evidence found" |
| `HS_MODULE_NAMES` | JSON | Display names of the modules (configurable until naming is approved) |
| `HS_DATABASE_URL` | SQLite | PostgreSQL in production (`postgresql+psycopg://...`) |
| `HS_ALLOW_DEMO_DATA` | `true` | Must be `false` in production |

Production refuses to start with a default secret, demo data, insecure cookies, SQLite or the
log notifier.

## 3. Database and migrations

- Schema: `app/models.py` (46 tables). Migrations: `migrations/` (Alembic).
- `app.database.init_db()` runs `alembic upgrade head` and inserts reference data; every CLI
  command and the app start-up call it.
- New migration after changing models:
  `alembic revision --autogenerate -m "describe change"` → review → commit.
- PostgreSQL DDL for review: `python -m app.cli schema-sql`.

## 4. Gyan SLM

- Runtime adapters: `app/slm/runtime.py` (Ollama, llama.cpp, optional central). Swap the
  runtime with configuration only.
- Grounded generation: `app/slm/gyan.py` (retrieval → passages as data → citation +
  grounding validation → honest "could not verify").
- Production on CPU servers: run `llama-server -m <model>.gguf --host 0.0.0.0 --port 8080
  -c 4096` and set `HS_SLM_RUNTIME=llamacpp`, `HS_SLM_URL=http://<host>:8080`. Use the same
  GGUF quantisation that was benchmarked (Ollama's default tags are Q4_K_M).
- Status: `python -m app.cli slm-status` or the admin "Curriculum & AI" tab.

## 5. Curriculum knowledge base

Ingest authorised material with a manifest:

```json
{"documents": [{"file": "class5_maths_hi.pdf", "title": "à¤—à¤£à¤¿à¤¤ à¤•à¤•à¥à¤·à¤¾ 5", "doc_type": "textbook",
  "subject": "MATH", "grade": 5, "language": "hi", "curriculum_version": "SCERT 2026-27",
  "publisher": "SCERT Chhattisgarh"}]}
```

```bash
python -m app.cli ingest-curriculum path/to/manifest.json
```

or upload single files in the admin "Curriculum & AI" tab (state administrators). PDFs need a
text layer (scanned books need OCR first). Each chunk keeps class, subject, chapter, page,
language, version and source; identical files are skipped by checksum; withdrawn documents
stop being cited immediately. Vectors (if enabled) are cached in `HS_KB_DIR`.

## 6. Evaluation and benchmarking

```bash
python -m eval.run_eval --models llama3.2:3b,gemma2:2b --modes base,rag            # GPU if available
python -m eval.run_eval --models qwen2.5:1.5b --modes rag --cpu --tag cpu            # CPU-only (school PC proxy)
python -m eval.run_eval --models llama3.2:3b --modes rag --embedding BAAI/bge-m3      # hybrid retrieval
```

Results (JSON with every answer + Markdown summary) go to `eval/results/`. Dataset:
`eval/datasets/gyan_eval.jsonl`. Re-run on the actual target hardware before claiming
performance, and extend the dataset with SCERT material and teacher-written items.

## 7. Deployment (Docker)

```bash
cp .env.docker.example .env.docker      # set POSTGRES_PASSWORD, HS_SECRET_KEY, SITE_ADDRESS, HS_SLM_MODEL
docker compose --env-file .env.docker up -d --build
```

Services: `db` (PostgreSQL 16), `slm` (Ollama; `slm-init` pulls the model once), `app`
(runs migrations then uvicorn), `proxy` (Caddy, HTTPS). For a demonstration stack set
`HS_ENVIRONMENT=development HS_ALLOW_DEMO_DATA=true HS_SEED_DEMO=1 HS_NOTIFIER=log`.
First production admin: `docker compose exec app python -m app.cli create-state-admin --login ... --name ...`.

GPU hosts: uncomment the `deploy` block of `slm`. Without a GPU, Ollama runs on CPU (see
MODEL_SELECTION.md for measured CPU latency).

> The compose file has been validated (`docker compose config`); the image build and stack
> start-up were **not** executed in this environment (Docker daemon not running).

Manual (non-Docker) production: Python 3.10+, PostgreSQL 14+, `pip install -r
requirements-postgres.txt`, the steps of §1 with production settings, uvicorn behind a TLS
proxy with `--proxy-headers`.

## 8. Scheduled jobs

| Schedule | Command |
|---|---|
| Nightly | `python -m app.cli recompute-snapshots --months 2` |
| Nightly, after snapshots | `python -m app.cli refresh-insights` |
| Weekly | `python -m app.cli purge-retention` |

## 9. Backup and disaster recovery

PostgreSQL WAL archiving + point-in-time recovery, nightly encrypted `pg_dump` to a second
site, quarterly restore drills. Also back up the Ollama model volume (or keep the exact model
tag/digest) and `HS_KB_DIR` (vector cache, rebuildable). Targets to agree with the department:
RPO ≤ 15 min, RTO ≤ 4 h. The app is stateless otherwise.

## 10. Tests

```bash
python -m pytest                 # 103 tests: auth, RBAC/scope, registry, analytics, AI safeguards, voice, Kruti Dev conversion,
                                 # learner record, Pariksha, Saathi, sync, Command Centre, KB, exports
HS_LIVE_SLM_MODEL=llama3.2:3b python -m pytest -m slm   # 3 opt-in tests against the real local model
python -m eval.sample_workflow --model llama3.2:3b --embedding BAAI/bge-m3      # end-to-end journey, writes docs/SAMPLE_WORKFLOW.md
```

Default tests use a deterministic fake SLM and keyword retrieval, so they need no GPU or
Ollama. Live-model quality is measured by `eval/run_eval.py` and the `-m slm` tests.

## 11. Removing demo data

`python -m app.cli purge-demo --yes` deletes every demo user, school, registry entry,
curriculum document, learning outcome, question, plan, event and calendar.
