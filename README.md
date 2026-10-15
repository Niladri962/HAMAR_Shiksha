# HAMAR SHIKSHA

**Holistic Approach for Meaningful Achievements & Reforms in Education**: an SLM-first, offline-capable
school education platform for government schools in Chhattisgarh, aligned with the NeeevAI
"AI in Education" proposal.

**One Gyan SLM + one curriculum knowledge base + one continuous learner record + four connected
modules + three role-specific portals.**

| Module (configurable name) | What it does | Portal |
|---|---|---|
| **Gyan SLM** | Local open-weight small language model + curriculum retrieval + citation/grounding validation | shared |
| **Teacher Saathi** | Academic plan & milestones, grounded lesson plans, worksheets, remediation, micro-courses, substitute lessons | `/teacher` |
| **AI Class** | Supervised tutor with textbook citations, adaptive practice, lessons, quizzes, live substitute lessons | `/student` |
| **Pariksha Engine** | Question bank by learning outcome, deterministic scoring, teacher review queue, misconceptions, competency reports | `/teacher` |
| **Command Centre** | State → district → block → school → class drill-down, planned/taught/learned, expertise gaps, sync health | `/admin` |

> **Demonstration data**: `seed-demo` uses the **real names of Chhattisgarh's 33 districts and 5
> divisions**, but every school, teacher, student and number is fictional (school codes in the
> reserved demo range 2260-2299). Demo curriculum primers are **not SCERT material**. Everything is
> flagged `is_demo`, banners say so, and production refuses demo data.

**Also included**
- **Chhattisgarh textbooks**: 37 official SCERT Chhattisgarh 2024-25 textbooks for classes 1-8
  (Hindi, Hindi-Chhattisgarhi, Maths, EVS, Science, Social Science, Sanskrit, English) can be loaded
  so students ask questions about their real books and read them chapter by chapter. Hindi-medium PDFs use the legacy Kruti Dev font and are
  converted to Unicode on ingestion. See [docs/CURRICULUM.md](docs/CURRICULUM.md).
- **Voice assistant**: students (AI Class → Ask) and teachers (Saathi → Ask) can speak a question
  in Hindi or English; it is transcribed on the server by a local Whisper model (audio is not
  stored). Answers can be read aloud with the device's voices.
- **Divisions, districts and map analysis**: all 33 districts grouped into the Raipur, Durg,
  Bilaspur, Surguja and Bastar divisions. *Admin → Map & divisions* shows division cards, a district
  map of Chhattisgarh coloured by schools (registry / onboarded), students, teachers, scores or
  attendance, a ranking and a table; click a district to drill down.
- **Classes 1-8 everywhere**: every district has demo schools with classes 1-8, teachers and
  students (~3,600 students, 170 teachers).
- **Students improve themselves, or with help**: levels, XP and a learning streak; weekly goals;
  a *Fix my mistakes* deck (spaced revision of wrong answers); a textbook library to read chapter
  by chapter; *Ask teacher* privately; a *class doubt board* where classmates answer (teacher
  moderated, screened for personal details and unkind words); *study buddies* paired by the
  teacher from mastery data. Teachers get a *Student help* tab.
- **Progress grades and corrective actions**: every class-subject and school is graded A (on track)
  to D (needs support) against its milestones, from what was planned, taught and learned, with the
  next steps (outcomes to cover, outcomes to re-teach). Teacher → *Progress & follow-up*;
  Admin → *Command Centre → Progress grades*.
- **Attendance follow-up**: children whose attendance is irregular, falling or has stopped, with
  the lessons they missed and whether they have since learned them; administrators see counts only.
- **Digital infrastructure**: ICT labs, smart classes, digital libraries, language labs and tablet
  sets per school; sessions recorded in one tap; utilisation, alignment with learning outcomes,
  gaps and use-versus-results in the Command Centre and on the map.
- **Recognition**: student and teacher badges that reward improvement, effort and regularity, a
  weekly class challenge, printable certificates, and appreciation notes (teacher → student, head
  teacher / administrator → teacher).
- **All 16 project objectives** are mapped to features, screens and tests in
  [docs/OBJECTIVES.md](docs/OBJECTIVES.md).
