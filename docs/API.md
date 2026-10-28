# HAMAR SHIKSHA - API reference

Generated from the OpenAPI schema (`docs/openapi.json`). Interactive docs: `/api/docs` (disabled in production).
All non-GET requests need the session cookie and the `X-CSRF-Token` header (value of the `hs_csrf` cookie).
Out-of-scope resources return 404; wrong portal/role returns 403.

## Authentication (shared by all portals)

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/change-password` | Change Password |
| POST | `/api/auth/language` | Set Language |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Me |
| POST | `/api/auth/mfa/enable` | Mfa Enable |
| POST | `/api/auth/mfa/setup` | Mfa Setup |
| POST | `/api/auth/password-reset/confirm` | Password Reset Confirm |
| POST | `/api/auth/password-reset/request` | Self-service reset for staff. Students reset through their school (teacher-issued temporary password), never by self-service. |
| POST | `/api/auth/{portal}/login` | Login |

## Admin portal / Command Centre (scoped)

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/admins` | List Admins |
| POST | `/api/admin/admins` | Create Admin |
| POST | `/api/admin/admins/{assignment_id}/revoke` | Revoke Admin |
| GET | `/api/admin/audit-logs` | Audit Logs |
| GET | `/api/admin/blocks/{block_id}/schools` | Block Schools |
| GET | `/api/admin/classes/{class_id}` | Class Detail |
| POST | `/api/admin/classes/{class_id}/students` | Enroll Student |
| GET | `/api/admin/command/attendance-risk` | Counts only: administrators never see the names of flagged children. |
| GET | `/api/admin/command/correlation` | Attendance Learning |
| GET | `/api/admin/command/devices` | Devices |
| POST | `/api/admin/command/devices/{device_id}/revoke` | Revoke Device |
| GET | `/api/admin/command/digital` | Digital Infrastructure |
| GET | `/api/admin/command/expertise-gaps` | Expertise Gaps |
| GET | `/api/admin/command/participation` | Participation |
| GET | `/api/admin/command/progress-grades` | Milestone-based academic progress grade per school, rolled up to the next level down. |
| GET | `/api/admin/command/ptl` | Planned Taught Learned |
| GET | `/api/admin/command/recognition` | Improvement-based recognition: most improved schools, and their teachers' earned badges. |
| GET | `/api/admin/districts` | Districts |
| GET | `/api/admin/districts/{district_id}/blocks` | District Blocks |
| GET | `/api/admin/geography` | Districts/blocks the admin may use in filters and forms. |
| GET | `/api/admin/insights` | List Insights |
| POST | `/api/admin/insights/refresh` | Refresh Insights |
| POST | `/api/admin/insights/{rec_id}/review` | Review Insight |
| GET | `/api/admin/map` | Division -> district analysis for the map: schools (onboarded and in the registry), teachers, students and outcome metrics, within the admin's scope. |
| GET | `/api/admin/needs-support` | Needs Support |
| GET | `/api/admin/overview` | Overview |
| POST | `/api/admin/registry/import` | Registry Import |
| GET | `/api/admin/registry/{code}` | Registry Lookup |
| GET | `/api/admin/reports/{kind}` | Export Report |
| GET | `/api/admin/school-reports` | School Reports |
| POST | `/api/admin/school-reports/{report_id}/acknowledge` | Acknowledge Report |
| GET | `/api/admin/schools` | List Schools |
| POST | `/api/admin/schools` | Register School |
| GET | `/api/admin/schools/{school_id}` | School Detail |
| POST | `/api/admin/schools/{school_id}/activate` | Activate School |
| POST | `/api/admin/schools/{school_id}/classes` | Create Class |
| POST | `/api/admin/schools/{school_id}/status` | Set School Status |
| GET | `/api/admin/schools/{school_id}/teachers` | School Teachers |
| POST | `/api/admin/schools/{school_id}/teachers` | Invite Teacher |
| GET | `/api/admin/search/schools` | Search Schools |
| GET | `/api/admin/teachers/pending` | Pending Teachers |
| POST | `/api/admin/teachers/{user_id}/appreciate` | Appreciate Teacher |
| POST | `/api/admin/teachers/{user_id}/assignments` | Assign Teacher |
| POST | `/api/admin/teachers/{user_id}/reset-password` | Reset Teacher Password |
| POST | `/api/admin/teachers/{user_id}/transfer` | Transfer Teacher |
| POST | `/api/admin/teachers/{user_id}/verify` | Verify Teacher |

