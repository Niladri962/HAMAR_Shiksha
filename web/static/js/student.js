/* Student app: simple, mobile-first, Hindi by default. Every request is
   answered from the signed-in student's own records only. */
(async function () {
  "use strict";
  const HS = window.HS;
  const el = HS.el;
  const me0 = await HS.boot();
  if (!me0) return;
  let S;
  try {
    S = await HS.api("/api/student/me");
    try { localStorage.setItem("hs_student_me", JSON.stringify(S)); } catch (_) { /* ignore */ }
  } catch (e) {
    try { S = JSON.parse(localStorage.getItem("hs_student_me") || "null"); } catch (_) { S = null; }
    if (!S || e.status !== 0) { HS.mount(document.getElementById("app"), HS.errorBox(e)); return; }
  }

  const view = document.getElementById("app");
  const nav = document.getElementById("bottom-nav");
  const SECTIONS = [["home", "🏠", "nav_home"], ["learn", "📖", "nav_learn"], ["quiz", "✏️", "nav_quiz"], ["help", "🤝", "nav_help"], ["me", "⭐", "nav_me"]];
  let current = "home";
  const buttons = SECTIONS.map(([id, ic, key]) => el("button", { type: "button", "aria-selected": "false", onclick: () => go(id) },
    el("span", { class: "ic", "aria-hidden": "true" }, ic), el("span", { "data-i18n": key }, HS.t(key))));
  nav.append(...buttons);
  // Each section has sub-views chosen with a segmented control.
  const SUB = {
    learn: [["activities", "📝", "Activities", "गतिविधियाँ"], ["books", "📚", "Textbooks", "पाठ्यपुस्तकें"]],
    quiz: [["quizzes", "✏️", "Quizzes", "क्विज़"], ["revise", "🔁", "Fix my mistakes", "गलतियाँ सुधारें"]],
    help: [["ai", "🤖", "Ask Gyan", "ज्ञान से पूछें"], ["teacher", "👩‍🏫", "Ask teacher", "शिक्षक से पूछें"],
      ["class", "👥", "Class doubts", "कक्षा के प्रश्न"], ["buddies", "🤝", "Study buddies", "पढ़ाई के साथी"]],
    me: [["growth", "🚀", "My goals", "मेरे लक्ष्य"], ["badges", "🏅", "Badges", "बैज"], ["progress", "📈", "My progress", "मेरी प्रगति"]],
  };
  const sub = { learn: "activities", quiz: "quizzes", help: "ai", me: "growth" };
  const VIEWS = {
    learn: { activities: (c) => learn(c), books: (c) => books(c) },
    quiz: { quizzes: (c) => quiz(c), revise: (c) => revise(c) },
    help: { ai: (c) => ask(c), teacher: (c) => doubts(c, "teacher"), class: (c) => doubts(c, "class"), buddies: (c) => buddies(c) },
    me: { growth: (c) => growth(c), badges: (c) => badges(c), progress: (c) => progress(c) },
  };
  function sectioned(id) {
    return async (c) => {
      const seg = el("div", { class: "segmented", role: "tablist", "aria-label": HS.t("nav_" + id) }, SUB[id].map(([k, ic, en, hi]) =>
        el("button", { type: "button", role: "tab", "aria-selected": String(sub[id] === k), onclick: () => { sub[id] = k; go(id); } },
          el("span", { "aria-hidden": "true" }, ic), " ", HS.pick(en, hi))));
      const body = el("div");
      HS.mount(c, el("div", { class: "stack" }, seg, body));
      await HS.load(body, VIEWS[id][sub[id]]);
    };
  }
  function go(id, subId) {
    current = id;
    if (subId) sub[id] = subId;
    buttons.forEach((b, i) => b.setAttribute("aria-selected", String(SECTIONS[i][0] === id)));
    HS.load(view, id === "home" ? home : sectioned(id));
    window.scrollTo(0, 0);
  }
  document.addEventListener("hs:lang", () => go(current));
  const subj = (o) => HS.pick(o.subject || o.name, o.subject_hi || o.name_hi);
  const card = (title, ...body) => el("section", { class: "card" }, title ? el("h2", null, title) : null, ...body);
  const masteryWord = (m) => (m >= 0.75 ? HS.t("strong") : m >= 0.5 ? HS.t("getting_there") : HS.t("keep_practising"));

  // --------------------------------------------------------------- home --
  async function home(c) {
    const [work, recs, prog, live, gr, rec] = await Promise.all([HS.api("/api/student/assignments"), HS.api("/api/student/recommendations"),
      HS.api("/api/student/progress"), HS.api("/api/student/live-lesson"), HS.api("/api/student/growth"), HS.api("/api/student/recognition")]);
    HS.sync.pull(); // refresh the offline bundle while online
    const open = work.filter((w) => !w.submitted);
    const nextSteps = [];
    if (gr.revision.due) nextSteps.push(el("button", { class: "big-item next-step", onclick: () => go("quiz", "revise") },
      el("span", null, "🔁 ", el("strong", null, HS.pick(`${gr.revision.due} ${gr.revision.due === 1 ? "mistake" : "mistakes"} to fix today`, `आज ${gr.revision.due} गलतियाँ सुधारें`))), el("span", null, "›")));
    if (gr.class_doubts_waiting) nextSteps.push(el("button", { class: "big-item next-step", onclick: () => go("help", "class") },
      el("span", null, "👥 ", el("strong", null, HS.pick(gr.class_doubts_waiting === 1 ? "A classmate needs help" : `${gr.class_doubts_waiting} classmates need help`,
        `${gr.class_doubts_waiting} सहपाठी को मदद चाहिए`))), el("span", null, "›")));
    gr.study_buddies.forEach((b) => nextSteps.push(el("button", { class: "big-item next-step", onclick: () => go("help", "buddies") },
      el("span", null, "🤝 ", el("strong", null, b.role === "helper" ? HS.pick(`Help ${b.partner} with ${b.topic}`, `${b.partner} की ${b.topic} में मदद करें`)
        : HS.pick(`Study ${b.topic} with ${b.partner}`, `${b.partner} के साथ ${b.topic} पढ़ें`))), el("span", null, "›"))));
    HS.mount(c, el("div", { class: "stack" },
      el("div", null, el("h1", null, `${HS.t("hello")}, ${S.name.split(" ")[0]} 👋`), el("p", { class: "muted" }, `${S.class} · ${S.school}`)),
      levelCard(gr.level, () => go("me", "growth")),
      challengeCard(rec.challenge),
      rec.appreciations[0] ? el("div", { class: "kudos" }, "🌟 ", el("strong", null, HS.pick(rec.appreciations[0].title, rec.appreciations[0].title_hi)),
        rec.appreciations[0].message ? ` — “${rec.appreciations[0].message}”` : "", el("span", { class: "small muted" }, ` · ${rec.appreciations[0].from || ""}`)) : null,
      nextSteps.length ? el("div", { class: "stack-sm" }, nextSteps) : null,
      gr.goals.length ? card(HS.pick("This week's goals", "इस सप्ताह के लक्ष्य"), goalList(gr.goals, true)) : null,
      live ? card("🔴 " + HS.t("live_lesson") + ": " + live.title, el("p", { class: "small muted" }, `${live.subject} · ${live.notice}`),
        el("details", { open: true }, el("summary", null, live.topic), el("pre", { class: "output" }, live.body)),
        HS.citations(live.sources)) : null,
      card(HS.t("practice_suggestions"), recs.length ? el("ul", { class: "list big-list" }, recs.map((r) => el("li", null,
        el("button", { class: "big-item", onclick: () => learnTopic(r.evidence.subject_id, r.evidence.topic) },
          el("span", null, el("strong", null, r.evidence.topic), el("br"), el("span", { class: "small muted" }, r.summary)), el("span", { "aria-hidden": "true" }, "›")))))
        : HS.empty(HS.lang === "hi" ? "बहुत बढ़िया! अभी कोई सुझाव नहीं।" : "Great work! No suggestions right now."),
      recs.length ? el("p", { class: "small muted" }, HS.lang === "hi" ? "ये सुझाव आपके उत्तरों पर आधारित हैं, आपके शिक्षक इन्हें देख सकते हैं।" : "Suggestions come from your answers; your teacher can see and adjust them.") : null),
      card(HS.t("upcoming"), open.length ? el("ul", { class: "list" }, open.map(assignmentItem)) : HS.empty()),
      card(HS.t("achievements"), prog.achievements.length ? el("div", { class: "badges" }, prog.achievements.map((b) => el("span", { class: "badge-pill" }, HS.pick(b.label, b.label_hi))))
        : HS.empty(HS.lang === "hi" ? "पहला पाठ पूरा करके शुरुआत करें!" : "Complete your first lesson to start!"))));
  }

  function assignmentItem(a) {
    const box = el("div");
    const ta = el("textarea", { maxlength: "5000", "aria-label": a.title });
    return el("li", null, el("strong", null, a.title), el("div", { class: "small muted" }, `${subj(a)} · ${a.due_date ? HS.date(a.due_date) : ""}`),
      a.description ? el("p", null, a.description) : null,
      el("details", null, el("summary", null, HS.t("submit")), ta,
        el("button", { class: "primary", onclick: async () => {
          try { await HS.api(`/api/student/assignments/${a.id}/submit`, { method: "POST", body: { content: ta.value } }); HS.toast("✓"); go("home"); }
          catch (ex) { HS.mount(box, el("p", { class: "form-error" }, ex.message)); }
        } }, HS.t("submit")), box));
  }

  // -------------------------------------------------------------- learn --
  let learnFilter = null;
  async function learn(c) {
    const acts = await HS.api("/api/student/activities" + (learnFilter ? "?subject_id=" + learnFilter : ""));
    const chips = el("div", { class: "row" }, el("button", { class: learnFilter ? "" : "primary", onclick: () => { learnFilter = null; go("learn"); } }, HS.lang === "hi" ? "सभी" : "All"),
      S.subjects.map((s) => el("button", { class: learnFilter === s.id ? "primary" : "", onclick: () => { learnFilter = s.id; go("learn"); } }, subj(s))),
      learnFilter ? el("button", { class: "primary", onclick: () => practice(learnFilter) }, "🎯 " + HS.t("nav_practice")) : null);
    const byTopic = new Map();
    acts.forEach((a) => { const k = `${subj(a)} · ${a.topic}`; if (!byTopic.has(k)) byTopic.set(k, []); byTopic.get(k).push(a); });
    HS.mount(c, el("div", { class: "stack" }, chips, byTopic.size ? el("ul", { class: "list big-list" }, [...byTopic].map(([k, list]) => el("li", null,
      el("h3", null, k), list.map((a) => el("button", { class: "big-item", onclick: () => openActivity(a) },
        el("span", null, (a.kind === "lesson" ? "📖 " : "✏️ ") + a.title), el("span", null, a.completed ? "✓" + (a.score !== null ? " " + HS.pct(a.score) : "") : "›"))))))
      : HS.empty()));
  }

  async function learnTopic(subjectId, topic) {
    learnFilter = subjectId;
    current = "learn";
    buttons.forEach((b, i) => b.setAttribute("aria-selected", String(SECTIONS[i][0] === "learn")));
    HS.load(view, async (c) => {
      const acts = (await HS.api("/api/student/activities?subject_id=" + subjectId)).filter((a) => a.topic.toLowerCase() === String(topic).toLowerCase());
      if (acts.length) openActivity(acts.find((a) => a.kind === "exercise") || acts[0]);
      else await learn(c);
    });
  }

  function openActivity(a) {
    HS.load(view, async (c) => {
      const back = el("button", { onclick: () => go("learn") }, "← " + HS.t("back"));
      if (a.kind === "lesson") {
        const done = el("button", { class: "primary", onclick: async () => {
          await HS.api(`/api/student/activities/${a.id}/complete`, { method: "POST", body: { answers: {} } }); HS.toast("✓"); go("learn");
        } }, HS.lang === "hi" ? "पढ़ लिया ✓" : "I have read this ✓");
        HS.mount(c, el("div", { class: "stack" }, back, card(a.title, el("p", { class: "muted small" }, `${subj(a)} · ${a.topic}`),
          el("p", { lang: a.language }, a.content.body), done)));
        return;
      }
      HS.mount(c, el("div", { class: "stack" }, back, card(a.title, quizForm(a.content.questions, async (answers) => {
        const out = await HS.sync.submit("activity.complete", { activity_id: a.id, answers },
          () => HS.api(`/api/student/activities/${a.id}/complete`, { method: "POST", body: { answers } }));
        return out.result;
      }))));
    });
  }

  /** Renders MCQ, short-answer and descriptive questions. submitFn returns the
      server review, or null when the answers were queued offline. */
  function quizForm(questions, submitFn) {
    const form = el("form");
    questions.forEach((q, i) => {
      const qtype = q.qtype || "mcq";
      const fs = el("fieldset", { class: "field" }, el("legend", null, el("strong", null, `${i + 1}. ${q.text}`),
        q.max_marks > 1 ? el("span", { class: "small muted" }, ` (${q.max_marks})`) : null));
      if (qtype === "mcq") {
        q.options.forEach((o, oi) => fs.append(el("label", { class: "option", dataset: { q: q.id, o: String(oi) } },
          el("input", { type: "radio", name: q.id, value: String(oi), required: true }), o)));
      } else if (qtype === "short") {
        fs.append(el("input", { name: q.id, maxlength: "200", required: true, "aria-label": q.text, dataset: { q: q.id } }));
      } else {
        fs.append(el("textarea", { name: q.id, maxlength: "3000", required: true, "aria-label": q.text, dataset: { q: q.id } }),
          el("p", { class: "small muted" }, HS.lang === "hi" ? "आपके शिक्षक इसे जाँचेंगे।" : "Your teacher will mark this answer."));
      }
      form.append(fs);
    });
    const result = el("div", { role: "status" });
    const btn = el("button", { class: "primary", type: "submit" }, HS.t("submit"));
    form.append(btn, result);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const answers = {};
      new FormData(form).forEach((v, k) => {
        const q = questions.find((x) => x.id === k);
        answers[k] = (q && (q.qtype || "mcq") === "mcq") ? Number(v) : String(v);
      });
      btn.disabled = true;
      try {
        const r = await submitFn(answers);
        form.querySelectorAll("input, textarea").forEach((i) => { i.disabled = true; });
        btn.remove();
        if (!r) { HS.mount(result, el("p", { class: "card" }, HS.t("saved_offline"))); return; }
        (r.review || []).forEach((rv) => {
          form.querySelectorAll(`label[data-q="${rv.id}"]`).forEach((lab) => {
            const oi = Number(lab.dataset.o);
            if (oi === rv.correct_index) lab.classList.add("correct");
            else if (lab.querySelector("input").checked) lab.classList.add("wrong");
          });
          const box = form.querySelector(`[data-q="${rv.id}"]:not(label)`);
          if (box) box.after(el("span", { class: "chip " + (rv.needs_review ? "st-stale" : rv.correct ? "verified-badge" : "flag") },
            rv.needs_review ? (HS.lang === "hi" ? "शिक्षक जाँचेंगे" : "teacher will check") : rv.correct ? "✓" : "✗"));
        });
        const score = r.score !== undefined && r.max_score !== undefined ? `${r.score}/${r.max_score}` : HS.pct(r.score);
        HS.mount(result, el("p", { class: "card" }, el("strong", null, (HS.lang === "hi" ? "आपके अंक: " : "Your score: ") + score),
          el("br"), r.status === "pending_review" ? (HS.lang === "hi" ? "कुछ उत्तर शिक्षक जाँचेंगे; अंतिम अंक बाद में।" : "Some answers will be checked by your teacher; final marks later.")
            : (HS.lang === "hi" ? "हरे रंग में सही उत्तर दिखाए गए हैं।" : "Correct answers are marked in green.")));
      } catch (ex) { btn.disabled = false; HS.mount(result, el("p", { class: "form-error" }, ex.message)); }
    });
    return form;
  }

  async function practice(subjectId) {
    HS.load(view, async (c) => {
      const p = await HS.api(`/api/student/practice?subject_id=${subjectId}&count=5`);
      const level = ["", HS.lang === "hi" ? "आसान" : "easy", HS.lang === "hi" ? "मध्यम" : "medium", HS.lang === "hi" ? "कठिन" : "challenging"][p.difficulty];
      HS.mount(c, el("div", { class: "stack" }, el("button", { onclick: () => go("learn") }, "← " + HS.t("back")),
        card(`🎯 ${HS.t("nav_practice")}: ${p.topic || ""}`,
          el("p", { class: "small muted" }, (HS.lang === "hi" ? "स्तर: " : "Level: ") + level +
            (HS.lang === "hi" ? " (आपकी पिछली प्रगति के आधार पर)" : " (chosen from your recent progress)")),
          p.questions.length ? quizForm(p.questions, (answers) => HS.api("/api/student/practice/check", { method: "POST", body: { answers } }))
            : HS.empty())));
    });
  }

  // --------------------------------------------------------------- quiz --
  async function quiz(c) {
    let list;
    try { list = await HS.api("/api/student/assessments"); }
    catch (e) {
      // Offline: offer the quizzes cached in the last sync bundle.
      const b = await HS.sync.cached();
      if (!b || !b.assessments.length) throw e;
      HS.mount(c, el("div", { class: "stack" }, el("h1", null, HS.t("nav_quiz")), el("p", { class: "small muted" }, HS.t("offline")),
        el("ul", { class: "list big-list" }, b.assessments.map((a) => el("li", null,
          el("button", { class: "big-item", onclick: () => takeCached(a) }, el("span", null, el("strong", null, a.title), el("br"),
            el("span", { class: "small muted" }, a.subject)), el("span", null, "›")))))));
      return;
    }
    HS.mount(c, el("div", { class: "stack" }, el("h1", null, HS.t("nav_quiz")), list.length ? el("ul", { class: "list big-list" }, list.map((a) => el("li", null,
      el("button", { class: "big-item", disabled: a.result ? true : null, onclick: () => takeQuiz(a.id) },
        el("span", null, el("strong", null, a.title), el("br"), el("span", { class: "small muted" }, `${subj(a)}${a.due_date ? " · " + HS.date(a.due_date) : ""}`)),
        el("span", null, a.result ? `${a.result.score}/${a.result.max_score}` : "›"))))) : HS.empty()));
  }

  function takeQuiz(id) {
    HS.load(view, async (c) => {
      const a = await HS.api(`/api/student/assessments/${id}`);
      HS.mount(c, el("div", { class: "stack" }, el("button", { onclick: () => go("quiz") }, "← " + HS.t("back")),
        card(a.title, el("p", { class: "muted small" }, a.subject),
          a.already_submitted ? HS.empty("✓") : quizForm(a.questions, async (answers) => {
            const out = await HS.sync.submit("assessment.submit", { assessment_id: id, answers },
              () => HS.api(`/api/student/assessments/${id}/submit`, { method: "POST", body: { answers } }));
            return out.result;
          }))));
    });
  }

  function takeCached(a) {
    HS.mount(view, el("div", { class: "stack" }, el("button", { onclick: () => go("quiz") }, "← " + HS.t("back")),
      card(a.title, el("p", { class: "muted small" }, `${a.subject} · ${HS.t("offline_short")}`),
        quizForm(a.questions, async (answers) => { await HS.sync.queue("assessment.submit", { assessment_id: a.id, answers }); return null; }))));
  }

  // ----------------------------------------------------------- progress --
  async function progress(c) {
    const [p, rec] = await Promise.all([HS.api("/api/student/progress"), HS.api("/api/student/record")]);
    const statusWord = (s) => ({ achieved: HS.t("strong"), developing: HS.t("getting_there"), needs_practice: HS.t("keep_practising") }[s]);
    const compCard = card(HS.lang === "hi" ? "मेरे अधिगम परिणाम" : "My learning outcomes",
      rec.competencies.length ? el("ul", { class: "list" }, rec.competencies.map((k) => el("li", null,
        el("div", { class: "row" }, el("strong", null, k.topic), el("span", { class: "small muted" }, HS.pick(k.description, k.description_hi)),
          el("span", { class: "spacer" }), el("span", { class: "small" }, `${statusWord(k.status)} · ${k.correct}/${k.attempted}`)),
        HS.charts.meter(k.mastery, k.topic)))) : HS.empty());
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "kpis" },
        el("div", { class: "kpi" }, el("div", { class: "label" }, HS.lang === "hi" ? "उपस्थिति (30 दिन)" : "Attendance (30 days)"), el("div", { class: "value num" }, HS.pct(p.attendance_30d))),
        el("div", { class: "kpi" }, el("div", { class: "label" }, HS.lang === "hi" ? "पूरी गतिविधियाँ" : "Activities done"), el("div", { class: "value num" }, p.lessons_completed))),
      compCard,
      card(HS.lang === "hi" ? "विषय और टॉपिक" : "Subjects and topics", p.topics.length ? el("ul", { class: "list" }, p.topics.map((t) => el("li", null,
        el("div", { class: "row" }, el("strong", null, t.topic), el("span", { class: "small muted" }, HS.pick(t.subject, t.subject_hi)), el("span", { class: "spacer" }),
          el("span", { class: "small" }, `${masteryWord(t.mastery)} · ${t.correct}/${t.attempted}`)),
        HS.charts.meter(t.mastery, t.topic)))) : HS.empty()),
      card(HS.lang === "hi" ? "मेरे परिणाम" : "My results", HS.table([{ label: HS.lang === "hi" ? "आकलन" : "Assessment", key: "assessment" },
        { label: HS.lang === "hi" ? "अंक" : "Score", num: true, render: (r) => `${r.score}/${r.max_score}` }, { label: "", render: (r) => HS.date(r.submitted_at) }], p.results)),
      card(HS.t("achievements"), p.achievements.length ? el("div", { class: "badges" }, p.achievements.map((b) => el("span", { class: "badge-pill" }, HS.pick(b.label, b.label_hi)))) : HS.empty())));
  }

  // ------------------------------------------------- level, goals, growth --
  function levelCard(lv, onClick) {
    const span = (lv.next_level_xp || lv.xp + 1) - lv.level_floor_xp;
    const fill = el("div", { class: "xp-fill" });
    fill.style.width = Math.round(Math.min(1, (lv.xp - lv.level_floor_xp) / span) * 100) + "%";
    return el("button", { type: "button", class: "level-card", onclick: onClick },
      el("div", { class: "level-badge", "aria-hidden": "true" }, String(lv.level)),
      el("div", { class: "level-main" },
        el("div", { class: "row" }, el("strong", null, HS.pick(`Level ${lv.level} · ${lv.level_name}`, `स्तर ${lv.level} · ${lv.level_name_hi}`)),
          el("span", { class: "spacer" }), el("span", { class: "streak" + (lv.streak_days ? " on" : "") }, `🔥 ${lv.streak_days} ${HS.pick("day streak", "दिन लगातार")}`)),
        el("div", { class: "xp-track", role: "meter", "aria-valuemin": "0", "aria-valuemax": String(span), "aria-valuenow": String(lv.xp - lv.level_floor_xp),
          "aria-label": "XP" }, fill),
        el("div", { class: "small muted" }, lv.next_level_xp ? HS.pick(`${lv.xp} XP · ${lv.next_level_xp - lv.xp} XP to the next level`, `${lv.xp} XP · अगले स्तर तक ${lv.next_level_xp - lv.xp} XP`)
          : `${lv.xp} XP`)));
  }

  function goalList(goals, compact) {
    return el("ul", { class: "list goals" }, goals.map((g) => {
      const fill = el("div", { class: "bar-fill" + (g.done ? " done" : "") });
      fill.style.width = Math.round((g.progress / g.target) * 100) + "%";
      return el("li", null,
        el("div", { class: "row" }, el("strong", null, (g.done ? "✅ " : "🎯 ") + g.title), el("span", { class: "spacer" }),
          el("span", { class: "small num" }, `${g.progress}/${g.target}`)),
        el("div", { class: "bar-track" }, fill),
        compact ? null : el("div", { class: "row" }, el("span", { class: "small muted" }, g.manual ? HS.pick("Tick it when you do it", "करने पर टिक करें") : HS.pick("Counted automatically", "अपने-आप गिना जाता है")),
          el("span", { class: "spacer" }),
          g.manual && !g.done ? el("button", { class: "small-btn", onclick: async () => { await HS.api(`/api/student/goals/${g.id}/tick`, { method: "POST" }); go("me", "growth"); } }, "+1") : null,
          el("button", { class: "small-btn", onclick: async () => { await HS.api(`/api/student/goals/${g.id}/archive`, { method: "POST" }); go("me", "growth"); } }, HS.pick("Remove", "हटाएँ"))));
    }));
  }

  async function growth(c) {
    const gr = await HS.api("/api/student/growth");
    const kind = el("select", { name: "kind", "aria-label": HS.pick("Goal type", "लक्ष्य का प्रकार") },
      Object.entries(gr.goal_kinds).map(([k, v]) => el("option", { value: k }, HS.pick(v.label, v.label_hi))));
    const title = el("input", { name: "title", maxlength: "140", placeholder: HS.pick("e.g. Read chapter 3 of EVS", "जैसे: पर्यावरण का पाठ 3 पढ़ना") });
    const target = el("input", { name: "target", type: "number", min: "1", max: "50", value: "3", "aria-label": HS.pick("How many", "कितने") });
    const err = el("p", { class: "form-error", role: "alert" });
    const form = el("form", { class: "stack" }, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, HS.pick("Goal", "लक्ष्य")), kind), el("div", null, el("label", null, HS.pick("Target", "संख्या")), target)),
    el("div", null, el("label", null, HS.pick("Describe it (optional)", "विवरण (वैकल्पिक)")), title), err,
    el("button", { class: "primary", type: "submit" }, HS.pick("Add goal", "लक्ष्य जोड़ें")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await HS.api("/api/student/goals", { method: "POST", body: { kind: kind.value, title: title.value.trim() || kind.selectedOptions[0].textContent, target: Number(target.value) } });
        go("me", "growth");
      } catch (ex) { err.textContent = ex.message; }
    });
    const ways = [["✏️", "Practice or quiz", "अभ्यास या क्विज़", 10], ["📖", "Read a lesson", "पाठ पढ़ना", 5], ["📚", "Read a textbook chapter", "पाठ्यपुस्तक अध्याय पढ़ना", 5],
      ["🔁", "Answer a revision question", "दोहराने का प्रश्न", 3], ["🤝", "Help a classmate (answer marked helpful)", "सहपाठी की मदद", 15]];
    HS.mount(c, el("div", { class: "stack" },
      levelCard(gr.level),
      card(HS.pick("My goals this week", "इस सप्ताह के मेरे लक्ष्य"), gr.goals.length ? goalList(gr.goals, false)
        : HS.empty(HS.pick("Set a goal for this week. Small goals are easier to finish!", "इस सप्ताह के लिए एक लक्ष्य बनाएँ। छोटे लक्ष्य जल्दी पूरे होते हैं!")),
      gr.goals.length < 6 ? el("details", { open: !gr.goals.length || null }, el("summary", null, "➕ " + HS.pick("New goal", "नया लक्ष्य")), form) : null),
      card(HS.pick("How to earn XP", "XP कैसे कमाएँ"), el("ul", { class: "list" }, ways.map(([ic, en, hi, xp]) =>
        el("li", { class: "row" }, el("span", { "aria-hidden": "true" }, ic), el("span", null, HS.pick(en, hi)), el("span", { class: "spacer" }), el("strong", { class: "num" }, `+${xp} XP`))))),
      card(HS.pick("Topics to revise", "दोहराने वाले टॉपिक"), gr.revision.topics.length
        ? el("div", { class: "badges" }, gr.revision.topics.map((t) => el("span", { class: "badge-pill" }, `${t.topic} (${t.open})`)))
        : HS.empty(HS.pick("No open mistakes. Well done!", "कोई गलती बाकी नहीं। शाबाश!")),
      gr.revision.due ? el("button", { class: "primary", onclick: () => go("quiz", "revise") }, HS.pick(`Fix ${gr.revision.due} mistakes now`, `अभी ${gr.revision.due} गलतियाँ सुधारें`)) : null)));
  }

  // ------------------------------------------- badges and certificates --
  function challengeCard(ch) {
    const fill = el("div", { class: "bar-fill" });
    fill.style.width = Math.round((ch.done / ch.target) * 100) + "%";
    return el("div", { class: "challenge" }, el("span", { class: "big", "aria-hidden": "true" }, ch.complete ? "🏆" : "⚡"),
      el("div", null, el("span", { class: "small" }, HS.pick("This week's class challenge", "इस सप्ताह की कक्षा चुनौती")),
        el("strong", null, HS.pick(ch.title, ch.title_hi)),
        el("div", { class: "bar-track", role: "meter", "aria-valuemin": "0", "aria-valuemax": String(ch.target), "aria-valuenow": String(ch.done), "aria-label": ch.title }, fill),
        el("span", { class: "small" }, ch.complete ? HS.pick("Completed! Well done.", "पूरा हो गया! शाबाश।") : `${ch.done}/${ch.target}`)));
  }

  async function badges(c) {
    const r = await HS.api("/api/student/recognition");
    const earned = r.badges.filter((b) => b.earned), locked = r.badges.filter((b) => !b.earned);
    const cert = (b) => HS.certificate({ title: HS.pick(b.title, b.title_hi), recipient: r.certificate.name,
      detail: `${r.certificate.class} · ${r.certificate.school}`, reason: b.why, issuer: "HAMAR SHIKSHA" });
    HS.mount(c, el("div", { class: "stack" },
      challengeCard(r.challenge),
      card(HS.pick(`My badges (${earned.length})`, `मेरे बैज (${earned.length})`),
        earned.length ? el("div", { class: "badge-grid" }, earned.map((b) => HS.badgeCard(b, cert)))
          : HS.empty(HS.pick("Your first badge is close. Look below to see what to do next!", "आपका पहला बैज करीब है। नीचे देखें आगे क्या करना है!")),
        el("p", { class: "small muted" }, HS.pick("Badges reward improvement, effort and regularity, not only marks. Print a certificate for any badge you earn.",
          "बैज सुधार, मेहनत और नियमितता के लिए मिलते हैं, केवल अंकों के लिए नहीं। हर बैज का प्रमाण-पत्र छाप सकते हैं।"))),
      locked.length ? card(HS.pick("Badges to earn next", "अगले बैज"), el("div", { class: "badge-grid" }, locked.map((b) => HS.badgeCard(b)))) : null,
      card(HS.pick("Appreciation from my teachers", "शिक्षकों से सराहना"), r.appreciations.length
        ? el("div", null, r.appreciations.map((a) => el("div", { class: "kudos" }, "🌟 ", el("strong", null, HS.pick(a.title, a.title_hi)),
          a.message ? el("div", null, a.message) : null, el("div", { class: "small muted" }, `${a.from || ""} · ${HS.date(a.at)}`))))
        : HS.empty(HS.pick("Keep going — your teacher can see your effort.", "लगे रहो — आपके शिक्षक आपकी मेहनत देख रहे हैं।")))));
  }

  // --------------------------------------------------- revise mistakes --
  async function revise(c) {
    const r = await HS.api("/api/student/revision");
    const s = r.summary;
    const head = el("div", { class: "kpis" },
      el("div", { class: "kpi" }, el("div", { class: "label" }, HS.pick("Due today", "आज के")), el("div", { class: "value num" }, String(s.due))),
      el("div", { class: "kpi" }, el("div", { class: "label" }, HS.pick("Still to fix", "बाकी")), el("div", { class: "value num" }, String(s.open))),
      el("div", { class: "kpi" }, el("div", { class: "label" }, HS.pick("Mastered", "पक्के")), el("div", { class: "value num" }, String(s.mastered))));
    const intro = el("p", { class: "small muted" }, HS.pick("Questions you got wrong come back after 1, 3 and 7 days. Answer one correctly twice in a row and it is mastered.",
      "जो प्रश्न गलत हुए, वे 1, 3 और 7 दिन बाद फिर आते हैं। लगातार दो बार सही उत्तर देने पर वह पक्का हो जाता है।"));
    if (!r.items.length) {
      HS.mount(c, el("div", { class: "stack" }, head, intro, HS.empty(s.open ? HS.pick("Nothing due today. Come back tomorrow!", "आज कुछ बाकी नहीं। कल फिर आएँ!")
        : HS.pick("No mistakes to fix. Try a quiz!", "सुधारने के लिए कोई गलती नहीं। क्विज़ करें!"))));
      return;
    }
    const cards = r.items.map((it) => {
      const result = el("div", { role: "status" });
      const opts = it.options.map((o, oi) => el("button", { type: "button", class: "option-btn", onclick: async () => {
        opts.forEach((b) => { b.disabled = true; });
        try {
          const out = await HS.api(`/api/student/revision/${it.id}/answer`, { method: "POST", body: { choice: oi } });
          opts[out.correct_index].classList.add("correct");
          if (!out.correct) opts[oi].classList.add("wrong");
          HS.mount(result, el("p", { class: "small" }, out.correct
            ? (out.mastered ? HS.pick("🎉 Mastered! +3 XP", "🎉 पक्का हो गया! +3 XP") : HS.pick(`✓ Correct! Next review: ${HS.date(out.next_review)}`, `✓ सही! अगली बार: ${HS.date(out.next_review)}`))
            : HS.pick("Not yet. The correct answer is shown in green. It will come back tomorrow.", "अभी नहीं। सही उत्तर हरे रंग में है। यह कल फिर आएगा।")));
        } catch (ex) { HS.mount(result, el("p", { class: "form-error" }, ex.message)); }
      } }, o));
      return el("section", { class: "card revise-card" },
        el("div", { class: "small muted" }, `${HS.pick(it.subject, it.subject_hi) || ""} · ${it.topic} · ${HS.pick(`wrong ${it.times_wrong}×`, `${it.times_wrong} बार गलत`)}`),
        el("p", null, el("strong", null, it.text)), el("div", { class: "stack-sm" }, opts), result);
    });
    HS.mount(c, el("div", { class: "stack" }, head, intro, cards));
  }

  // ----------------------------------------------------------- textbooks --
  async function books(c) {
    const lib = await HS.api("/api/student/library");
    if (!lib.books.length) { HS.mount(c, HS.empty(HS.pick("No textbooks loaded for your class yet.", "आपकी कक्षा की पाठ्यपुस्तकें अभी उपलब्ध नहीं हैं।"))); return; }
    HS.mount(c, el("div", { class: "stack" },
      el("p", { class: "small muted" }, HS.pick(`Class ${lib.grade} textbooks. Read a chapter, ask Gyan about it, and mark it as read (+5 XP).`,
        `कक्षा ${lib.grade} की पाठ्यपुस्तकें। अध्याय पढ़ें, उसके बारे में ज्ञान से पूछें और पढ़ा हुआ चिह्नित करें (+5 XP)।`)),
      lib.books.map((b) => {
        const done = b.sections.filter((s) => s.read).length;
        return el("details", { class: "card book" },
          el("summary", null, el("span", { class: "book-title" }, `📘 ${b.title}`),
            el("span", { class: "small muted" }, ` ${HS.pick(b.subject, b.subject_hi) || ""} · ${done}/${b.sections.length} ${HS.pick("read", "पढ़े")}`),
            b.is_demo ? el("span", { class: "chip demo-badge" }, "demo") : null),
          el("p", { class: "small muted" }, b.publisher),
          el("ul", { class: "list big-list" }, b.sections.map((s) => el("li", null,
            el("button", { class: "big-item", onclick: () => readSection(b, s) },
              el("span", null, (s.read ? "✅ " : "📄 ") + s.title, el("br"), el("span", { class: "small muted" }, `p. ${s.pages}`)), el("span", null, "›"))))));
      })));
  }

  function readSection(book, sec) {
    HS.load(view, async (c) => {
      const d = await HS.api(`/api/student/library/${book.id}?key=${encodeURIComponent(sec.key)}`);
      const askBtn = el("button", { onclick: () => { pendingQuestion = HS.pick(`Explain the main idea of "${sec.title}" in simple words.`, `"${sec.title}" का मुख्य विचार सरल शब्दों में समझाइए।`); go("help", "ai"); } },
        "🤖 " + HS.pick("Ask Gyan about this", "इसके बारे में ज्ञान से पूछें"));
      const readBtn = el("button", { class: "primary", disabled: sec.read || null, onclick: async () => {
        try { await HS.api(`/api/student/library/${book.id}/read`, { method: "POST", body: { key: sec.key } }); HS.toast(HS.pick("Marked as read · +5 XP", "पढ़ा हुआ · +5 XP")); sec.read = true; readBtn.disabled = true; }
        catch (ex) { HS.toast(ex.message, true); }
      } }, sec.read ? "✅ " + HS.pick("Read", "पढ़ लिया") : HS.pick("I have read this ✓", "मैंने पढ़ लिया ✓"));
      HS.mount(c, el("div", { class: "stack" },
        el("button", { onclick: () => go("learn", "books") }, "← " + HS.t("back")),
        el("section", { class: "card reader" }, el("h2", null, sec.title), el("p", { class: "small muted" }, `${d.document} · ${d.publisher}`),
          d.passages.length ? d.passages.map((p) => el("div", { class: "passage" }, el("span", { class: "page-tag" }, `p. ${p.page}`),
            el("p", { lang: /[ऀ-ॿ]/.test(p.text) ? "hi" : "en" }, p.text))) : HS.empty(),
          el("div", { class: "row" }, readBtn, askBtn),
          el("p", { class: "small muted" }, HS.pick("Text extracted from the textbook PDF; pictures, maps and tables are not shown. Check your printed book.",
            "पाठ्यपुस्तक PDF से लिया गया पाठ; चित्र, नक्शे और तालिकाएँ नहीं दिखतीं। अपनी छपी किताब देखें।")))));
      window.scrollTo(0, 0);
    });
  }
  let pendingQuestion = null;

  // ------------------------------------------------- doubts & buddies --
  async function doubts(c, audience) {
    const list = (await HS.api("/api/student/doubts")).filter((d) => d.audience === audience);
    const sel = el("select", { "aria-label": "Subject" }, el("option", { value: "" }, HS.pick("Any subject", "कोई भी विषय")), S.subjects.map((s) => el("option", { value: s.id }, subj(s))));
    const topic = el("input", { maxlength: "120", placeholder: HS.pick("Topic (e.g. Fractions)", "टॉपिक (जैसे भिन्न)"), "aria-label": "Topic" });
    const body = el("textarea", { maxlength: "600", rows: "3", required: true, "aria-label": "Doubt",
      placeholder: audience === "teacher" ? HS.pick("Write your doubt for your teacher…", "अपने शिक्षक के लिए प्रश्न लिखें…") : HS.pick("Ask your classmates…", "अपने सहपाठियों से पूछें…") });
    const err = el("p", { class: "form-error", role: "alert" });
    const form = el("form", { class: "stack" }, el("div", { class: "inline-fields" }, sel, topic), body,
      HS.voice ? el("div", { class: "row voice-row" }, HS.voice.micButton(body)) : null, err,
      el("button", { class: "primary", type: "submit" }, audience === "teacher" ? HS.pick("Send to teacher", "शिक्षक को भेजें") : HS.pick("Post to class", "कक्षा में पूछें")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      try {
        await HS.api("/api/student/doubts", { method: "POST", body: { audience, subject_id: sel.value ? Number(sel.value) : null, topic: topic.value.trim(), body: body.value.trim() } });
        go("help", audience);
      } catch (ex) { err.textContent = ex.message; }
    });
    const intro = audience === "teacher"
      ? HS.pick("Only your teacher sees these questions.", "ये प्रश्न केवल आपके शिक्षक देखते हैं।")
      : HS.pick("Your classmates can answer, and your teacher checks the board. Be kind, and never share phone numbers or personal details. Answers marked helpful earn +15 XP.",
        "सहपाठी उत्तर दे सकते हैं और शिक्षक बोर्ड देखते हैं। अच्छे शब्दों में लिखें और कभी फ़ोन नंबर या निजी जानकारी न लिखें। मददगार उत्तर पर +15 XP मिलते हैं।");
    HS.mount(c, el("div", { class: "stack" },
      el("p", { class: "small muted" }, "🔒 " + intro),
      el("details", { class: "card", open: !list.length || null }, el("summary", null, "➕ " + HS.pick("Ask a new question", "नया प्रश्न पूछें")), form),
      list.length ? el("ul", { class: "list doubts" }, list.map(doubtItem)) : HS.empty(HS.pick("No questions yet.", "अभी कोई प्रश्न नहीं।"))));

    function doubtItem(d) {
      const ta = el("textarea", { rows: "2", maxlength: "800", "aria-label": HS.pick("Your answer", "आपका उत्तर") });
      const msg = el("p", { class: "form-error", role: "alert" });
      const canReply = d.status !== "resolved" && (audience === "class" || d.mine);
      return el("li", { class: "doubt card" + (d.status === "open" ? " open" : "") },
        el("div", { class: "row" }, el("strong", null, d.mine ? HS.pick("You", "आप") : d.asker),
          el("span", { class: "small muted" }, `${HS.pick(d.subject, d.subject_hi) || ""}${d.topic ? " · " + d.topic : ""}`), el("span", { class: "spacer" }),
          el("span", { class: "chip " + (d.status === "open" ? "st-stale" : "st-current") }, d.status === "open" ? HS.pick("waiting", "प्रतीक्षा") : HS.pick("answered", "उत्तर मिला"))),
        el("p", { class: "doubt-body" }, d.body),
        d.replies.length ? el("ul", { class: "replies" }, d.replies.map((r) => el("li", { class: r.role === "teacher" ? "teacher-reply" : "" },
          el("div", { class: "row" }, el("strong", { class: "small" }, r.mine ? HS.pick("You", "आप") : r.role === "teacher" ? "👩‍🏫 " + HS.pick("Teacher", "शिक्षक") : r.author),
            r.accepted ? el("span", { class: "chip verified-badge" }, HS.pick("helpful", "मददगार")) : null, el("span", { class: "spacer" }),
            d.mine && !r.accepted && !r.mine ? el("button", { class: "small-btn", onclick: async () => { await HS.api(`/api/student/replies/${r.id}/accept`, { method: "POST" }); go("help", audience); } }, "👍 " + HS.pick("Helpful", "मददगार")) : null,
            !r.mine && r.role === "student" ? el("button", { class: "small-btn link-btn", onclick: async () => { const o = await HS.api(`/api/student/replies/${r.id}/report`, { method: "POST" }); HS.toast(o.message); } }, "⚑ " + HS.pick("Report", "शिकायत")) : null),
          el("p", { class: "small" }, r.body)))) : null,
        canReply ? el("div", { class: "row" }, ta, el("button", { class: "small-btn primary", onclick: async () => {
          if (ta.value.trim().length < 2) return;
          try { await HS.api(`/api/student/doubts/${d.id}/replies`, { method: "POST", body: { body: ta.value.trim() } }); go("help", audience); }
          catch (ex) { msg.textContent = ex.message; }
        } }, d.mine ? HS.pick("Add", "जोड़ें") : HS.pick("Answer", "उत्तर दें")), msg) : null);
    }
  }

  async function buddies(c) {
    const list = await HS.api("/api/student/study-buddies");
    HS.mount(c, el("div", { class: "stack" },
      el("p", { class: "small muted" }, HS.pick("Your teacher pairs classmates so they can learn a topic together. Helping others is also the best way to learn!",
        "आपके शिक्षक सहपाठियों की जोड़ी बनाते हैं ताकि वे साथ में सीख सकें। दूसरों की मदद करना भी सीखने का सबसे अच्छा तरीका है!")),
      list.length ? list.map((b) => el("section", { class: "card buddy" },
        el("div", { class: "row" }, el("span", { class: "buddy-avatar", "aria-hidden": "true" }, b.partner.slice(0, 1)),
          el("div", null, el("strong", null, b.partner), el("div", { class: "small muted" }, `${HS.pick(b.subject, b.subject_hi) || ""} · ${b.topic}`)),
          el("span", { class: "spacer" }), el("span", { class: "chip " + (b.role === "helper" ? "ok-badge" : "ai-badge") }, b.role === "helper" ? HS.pick("You help", "आप मदद करते हैं") : HS.pick("Helps you", "आपकी मदद करते हैं"))),
        b.note ? el("p", { class: "small" }, "📝 " + b.note) : null))
        : HS.empty(HS.pick("No study buddy yet. Ask your teacher!", "अभी कोई साथी नहीं। अपने शिक्षक से पूछें!"))));
  }

  // ---------------------------------------------------------------- ask --
  async function ask(c) {
    const history = await HS.api("/api/student/assistant/history");
    const chat = el("div", { class: "chat", "aria-live": "polite" });
    const voice = HS.voice;
    const botMsg = (text, verified, citations) => el("div", { class: "msg bot" }, text,
      el("div", { class: "row msg-tools" },
        verified !== undefined ? el("span", { class: "chip " + (verified ? "verified-badge" : "unverified-badge") },
          verified ? HS.t("verified") : HS.t("not_verified")) : null,
        voice ? voice.speakButton(text) : null),
      HS.citations(citations));
    history.forEach((h) => chat.append(el("div", { class: "msg me" }, h.question), botMsg(h.answer, h.verified, h.citations)));
    const sel = el("select", { "aria-label": "Subject" }, el("option", { value: "" }, HS.lang === "hi" ? "कोई भी विषय" : "Any subject"), S.subjects.map((s) => el("option", { value: s.id }, subj(s))));
    const input = el("textarea", { maxlength: "500", rows: "2", "data-i18n-ph": "ask_ph", placeholder: HS.t("ask_ph"), "aria-label": HS.t("ask_ph") });
    if (pendingQuestion) { input.value = pendingQuestion; pendingQuestion = null; }
    const btn = el("button", { class: "primary", type: "submit" }, HS.t("nav_ask"));
    const auto = el("input", { type: "checkbox", id: "voice-autoread", checked: voice && voice.autoRead.get() ? true : null });
    auto.addEventListener("change", () => voice.autoRead.set(auto.checked));
    const voiceRow = voice ? el("div", { class: "stack voice-row" },
      el("div", { class: "row" }, voice.micButton(input), el("span", { class: "spacer" }),
        voice.canSpeak() ? el("label", { class: "inline-check", for: "voice-autoread" }, auto, HS.t("voice_autoread")) : null),
      el("p", { class: "small muted" }, "🔒 " + HS.t("voice_privacy"))) : null;
    const form = el("form", { class: "stack" }, sel, input, voiceRow, btn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (q.length < 2) return;
      chat.append(el("div", { class: "msg me" }, q));
      const pending = el("div", { class: "msg bot loading" }, HS.t("loading"));
      chat.append(pending);
      input.value = "";
      btn.disabled = true;
      try {
        const r = await HS.api("/api/student/assistant", { method: "POST", body: { question: q, subject_id: sel.value ? Number(sel.value) : null, language: HS.lang } });
        pending.replaceWith(botMsg(r.answer, r.flagged ? undefined : r.verified, r.citations));
        if (voice && voice.autoRead.get()) voice.speak(r.answer);
      } catch (ex) { pending.replaceWith(el("div", { class: "msg bot" }, ex.message)); }
      finally { btn.disabled = false; pending.scrollIntoView({ block: "end" }); }
    });
    HS.mount(c, el("div", { class: "stack" }, el("h1", null, `${HS.module("student", "AI Class")} · ${HS.module("slm", "Gyan")}`),
      el("p", { class: "small muted" }, HS.t("ask_notice") + (HS.lang === "hi"
        ? " उत्तर केवल आपकी स्वीकृत पाठ्यपुस्तक से दिए जाते हैं।" : " Answers come only from your approved textbooks.")),
      chat, form));
  }

  go(HS.offlineMode ? "quiz" : "home");
})();
