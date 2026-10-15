# HAMAR SHIKSHA — Security, Privacy and Child Safety

For security reviewers, the department's data-protection officer and technical maintainers.

## 1. Identity and access

| Control | Implementation | Test |
|---|---|---|
| Three separate portals; an account works only on its own portal | `routers/auth.login` checks an active role for that portal | `test_auth.py::test_credentials_only_work_on_their_own_portal` |
| Server-side RBAC on every API | `deps.require_portal`, `deps.require_admin` | `test_authorization.py` |
| Data scope (state / district / block / school / class / self) | `scope.py`; out-of-scope = 404 (no existence oracle) | `test_district_admin_cannot_see_other_districts`, `test_block_admin_limited_to_block` |
| School codes identify schools, never authenticate | Codes are only search keys; registration checks the registry, the admin's scope and a second-admin activation | `test_registry.py` |
| URL / parameter / storage tampering cannot widen scope | Scope comes only from `user_role_assignments`; student APIs take no student ID; teachers address students by random `public_id` and only within assigned classes | `test_student_identity_comes_from_session_not_request` |
| Passwords | Argon2id, policy (length, common list), forced change of issued passwords | `test_new_teacher_must_be_verified_and_change_password` |
| Sessions | Opaque token (SHA-256 at rest), httpOnly + SameSite=Strict + Secure cookie, CSRF header, 60-min admin TTL, revocation on logout/password change/role revoke | `test_logout_revokes_the_server_side_session`, `test_revoked_role_ends_existing_session` |
| Brute force | 5 failures / 15 min per login ID → lockout; per-IP limit; generic errors | `test_account_locks_after_repeated_failures` |
| Privileged admins | TOTP MFA; `HS_ADMIN_MFA_REQUIRED=true` makes it mandatory; first state admin bootstrapped with MFA | `test_admin_mfa_enrolment_and_login` |
| Account recovery | Staff: single-use 30-min reset token via approved gateway; students: class teacher reissues a temporary password (audited) | `test_password_reset_flow_for_staff` |
| Devices (offline sync) | Device registry; devices bound to a school; admins can revoke; revoked devices cannot sync | `test_revoked_device_cannot_sync` |

## 2. Offline mode cannot bypass permissions

Every queued event is re-validated on the server by the same service functions used online,
under the pushing user's own permissions (`services/sync.py`). Event IDs are deduplicated;
conflicts follow documented rules; every outcome is stored in `synchronization_events`.
Tests: `test_sync_cannot_widen_permissions`, `test_offline_attendance_sync_dedup_and_conflict`,
`test_offline_quiz_submission_syncs_once`. Offline bundles never contain answer keys; the
outbox, cache and cached profile are wiped at logout.

## 3. AI safety

- **Untrusted input:** student prompts and retrieved documents are treated as data. Passages are
  wrapped in `<source>` blocks and the system prompt tells the model to ignore instructions
  inside them; a pattern screen intercepts common injection phrasing before the model.
- **No tools / no privileges:** the SLM receives text and returns text (or schema-validated
  JSON). It cannot run queries, change records or grant access. All writes happen in backend
  code after authorization checks.
- **Grounding:** answers are verified against the retrieved passages (citation and word-coverage
  checks); otherwise the user sees "could not verify from approved textbooks".
- **Child safety:** wellbeing phrases (self-harm, abuse) get a supportive reply with CHILDLINE
  1098 and are flagged for the class teacher; privacy probes are refused and flagged.
- **Rate limits:** 30 tutor questions/hour per student; 100 AI requests/day per teacher.
- **Human decisions:** recommendations, remediation plans, lesson plans and AI-drafted
  questions are drafts until a teacher approves them. No AI output changes a grade, promotion,
  attendance or teacher record. Uncertain grading always goes to a teacher.
- **No training on student data:** the platform has no fine-tuning pipeline that reads learner
  records. `ai_interactions` are retained for supervision only (180 days by default).

## 4. Data protection

| Principle | How |
|---|---|
| Minimisation | Students: name, birth year (not DOB), gender, guardian contact, consent record. No Aadhaar, caste or address fields |
| Consent | A student account cannot be created without recorded guardian consent (who/when) |
| Purpose limitation | Statewide views read aggregate snapshots; admin class views suppress groups < 5; reports for admins are aggregate-only |
| Visibility | Students: own record only. Teachers: assigned classes/subjects only. Admins: scoped aggregates; identifiable data only within duties |
| No advertising / sale | No third-party scripts, trackers, fonts or CDNs; CSP `default-src 'self'` |
| Exports | Scope-filtered, audited (`report.exported`), formula-injection safe, `Cache-Control: no-store` |
| Retention | `HS_RETENTION_*` settings; `python -m app.cli purge-retention` (schedule weekly) |
| Encryption | TLS at the proxy (Caddy in compose); HSTS when `HS_COOKIE_SECURE=true`; use encrypted volumes / managed-key storage for PostgreSQL and backups |
| Secrets | Environment only (`.env`, `.env.docker`, ignored by git and Docker); production refuses default secrets |
| Uploads | Registry CSV ≤ 5 MB UTF-8; curriculum PDF/TXT/MD ≤ 50 MB with type check; state admins only |
| Audit | Logins, denials, lockouts, registry/school lifecycle, account changes, record views, exports, AI usage, reviews, sync pushes, device revocation |
| Peer help (doubt board, study buddies) | Class-scoped only: a student sees their own doubts and the board of their own class; there are no private student-to-student messages. Classmates see first names only; the teacher sees full names. Every post is screened before anyone else sees it: phone numbers, links/social-media names, passwords and other students' marks are refused; unkind words are refused; anything matching the wellbeing patterns is never posted publicly but goes privately to the teacher (and the student sees the CHILDLINE 1098 message). Students can report an answer; teachers can hide answers or whole doubts (audited) and see reported items. 20 posts per student per hour. Study pairs are created only by the teacher; suggestions use mastery, shown only to the teacher |
| Attendance follow-up | Names of flagged children are shown only to teachers of that class; administrators get counts and averages only (groups under 5 hidden). Wording is "follow up" / "keep watch", never "dropout"; no automated action is taken |
| Appreciation | Teachers can appreciate only students in their own classes; head teachers only colleagues in their school; administrators only teachers in their scope (others 404). Messages pass the same screen as student posts (no phone numbers, links or unkind words); 30 per giver per day; audited |
| Voice | Microphone only after the user presses **Speak** and the browser asks permission; `Permissions-Policy: microphone=(self)` (no embedded third party can use it). Audio (≤ 30 s, ≤ 2 MB, signed-in users, 60/hour) is transcribed **in memory** by local Whisper on this server and discarded: it is never written to disk, the database or logs, and never sent to an external service. Only the transcript, which the user checks and may edit, becomes a question. Read-aloud uses the device's voices; on-device voices are preferred, but on some browsers the only Hindi voice is an online service, which then receives the answer text (textbook content, not personal data) |

## 5. Before go-live (not done here)

1. Independent VAPT by a CERT-In empanelled auditor.
2. Data Protection Impact Assessment under the DPDP Act 2023 (children's data: verifiable
   parental consent, no tracking/behavioural monitoring/targeted advertising).
3. Department approval of retention periods, consent wording (Hindi/English) and the
   safeguarding escalation route for flagged conversations.
4. Hosting on approved infrastructure (State Data Centre / MeitY-empanelled cloud) with backup
   and DR drills.
5. Native-speaker and teacher review of AI behaviour in each enabled language.