- **Light / dark theme** (☾ / ☀) and a **colour scheme picker** (🎨: portal default, ocean, forest,
  saffron, plum, rose) in every page header; choices are remembered on the device.

## Deploy a demo on Vercel

Import this repository in Vercel (framework preset **Other**) and deploy; it runs with a bundled
demo database. For a stable client demo add a Neon Postgres database. The local SLM, vector search
and voice need the Docker deployment. Step by step: [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md).

## Quick start

```bash
pip install -r requirements.txt -r requirements-embeddings.txt -r requirements-voice.txt
ollama pull llama3.2:3b                 # Gyan SLM, runs locally (see docs/MODEL_SELECTION.md)
copy .env.example .env                  # local Llama + hybrid retrieval + voice (cp on Linux/macOS)
python -m app.cli seed-demo
ollama pull bge-m3                      # multilingual embeddings for search (GPU via Ollama)
python scripts/fetch_scert_cg.py        # SCERT Chhattisgarh textbooks (checksum-verified)
python -m app.cli ingest-curriculum data/scert_cg/manifest.json
uvicorn app.main:app --reload
```

The AI runs locally by default (`HS_SLM_RUNTIME=ollama`, `llama3.2:3b`). Cloud inference is never
used unless `HS_SLM_RUNTIME=anthropic` is set deliberately.

| Portal | Login ID | Password |
|---|---|---|
| Admin (state) | `state.admin` | `Demo@State2026` |
| Admin (district / block) | `district.raipur` (any district: `district.<name>`, e.g. `district.bastar`) / `block.dharsiwa` | `Demo@District2026` / `Demo@Block2026` |
| Teacher (head teacher) | `DEMO-T-001` | `Demo@Teacher2026` |
| Teacher (maths & science) | `DEMO-T-002` | `Demo@Teacher2026` |
| Student (Class 5 / Class 8) | `st-demo01` / `st-demo02` | `Demo@Student26` |

One teacher and one student login for **every district** are listed in [docs/DEMO_ACCOUNTS.md](docs/DEMO_ACCOUNTS.md).

Tests: `python -m pytest`. Benchmarks: `python -m eval.run_eval --models llama3.2:3b --modes base,rag`.
Docker: `docker compose --env-file .env.docker up -d --build` (see docs/TECHNICAL.md).

## Sample curriculum-grounded workflow (try it)

1. **Teacher** `DEMO-T-002` → *Teacher Saathi → Academic plan*: Class 5 maths milestones; tap **Mark taught**.
2. *Lesson plans*: pick outcome `DEMO-MATH5.2 Fractions` → **Draft lesson plan** → the draft cites
   *Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 3-5* → edit → **Approve**.
3. *Pariksha → Build assessment*: choose the Fractions outcome, MCQ + short answer → publish.
4. **Student** `st-demo01` → *Quizzes* → answer (try going offline: answers queue and sync later).
   Short answers that are near-misses go to the teacher's **Review queue** instead of being auto-marked.
5. The result becomes a `learner_event`; competency for `DEMO-MATH5.2` updates; *AI Class*
   suggests Fractions practice at a matched difficulty; the teacher's **This week's priorities**
   lists the student with the evidence ("2 of 7 marks").
6. *Class progress → Analyse learning gaps* → *Saathi → Remediation → Draft remediation plan* → approve.
7. **Admin** `state.admin` → *Command Centre*: planned / taught / learned by district, expertise gaps,
   attendance-learning correlation, device sync health. Every number is computed from records.

