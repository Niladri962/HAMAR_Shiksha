/* Teacher dashboard. The API returns only the teacher's assigned classes
   and students; this file never decides access on its own. */
(async function () {
  "use strict";
  const HS = window.HS;
  const el = HS.el;
  const me0 = await HS.boot((m) => m.scope.school ? `${m.scope.school.name} (${m.scope.school.official_code})` : "Teacher");
  if (!me0) return;
  let T;
  try {
    T = await HS.api("/api/teacher/me");
    try { localStorage.setItem("hs_teacher_me", JSON.stringify(T)); } catch (_) { /* ignore */ }
  } catch (e) {
    try { T = JSON.parse(localStorage.getItem("hs_teacher_me") || "null"); } catch (_) { T = null; }
    if (!T || e.status !== 0) { HS.mount(document.getElementById("app"), HS.errorBox(e)); return; }
  }
  document.getElementById("scope-label").textContent = `${T.school.name} · UDISE ${T.school.official_code}`;
  if (!HS.offlineMode) HS.sync.pull();

  const app = document.getElementById("app");
  const view = el("div");
  const TABS = [{ id: "today", i18n: "tab_today" }, { id: "priorities", i18n: "tab_priorities" },
    { id: "attendance", i18n: "tab_attendance" }, { id: "saathi", i18n: "tab_saathi" },
    { id: "pariksha", i18n: "tab_pariksha" }, { id: "assignments", i18n: "tab_assignments" },
    { id: "assessments", i18n: "tab_assessments" }, { id: "progress", i18n: "tab_progress" },
    { id: "track", i18n: "tab_track" }, { id: "studenthelp", i18n: "tab_student_help" },
    { id: "digital", i18n: "tab_digital" }, { id: "recognition", i18n: "tab_recognition" },
    { id: "supervision", i18n: "tab_supervision" }, { id: "reports", i18n: "tab_reports" }];
  if (T.is_head_teacher) TABS.push({ id: "head", i18n: "tab_head" });
  let current = "today";
  const tabs = HS.tabs(app, TABS, (id) => { current = id; render(); });
  app.append(view);
  document.addEventListener("hs:lang", render);
  function render() {
    HS.load(view, { today, priorities, attendance, saathi, pariksha, assignments, assessments, progress, track, studenthelp,
      digital: digitalTab, recognition: recognitionTab, supervision, reports, head }[current]);
  }
  if (HS.offlineMode) setTimeout(() => tabs.select("attendance"), 0);

  const card = (title, ...body) => el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", null, title)), ...body);
  const classes = [...new Map(T.assignments.map((a) => [a.class_id, { id: a.class_id, label: a.class, grade: a.grade }])).values()];
  const subjectsOf = (classId) => T.assignments.filter((a) => a.class_id === classId);
  let selectedClass = classes[0] ? classes[0].id : null;

  function classPicker(onChange) {
    const sel = el("select", { "aria-label": "Class" }, classes.map((c) => el("option", { value: c.id, selected: c.id === selectedClass ? true : null }, c.label)));
    sel.addEventListener("change", () => { selectedClass = Number(sel.value); onChange(); });
    return sel;
  }
  const subjLabel = (a) => HS.pick(a.subject, a.subject_hi);
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  if (!classes.length) {
    HS.mount(view, HS.empty("No classes are assigned to you yet. Your administrator must approve your class assignments."));
    return;
  }

  // -------------------------------------------------------------- today --
  async function today(c) {
    const recs = await HS.api("/api/teacher/recommendations");
    const todayIdx = (new Date().getDay() + 6) % 7;
    const slots = T.timetable.filter((s) => s.day === todayIdx).sort((a, b) => a.period - b.period);
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "kpis" },
        el("div", { class: "kpi" }, el("div", { class: "label" }, "School"), el("div", { class: "value" }, T.school.name), el("div", { class: "sub" }, `${T.school.block}, ${T.school.district}`)),
        el("div", { class: "kpi" }, el("div", { class: "label" }, "My classes"), el("div", { class: "value num" }, classes.length)),
        el("div", { class: "kpi" }, el("div", { class: "label" }, "Suggestions to review"), el("div", { class: "value num" }, recs.class.length + recs.student.length))),
      el("div", { class: "grid grid-2" },
        card("My classes and subjects", HS.table([
          { label: "Class", key: "class" }, { label: "Subject", render: subjLabel },
          { label: "Students", key: "students", num: true }, { label: "Class teacher", render: (a) => (a.is_class_teacher ? "✓" : "") },
        ], T.assignments)),
        card("Today's timetable", slots.length ? HS.table([{ label: "Period", key: "period", num: true }, { label: "Class", key: "class" }, { label: "Subject", key: "subject" }], slots)
          : HS.empty(T.timetable.length ? "No periods today." : "No timetable has been entered for you."))),
      card("Teaching suggestions", el("p", { class: "small muted" }, "Suggestions are based on your students' recorded answers. You decide what to use."),
        recs.class.length ? el("ul", { class: "list" }, recs.class.slice(0, 5).map(recItem)) : HS.empty("No open class-level suggestions. Use 'Class progress' to analyse a class."))));
  }

  function recItem(r) {
    const note = el("input", { placeholder: "Note (optional)", maxlength: "1000", "aria-label": "Review note" });
    const act = async (decision) => {
      try { await HS.api(`/api/teacher/recommendations/${r.id}/review`, { method: "POST", body: { decision, note: note.value } }); HS.toast(HS.t(decision === "approve" ? "approved" : "dismissed")); render(); }
      catch (ex) { HS.toast(ex.message, true); }
    };
    return el("li", null,
      el("div", { class: "row" }, el("strong", null, r.title), HS.aiChip(r), r.student ? el("span", { class: "muted small" }, r.student.name) : null),
      el("p", null, r.summary),
      r.students_who_may_benefit && r.students_who_may_benefit.length
        ? el("p", { class: "small" }, el("span", { class: "muted" }, "May benefit from small-group practice: "), r.students_who_may_benefit.map((s) => s.name).join(", ")) : null,
      HS.evidence({ ...r.evidence, data_sources: r.data_sources, generated_by: r.generated_by }),
      r.status === "pending_review" ? el("div", { class: "row" }, note,
        el("button", { class: "primary", onclick: () => act("approve") }, HS.t("approve")),
        el("button", { onclick: () => act("dismiss") }, HS.t("dismiss"))) : el("span", { class: "chip ok-badge" }, r.status));
  }

  // --------------------------------------------------------- attendance --
  async function attendance(c) {
    const dateIn = el("input", { type: "date", value: HS.today(), max: HS.today(), "aria-label": "Date" });
    const holder = el("div");
    const load = () => HS.load(holder, async (h) => {
      let d;
      try { d = await HS.api(`/api/teacher/classes/${selectedClass}/attendance?on=${dateIn.value}`); }
      catch (e) {
        const b = await HS.sync.cached(); // offline: roster from the last sync bundle
        if (e.status !== 0 || !b || !b.rosters || !b.rosters[selectedClass]) throw e;
        d = { records: b.rosters[selectedClass].map((r) => ({ ...r, status: null })) };
      }
      const state = new Map(d.records.map((r) => [r.student, r.status || "present"]));
      const opts = [["present", "P"], ["absent", "A"], ["late", "L"], ["leave", "Lv"]];
      const tbl = HS.table([{ label: "Roll", key: "roll_no", num: true }, { label: "Name", key: "name" },
        { label: "Status", render: (r) => el("span", { class: "row", role: "radiogroup", "aria-label": r.name }, opts.map(([v, l]) => el("label", { class: "option" },
          el("input", { type: "radio", name: "att-" + r.student, value: v, checked: state.get(r.student) === v ? true : null,
            onchange: () => state.set(r.student, v) }), `${l}`))) }], d.records);
      const save = el("button", { class: "primary", onclick: async () => {
        save.disabled = true;
        const body = { date: dateIn.value, records: [...state].map(([student, status]) => ({ student, status })) };
        try {
          const out = await HS.sync.submit("attendance.mark", { class_id: selectedClass, ...body },
            () => HS.api(`/api/teacher/classes/${selectedClass}/attendance`, { method: "POST", body }));
          if (out.online) HS.toast(`Saved attendance for ${out.result.saved} students` + (out.result.note ? ` (${out.result.note})` : ""));
        } catch (ex) { HS.toast(ex.message, true); } finally { save.disabled = false; }
      } }, HS.t("save"));
      const allP = el("button", { onclick: () => { state.forEach((_, k) => state.set(k, "present")); h.querySelectorAll("input[value=present]").forEach((i) => { i.checked = true; }); } }, "Mark all present");
      HS.mount(h, el("p", { class: "small muted" }, "P = present, A = absent, L = late, Lv = leave. Records can be edited for 7 days."), tbl, el("div", { class: "row" }, allP, save));
    });
    dateIn.addEventListener("change", load);
    HS.mount(c, card(HS.t("tab_attendance"), el("div", { class: "row" }, classPicker(load), dateIn), holder));
    load();
  }

  // -------------------------------------------------------- assignments --
  async function assignments(c) {
    const list = el("div");
    const loadList = () => HS.load(list, async (h) => {
      const rows = await HS.api("/api/teacher/assignments?class_id=" + selectedClass);
      HS.mount(h, HS.table([{ label: "Title", key: "title" }, { label: "Subject", key: "subject" }, { label: "Due", render: (r) => HS.date(r.due_date) },
        { label: "Submitted", num: true, render: (r) => `${r.submitted}/${r.enrolled}` },
        { label: "", render: (r) => el("button", { onclick: () => showSubs(r) }, "View") }], rows));
    });
    async function showSubs(a) {
      const d = await HS.api(`/api/teacher/assignments/${a.id}/submissions`);
      HS.mount(list, el("button", { onclick: loadList }, "← " + HS.t("back")), el("h3", null, d.assignment.title),
        el("ul", { class: "list" }, d.submissions.map((s) => {
          const fb = el("input", { value: s.feedback || "", maxlength: "2000", "aria-label": "Feedback for " + s.name });
          return el("li", null, el("div", { class: "row" }, el("strong", null, `${s.roll_no ?? ""}. ${s.name}`),
            el("span", { class: "chip " + (s.submission_id ? "ok-badge" : "st-missing") }, s.submission_id ? "submitted" : "not submitted")),
          s.content ? el("p", null, s.content) : null,
          s.submission_id ? el("div", { class: "row" }, fb, el("button", { onclick: async () => {
            try { await HS.api(`/api/teacher/submissions/${s.submission_id}/feedback`, { method: "POST", body: { feedback: fb.value } }); HS.toast("Feedback saved"); }
            catch (ex) { HS.toast(ex.message, true); }
          } }, "Save feedback")) : null);
        })));
    }
    const subjSel = () => el("select", { name: "subject_id", required: true }, subjectsOf(selectedClass).map((a) => el("option", { value: a.subject_id }, subjLabel(a))));
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Subject"), subjSel()),
      el("div", null, el("label", null, "Title"), el("input", { name: "title", required: true, minlength: "3", maxlength: "200" })),
      el("div", null, el("label", null, "Topic"), el("input", { name: "topic", maxlength: "120" })),
      el("div", null, el("label", null, "Type"), el("select", { name: "kind" }, ["homework", "worksheet", "project"].map((k) => el("option", null, k)))),
      el("div", null, el("label", null, "Due date"), el("input", { name: "due_date", type: "date", min: HS.today() }))),
    el("div", { class: "field" }, el("label", null, "Instructions"), el("textarea", { name: "description", maxlength: "5000" })),
    el("button", { class: "primary", type: "submit" }, "Create assignment"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      try {
        await HS.api("/api/teacher/assignments", { method: "POST", body: { class_section_id: selectedClass, subject_id: Number(d.subject_id),
          title: d.title, topic: d.topic, kind: d.kind, due_date: d.due_date || null, description: d.description } });
        HS.toast("Assignment created"); form.reset(); loadList();
      } catch (ex) { HS.toast(ex.message, true); }
    });
    HS.mount(c, el("div", { class: "stack" },
      card(HS.t("tab_assignments"), el("div", { class: "row" }, classPicker(() => render())), list),
      card("New assignment", form)));
    loadList();
  }

  // -------------------------------------------------------- assessments --
  let draftQuestions = null; // handed over from the AI quiz tool
  async function assessments(c) {
    const list = el("div");
    const loadList = () => HS.load(list, async (h) => {
      const rows = await HS.api("/api/teacher/assessments?class_id=" + selectedClass);
      HS.mount(h, HS.table([{ label: "Title", key: "title" }, { label: "Subject", key: "subject" }, { label: "Type", key: "kind" },
        { label: "Results", key: "results", num: true }, { label: HS.t("avg_score"), num: true, render: (r) => HS.pct(r.avg_score_pct) },
        { label: "", render: (r) => el("span", { class: "row" }, r.ai_assisted ? el("span", { class: "chip ai-badge" }, "AI draft") : null,
          !r.published ? el("button", { onclick: async () => { await HS.api(`/api/teacher/assessments/${r.id}/publish`, { method: "POST" }); loadList(); } }, "Publish") : el("span", { class: "chip ok-badge" }, "published"),
          el("button", { onclick: () => showResults(r) }, "Results")) }], rows));
    });
    async function showResults(a) {
      const d = await HS.api(`/api/teacher/assessments/${a.id}/results`);
      const scoreInputs = new Map();
      HS.mount(list, el("button", { onclick: loadList }, "← " + HS.t("back")), el("h3", null, d.assessment.title),
        HS.table([{ label: "Roll", key: "roll_no", num: true }, { label: "Name", key: "name" },
          { label: "Score", num: true, render: (r) => r.score !== null ? `${r.score}/${r.max_score}` :
            (a.kind === "offline" ? (() => { const i = el("input", { type: "number", min: "0", max: String(d.assessment.max_score), step: "0.5", "aria-label": "Score for " + r.name }); scoreInputs.set(r.student, i); return i; })() : "—") }],
        d.results),
        a.kind === "offline" ? el("button", { class: "primary", onclick: async () => {
          const scores = [...scoreInputs].filter(([, i]) => i.value !== "").map(([student, i]) => ({ student, score: Number(i.value) }));
          try { await HS.api(`/api/teacher/assessments/${a.id}/scores`, { method: "POST", body: { scores } }); HS.toast("Marks saved"); showResults(a); }
          catch (ex) { HS.toast(ex.message, true); }
        } }, "Save marks") : null);
    }

    // Question editor
    const qBox = el("div");
    const questions = draftQuestions ? draftQuestions.map((q) => ({ ...q })) : [];
    const fromAI = !!draftQuestions;
    draftQuestions = null;
    function drawQuestions() {
      HS.mount(qBox, questions.map((q, i) => el("fieldset", { class: "card" }, el("legend", null, `Q${i + 1}`),
        el("input", { value: q.text, "aria-label": `Question ${i + 1}`, oninput: (e) => { q.text = e.target.value; } }),
        q.options.map((o, oi) => el("label", { class: "option" },
          el("input", { type: "radio", name: "ans" + i, checked: q.answer_index === oi ? true : null, onchange: () => { q.answer_index = oi; }, "aria-label": "Correct answer" }),
          el("input", { value: o, "aria-label": `Option ${oi + 1}`, oninput: (e) => { q.options[oi] = e.target.value; } }))),
        el("button", { type: "button", class: "danger", onclick: () => { questions.splice(i, 1); drawQuestions(); } }, "Remove"))),
      el("button", { type: "button", onclick: () => { questions.push({ text: "", options: ["", "", "", ""], answer_index: 0, topic: "" }); drawQuestions(); } }, "+ Add question"));
    }
    drawQuestions();
    const kindSel = el("select", { name: "kind" }, ["quiz", "unit_test", "baseline", "offline"].map((k) => el("option", null, k)));
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Subject"), el("select", { name: "subject_id" }, subjectsOf(selectedClass).map((a) => el("option", { value: a.subject_id }, subjLabel(a))))),
      el("div", null, el("label", null, "Title"), el("input", { name: "title", required: true, minlength: "3" })),
      el("div", null, el("label", null, "Topic"), el("input", { name: "topic", value: questions[0]?.topic || "" })),
      el("div", null, el("label", null, "Type"), kindSel),
      el("div", null, el("label", null, "Max marks (offline only)"), el("input", { name: "max_score", type: "number", min: "1" })),
      el("div", null, el("label", { class: "option" }, el("input", { type: "checkbox", name: "publish" }), "Publish now"))),
    fromAI ? el("p", { class: "chip ai-badge" }, "AI draft — check every question and answer key before publishing") : null,
    qBox, el("button", { class: "primary", type: "submit" }, "Create assessment"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      const body = { class_section_id: selectedClass, subject_id: Number(d.subject_id), title: d.title, topic: d.topic, kind: d.kind,
        publish: !!d.publish, ai_assisted: fromAI,
        questions: d.kind === "offline" ? [] : questions.map((q) => ({ ...q, topic: q.topic || d.topic })),
        max_score: d.kind === "offline" ? Number(d.max_score) : null };
      try { const r = await HS.api("/api/teacher/assessments", { method: "POST", body }); HS.toast(`Created with ${r.questions} questions`); render(); }
      catch (ex) { HS.toast(ex.message, true); }
    });
    HS.mount(c, el("div", { class: "stack" }, card(HS.t("tab_assessments"), el("div", { class: "row" }, classPicker(() => render())), list),
      card("New assessment", form)));
    loadList();
  }

  // ----------------------------------------------------------- progress --
  async function progress(c) {
    const d = await HS.api(`/api/teacher/classes/${selectedClass}/performance`);
    const parts = [el("div", { class: "row" }, classPicker(() => render()),
      el("button", { onclick: async () => {
        try { const r = await HS.api("/api/teacher/recommendations/refresh", { method: "POST", body: { class_id: selectedClass } }); HS.toast(`${r.generated_or_updated} suggestions updated`); render(); }
        catch (ex) { HS.toast(ex.message, true); }
      } }, "Analyse learning gaps"),
      el("span", { class: "spacer" }),
      ["csv", "xlsx", "pdf"].map((f) => el("button", { onclick: () => HS.download(`/api/teacher/classes/${selectedClass}/export?format=${f}`) }, "⇩ " + f.toUpperCase())))];
    parts.push(el("div", { class: "kpis" },
      el("div", { class: "kpi" }, el("div", { class: "label" }, "Students"), el("div", { class: "value num" }, d.students)),
      el("div", { class: "kpi" }, el("div", { class: "label" }, HS.t("student_attendance") + " (30d)"), el("div", { class: "value num" }, HS.pct(d.attendance_rate_30d)))));
    d.subjects.forEach((s) => {
      parts.push(card(`${s.name} — ${HS.t("avg_score")} ${HS.pct(s.avg_score_pct)}`,
        s.topics.length ? HS.charts.bars(s.topics.map((t) => ({ label: t.topic, value: t.avg_mastery, sub: `${t.students} students` })), { threshold: 0.6, thresholdLabel: "60% mastery" })
          : HS.empty("No answers recorded yet.")));
    });
    // Student × topic grid
    const topicKeys = [...new Set(d.students.flatMap((s) => Object.keys(s.topics)))].sort();
    if (topicKeys.length) {
      const subjectName = Object.fromEntries(d.subjects.map((s) => [String(s.subject_id), s.code]));
      const head = el("tr", null, el("th", { scope: "col" }, "Student"), topicKeys.map((k) => { const [sid, topic] = k.split(/:(.*)/s); return el("th", { scope: "col" }, `${subjectName[sid] || ""} · ${topic}`); }));
      const body = d.students.map((s) => el("tr", { class: "clickable", tabindex: "0", onclick: () => studentDetail(s.student) },
        el("td", null, `${s.roll_no ?? ""}. ${s.name}`),
        topicKeys.map((k) => {
          const v = s.topics[k];
          return el("td", { class: "cell" + (v ? " seq-" + Math.max(1, Math.min(7, Math.round(v.mastery * 6) + 1)) : "") }, v ? HS.pct(v.mastery) : "—");
        })));
      parts.push(card("Topic mastery by student", el("p", { class: "small muted" }, "Share of questions answered correctly per topic. A working estimate for planning — not a label. Click a student for details."),
        el("div", { class: "table-wrap heat" }, el("table", null, el("thead", null, head), el("tbody", null, body)))));
    }
    const recs = await HS.api("/api/teacher/recommendations");
    parts.push(card("Suggestions for this class", el("ul", { class: "list" },
      [...recs.class.filter((r) => r.target_id === selectedClass), ...recs.student].map(recItem)), ));
    HS.mount(c, el("div", { class: "stack" }, parts));
  }

  async function studentDetail(id) {
    HS.load(view, async (c) => {
      const d = await HS.api(`/api/teacher/students/${id}/progress`);
      const reset = el("button", { onclick: async () => {
        if (!confirm("Issue a new temporary password for this student?")) return;
        try {
          const r = await HS.api(`/api/teacher/students/${id}/reset-credentials`, { method: "POST" });
          HS.mount(resetOut, el("div", { class: "card" }, el("p", null, r.note), el("div", null, "Login ID: ", el("span", { class: "secret" }, r.login_id)),
            el("div", null, "Temporary password: ", el("span", { class: "secret" }, r.temporary_password))));
        } catch (ex) { HS.toast(ex.message, true); }
      } }, "Reset student password");
      const resetOut = el("div");
      HS.mount(c, el("div", { class: "stack" }, el("button", { onclick: render }, "← " + HS.t("back")),
        card(d.student.name, el("div", { class: "row" }, reset), resetOut,
          d.topics.length ? HS.charts.bars(d.topics.map((t) => ({ label: `${t.subject} · ${t.topic}`, value: t.mastery, sub: `${t.correct}/${t.attempted} correct` })), { threshold: 0.6 }) : HS.empty()),
        card("Recent results", HS.table([{ label: "Assessment", key: "assessment" }, { label: "Subject", key: "subject" },
          { label: "Score", num: true, render: (r) => `${r.score}/${r.max_score}` }, { label: "Date", render: (r) => HS.date(r.submitted_at) }], d.results)),
        card("Suggestions", d.recommendations.length ? el("ul", { class: "list" }, d.recommendations.map(recItem)) : HS.empty())));
    });
  }

  // ---------------------------------------------------------- priorities --
  async function priorities(c) {
    const d = await HS.api("/api/teacher/priorities");
    HS.mount(c, card(`${HS.t("tab_priorities")} (${HS.date(d.week_of)})`,
      el("p", { class: "small muted" }, "Students whose recorded answers show a learning outcome needing practice, most need first. " +
        "Each line shows the evidence. Use it to plan small-group time - it is not a label."),
      d.students.length ? el("ul", { class: "list" }, d.students.map((s) => el("li", null,
        el("div", { class: "row" }, el("strong", null, `${s.roll_no ?? ""}. ${s.name}`), el("span", { class: "muted small" }, s.class),
          el("span", { class: "spacer" }), el("button", { class: "link", onclick: () => studentDetail(s.student) }, "Open record")),
        el("ul", { class: "small" }, s.needs.map((n) => el("li", null, el("strong", null, `${n.subject} · ${n.topic}`), ` — ${HS.pct(n.mastery)} (${n.evidence})`,
          el("span", { class: "muted" }, ` · ${n.code}: ${n.description}`))))))) : HS.empty("No students flagged this week.")));
  }

  // ------------------------------------------------------- Teacher Saathi --
  let saathiSection = "plan";
  // ------------------------------------------------- student help (doubts, pairs) --
  async function studenthelp(c) {
    const [doubts, pairs] = await Promise.all([HS.api(`/api/teacher/help/doubts?class_id=${selectedClass}`),
      HS.api(`/api/teacher/help/classes/${selectedClass}/pairs`)]);
    const post = async (url, body) => {
      try { await HS.api(url, { method: "POST", body }); render(); } catch (ex) { HS.toast(ex.message, true); }
    };
    const doubtCard = (d) => {
      const ta = el("textarea", { rows: "2", maxlength: "800", "aria-label": "Reply" });
      return el("li", { class: "doubt" + (d.status === "open" ? " open" : "") },
        el("div", { class: "row" },
          el("span", { class: "chip " + (d.audience === "teacher" ? "ai-badge" : "ok-badge") }, d.audience === "teacher" ? "To you" : "Class board"),
          el("strong", null, d.asker), el("span", { class: "small muted" }, `${d.subject || ""} ${d.topic ? "· " + d.topic : ""}`),
          el("span", { class: "spacer" }), el("span", { class: "chip " + (d.status === "open" ? "st-stale" : d.status === "hidden" ? "st-missing" : "st-current") }, d.status)),
        el("p", { class: "doubt-body" }, d.body),
        d.replies.length ? el("ul", { class: "replies" }, d.replies.map((r) => el("li", { class: r.hidden ? "hidden-reply" : "" },
          el("div", { class: "row" }, el("strong", { class: "small" }, `${r.author}${r.role === "teacher" ? " (teacher)" : ""}`),
            r.accepted ? el("span", { class: "chip verified-badge" }, "helpful") : null,
            r.reported ? el("span", { class: "chip flag" }, "reported") : null, r.hidden ? el("span", { class: "chip st-missing" }, "hidden") : null,
            el("span", { class: "spacer" }),
            !r.accepted && !r.hidden && r.role === "student" ? el("button", { class: "small-btn", onclick: () => post(`/api/teacher/help/replies/${r.id}/accept`) }, "Mark helpful") : null,
            !r.hidden ? el("button", { class: "small-btn danger", onclick: () => post(`/api/teacher/help/replies/${r.id}/hide`) }, "Hide") : null),
          el("p", { class: "small" }, r.body)))) : null,
        el("div", { class: "row" }, ta,
          el("button", { class: "primary small-btn", onclick: () => ta.value.trim().length > 1 && post(`/api/teacher/help/doubts/${d.id}/replies`, { body: ta.value.trim() }) }, "Reply"),
          d.status !== "resolved" ? el("button", { class: "small-btn", onclick: () => post(`/api/teacher/help/doubts/${d.id}/status`, { status: "resolved" }) }, "Resolve") : null,
          d.status !== "hidden" && d.audience === "class" ? el("button", { class: "small-btn danger", onclick: () => post(`/api/teacher/help/doubts/${d.id}/status`, { status: "hidden" }) }, "Hide doubt") : null));
    };
    const open = doubts.filter((d) => d.status === "open").length;
    const reported = doubts.reduce((n, d) => n + d.replies.filter((r) => r.reported && !r.hidden).length, 0);
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "row" }, el("h2", null, "Student help"), el("span", { class: "spacer" }), classPicker(render)),
      el("div", { class: "kpis" },
        el("div", { class: "kpi" }, el("div", { class: "label" }, "Open doubts"), el("div", { class: "value num" }, String(open))),
        el("div", { class: "kpi" }, el("div", { class: "label" }, "Reported answers"), el("div", { class: "value num" }, String(reported))),
        el("div", { class: "kpi" }, el("div", { class: "label" }, "Active study pairs"), el("div", { class: "value num" }, String(pairs.pairs.length)))),
      card("Doubts from your students",
        el("p", { class: "small muted" }, "Students can ask you privately or ask the class board, where classmates answer. You can answer, mark a classmate's answer as helpful (it earns them help points), hide anything unsuitable and resolve doubts. Posts are screened for personal information and unkind words before others see them."),
        doubts.length ? el("ul", { class: "list doubts" }, doubts.map(doubtCard)) : HS.empty("No doubts yet.")),
      card("Study buddies (peer learning)",
        el("p", { class: "small muted" }, pairs.rule),
        pairs.pairs.length ? HS.table([{ label: "Topic", key: "topic" }, { label: "Helper", key: "helper" }, { label: "Learner", key: "learner" },
          { label: "Plan", key: "note" }, { label: "", render: (sp) => el("button", { class: "small-btn", onclick: () => post(`/api/teacher/help/pairs/${sp.id}/end`) }, "End") }], pairs.pairs)
          : HS.empty("No active pairs."),
        el("h3", null, "Suggestions"),
        pairs.suggestions.length ? HS.table([{ label: "Topic", render: (s) => `${s.subject || ""} · ${s.topic}` },
          { label: "Helper (mastery)", render: (s) => `${s.helper.name} (${HS.pct(s.helper.mastery)})` },
          { label: "Learner (mastery)", render: (s) => `${s.learner.name} (${HS.pct(s.learner.mastery)})` },
          { label: "", render: (s) => el("button", { class: "primary small-btn", onclick: () => post(`/api/teacher/help/classes/${selectedClass}/pairs`,
            { helper: s.helper.public_id, learner: s.learner.public_id, topic: s.topic, subject_id: s.subject_id,
              note: `Practise ${s.topic} together for 15 minutes, twice this week.` }) }, "Create pair") }], pairs.suggestions)
          : HS.empty("No suggestions: not enough assessed answers yet, or everyone is at a similar level."))));
  }

  async function saathi(c) {
    const sections = [["plan", "Academic plan"], ["plans", "Lesson plans"], ["ask", "Ask Saathi"], ["worksheet", "Worksheets"],
      ["remediation", "Remediation"], ["training", "Micro-courses"]];
    if (T.is_head_teacher) sections.push(["substitute", "Substitute lesson"]);
    const nav = el("div", { class: "row", role: "group", "aria-label": "Teacher Saathi sections" }, sections.map(([id, label]) =>
      el("button", { class: saathiSection === id ? "primary" : "", "aria-pressed": String(saathiSection === id),
        onclick: () => { saathiSection = id; render(); } }, label)));
    const body = el("div");
    HS.mount(c, el("div", { class: "stack" }, el("h2", null, HS.module("teacher", "Teacher Saathi")),
      el("p", { class: "small muted" }, `Drafts from ${HS.module("slm", "Gyan SLM")} are grounded in the approved textbooks and always need your review. No student data is sent to the model.`),
      nav, body));
    const fns = { plan: saathiPlan, plans: saathiPlans, ask: saathiAsk, worksheet: saathiWorksheet, remediation: saathiRemediation,
      training: saathiTraining, substitute: saathiSubstitute };
    await HS.load(body, fns[saathiSection]);
  }

  function subjectPicker(onChange) {
    const opts = subjectsOf(selectedClass);
    if (!opts.some((a) => a.subject_id === selectedSubject)) selectedSubject = opts[0] && opts[0].subject_id;
    const sel = el("select", { "aria-label": "Subject" }, opts.map((a) => el("option", { value: a.subject_id, selected: a.subject_id === selectedSubject ? true : null }, subjLabel(a))));
    sel.addEventListener("change", () => { selectedSubject = Number(sel.value); onChange(); });
    return sel;
  }
  let selectedSubject = null;
  let planScope = "month";

  async function saathiPlan(c) {
    subjectPicker(() => {});
    const [d, dig] = await Promise.all([HS.api(`/api/teacher/saathi/plan?class_id=${selectedClass}&subject_id=${selectedSubject}&scope=${planScope}`),
      HS.offlineMode ? Promise.resolve({ resources: [] }) : digitalResources().catch(() => ({ resources: [] }))]);
    const working = dig.resources.filter((r) => r.status === "working");
    const usedSel = () => working.length ? el("select", { "aria-label": "Digital resource used", class: "compact" },
      el("option", { value: "" }, "No digital resource"), working.map((r) => el("option", { value: r.id }, "Used: " + r.label))) : el("span");
    const s = d.summary;
    const bar = (v) => HS.charts.meter(v, "");
    const scopeSel = el("select", { "aria-label": "Plan range", onchange: (e) => { planScope = e.target.value; render(); } },
      [["week", "This week"], ["month", "This month"], ["year", "Whole year"]].map(([v, l]) => el("option", { value: v, selected: planScope === v ? true : null }, l)));
    const list = el("div", null, d.milestones.length ? d.milestones.map((m) => el("div", { class: "milestone" + (m.status === "taught" ? " taught" : "") },
      el("span", { class: "small muted num" }, HS.date(m.week)),
      el("div", { class: "m-main" }, el("strong", null, `${m.code} · ${m.topic}`), el("div", { class: "small muted" }, HS.pick(m.description, m.description_hi)),
        m.learned ? el("div", { class: "small" }, `Class mastery ${HS.pct(m.learned.avg_mastery)} (${m.learned.students_assessed} assessed)`) : null),
      m.overdue ? el("span", { class: "overdue" }, "overdue") : null,
      m.status === "taught" ? el("span", { class: "chip verified-badge" }, "taught " + HS.date(m.taught_at))
        : el("div", { class: "row" }, usedSel(), el("button", { class: "primary", onclick: async (e) => {
          const rid = e.currentTarget.previousSibling && e.currentTarget.previousSibling.value;
          const out = await HS.sync.submit("milestone.taught", { milestone_id: m.id },
            () => HS.api(`/api/teacher/saathi/milestones/${m.id}/taught`, { method: "POST", body: rid ? { digital_resource_id: Number(rid) } : {} }));
          if (out.online) HS.toast(rid ? "Recorded as taught, with digital session" : "Recorded as taught");
          render();
        } }, "✓ Mark taught")))) : HS.empty("No milestones in this range."));
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "row" }, classPicker(() => render()), subjectPicker(() => render()), scopeSel),
      card("Planned · taught · learned (to date)", el("div", { class: "ptl" },
        el("span", null, "Planned"), bar(1), el("span", { class: "num" }, s.planned_due),
        el("span", null, "Taught"), bar(s.taught_rate), el("span", { class: "num" }, `${s.taught} (${HS.pct(s.taught_rate)})`),
        el("span", null, "Learned"), bar(s.learned_rate), el("span", { class: "num" }, `${s.learned}/${s.assessed} (${HS.pct(s.learned_rate)})`)),
      el("p", { class: "small muted" }, s.basis + (d.calendar ? ` · Calendar ${d.calendar.academic_year}${d.calendar.is_demo ? " (demo dates)" : ""}` : ""))),
      card(`Milestones (${planScope})`, list)));
  }

  async function saathiPlans(c) {
    subjectPicker(() => {});
    const [plans, los] = await Promise.all([HS.api(`/api/teacher/saathi/lesson-plans?class_id=${selectedClass}`),
      HS.api(`/api/teacher/saathi/learning-outcomes?subject_id=${selectedSubject}&grade=${classes.find((x) => x.id === selectedClass).grade}`)]);
    const out = el("div");
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Learning outcome"), el("select", { name: "lo" }, el("option", { value: "" }, "—"),
        los.map((lo) => el("option", { value: lo.id, dataset: { topic: lo.topic } }, `${lo.code} · ${lo.topic}`)))),
      el("div", null, el("label", null, "Topic"), el("input", { name: "topic", required: true, minlength: "2", maxlength: "120" })),
      el("div", null, el("label", null, "Language"), el("select", { name: "language" }, el("option", { value: "hi" }, "हिंदी"), el("option", { value: "en" }, "English"))),
      el("div", null, el("label", null, "Minutes"), el("input", { name: "minutes", type: "number", min: "10", max: "120", value: "40" }))),
    el("div", { class: "field" }, el("label", null, "Notes (optional)"), el("input", { name: "notes", maxlength: "500", placeholder: "e.g. multi-grade class; few notebooks" })),
    el("button", { class: "primary", type: "submit" }, "Draft lesson plan"));
    form.querySelector("[name=lo]").addEventListener("change", (e) => {
      const o = e.target.selectedOptions[0];
      if (o && o.dataset.topic) form.querySelector("[name=topic]").value = o.dataset.topic;
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      HS.mount(out, HS.loading());
      try {
        const lp = await HS.api("/api/teacher/saathi/lesson-plans/generate", { method: "POST", body: { class_id: selectedClass,
          subject_id: selectedSubject, topic: d.topic, learning_outcome_id: d.lo ? Number(d.lo) : null, language: d.language,
          minutes: Number(d.minutes), notes: d.notes } });
        HS.mount(out, planEditor(lp));
      } catch (ex) { HS.mount(out, HS.errorBox(ex)); }
    });
    HS.mount(c, el("div", { class: "stack" }, el("div", { class: "row" }, classPicker(() => render()), subjectPicker(() => render())),
      card("Draft a curriculum-grounded lesson plan", form, out),
      card("Lesson plans for this class", plans.length ? el("ul", { class: "list" }, plans.map((lp) => el("li", null,
        el("details", null, el("summary", null, el("strong", null, lp.title), " ", el("span", { class: "chip " + (lp.status === "approved" ? "verified-badge" : "draft-badge") }, lp.status),
          lp.ai_generated ? el("span", { class: "chip ai-badge" }, HS.t("ai_generated")) : null), planEditor(lp))))) : HS.empty())));
  }

  function planEditor(lp) {
    const title = el("input", { value: lp.title, maxlength: "200", "aria-label": "Title" });
    const body = el("textarea", { rows: "16", "aria-label": "Lesson plan" });
    body.value = lp.body;
    return el("div", { class: "stack" },
      el("div", { class: "row" }, el("span", { class: "chip " + (lp.ai_generated ? "ai-badge" : "st-stale") }, lp.ai_generated ? `${HS.t("ai_generated")} · ${lp.model}` : "Template / teacher-written"),
        el("span", { class: "chip " + (lp.status === "approved" ? "verified-badge" : "draft-badge") }, lp.status)),
      lp.note ? el("p", { class: "small form-error" }, lp.note) : null,
      title, body, HS.citations(lp.sources),
      el("div", { class: "row" },
        el("button", { onclick: async () => {
          try { await HS.api(`/api/teacher/saathi/lesson-plans/${lp.id}`, { method: "PUT", body: { title: title.value, body: body.value } }); HS.toast("Saved as draft"); }
          catch (ex) { HS.toast(ex.message, true); }
        } }, HS.t("save")),
        el("button", { class: "primary", onclick: async () => {
          try {
            await HS.api(`/api/teacher/saathi/lesson-plans/${lp.id}`, { method: "PUT", body: { title: title.value, body: body.value } });
            await HS.api(`/api/teacher/saathi/lesson-plans/${lp.id}/approve`, { method: "POST" });
            HS.toast("Approved"); render();
          } catch (ex) { HS.toast(ex.message, true); }
        } }, HS.t("approve"))));
  }

  async function saathiAsk(c) {
    const out = el("div", { "aria-live": "polite" });
    const langSel = el("select", { name: "language" }, el("option", { value: "en" }, "English"), el("option", { value: "hi" }, "हिंदी"));
    const question = el("textarea", { name: "question", required: true, minlength: "3", maxlength: "600", rows: "3" });
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Class level"), el("input", { name: "grade", type: "number", min: "1", max: "12", value: String(classes[0].grade) })),
      el("div", null, el("label", null, "Language"), langSel)),
    el("div", { class: "field" }, el("label", null, "Question about the curriculum"), question,
      HS.voice ? el("div", { class: "row voice-row" }, HS.voice.micButton(question, { lang: () => langSel.value })) : null),
    el("button", { class: "primary", type: "submit" }, "Ask"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      HS.mount(out, HS.loading());
      try {
        const r = await HS.api("/api/teacher/saathi/ask", { method: "POST", body: { question: d.question, grade: Number(d.grade), language: d.language } });
        HS.mount(out, el("div", { class: "card" }, el("div", { class: "row" },
          el("span", { class: "chip " + (r.verified ? "verified-badge" : "unverified-badge") }, r.verified ? HS.t("verified") : HS.t("not_verified")),
          r.ai_generated ? el("span", { class: "chip ai-badge" }, `${r.model} · ${r.latency_ms} ms`) : el("span", { class: "chip st-stale" }, "textbook excerpt")),
        el("p", { class: "msg" }, r.answer), HS.voice ? HS.voice.speakButton(r.answer) : null, HS.citations(r.citations),
        r.related && r.related.length ? el("p", { class: "small muted" }, "Closest passages: " + r.related.map((x) => x.citation).join("; ")) : null));
      } catch (ex) { HS.mount(out, HS.errorBox(ex)); }
    });
    HS.mount(c, card("Ask Saathi (answers only from approved textbooks)", form, out));
  }

  async function saathiWorksheet(c) {
    const out = el("div");
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Subject"), el("select", { name: "subject_id" }, T.assignments.filter((a, i, arr) =>
        arr.findIndex((b) => b.subject_id === a.subject_id && b.grade === a.grade) === i).map((a) => el("option", { value: `${a.subject_id}:${a.grade}` }, `${subjLabel(a)} · Class ${a.grade}`)))),
      el("div", null, el("label", null, "Topic"), el("input", { name: "topic", required: true, minlength: "2" })),
      el("div", null, el("label", null, "Language"), el("select", { name: "language" }, el("option", { value: "hi" }, "हिंदी"), el("option", { value: "en" }, "English"))),
      el("div", null, el("label", null, "Questions"), el("input", { name: "count", type: "number", min: "1", max: "10", value: "5" })),
      el("div", null, el("button", { class: "primary", type: "submit" }, "Draft questions"))));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      const [sid, grade] = d.subject_id.split(":").map(Number);
      HS.mount(out, HS.loading());
      try {
        const r = await HS.api("/api/teacher/saathi/worksheet", { method: "POST", body: { subject_id: sid, grade, topic: d.topic, language: d.language, count: Number(d.count) } });
        HS.mount(out, el("p", { class: "small muted" }, r.notice), r.note ? el("p", { class: "small form-error" }, r.note) : null,
          el("ol", null, r.drafts.map((q) => el("li", null, q.text, el("ul", null, q.options.map((o, i) => el("li", null, i === q.correct_option ? el("strong", null, o + " ✓") : o))),
            q.explanation ? el("div", { class: "small muted" }, q.explanation) : null,
            el("button", { onclick: async (ev) => {
              try { await HS.api(`/api/teacher/pariksha/bank/${q.id}/approve`, { method: "POST" }); ev.target.replaceWith(el("span", { class: "chip verified-badge" }, "approved")); }
              catch (ex) { HS.toast(ex.message, true); }
            } }, "Approve into question bank")))),
          HS.citations(r.sources));
      } catch (ex) { HS.mount(out, HS.errorBox(ex)); }
    });
    HS.mount(c, card("Worksheet questions from the textbook", form, out));
  }

  async function saathiRemediation(c) {
    const [plans, recs] = await Promise.all([HS.api(`/api/teacher/saathi/remediation?class_id=${selectedClass}`), HS.api("/api/teacher/recommendations")]);
    const gaps = recs.class.filter((r) => r.target_id === selectedClass);
    HS.mount(c, el("div", { class: "stack" }, el("div", { class: "row" }, classPicker(() => render())),
      card("Learning gaps in this class", gaps.length ? el("ul", { class: "list" }, gaps.map((g) => el("li", null,
        el("strong", null, g.title), el("p", { class: "small" }, g.summary),
        el("button", { class: "primary", onclick: async (ev) => {
          ev.target.disabled = true;
          try { await HS.api(`/api/teacher/saathi/remediation/from-recommendation/${g.id}`, { method: "POST" }); render(); }
          catch (ex) { HS.toast(ex.message, true); ev.target.disabled = false; }
        } }, "Draft remediation plan")))) : HS.empty("No open class-level gaps. Use Class progress → Analyse learning gaps.")),
      card("Remediation plans", plans.length ? el("ul", { class: "list" }, plans.map((p) => {
        const ta = el("textarea", { rows: "8", "aria-label": "Plan" });
        ta.value = p.plan_text;
        const act = (status) => async () => {
          try { await HS.api(`/api/teacher/saathi/remediation/${p.id}/status`, { method: "POST", body: { status, plan_text: ta.value } }); render(); }
          catch (ex) { HS.toast(ex.message, true); }
        };
        return el("li", null, el("div", { class: "row" }, el("strong", null, p.topic), el("span", { class: "chip draft-badge" }, p.status),
          p.ai_generated ? el("span", { class: "chip ai-badge" }, HS.t("ai_generated")) : null),
        el("p", { class: "small" }, "Students: " + (p.students.join(", ") || "—")), el("p", { class: "small muted" }, p.evidence.summary || ""),
        ta, HS.citations(p.sources),
        el("div", { class: "row" }, p.status === "proposed" ? el("button", { class: "primary", onclick: act("approved") }, HS.t("approve")) : null,
          p.status === "approved" ? el("button", { class: "primary", onclick: act("completed") }, "Mark completed") : null,
          p.status !== "dismissed" && p.status !== "completed" ? el("button", { onclick: act("dismissed") }, HS.t("dismiss")) : null));
      })) : HS.empty())));
  }

  async function saathiTraining(c) {
    const mods = await HS.api("/api/teacher/saathi/training");
    const holder = el("div");
    async function open(m) {
      const d = await HS.api(`/api/teacher/saathi/training/${m.id}`);
      const f = el("form", null, d.content.check.map((q, i) => el("fieldset", { class: "field" }, el("legend", null, q.q),
        q.options.map((o, oi) => el("label", { class: "option" }, el("input", { type: "radio", name: "q" + i, value: String(oi), required: true }), o)))),
      el("button", { class: "primary", type: "submit" }, "Complete"));
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const answers = d.content.check.map((_, i) => Number(new FormData(f).get("q" + i)));
        const r = await HS.api(`/api/teacher/saathi/training/${m.id}/complete`, { method: "POST", body: { answers } });
        HS.toast(`Completed: ${r.correct}/${r.total}`); render();
      });
      HS.mount(holder, card(HS.pick(d.title, d.title_hi), d.is_demo ? el("span", { class: "chip demo-badge" }, "demo course") : null,
        d.content.sections.map((s) => el("div", null, el("h3", null, s.heading), el("p", null, s.body))), el("h3", null, "Check your understanding"), f));
    }
    HS.mount(c, el("div", { class: "stack" }, card("Micro-courses", HS.table([
      { label: "Course", render: (m) => el("span", null, HS.pick(m.title, m.title_hi), m.recommended ? el("span", { class: "chip st-stale" }, "recommended for you") : null,
        m.recommended && m.reasons.length ? el("div", { class: "small muted" }, m.reasons.join(" ")) : null) },
      { label: "Area", key: "area" }, { label: "Minutes", key: "minutes", num: true },
      { label: "Status", render: (m) => (m.completed ? `✓ ${HS.pct(m.score)}` : "—") },
    ], mods, { onRow: open })), holder));
  }

  async function saathiSubstitute(c) {
    const [plans, cls, dig] = await Promise.all([HS.api("/api/teacher/saathi/approved-plans"), HS.api("/api/teacher/school/classes"),
      digitalResources().catch(() => ({ resources: [] }))]);
    const screens = dig.resources.filter((r) => r.status === "working");
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Class"), el("select", { name: "class_id" }, cls.map((x) => el("option", { value: x.id }, x.label)))),
      el("div", null, el("label", null, "Approved lesson plan"), el("select", { name: "plan" }, plans.map((p) => el("option", { value: p.id }, `Class ${p.grade} · ${p.title}`)))),
      screens.length ? el("div", null, el("label", null, "Shown on"), el("select", { name: "resource" }, el("option", { value: "" }, "Blackboard / print"),
        screens.map((r) => el("option", { value: r.id }, r.label)))) : null,
      el("div", null, el("label", null, "Note for students"), el("input", { name: "notes", maxlength: "500" }))),
    el("button", { class: "primary", type: "submit", disabled: plans.length ? null : true }, "Launch supervised lesson"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      try { const r = await HS.api("/api/teacher/saathi/substitute", { method: "POST", body: { class_id: Number(d.class_id), lesson_plan_id: Number(d.plan), notes: d.notes,
        digital_resource_id: d.resource ? Number(d.resource) : null } }); HS.toast(`Launched for ${r.class}`); }
      catch (ex) { HS.toast(ex.message, true); }
    });
    HS.mount(c, card("Substitute lesson (teacher absent)", el("p", { class: "small muted" },
      "Launch an approved lesson plan for a class whose subject teacher is absent. Students see it on their home screen. A school supervisor must stay with the class; the AI does not replace a teacher."), form));
  }

  // ----------------------------------------------------------- Pariksha --
  let parikshaSection = "review";
  async function pariksha(c) {
    const sections = [["review", "Review queue"], ["bank", "Question bank"], ["build", "Build assessment"], ["analysis", "Competencies & misconceptions"]];
    const nav = el("div", { class: "row", role: "group", "aria-label": "Pariksha sections" }, sections.map(([id, label]) =>
      el("button", { class: parikshaSection === id ? "primary" : "", "aria-pressed": String(parikshaSection === id), onclick: () => { parikshaSection = id; render(); } }, label)));
    const body = el("div");
    HS.mount(c, el("div", { class: "stack" }, el("h2", null, HS.module("assessment", "Pariksha Engine")), nav, body));
    await HS.load(body, { review: pReview, bank: pBank, build: pBuild, analysis: pAnalysis }[parikshaSection]);
  }

  async function pReview(c) {
    const q = await HS.api("/api/teacher/pariksha/review-queue");
    HS.mount(c, card("Answers waiting for your marks", el("p", { class: "small muted" },
      "Short answers the engine could not match with confidence, and all descriptive answers. They count only after you confirm."),
    q.length ? el("ul", { class: "list" }, q.map((it) => {
      const inp = el("input", { type: "number", min: "0", max: String(it.max), step: "0.5", "aria-label": "Marks", value: "0" });
      return el("li", null, el("div", { class: "row" }, el("strong", null, it.student), el("span", { class: "muted small" }, it.assessment),
        el("span", { class: "chip st-stale" }, `${it.method} · confidence ${it.confidence}`)),
      el("p", null, el("span", { class: "muted" }, "Q: "), it.question), el("p", null, el("span", { class: "muted" }, "Answer: "), it.response || "—"),
      it.accepted && it.accepted.length ? el("p", { class: "small muted" }, "Accepted: " + it.accepted.join(" | ")) : null,
      it.rubric ? el("p", { class: "small muted" }, "Rubric: " + it.rubric) : null,
      el("div", { class: "row" }, inp, el("span", null, `/ ${it.max}`), el("button", { class: "primary", onclick: async () => {
        try { await HS.api(`/api/teacher/pariksha/results/${it.result_id}/review`, { method: "POST", body: { marks: { [it.item_id]: Number(inp.value) } } }); HS.toast("Marks saved"); render(); }
        catch (ex) { HS.toast(ex.message, true); }
      } }, HS.t("save"))));
    })) : HS.empty("Nothing to review.")));
  }

  async function pBank(c) {
    const pairs = T.assignments.filter((a, i, arr) => arr.findIndex((b) => b.subject_id === a.subject_id && b.grade === a.grade) === i);
    const sel = el("select", { "aria-label": "Subject and class" }, pairs.map((a) => el("option", { value: `${a.subject_id}:${a.grade}` }, `${subjLabel(a)} · Class ${a.grade}`)));
    const list = el("div");
    const load = () => HS.load(list, async (h) => {
      const [sid, grade] = sel.value.split(":").map(Number);
      const qs = await HS.api(`/api/teacher/pariksha/bank?subject_id=${sid}&grade=${grade}`);
      HS.mount(h, HS.table([
        { label: "Status", render: (q) => el("span", { class: "chip " + (q.status === "approved" ? "verified-badge" : "draft-badge") }, q.status) },
        { label: "Type", key: "qtype" }, { label: "LO", key: "learning_outcome" }, { label: "Diff.", key: "difficulty", num: true },
        { label: "Question", render: (q) => el("span", null, q.text, q.ai_generated ? el("span", { class: "chip ai-badge" }, "AI draft") : null,
          q.is_demo ? el("span", { class: "chip demo-badge" }, "demo") : null) },
        { label: "Key", render: (q) => q.qtype === "mcq" ? (q.options[q.correct_option] || "—") : (q.accepted_answers.join(" | ") || q.rubric || "—") },
        { label: "", render: (q) => q.status === "draft" ? el("button", { onclick: async () => { await HS.api(`/api/teacher/pariksha/bank/${q.id}/approve`, { method: "POST" }).catch((e) => HS.toast(e.message, true)); load(); } }, HS.t("approve"))
          : (q.source !== "scert" ? el("button", { class: "link", onclick: async () => { await HS.api(`/api/teacher/pariksha/bank/${q.id}/retire`, { method: "POST" }); load(); } }, "Retire") : null) },
      ], qs));
    });
    sel.addEventListener("change", load);
    const add = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Type"), el("select", { name: "qtype" }, ["mcq", "short", "descriptive"].map((t) => el("option", null, t)))),
      el("div", null, el("label", null, "Topic"), el("input", { name: "topic", required: true })),
      el("div", null, el("label", null, "Difficulty (1-3)"), el("input", { name: "difficulty", type: "number", min: "1", max: "3", value: "2" }))),
    el("div", { class: "field" }, el("label", null, "Question"), el("textarea", { name: "text", required: true, rows: "2" })),
    el("div", { class: "field" }, el("label", null, "Options (MCQ, one per line; mark the correct one with *)"), el("textarea", { name: "options", rows: "4" })),
    el("div", { class: "field" }, el("label", null, "Accepted answers (short; separate with |) or rubric (descriptive)"), el("input", { name: "key" })),
    el("button", { class: "primary", type: "submit" }, "Add to bank"));
    add.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(add);
      const [sid, grade] = sel.value.split(":").map(Number);
      const lines = (d.options || "").split("\n").map((s) => s.trim()).filter(Boolean);
      const body = { subject_id: sid, grade, topic: d.topic, qtype: d.qtype, text: d.text, difficulty: Number(d.difficulty) };
      if (d.qtype === "mcq") { body.options = lines.map((l) => l.replace(/^\*/, "").trim()); body.correct_option = lines.findIndex((l) => l.startsWith("*")); }
      if (d.qtype === "short") body.accepted_answers = (d.key || "").split("|").map((s) => s.trim()).filter(Boolean);
      if (d.qtype === "descriptive") { body.rubric = d.key; body.max_marks = 2; }
      try { await HS.api("/api/teacher/pariksha/bank", { method: "POST", body }); HS.toast("Added"); add.reset(); load(); }
      catch (ex) { HS.toast(ex.message, true); }
    });
    HS.mount(c, el("div", { class: "stack" }, card("Question bank", el("div", { class: "row" }, sel), list), card("Add a question", add)));
    load();
  }

  async function pBuild(c) {
    const cls = classes.find((x) => x.id === selectedClass);
    subjectPicker(() => {});
    const los = await HS.api(`/api/teacher/saathi/learning-outcomes?subject_id=${selectedSubject}&grade=${cls.grade}`);
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Title"), el("input", { name: "title", required: true, minlength: "3", value: "Unit assessment" })),
      el("div", null, el("label", null, "Kind"), el("select", { name: "kind" }, ["unit_test", "quiz", "quarterly", "annual", "baseline"].map((k) => el("option", null, k)))),
      el("div", null, el("label", null, "Questions"), el("input", { name: "count", type: "number", min: "1", max: "40", value: "8" })),
      el("div", null, el("label", null, "Difficulty"), el("select", { name: "difficulty" }, el("option", { value: "" }, "Mixed"), el("option", { value: "1" }, "Easy"), el("option", { value: "2" }, "Medium"), el("option", { value: "3" }, "Hard")))),
    el("fieldset", { class: "field" }, el("legend", null, "Learning outcomes"), los.map((lo) => el("label", { class: "option" },
      el("input", { type: "checkbox", name: "lo", value: lo.id }), `${lo.code} · ${lo.topic} — ${lo.description}`))),
    el("fieldset", { class: "field" }, el("legend", null, "Question types"), ["mcq", "short", "descriptive"].map((t) => el("label", { class: "option" },
      el("input", { type: "checkbox", name: "qt", value: t, checked: t !== "descriptive" ? true : null }), t))),
    el("label", { class: "option" }, el("input", { type: "checkbox", name: "publish" }), "Publish to students now"),
    el("button", { class: "primary", type: "submit" }, "Create from approved questions"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const d = HS.formData(form);
      try {
        const r = await HS.api("/api/teacher/pariksha/assessments", { method: "POST", body: { class_id: selectedClass, subject_id: selectedSubject,
          title: d.title, kind: d.kind, count: Number(d.count), difficulty: d.difficulty ? Number(d.difficulty) : null,
          learning_outcome_ids: fd.getAll("lo").map(Number), qtypes: fd.getAll("qt"), publish: !!d.publish } });
        HS.toast(`Created: ${r.questions} questions, ${r.max_score} marks`);
      } catch (ex) { HS.toast(ex.message, true); }
    });
    HS.mount(c, card("Build an assessment from the question bank", el("div", { class: "row" }, classPicker(() => render()), subjectPicker(() => render())), form));
  }

  async function pAnalysis(c) {
    subjectPicker(() => {});
    const [comp, asm] = await Promise.all([HS.api(`/api/teacher/pariksha/competencies?class_id=${selectedClass}&subject_id=${selectedSubject}`),
      HS.api(`/api/teacher/assessments?class_id=${selectedClass}`)]);
    const misc = el("div");
    const asel = el("select", { "aria-label": "Assessment" }, el("option", { value: "" }, "Choose an assessment…"),
      asm.filter((a) => a.results > 0).map((a) => el("option", { value: a.id }, `${a.title} (${a.results})`)));
    asel.addEventListener("change", () => asel.value && HS.load(misc, async (h) => {
      const rows = await HS.api(`/api/teacher/pariksha/assessments/${asel.value}/misconceptions`);
      HS.mount(h, rows.length ? el("ul", { class: "list" }, rows.map((r) => el("li", null, el("strong", null, r.text),
        el("div", { class: "small" }, `Correct: ${HS.pct(r.correct_rate)} · most common wrong answer: ${r.common_wrong_option !== null ? r.options[r.common_wrong_option] : "—"} (${HS.pct(r.common_wrong_share)})`),
        r.likely_misconception ? el("div", { class: "small form-error" }, "Likely misconception: " + r.likely_misconception) : null))) : HS.empty());
    }));
    HS.mount(c, el("div", { class: "stack" }, el("div", { class: "row" }, classPicker(() => render()), subjectPicker(() => render())),
      card("Competency (learning outcome) report", HS.table([
        { label: "LO", key: "code" }, { label: "Topic", key: "topic" }, { label: "Assessed", key: "students_assessed", num: true },
        { label: "Achieved", key: "achieved", num: true }, { label: "Needs practice", key: "needs_practice", num: true },
        { label: "Avg mastery", num: true, render: (r) => HS.pct(r.avg_mastery) }], comp)),
      card("Misconceptions", asel, misc)));
  }

  // -------------------------------------------------------- supervision --
  async function supervision(c) {
    const holder = el("div");
    const load = () => HS.load(holder, async (h) => {
      const rows = await HS.api(`/api/teacher/classes/${selectedClass}/ai-interactions`);
      HS.mount(h, rows.length ? el("ul", { class: "list" }, rows.map((r) => el("li", null,
        el("div", { class: "row" }, el("strong", null, r.student.name), el("span", { class: "chip flag" }, r.reason), el("span", { class: "small muted" }, HS.date(r.at))),
        el("p", null, el("span", { class: "muted" }, "Q: "), r.question), el("p", null, el("span", { class: "muted" }, "A: "), r.answer)))) : HS.empty("No flagged questions."));
    });
    HS.mount(c, card(HS.t("tab_supervision"), el("p", { class: "small muted" }, "Questions to the student assistant that its safety filter flagged (wellbeing or privacy). Follow up with care according to school safeguarding procedure."),
      classPicker(load), holder));
    load();
  }

  // ------------------------------------------- progress & follow-up --
  let trackScope = "mine";
  async function track(c) {
    const att = el("div");
    const grades = el("div");
    const loadAtt = () => HS.load(att, attendanceFollowUp);
    const scopeSel = T.is_head_teacher ? el("select", { "aria-label": "Scope", onchange: (e) => { trackScope = e.target.value; HS.load(grades, progressGrades); } },
      [["mine", "My class-subjects"], ["school", "Whole school"]].map(([v, l]) => el("option", { value: v, selected: trackScope === v ? true : null }, l))) : null;
    HS.mount(c, el("div", { class: "stack" },
      card("Progress against the academic plan", el("p", { class: "small muted" },
        "Computed automatically from milestones you mark taught and from your students' answers. Nothing extra to enter."), scopeSel, grades),
      card("Attendance follow-up", el("p", { class: "small muted" }, "Children whose attendance is irregular, falling or has stopped, with the lessons they missed. A prompt for a caring call or visit — not a label."),
        classPicker(loadAtt), att)));
    HS.load(grades, progressGrades);
    loadAtt();
  }

  async function progressGrades(h) {
    const d = await HS.api("/api/teacher/progress-grades?scope=" + trackScope);
    const counts = { A: 0, B: 0, C: 0, D: 0 };
    d.rows.forEach((r) => { if (r.grade) counts[r.grade] += 1; });
    HS.mount(h, el("div", { class: "stack" },
      d.school ? el("div", { class: "row" }, el("strong", null, "School grade: "), HS.gradeChip(d.school.grade),
        el("span", { class: "small muted" }, `taught ${HS.pct(d.school.taught_rate)} · learned ${HS.pct(d.school.learned_rate)}`)) : null,
      d.school && d.school.action ? el("p", { class: "small" }, d.school.action) : null,
      HS.gradeBar(counts), HS.gradeLegend(counts),
      d.rows.length ? el("ul", { class: "list" }, d.rows.map((r) => el("li", null,
        el("div", { class: "row" }, el("strong", null, `${r.class} · ${HS.pick(r.subject, r.subject_hi)}`), HS.gradeChip(r.grade),
          r.provisional ? el("span", { class: "chip", title: "Few outcomes due or assessed yet" }, "provisional") : null, el("span", { class: "spacer" }),
          el("span", { class: "small num" }, `taught ${r.taught}/${r.planned_due} · learned ${r.learned}/${r.assessed}` + (r.overdue ? ` · ${r.overdue} overdue` : ""))),
        el("div", { class: "grid grid-2" }, el("div", null, el("span", { class: "small muted" }, "Taught"), HS.charts.meter(r.taught_rate, "Taught")),
          el("div", null, el("span", { class: "small muted" }, "Learned"), HS.charts.meter(r.learned_rate, "Learned"))),
        r.actions.length ? el("ul", { class: "action-list small" }, r.actions.map((a) => el("li", null, a.text))) : null)))
        : HS.empty("No milestones are due yet."),
      el("details", null, el("summary", { class: "small" }, "How the grade is worked out"), el("p", { class: "small muted" }, d.definition))));
  }

  async function attendanceFollowUp(h) {
    const d = await HS.api(`/api/teacher/classes/${selectedClass}/attendance-risk`);
    const levelChip = (l) => el("span", { class: "chip " + (l === "high" ? "risk-high" : "risk-watch") }, l === "high" ? "Follow up now" : "Keep watch");
    const FLAG = { irregular: "irregular", continuous_absence: "absent continuously", falling: "falling" };
    HS.mount(h, el("div", { class: "stack" },
      el("div", { class: "kpis" }, kpiT("Students", d.students), kpiT("Follow up now", d.counts.high), kpiT("Keep watch", d.counts.watch)),
      d.flagged.length ? el("div", { class: "stack-sm" }, d.flagged.map((r) => el("div", { class: "card risk-card" + (r.level === "high" ? " high" : "") },
        el("div", { class: "row" }, el("strong", null, r.name), levelChip(r.level), r.flags.map((f) => el("span", { class: "chip" }, FLAG[f] || f)),
          el("span", { class: "spacer" }), el("span", { class: "small num" }, `attendance ${HS.pct(r.rate)} · last 30 days ${HS.pct(r.rate_last_30)}`)),
        el("div", { class: "small muted" }, `Recent score ${HS.pct(r.avg_score)}` + (r.last_absent ? ` · last absent ${HS.date(r.last_absent)}` : "")),
        el("ul", { class: "action-list small" }, r.actions.map((a) => el("li", null, a))),
        r.missed_outcomes.length ? el("details", null, el("summary", { class: "small" }, `Lessons taught while mostly absent (${r.missed_outcomes.length})`),
          el("ul", { class: "list small" }, r.missed_outcomes.map((m) => el("li", null, `${m.code}: ${m.outcome} `,
            m.needs_catch_up ? el("span", { class: "chip flag" }, "catch up") : el("span", { class: "chip st-current" }, "learned")))))
          : null)))
        : HS.empty("No attendance concerns in this class. 👍"),
      card("Attendance and scores in this class", el("p", { class: "small muted" }, d.band_note),
        HS.table([{ label: "Attendance", key: "band" }, { label: "Students", key: "students", num: true },
          { label: "Average score", num: true, render: (b) => HS.pct(b.avg_score) }], d.by_band)),
      el("details", null, el("summary", { class: "small" }, "Definitions"), el("p", { class: "small muted" }, d.definition))));
  }
  const kpiT = (label, value, sub) => el("div", { class: "kpi" }, el("div", { class: "label" }, label), el("div", { class: "value num" }, HS.num(value)),
    sub ? el("div", { class: "sub" }, sub) : null);

  // ------------------------------------------------ digital resources --
  let digitalCache = null;
  async function digitalResources() {
    if (!digitalCache) digitalCache = await HS.api("/api/teacher/digital");
    return digitalCache;
  }

  async function digitalTab(c) {
    digitalCache = null;
    const d = await digitalResources();
    const working = d.resources.filter((r) => r.status === "working");
    const out = el("p", { class: "form-error", role: "alert" });
    const resSel = el("select", { name: "resource_id", required: true }, working.map((r) => el("option", { value: r.id }, `${r.label} · ${HS.pick(r.kind_label, r.kind_label_hi)}`)));
    const subjSel = el("select", { name: "subject_id" });
    const loSel = el("select", { name: "learning_outcome_id" });
    const fillLos = async () => {
      const los = await HS.api(`/api/teacher/learning-outcomes?class_id=${selectedClass}&subject_id=${subjSel.value}`);
      HS.mount(loSel, el("option", { value: "" }, "— not linked —"), los.map((lo) => el("option", { value: lo.id }, `${lo.code} · ${lo.topic}`)));
    };
    const fillSubjects = () => { HS.mount(subjSel, subjectsOf(selectedClass).map((a) => el("option", { value: a.subject_id }, subjLabel(a)))); fillLos(); };
    subjSel.addEventListener("change", fillLos);
    const form = el("form", { class: "stack-sm" }, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Resource"), resSel),
      el("div", null, el("label", null, "Class"), classPicker(fillSubjects)),
      el("div", null, el("label", null, "Subject"), subjSel),
      el("div", null, el("label", null, "Learning outcome"), loSel),
      el("div", null, el("label", null, "Minutes"), el("input", { name: "minutes", type: "number", min: "5", max: "240", value: "35" }))),
    el("div", null, el("label", null, "What did the class do? (optional)"), el("input", { name: "activity", maxlength: "200", placeholder: "e.g. Fraction strips video and quiz on the smart board" })),
    out, el("button", { class: "primary", type: "submit", disabled: working.length ? null : true }, "Record session"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = HS.formData(form);
      try {
        await HS.api("/api/teacher/digital/usage", { method: "POST", body: { resource_id: Number(f.resource_id), class_id: selectedClass,
          subject_id: Number(f.subject_id), learning_outcome_id: f.learning_outcome_id ? Number(f.learning_outcome_id) : null,
          minutes: Number(f.minutes || 35), activity: f.activity || "" } });
        HS.toast("Session recorded"); render();
      } catch (ex) { out.textContent = ex.message; }
    });
    fillSubjects();
    const statusBtn = (r) => el("button", { class: "small-btn", onclick: async () => {
      const note = r.status === "working" ? (prompt("What is wrong? (optional)") || "") : "";
      try { await HS.api(`/api/teacher/digital/resources/${r.id}/status`, { method: "POST", body: { status: r.status === "working" ? "not_working" : "working", note } }); render(); }
      catch (ex) { HS.toast(ex.message, true); }
    } }, r.status === "working" ? "Report fault" : "Mark repaired");
    const util = new Map(d.school.rows.map((r) => [r.id, r]));
    let addForm = null;
    if (d.is_head_teacher) {
      addForm = el("form", { class: "inline-fields" },
        el("div", null, el("label", null, "Type"), el("select", { name: "kind" }, [["smart_class", "Smart class"], ["ict_lab", "ICT lab"], ["digital_library", "Digital library"], ["language_lab", "Language lab"], ["tablets", "Tablet set"]].map(([v, l]) => el("option", { value: v }, l)))),
        el("div", null, el("label", null, "Name"), el("input", { name: "label", required: true, minlength: "2", maxlength: "120", placeholder: "e.g. Smart class room 2" })),
        el("div", null, el("label", null, "Devices"), el("input", { name: "devices", type: "number", min: "1", max: "500", value: "1" })),
        el("div", null, el("label", null, "Target sessions / week"), el("input", { name: "target_sessions_per_week", type: "number", min: "1", max: "60", value: "10" })),
        el("div", null, el("label", null, " "), el("button", { class: "primary", type: "submit" }, "Add")));
      addForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = HS.formData(addForm);
        try { await HS.api("/api/teacher/digital/resources", { method: "POST", body: { kind: f.kind, label: f.label, devices: Number(f.devices), target_sessions_per_week: Number(f.target_sessions_per_week) } }); HS.toast("Added"); render(); }
        catch (ex) { HS.toast(ex.message, true); }
      });
    }
    HS.mount(c, el("div", { class: "stack" },
      el("p", { class: "small muted" }, "Tip: when you mark a milestone taught in Teacher Saathi → Academic plan you can tick the resource used — that records the session for you."),
      el("div", { class: "grid grid-2" },
        card("Record a session", form),
        card("School resources", d.resources.length ? HS.table([
          { label: "Resource", render: (r) => el("span", null, r.label, el("div", { class: "small muted" }, HS.pick(r.kind_label, r.kind_label_hi))) },
          { label: "Status", render: (r) => el("span", { class: "chip " + (r.status === "working" ? "st-current" : "flag") }, r.status === "working" ? "working" : "not working") },
          { label: "Use (4 wk)", num: true, render: (r) => util.get(r.id) ? `${util.get(r.id).sessions} · ${HS.pct(util.get(r.id).utilisation)}` : "—" },
          { label: "", render: statusBtn }], d.resources) : HS.empty("No digital resources registered for this school."),
        el("p", { class: "small muted" }, d.school.definition), addForm ? el("details", null, el("summary", null, "➕ Register a resource (head teacher)"), addForm) : null)),
      card("My recent sessions", d.my_recent.length ? HS.table([{ label: "Date", render: (u) => HS.date(u.used_on) }, { label: "Resource", key: "resource" },
        { label: "Class", key: "class" }, { label: "Subject", key: "subject" }, { label: "Min", key: "minutes", num: true },
        { label: "Linked to outcome", render: (u) => (u.aligned ? "✓" : "—") }], d.my_recent) : HS.empty("No sessions recorded yet."))));
  }

  // ------------------------------------------------------- recognition --
  async function recognitionTab(c) {
    const r = await HS.api("/api/teacher/recognition");
    const earned = r.badges.filter((b) => b.earned);
    const cert = (b) => HS.certificate({ title: b.title, recipient: r.certificate.name, detail: r.certificate.school, reason: b.why, issuer: "HAMAR SHIKSHA" });
    const catSel = (cats) => el("select", { name: "category", "aria-label": "Category" }, cats.map((k) => el("option", { value: k.key }, HS.pick(k.label, k.label_hi))));
    const appreciateForm = (who, url, cats) => {
      const f = el("form", { class: "row" }, catSel(cats), el("input", { name: "message", maxlength: "300", placeholder: "Short message (optional)", "aria-label": "Message" }),
        el("button", { class: "primary", type: "submit" }, "🌟 Appreciate"));
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await HS.api(url, { method: "POST", body: HS.formData(f) }); HS.toast(`Appreciation sent to ${who}`); render(); }
        catch (ex) { HS.toast(ex.message, true); }
      });
      return f;
    };
    const rosterHolder = el("div");
    const loadRoster = () => HS.load(rosterHolder, async (h) => {
      const ro = await HS.api(`/api/teacher/classes/${selectedClass}/roster`);
      const sel = el("select", { "aria-label": "Student" }, ro.students.map((s) => el("option", { value: s.student }, s.name)));
      const holder = el("div");
      const draw = () => HS.mount(holder, appreciateForm(sel.selectedOptions[0]?.textContent || "", `/api/teacher/students/${sel.value}/appreciate`, r.student_categories));
      sel.addEventListener("change", draw);
      HS.mount(h, el("div", { class: "stack-sm" }, sel, holder));
      draw();
    });
    HS.mount(c, el("div", { class: "stack" },
      card(`My badges (${earned.length} of ${r.badges.length})`, el("div", { class: "badge-grid" }, r.badges.map((b) => HS.badgeCard(b, cert))),
        el("p", { class: "small muted" }, "Earned automatically from your planning, classes and training records. Badges recognise progress and effort; they are not used for appraisal.")),
      el("div", { class: "grid grid-2" },
        card("Students who are improving", el("p", { class: "small muted" }, "Largest gains in recent results. A word of appreciation keeps them going."),
          r.improvers.length ? el("ul", { class: "list" }, r.improvers.map((s) => el("li", null,
            el("div", { class: "row" }, el("strong", null, s.name), el("span", { class: "chip st-current" }, `+${s.gain_points} points`)),
            el("details", null, el("summary", { class: "small" }, "🌟 Appreciate"), appreciateForm(s.name, `/api/teacher/students/${s.public_id}/appreciate`, r.student_categories)))))
            : HS.empty("No clear improvers yet — needs a few more results.")),
        card("Appreciate any student", classPicker(loadRoster), rosterHolder)),
      r.colleagues.length ? card("Appreciate a colleague (head teacher)", el("ul", { class: "list" }, r.colleagues.map((t) => el("li", null,
        el("strong", null, t.name), el("details", null, el("summary", { class: "small" }, "🌟 Appreciate"),
          appreciateForm(t.name, `/api/teacher/colleagues/${t.public_id}/appreciate`, r.teacher_categories)))))) : null,
      el("div", { class: "grid grid-2" },
        card("Appreciation I received", r.received.length ? el("div", null, r.received.map((a) => el("div", { class: "kudos" }, "🌟 ",
          el("strong", null, HS.pick(a.title, a.title_hi)), a.message ? el("div", null, a.message) : null,
          el("div", { class: "small muted" }, `${a.from || ""} (${a.from_role.replace("_", " ")}) · ${HS.date(a.at)}`)))) : HS.empty()),
        card("Appreciation I gave", r.given.length ? HS.table([{ label: "To", key: "to" }, { label: "For", render: (a) => HS.pick(a.title, a.title_hi) },
          { label: "When", render: (a) => HS.date(a.at) }], r.given) : HS.empty()))));
    loadRoster();
  }

  // ------------------------------------------------------------ reports --
  async function reports(c) {
    const mine = await HS.api("/api/teacher/reports");
    const now = new Date();
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Month"), el("input", { name: "period", type: "month", required: true, value: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}` })),
      el("div", null, el("label", null, "Title"), el("input", { name: "title", required: true, minlength: "3", value: "Monthly academic report" }))),
    el("div", { class: "field" }, el("label", null, "Summary, challenges and support needed"), el("textarea", { name: "body", required: true, minlength: "10" })),
    el("p", { class: "small muted" }, "Class-level aggregates (attendance, average scores) are attached automatically."),
    el("button", { class: "primary", type: "submit" }, HS.t("submit")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await HS.api("/api/teacher/reports", { method: "POST", body: HS.formData(form) }); HS.toast("Report submitted"); render(); }
      catch (ex) { HS.toast(ex.message, true); }
    });
    HS.mount(c, el("div", { class: "stack" }, card("Submit report to education office", form),
      card("My submitted reports", HS.table([{ label: "Title", key: "title" }, { label: "Month", key: "period" }, { label: "Status", key: "status" },
        { label: "Submitted", render: (r) => HS.date(r.submitted_at) }], mine))));
  }

  // --------------------------------------------------------------- head --
  async function head(c) {
    const cls = await HS.api("/api/teacher/school/classes");
    const enrollOut = el("div");
    const ef = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "Class"), el("select", { name: "class_id" }, cls.map((x) => el("option", { value: x.id }, `${x.label} (${x.academic_year})`)))),
      el("div", null, el("label", null, "Student name"), el("input", { name: "full_name", required: true, minlength: "2" })),
      el("div", null, el("label", null, "Roll no."), el("input", { name: "roll_no", type: "number", min: "1", max: "999" })),
      el("div", null, el("label", null, "Guardian name"), el("input", { name: "guardian_name", required: true, minlength: "2" })),
      el("div", null, el("label", null, "Guardian mobile"), el("input", { name: "guardian_phone", inputmode: "tel", maxlength: "20" }))),
    el("label", { class: "option" }, el("input", { type: "checkbox", name: "guardian_consent", required: true }),
      "Guardian has given informed consent for the student's account and learning data (record kept at school)."),
    el("button", { class: "primary", type: "submit" }, "Enrol student"));
    ef.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(ef);
      try {
        const r = await HS.api(`/api/teacher/school/classes/${d.class_id}/students`, { method: "POST", body: {
          full_name: d.full_name, guardian_name: d.guardian_name, guardian_phone: d.guardian_phone || null,
          guardian_consent: !!d.guardian_consent, roll_no: d.roll_no ? Number(d.roll_no) : null } });
        HS.mount(enrollOut, el("div", { class: "card" }, el("strong", null, "Student enrolled"),
          el("div", null, "Login ID: ", el("span", { class: "secret" }, r.login_id)),
          el("div", null, "Temporary password: ", el("span", { class: "secret" }, r.temporary_password)),
          el("p", { class: "small muted" }, "Give these to the student/guardian in person. Shown once.")));
        ef.reset();
      } catch (ex) { HS.mount(enrollOut, el("p", { class: "form-error" }, ex.message)); }
    });

    const dateIn = el("input", { type: "date", value: HS.today(), max: HS.today(), "aria-label": "Date" });
    const tHolder = el("div");
    const loadT = () => HS.load(tHolder, async (h) => {
      const d = await HS.api("/api/teacher/school/teacher-attendance?on=" + dateIn.value);
      const st = new Map(d.records.map((r) => [r.teacher, r.status || "present"]));
      HS.mount(h, HS.table([{ label: "Teacher", key: "name" }, { label: "Status", render: (r) => {
        const s = el("select", { "aria-label": r.name, onchange: (e) => st.set(r.teacher, e.target.value) }, ["present", "absent", "late", "leave"].map((v) => el("option", { value: v, selected: st.get(r.teacher) === v ? true : null }, v)));
        return s;
      } }], d.records), el("button", { class: "primary", onclick: async () => {
        try { await HS.api("/api/teacher/school/teacher-attendance", { method: "POST", body: { date: dateIn.value, records: [...st].map(([teacher, status]) => ({ teacher, status })) } }); HS.toast("Saved"); }
        catch (ex) { HS.toast(ex.message, true); }
      } }, HS.t("save")));
    });
    dateIn.addEventListener("change", loadT);
    HS.mount(c, el("div", { class: "stack" }, card("Enrol a student (Workflow C)", ef, enrollOut), card("Teacher attendance", dateIn, tHolder)));
    loadT();
  }

  tabs.select(tabs.initial);
})();