## Teacher portal

| Method | Path | Description |
|---|---|---|
| GET | `/api/teacher/assessments` | List Assessments |
| POST | `/api/teacher/assessments` | Create Assessment |
| GET | `/api/teacher/assessments/{assessment_id}` | Get Assessment |
| POST | `/api/teacher/assessments/{assessment_id}/publish` | Publish Assessment |
| GET | `/api/teacher/assessments/{assessment_id}/results` | Assessment Results |
| POST | `/api/teacher/assessments/{assessment_id}/scores` | Record marks for an offline (paper) test. |
| GET | `/api/teacher/assignments` | List Assignments |
| POST | `/api/teacher/assignments` | Create Assignment |
| GET | `/api/teacher/assignments/{assignment_id}/submissions` | Submissions |
| GET | `/api/teacher/classes/{class_id}/ai-interactions` | Supervision view: assistant exchanges flagged by the safety filter. |
| GET | `/api/teacher/classes/{class_id}/attendance` | Get Attendance |
| POST | `/api/teacher/classes/{class_id}/attendance` | Record Attendance |
| GET | `/api/teacher/classes/{class_id}/export` | Export Class |
| GET | `/api/teacher/classes/{class_id}/performance` | Class Performance |
| GET | `/api/teacher/classes/{class_id}/roster` | Roster |
| GET | `/api/teacher/me` | Me |
| GET | `/api/teacher/priorities` | Weekly priority list: students with competencies needing practice, with evidence. |
| GET | `/api/teacher/recommendations` | Recommendations |
| POST | `/api/teacher/recommendations/refresh` | Refresh Recommendations |
| POST | `/api/teacher/recommendations/{rec_id}/review` | Review Recommendation |
| GET | `/api/teacher/reports` | My Reports |
| POST | `/api/teacher/reports` | Submit Report |
| GET | `/api/teacher/school/classes` | School Classes |
| POST | `/api/teacher/school/classes/{class_id}/students` | Head Enroll |
| GET | `/api/teacher/school/teacher-attendance` | Get Teacher Attendance |
| POST | `/api/teacher/school/teacher-attendance` | Record Teacher Attendance |
| GET | `/api/teacher/students/{public_id}/progress` | Student Progress |
| GET | `/api/teacher/students/{public_id}/record` | Student Record |
| POST | `/api/teacher/students/{public_id}/reset-credentials` | School-mediated recovery: only the student's class teacher may reissue a password. |
| POST | `/api/teacher/submissions/{submission_id}/feedback` | Give Feedback |

## Teacher: progress grades, attendance follow-up, digital resources, recognition

| Method | Path | Description |
|---|---|---|
| GET | `/api/teacher/classes/{class_id}/attendance-risk` | Class Attendance Risk |
| POST | `/api/teacher/colleagues/{public_id}/appreciate` | Appreciate Colleague |
| GET | `/api/teacher/digital` | Teacher Digital |
| POST | `/api/teacher/digital/resources` | Add Resource |
| POST | `/api/teacher/digital/resources/{resource_id}/status` | Any teacher of the school can report a fault or a repair (audited). |
| POST | `/api/teacher/digital/usage` | Log Digital Usage |
| GET | `/api/teacher/learning-outcomes` | Outcomes For Class |
| GET | `/api/teacher/progress-grades` | Planned / taught / learned grade per class-subject, with corrective actions. `scope=school` (head teacher only) covers every class in the school. |
| GET | `/api/teacher/recognition` | Teacher Recognition |
| POST | `/api/teacher/students/{public_id}/appreciate` | Appreciate Student |