## Acceptance criteria → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Independent logins | `test_auth.py::test_each_portal_logs_in_and_redirects_to_its_dashboard`, `test_credentials_only_work_on_their_own_portal` |
| 2 | Role permissions only | `test_authorization.py` (teacher/student/admin cross-access) |
| 3 | District/block isolation | `test_district_admin_cannot_see_other_districts`, `test_block_admin_limited_to_block`, `test_command_centre_ptl_and_scope` |
| 4 | Codes validated, duplicates rejected | `test_registry.py` |
| 5 | SLM answers with citations | `test_teacher_saathi_answers_with_citations`, `test_student_assistant_safeguards`; live model: `eval/results/*` (citation_page_correct) |
| 6 | Unsupported questions handled honestly | `test_unsupported_questions_are_answered_honestly`; eval `honest_refusal` |
| 7 | Local model without internet | Ollama local runtime, benchmarks run locally (docs/MODEL_SELECTION.md). *Not tested with the network physically disabled on target hardware.* |
| 8 | Cached lessons/assessments offline | Service worker + IndexedDB bundle; `test_offline_quiz_submission_syncs_once` (server side). *Browser offline behaviour verified manually only.* |
| 9 | Offline changes sync safely | `test_offline_attendance_sync_dedup_and_conflict`, `test_sync_cannot_widen_permissions`, `test_revoked_device_cannot_sync` |
| 10 | Results update the correct learner record | `test_assessment_result_updates_the_correct_learner_record`, `test_seeded_learner_record_is_event_based` |
| 11 | Recommendations cite evidence | `test_recommendations_are_traceable_to_the_students_own_records`, `test_teacher_priority_list_cites_evidence` |
| 12 | Metrics from structured data | `test_analytics.py`, `test_command_centre_gaps_correlation_participation` |
| 13 | AI vs approved content distinguishable | `test_teacher_worksheet_drafts_need_approval`, `test_lesson_plan_is_grounded_draft_until_approved`, `test_offline_fallback_is_not_presented_as_ai` |
| 14 | Uncertain grading reviewable | `test_short_answer_scoring_is_deterministic_and_flags_uncertainty`, `test_bank_assessment_review_queue_and_competency_update` |
| 15 | No fabricated production statistics | `test_production_guards.py` |
| 16 | Sensitive data protected server-side | `test_authorization.py`, `test_platform.py` (sync, KB, devices) |
| 17 | Audit logs | `test_onboarding_workflow_with_maker_checker`, `test_exports_are_audited`, `test_teacher_cannot_use_admin_apis` |
| 18 | Automated tests | `python -m pytest` - see docs/TECHNICAL.md §10 |
| 19 | Reproducible setup | docs/TECHNICAL.md, `.env.example`, `.env.docker.example`, `docker-compose.yml` |
| 20 | Honest model/hardware/language docs | docs/MODEL_SELECTION.md, docs/LIMITATIONS.md |

## Documentation

| Document | Audience |
|---|---|
| [docs/OBJECTIVES.md](docs/OBJECTIVES.md) | The 16 project objectives → features, screens, tests |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture + diagrams, design decisions |
| [docs/MODEL_SELECTION.md](docs/MODEL_SELECTION.md) | SLM benchmark, selection, hardware, languages |
| [docs/CURRICULUM.md](docs/CURRICULUM.md) | SCERT Chhattisgarh textbooks, Kruti Dev conversion, voice |
| [docs/TECHNICAL.md](docs/TECHNICAL.md) | Setup, configuration, deployment, operations |
| [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md) | One-click demo deployment on Vercel (and its limits) |
| [docs/API.md](docs/API.md) | API reference (generated from OpenAPI) |
| [docs/SECURITY_PRIVACY.md](docs/SECURITY_PRIVACY.md) | Security, privacy, child safety |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | Remaining integrations and production prerequisites |
| [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md), [docs/TEACHER_GUIDE.md](docs/TEACHER_GUIDE.md) | End users (incl. student quick guide) |

## Layout

```
app/
  slm/        runtime.py (Ollama / llama.cpp / optional central), gyan.py (grounded generation)
  kb/         ingest.py (PDF/TXT -> chunks with page/chapter), retrieval.py (BM25 + vectors)
  services/   learner (event record), pariksha, planning, aiclass, sync, analytics, insights, ...
  routers/    auth, admin (+Command Centre), teacher, saathi, pariksha, student, sync, kb
  models.py   46-table schema           migrations/  Alembic
web/          HTML/CSS/JS, service worker (no build step)
eval/         run_eval.py + datasets/ + results/
data/demo_curriculum/   demo primers (NOT SCERT) + manifest
data/scert_cg/          SCERT Chhattisgarh textbook manifest (PDFs fetched by scripts/fetch_scert_cg.py)
docker-compose.yml, Dockerfile, docker/   app + PostgreSQL + Ollama + Caddy
```
