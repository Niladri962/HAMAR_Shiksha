# HAMAR SHIKSHA — Administrator Guide

For state, district and block education officers.

## Signing in
1. Open `/admin/login` (the blue page). Teachers and students cannot sign in here.
2. Enter your login ID and password. If you have set up two-step verification, enter the
   6-digit code from your authenticator app.
3. The first time you sign in with a password issued to you, you must choose a new one
   (at least 12 characters).
4. After 5 wrong attempts the account is locked for 15 minutes. Sessions end after 60 minutes.

**Set up two-step verification:** go to *Manage → Account security → Set up two-step
verification*. Add the key to an authenticator app, then enter the code it shows.

## What you can see
| Role | Scope |
|---|---|
| State administrator | All schools in Chhattisgarh; manages district and block administrators; audit log |
| District administrator | Schools in your district only |
| Block administrator | Schools in your block only |

The server enforces this. A school outside your area is reported as "not found", even if you
type its code directly.

## Overview tab
- **Search** by the 11-digit UDISE+ code, or by at least 3 letters of a school or village name.
- **Tiles:** active schools, coverage, teachers, students, and schools needing support.
- **Data status** of each school:
  - ✓ **Current**: data reported within the last 35 days.
  - ◷ **Stale**: the last report is older than that.
  - – **Missing**: nothing has been reported.
  - ≈ **Estimated**: not measured directly.

  Outcome figures use **current data only**; the line "Metrics based on N of M schools" says how
  many schools that is.
- **Charts:** monthly trends, scores by subject and by class, and (for the state) district tiles.
  Every chart has a *Show table* option.
- **Schools that may need support** are listed using published thresholds: student attendance
  under 75%, teacher attendance under 85%, participation under 60%, average score under 45%, or
  missing/stale reporting. Treat these as prompts to follow up, not judgements.

## Command Centre tab
- **Planned → taught → learned**, per district, block or school (one level below yours):
  - *Planned*: learning outcomes scheduled up to today in the academic calendar.
  - *Taught*: outcomes teachers marked as taught.
  - *Learned*: taught outcomes where the class average mastery is at least 60%.
- **Attendance and learning**: each dot is a school with current data, plus the correlation
  coefficient. This shows association, not cause.
- **Subject expertise gaps**: classes taught by a teacher with no recorded qualification and no
  completed micro-course in that subject. Use it to plan training; it is not a performance
  rating.
- **Participation**: teachers and students active in the last 7 days.
- **Devices and synchronisation**: devices used offline in your area, their last sync and any
  problems. **Revoke** a lost or shared device.

### Command Centre sections
- **Progress grades**: every school graded against its academic plan — **A** on track, **B** slightly
  behind, **C** behind plan, **D** needs support. The grade is the weaker of *taught* (share of due
  outcomes marked taught) and *learned* (share of taught outcomes the class has learned). Schools
  graded C or D are listed with a suggested corrective action. It grades progress, not teachers.
- **Attendance follow-up**: how many children need a follow-up now or should be watched (irregular,
  continuously absent, falling attendance), and the average score of children in each attendance
  band. You see counts only; the child's teachers see names and make the call or visit.
- **Digital infrastructure**: resources registered by schools, how much they are used against each
  school's weekly target, sessions linked to learning outcomes, sessions by subject, and the gaps
  (not working, unused, under-used). "Use and learning results" compares classes that use the
  resources regularly with those that do not — an association, not proof.
- **Recognition**: the most *improved* schools (gain, not rank) and their teachers' earned badges.
  Send a note of appreciation; it appears in the teacher's Recognition tab.
- The **Map & divisions** tab can also colour districts by *schools on track*, *digital resource use*
  and *children needing attendance follow-up*.

## Curriculum & AI tab
- **Gyan SLM status**: whether the local model is running, which model is used, and the
  retrieval mode.
- **Curriculum documents**: every source the tutor may cite. Demo primers are marked "demo -
  not SCERT".
- **Test retrieval**: type a question to see which pages would support an answer. If nothing
  supports it, the tutor will say it cannot verify an answer.
- **Ingest authorised material** (state only): upload SCERT PDFs (with a text layer), syllabi or
  learning-outcome frameworks, with their version and publisher. **Withdraw** removes a
  document from the tutor immediately.

## Schools tab (drill-down)
State → District → Block → School → Class. A class view shows only aggregated subject and topic
results. Classes with fewer than 5 students are hidden to protect privacy.

## Insights tab
Suggested interventions for schools, with the evidence and data used. Review each one:
**Approve** (add a note about the action you will take) or **Dismiss**. Suggestions never change
any record by themselves.

## Teacher reports tab
Monthly academic reports submitted by teachers in your area. Mark them *Acknowledged* once read.

## Reports tab
Choose a report, a format (CSV / Excel / PDF) and optionally a district or block. Reports
contain only your area and only aggregated figures. Every download is logged. Use CSV or Excel
when names are in Hindi; PDF shows Latin script only.

## Manage tab
1. **Register a school (Workflow A).** Enter the UDISE+ code and press *Look up in registry*.
   Check the details, choose the medium and classes, then press *Register*. The school stays
   *pending* until **another** administrator (district or state) activates it.
2. **Schools awaiting activation.** Activate after checking the details.
3. **Teachers awaiting verification (Workflow B).** Check the person's identity and posting
   against service records before you approve.
4. **Invite a teacher.** Enter the school code, employee ID and name. A temporary password is
   shown **once**; hand it over through an approved channel. The teacher can sign in only after
   verification.
5. **Administrator accounts** (state only). Create district or block administrators, or revoke
   access. Revoking signs the person out immediately.
6. **Import official school registry** (state only). Upload the UDISE+ CSV extract with its source
   and authorisation reference. Invalid, duplicate or mismatched rows are rejected and listed.

## Audit log (state only)
Shows who did what, when and from where, including denied access attempts. Filter by action
(for example `login`, `report`, `school`) or by outcome.

## Good practice
- Never share your password or your authenticator code.
- Download personal data only when needed, and store it securely.
- Confirm data that looks unusual with the school before acting on it.
