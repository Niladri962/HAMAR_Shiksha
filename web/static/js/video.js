/* AI video lesson player: plays a scene-by-scene lesson script as an animated
   video with spoken narration (the device's own voices), captions, a scene
   timeline and an end-of-lesson quiz. Without a voice for the language it
   still plays, timed to the length of the narration. */
(function () {
  "use strict";
  const HS = window.HS;
  const el = HS.el;
  const canSpeak = () => "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  let voices = [];
  const loadVoices = () => { voices = canSpeak() ? window.speechSynthesis.getVoices() : []; };
  if (canSpeak()) { loadVoices(); window.speechSynthesis.addEventListener?.("voiceschanged", loadVoices); }
  function pickVoice(lang) {
    const want = lang === "hi" ? ["hi-IN", "hi"] : ["en-IN", "en-GB", "en-US", "en"];
    for (const tag of want) {
      const m = voices.filter((v) => v.lang && v.lang.replace("_", "-").toLowerCase().startsWith(tag.toLowerCase()));
      if (m.length) return m.find((v) => v.localService) || m[0];
    }
    return null;
  }
  // Short utterances: some browsers stop speaking long ones after ~15 s.
  const sentences = (t) => String(t).split(/(?<=[.!?।])\s+/).map((s) => s.trim()).filter(Boolean);
  let active = null; // only one player speaks at a time

  HS.videoPlayer = function videoPlayer(lesson, { onComplete, autoplay = false } = {}) {
    if (active) active.stop();
    const scenes = lesson.scenes || [];
    const lang = lesson.language === "en" ? "en" : "hi";
    const T = (en, hi) => (HS.lang === "hi" ? hi : en);
    let idx = 0, playing = false, token = 0, rate = 1, voiceOn = true, captions = true, timer = null;

    const stage = el("div", { class: "vl-stage", role: "region", "aria-label": T("Video lesson", "वीडियो पाठ") });
    const caption = el("div", { class: "vl-caption", "aria-live": "polite" });
    const bar = el("div", { class: "vl-timeline" }, scenes.map((_, i) =>
      el("button", { type: "button", class: "vl-seg", "aria-label": T(`Scene ${i + 1}`, `दृश्य ${i + 1}`), onclick: () => go(i, playing) },
        el("span", { class: "vl-fill" }))));
    const playBtn = el("button", { type: "button", class: "vl-btn vl-play", "aria-label": T("Play", "चलाएँ"), onclick: () => (playing ? pause() : play()) }, "▶");
    const voiceBtn = el("button", { type: "button", class: "vl-btn", "aria-pressed": "true", title: T("Narration", "आवाज़"),
      onclick: () => { voiceOn = !voiceOn; voiceBtn.setAttribute("aria-pressed", String(voiceOn)); voiceBtn.textContent = voiceOn ? "🔊" : "🔇"; if (playing) go(idx, true); } }, "🔊");
    const ccBtn = el("button", { type: "button", class: "vl-btn", "aria-pressed": "true", title: T("Captions", "कैप्शन"),
      onclick: () => { captions = !captions; ccBtn.setAttribute("aria-pressed", String(captions)); caption.hidden = !captions; } }, "CC");
    const speed = el("select", { class: "vl-speed", "aria-label": T("Speed", "गति"), onchange: (e) => { rate = Number(e.target.value); if (playing) go(idx, true); } },
      [["0.8", "0.8×"], ["1", "1×"], ["1.2", "1.2×"]].map(([v, l]) => el("option", { value: v, selected: v === "1" ? true : null }, l)));
    const fsBtn = el("button", { type: "button", class: "vl-btn", title: T("Full screen", "पूर्ण स्क्रीन"),
      onclick: () => { const f = root.requestFullscreen || root.webkitRequestFullscreen; if (document.fullscreenElement) document.exitFullscreen(); else if (f) f.call(root); } }, "⛶");
    const counter = el("span", { class: "vl-count small" });
    const controls = el("div", { class: "vl-controls" },
      el("button", { type: "button", class: "vl-btn", "aria-label": T("Previous scene", "पिछला दृश्य"), onclick: () => go(Math.max(0, idx - 1), playing) }, "⏮"),
      playBtn,
      el("button", { type: "button", class: "vl-btn", "aria-label": T("Next scene", "अगला दृश्य"), onclick: () => next() }, "⏭"),
      counter, el("span", { class: "spacer" }), voiceBtn, ccBtn, speed, fsBtn);
    const root = el("div", { class: "vl-player" }, stage, caption, bar, controls);
    const voice = pickVoice(lang);
    const note = !canSpeak() || !voice ? el("p", { class: "small muted" },
      T("No voice for this language on this device: the lesson plays with captions.", "इस डिवाइस पर इस भाषा की आवाज़ नहीं है: पाठ कैप्शन के साथ चलेगा।")) : null;

    function renderScene() {
      const s = scenes[idx];
      const oldQuiz = root.querySelector(".vl-quiz");
      if (oldQuiz) oldQuiz.remove();
      HS.mount(stage, el("div", { class: `vl-scene vl-bg-${idx % 5}` },
        el("div", { class: "vl-visual", "aria-hidden": "true" }, s.visual || "📘"),
        el("div", { class: "vl-text" },
          el("div", { class: "vl-kicker" }, `${lesson.subject ? HS.pick(lesson.subject, lesson.subject_hi) + " · " : ""}${idx + 1} / ${scenes.length}`),
          el("h3", { class: "vl-heading" }, s.heading),
          s.points && s.points.length ? el("ul", { class: "vl-points" }, s.points.map((p, i) => {
            const li = el("li", null, p); li.style.animationDelay = (0.6 + i * 0.9) / rate + "s"; return li;
          })) : null)));
      caption.textContent = s.narration;
      caption.hidden = !captions;
      counter.textContent = `${idx + 1}/${scenes.length}`;
      [...bar.children].forEach((b, i) => b.classList.toggle("done", i < idx));
      [...bar.children].forEach((b, i) => b.classList.toggle("now", i === idx));
    }
    function progress(ms) {
      const fill = bar.children[idx] && bar.children[idx].firstChild;
      if (!fill) return;
      fill.style.transition = "none"; fill.style.width = "0%";
      void fill.offsetWidth;
      fill.style.transition = `width ${ms}ms linear`; fill.style.width = "100%";
    }
    function stopSound() {
      token++;
      clearTimeout(timer);
      if (canSpeak()) window.speechSynthesis.cancel();
    }
    function narrate(text, done) {
      const my = ++token;
      const est = Math.max(4000, text.length * 65) / rate;
      progress(est);
      if (!voiceOn || !voice || !canSpeak()) { timer = setTimeout(() => my === token && done(), est); return; }
      const parts = sentences(text);
      let i = 0;
      const speakNext = () => {
        if (my !== token || !root.isConnected) return;
        if (i >= parts.length) { timer = setTimeout(() => my === token && done(), 600); return; }
        const u = new SpeechSynthesisUtterance(parts[i++]);
        u.voice = voice; u.lang = voice.lang; u.rate = 0.95 * rate;
        u.onend = speakNext;
        u.onerror = speakNext;
        window.speechSynthesis.speak(u);
      };
      window.speechSynthesis.cancel();
      speakNext();
    }
    function go(i, keepPlaying) {
      stopSound();
      idx = Math.max(0, Math.min(scenes.length - 1, i));
      renderScene();
      if (keepPlaying) play(); else { playing = false; playBtn.textContent = "▶"; }
    }
    function next() { if (idx < scenes.length - 1) go(idx + 1, playing); else finish(); }
    function play() {
      if (!root.isConnected) return stop();
      playing = true; playBtn.textContent = "⏸"; playBtn.setAttribute("aria-label", T("Pause", "रोकें"));
      narrate(scenes[idx].narration, () => { if (!root.isConnected) return stop(); next(); });
    }
    function pause() {
      stopSound(); playing = false; playBtn.textContent = "▶"; playBtn.setAttribute("aria-label", T("Play", "चलाएँ"));
      const fill = bar.children[idx] && bar.children[idx].firstChild;
      if (fill) { const w = getComputedStyle(fill).width; fill.style.transition = "none"; fill.style.width = w; }
    }
    function stop() { stopSound(); playing = false; if (active === api) active = null; }
    function finish() {
      stop();
      playBtn.textContent = "▶"; playBtn.setAttribute("aria-label", T("Play", "चलाएँ"));
      [...bar.children].forEach((b) => b.classList.add("done"));
      const quiz = lesson.quiz || [];
      const answers = new Map();
      const doneBtn = el("button", { type: "button", class: "primary", onclick: () => {
        const correct = quiz.filter((q, i) => answers.get(i) === q.answer_index).length;
        quiz.forEach((q, i) => {
          const box = qs[i];
          [...box.querySelectorAll(".vl-opt")].forEach((b, oi) => b.classList.add(oi === q.answer_index ? "right" : answers.get(i) === oi ? "wrong" : "x"));
          if (q.explanation) box.append(el("p", { class: "small muted" }, q.explanation));
        });
        doneBtn.disabled = true;
        if (onComplete) onComplete(correct, quiz.length);
      } }, quiz.length ? T("Check answers", "उत्तर जाँचें") : T("I watched it ✓", "मैंने देख लिया ✓"));
      const qs = quiz.map((q, i) => el("div", { class: "vl-q" }, el("strong", null, `${i + 1}. ${q.question}`),
        el("div", { class: "vl-opts" }, q.options.map((o, oi) => el("button", { type: "button", class: "vl-opt", onclick: (e) => {
          answers.set(i, oi);
          [...e.currentTarget.parentNode.children].forEach((b) => b.classList.toggle("picked", b === e.currentTarget));
        } }, o)))));
      HS.mount(stage, el("div", { class: "vl-scene vl-end" },
        el("div", { class: "vl-visual", "aria-hidden": "true" }, "🎉"),
        el("div", { class: "vl-text" }, el("h3", { class: "vl-heading" }, T("Well done!", "शाबाश!")),
          el("p", null, quiz.length ? T("Answer these to finish the lesson.", "पाठ पूरा करने के लिए इनके उत्तर दें।") : T("You finished the lesson.", "आपने पाठ पूरा किया।")),
          el("button", { type: "button", class: "small-btn", onclick: () => go(0, false) }, "↺ " + T("Watch again", "फिर से देखें")))));
      caption.hidden = true;
      root.append(el("div", { class: "vl-quiz" }, qs, doneBtn));
    }
    const api = { root, stop, play };
    active = api;
    if (!scenes.length) return { root: HS.empty(T("This lesson has no scenes.", "इस पाठ में कोई दृश्य नहीं है।")), stop() {}, play() {} };
    renderScene();
    if (note) root.append(note);
    if (autoplay) setTimeout(play, 300);
    return api;
  };
})();
