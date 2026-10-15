# Remaining integrations, limitations and production prerequisites

Stated plainly so nobody mistakes the demonstration for a finished government system.

## Not connected / not available

| Item | Status |
|---|---|
| UDISE+ | No live connection. Official codes are imported from a CSV extract (`import-registry`). A read-only API connector can call `registry.import_registry_csv` once access is granted |
| HRMS (teacher posting, qualifications) | Not integrated. `teacher_profiles.subject_qualifications` is entered/seeded; expertise-gap figures depend on it |
| State attendance / assessment portals | Not integrated |
| SCERT textbooks and question banks | **37 SCERT Chhattisgarh 2024-25 textbooks** (classes 1-8) can be ingested from the official public PDFs (`data/scert_cg`, see docs/CURRICULUM.md). This is **not** an approved SCERT data feed: there is no permission letter, and the Kruti Dev → Unicode conversion of Hindi-medium books has been spot-checked by us, not reviewed by SCERT. Seven books are not loaded (scanned pages need OCR; two use the unsupported Shree-Lipi font; one download failed). Question banks are not loaded. Learning outcomes and question items remain the demo set |
| SMS / e-mail gateway | Stub; production refuses `HS_NOTIFIER=log` |
| SSO (e-Pramaan etc.) | Not implemented |

## AI limitations

- **Verified does not mean correct.** In the real end-to-end run (`docs/SAMPLE_WORKFLOW.md`,
  llama3.2:3b), several answers were cited and passed grounding yet contained conceptual
  errors. For example, the Hindi answer described अंश (numerator) with the definition of हर
  (denominator), and an English answer said 1/3 and 1/5 have "equal denominators". The
  validator checks that the words come from the textbook, not that the reasoning is right.
  The same happened on the real SCERT Chhattisgarh books: 3 of 4 spot-checked answers were wrong
  or vague although verified (docs/CURRICULUM.md §2), including a geography answer about a map
  that exists only as an image.
  Before student use this needs: teacher review panels, a larger evaluation set scored by
  teachers, possibly a stronger model on central servers, and fine-tuning on approved
  question–answer data. Until then the tutor should be piloted with teacher supervision.

- **No fine-tuning has been done.** Gyan SLM is a selected open-weight base model + retrieval +
  validation. LoRA/QLoRA adaptation needs approved, de-identified training data and a
  separate evaluation; see `docs/MODEL_SELECTION.md`.
- **Evaluation is small**: 39 automatically-scored items on demo material. It ranks candidate
  models; it does not certify pedagogical quality. Teacher review panels are required.
- **Languages**: Hindi and English only are enabled. Chhattisgarhi, Gondi and Halbi are on the
  roadmap; the two Chhattisgarhi probes in the eval were written without native-speaker
  validation and no Gondi/Halbi data exists here. No claim of regional-language accuracy is made.
- **Cross-lingual retrieval** (Hindi question → English textbook) works only with the optional
  embedding model; keyword retrieval cannot match across scripts.
- **Voice**: speech-to-text uses a local Whisper model (`small` by default). English was checked
  with synthetic speech only; **Hindi recognition has not been tested with real children's voices**,
  and Whisper's error rate for Hindi is much higher than for English. The transcript is therefore
  always shown for the user to correct before it is sent. Chhattisgarhi, Gondi and Halbi speech are
  not supported. Reading answers aloud depends on the voices installed on the device; many devices
  have no Hindi voice, and some browsers' voices (e.g. Chrome's "Google हिन्दी") are online services.
  Microphone access needs HTTPS (or localhost).
- **Handwriting OCR** is not implemented; descriptive/handwritten answers always go to teacher
  review (`services/ocr.py` defines the interface).
- Benchmarks were run on one laptop (Ryzen 7 7445HS, 15 GB RAM, RTX 3050 4 GB). Target school
  hardware and Android devices have **not** been benchmarked.

## Districts, divisions and the map

- District and division **names** are real (33 districts in 5 revenue divisions, as of the 2022
  reorganisation). All schools, teachers, students and figures in the demo are generated. School
  counts on the map ("schools in registry") come from the demo registry extract, **not UDISE+**.
- Boundaries come from geoBoundaries (2021, ODbL, simplified). They show 28 districts: the five
  districts created in September 2022 (Khairagarh-Chhuikhadan-Gandai, Mohla-Manpur-Ambagarh Chowki,
  Sakti, Sarangarh-Bilaigarh, Manendragarh-Chirmiri-Bharatpur) are drawn inside the district they
  were carved from; their own figures appear in the table. Boundaries are indicative, not
  authoritative; official use needs Survey of India / state GIS boundaries.
- Divisions are an analysis grouping only; access control stays state → district → block.

## Student self-improvement and peer help

- Safety screening uses fixed patterns (phone numbers, links, a short list of unkind words in
  English and Hindi, wellbeing phrases). It will miss some content, especially in Chhattisgarhi or
  transliterated Hindi; teacher moderation and the report button are the main safeguards.
- Peer answers are not checked for correctness, only for safety. "Helpful" is marked by the asker
  or the teacher.
- XP and levels reward activity, not mastery. Revision questions come only from multiple-choice
  items answered wrongly in quizzes; practice items are not yet added to the deck.
- The textbook reader shows extracted text only (no pictures, maps or tables).

## Progress grades, attendance follow-up, digital resources, recognition

- Grades (A-D) and attendance levels are **fixed, transparent rules**, not trained predictors. The
  thresholds (e.g. "learned" at 60 % class mastery, "irregular" below 75 %) are proposals that need
  agreement with SCERT / Samagra Shiksha. They have not been validated against real dropout or
  achievement data, and should never be used for decisions about a child or a teacher on their own.
- "Lessons missed" is inferred from the week a milestone was marked taught and the child's absences
  that week; the platform does not know the exact period.
- Digital resources are a register kept by schools. There is no connection to ICT@School / Samagra
  Shiksha MIS or to device logs, so use is what teachers record. The demo register and sessions are
  generated. Use-versus-results compares groups of classes and is not causal.
- Badges are computed from records and reward activity and improvement; certificates are
  motivational printouts, not official certificates. Teacher badges must not be used for appraisal.

## Offline limitations

- Browser offline mode covers: cached app shell, cached quizzes (students), cached rosters
  (teachers), queued attendance / quiz answers / activity completions / milestones, sync status.
  The AI tutor needs a reachable SLM (school node or central).
- A first visit must happen online (to cache the shell and the bundle).
- On-device SLM for Android needs a native app (not built).
- School-node ↔ state-server replication (two servers syncing) is not implemented; the sync
  protocol is client ↔ server.

## Engineering

- Frontend is vanilla JS (decision recorded in ARCHITECTURE.md); no frontend unit/E2E browser
  tests yet - UI verified by API-level journey tests and manual review only.
- The demo dataset is synthetic; the generator is deterministic but not realistic at state scale.
- Docker images were not load-tested; capacity planning for ~56,000 schools is pending.
- Independent security audit, DPIA and accessibility audit (WCAG 2.1 AA) are pending.
