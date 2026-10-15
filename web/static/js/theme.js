/* Light / dark theme. Loaded without `defer` in <head> so the saved choice is
   applied before the first paint (no flash). With no saved choice the page
   follows the device setting. */
(function () {
  "use strict";
  const KEY = "hs_theme";
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function saved() {
    try { const t = localStorage.getItem(KEY); return t === "dark" || t === "light" ? t : null; } catch (_) { return null; }
  }
  const apply = (t) => { if (t) root.dataset.theme = t; else delete root.dataset.theme; };
  apply(saved());
  // Accent colour (optional): overrides the portal's brand colour on this device.
  const ACCENTS = [["default", "Portal", "पोर्टल"], ["ocean", "Ocean", "समुद्री"], ["forest", "Forest", "वन"],
    ["saffron", "Saffron", "केसरिया"], ["plum", "Plum", "जामुनी"], ["rose", "Rose", "गुलाबी"]];
  const savedAccent = () => { try { return localStorage.getItem("hs_accent"); } catch (_) { return null; } };
  const applyAccent = (a) => { if (a && a !== "default") root.dataset.accent = a; else delete root.dataset.accent; };
  applyAccent(savedAccent());

  const current = () => root.dataset.theme || (media && media.matches ? "dark" : "light");
  const t = (key, fallback) => (window.HS && window.HS.t ? window.HS.t(key) : fallback);

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "btn-theme";
    btn.className = "theme-toggle";
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    btn.append(icon);
    function render() {
      const dark = current() === "dark";
      icon.textContent = dark ? "☀" : "☾";
      const label = dark ? t("theme_to_light", "Switch to light theme") : t("theme_to_dark", "Switch to dark theme");
      btn.setAttribute("aria-label", label);
      btn.title = label;
    }
    btn.addEventListener("click", () => {
      const next = current() === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(KEY, next); } catch (_) { /* storage blocked: applies to this page only */ }
      render();
    });
    if (media && media.addEventListener) media.addEventListener("change", render);
    document.addEventListener("hs:lang", render);
    // Accent picker: a palette button with a small popover of colour choices.
    const lang = document.getElementById("btn-lang");
    const bar = document.querySelector(".topbar-inner");
    const pick = (en, hi) => ((window.HS && window.HS.lang === "hi") ? hi : en);
    const accBtn = document.createElement("button");
    accBtn.type = "button";
    accBtn.className = "theme-toggle";
    accBtn.setAttribute("aria-haspopup", "true");
    accBtn.setAttribute("aria-expanded", "false");
    accBtn.textContent = "🎨";
    const wrap = document.createElement("span");
    wrap.className = "accent-wrap";
    const pop = document.createElement("div");
    pop.className = "accent-pop hidden";
    pop.setAttribute("role", "dialog");
    wrap.append(accBtn, pop);
    function renderPop() {
      while (pop.firstChild) pop.removeChild(pop.firstChild);
      const h = document.createElement("h3");
      h.textContent = pick("Colour scheme", "रंग योजना");
      const grid = document.createElement("div");
      grid.className = "accent-grid";
      const current = savedAccent() || "default";
      ACCENTS.forEach(([key, en, hi]) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "swatch";
        b.setAttribute("aria-pressed", String(current === key));
        const dot = document.createElement("span");
        dot.className = "dot dot-" + key;
        dot.setAttribute("aria-hidden", "true");
        b.append(dot, document.createTextNode(pick(en, hi)));
        b.addEventListener("click", () => {
          applyAccent(key);
          try { localStorage.setItem("hs_accent", key); } catch (_) { /* this page only */ }
          renderPop();
        });
        grid.append(b);
      });
      pop.append(h, grid);
      const label = pick("Choose colour scheme", "रंग योजना चुनें");
      accBtn.setAttribute("aria-label", label);
      accBtn.title = label;
    }
    accBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = pop.classList.toggle("hidden") === false;
      accBtn.setAttribute("aria-expanded", String(open));
      if (open) renderPop();
    });
    document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) { pop.classList.add("hidden"); accBtn.setAttribute("aria-expanded", "false"); } });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { pop.classList.add("hidden"); accBtn.setAttribute("aria-expanded", "false"); } });
    document.addEventListener("hs:lang", renderPop);
    renderPop();

    if (lang) { lang.before(wrap); wrap.after(btn); }
    else if (bar) bar.append(wrap, btn);
    else { btn.classList.add("floating"); document.body.append(btn); }
    render();
  });
})();