## Teacher: student help (doubts, study pairs)

| Method | Path | Description |
|---|---|---|
| GET | `/api/teacher/help/classes/{class_id}/pairs` | Class Pairs |
| POST | `/api/teacher/help/classes/{class_id}/pairs` | Create Pair |
| GET | `/api/teacher/help/doubts` | Teacher Doubts |
| POST | `/api/teacher/help/doubts/{doubt_id}/replies` | Teacher Reply |
| POST | `/api/teacher/help/doubts/{doubt_id}/status` | Teacher Doubt Status |
| POST | `/api/teacher/help/pairs/{pair_id}/end` | End Pair |
| POST | `/api/teacher/help/replies/{reply_id}/accept` | Teacher Accept |
| POST | `/api/teacher/help/replies/{reply_id}/hide` | Teacher Hide |

## Teacher Saathi

| Method | Path | Description |
|---|---|---|
| GET | `/api/teacher/saathi/approved-plans` | Approved plans in the teacher's school (for the substitute workflow). |
| POST | `/api/teacher/saathi/ask` | Ask |
| GET | `/api/teacher/saathi/learning-outcomes` | Learning Outcomes |
| GET | `/api/teacher/saathi/lesson-plans` | List Plans |
| POST | `/api/teacher/saathi/lesson-plans/generate` | Generate Plan |
| PUT | `/api/teacher/saathi/lesson-plans/{plan_id}` | Edit Plan |
| POST | `/api/teacher/saathi/lesson-plans/{plan_id}/approve` | Approve Plan |
| POST | `/api/teacher/saathi/milestones/{milestone_id}/taught` | Mark Taught |
| GET | `/api/teacher/saathi/plan` | Plan |
| GET | `/api/teacher/saathi/remediation` | List Remediation |
| POST | `/api/teacher/saathi/remediation/from-recommendation/{rec_id}` | Remediation From Rec |
| POST | `/api/teacher/saathi/remediation/{plan_id}/status` | Remediation Status |
| POST | `/api/teacher/saathi/substitute` | A head teacher (school supervisor) launches an approved lesson plan for a class whose subject teacher is absent. Students see it as a supervised lesson. |
| POST | `/api/teacher/saathi/substitute/{session_id}/end` | End Substitute |
| GET | `/api/teacher/saathi/training` | Training |
| GET | `/api/teacher/saathi/training/{module_id}` | Training Module |
| POST | `/api/teacher/saathi/training/{module_id}/complete` | Complete Training |
| POST | `/api/teacher/saathi/worksheet` | Draft MCQs from the textbook passages; saved as *draft* bank questions for teacher approval. |

## Pariksha Engine (teacher)

| Method | Path | Description |
|---|---|---|
| POST | `/api/teacher/pariksha/assessments` | Assessment From Bank |
| GET | `/api/teacher/pariksha/assessments/{assessment_id}/misconceptions` | Misconceptions |
| GET | `/api/teacher/pariksha/bank` | Bank |
| POST | `/api/teacher/pariksha/bank` | Add Question |
| POST | `/api/teacher/pariksha/bank/{question_id}/{action}` | Question Action |
| GET | `/api/teacher/pariksha/competencies` | Competencies |
| POST | `/api/teacher/pariksha/results/{result_id}/review` | Review |
| GET | `/api/teacher/pariksha/review-queue` | Answers the engine could not grade with confidence. Nothing here counts towards a learner record until a teacher confirms the marks. |

## Student portal / AI Class

| Method | Path | Description |
|---|---|---|
| GET | `/api/student/activities` | Activities |
| POST | `/api/student/activities/{activity_id}/complete` | Complete Activity |
| GET | `/api/student/assessments` | Assessments |
| GET | `/api/student/assessments/{assessment_id}` | Take Assessment |
| POST | `/api/student/assessments/{assessment_id}/submit` | Submit Assessment |
| GET | `/api/student/assignments` | Assignments |
| POST | `/api/student/assignments/{assignment_id}/submit` | Submit Assignment |
| POST | `/api/student/assistant` | Ask |
| GET | `/api/student/assistant/history` | History |
| GET | `/api/student/live-lesson` | An approved lesson launched today for the student's class (e.g. substitute lesson). |
| GET | `/api/student/me` | Me |
| GET | `/api/student/practice` | Approved bank questions at a difficulty matched to demonstrated mastery. |
| POST | `/api/student/practice/check` | Score practice answers deterministically and record them in the learner record. |
| GET | `/api/student/progress` | Progress |
| GET | `/api/student/recommendations` | Recommendations |
| GET | `/api/student/record` | Record |

## Student: goals, revision, textbooks, doubts, study buddies

| Method | Path | Description |
|---|---|---|
| GET | `/api/student/doubts` | My Doubts |
| POST | `/api/student/doubts` | Ask Doubt |
| POST | `/api/student/doubts/{doubt_id}/replies` | Student Reply |
| POST | `/api/student/goals` | Add Goal |
| POST | `/api/student/goals/{goal_id}/archive` | Archive Goal |
| POST | `/api/student/goals/{goal_id}/tick` | Tick Goal |
| GET | `/api/student/growth` | Growth |
| GET | `/api/student/library` | Library |
| GET | `/api/student/library/{doc_id}` | Read Section |
| POST | `/api/student/library/{doc_id}/read` | Mark Read |
| POST | `/api/student/replies/{reply_id}/accept` | Student Accept |
| POST | `/api/student/replies/{reply_id}/report` | Student Report |
| GET | `/api/student/revision` | Revision |
| POST | `/api/student/revision/{item_id}/answer` | Revision Answer |
| GET | `/api/student/study-buddies` | Study Buddies |

## Student: badges, weekly challenge, appreciation

| Method | Path | Description |
|---|---|---|
| GET | `/api/student/recognition` | Student Recognition |

## AI video lessons (teacher and student)

| Method | Path | Description |
|---|---|---|
| GET | `/api/student/video-lessons` | Student Lessons |
| GET | `/api/student/video-lessons/{lesson_id}` | Student Lesson |
| POST | `/api/student/video-lessons/{lesson_id}/watched` | Watched |
| GET | `/api/teacher/video-lessons` | List Lessons |
| POST | `/api/teacher/video-lessons/generate` | Generate |
| GET | `/api/teacher/video-lessons/options` | Classes and subjects this teacher may make lessons for (head teacher: the whole school). |
| GET | `/api/teacher/video-lessons/{lesson_id}` | Get Lesson |
| PUT | `/api/teacher/video-lessons/{lesson_id}` | Edit Lesson |
| POST | `/api/teacher/video-lessons/{lesson_id}/{action}` | Lesson Action |

## Offline synchronisation

| Method | Path | Description |
|---|---|---|
| GET | `/api/sync/pull` | Offline bundle for the signed-in user, built with the same scope rules as the online APIs. Answer keys are never included. |
| POST | `/api/sync/push` | Push |
| GET | `/api/sync/status` | Status |

## Curriculum KB, Gyan SLM status, platform config

| Method | Path | Description |
|---|---|---|
| GET | `/api/kb/documents` | Documents |
| POST | `/api/kb/documents` | State administrators ingest authorised material (validated upload). |
| POST | `/api/kb/documents/{doc_id}/withdraw` | Withdraw |
| GET | `/api/kb/search` | Search |
| GET | `/api/kb/status` | Kb Status |
| GET | `/api/platform` | Public: module names, enabled languages, demo flag. |

## Voice (local speech-to-text)

| Method | Path | Description |
|---|---|---|
| GET | `/api/voice/status` | Whether voice input is enabled, model, limits (signed-in users) |
| POST | `/api/voice/transcribe` | Multipart `audio` (16-bit PCM WAV, ≤ 30 s, ≤ 2 MB) + `language` (`hi`/`en`) → `{text, seconds, latency_ms, model, reason}`. Transcribed in memory by local Whisper; audio is not stored. 503 if disabled, 413 too long, 422 invalid audio, 429 over the hourly limit |

## Other

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health |
