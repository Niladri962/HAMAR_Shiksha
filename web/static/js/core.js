/* Shared client helpers. No innerHTML is used anywhere: all text goes through
   textContent so server data can never inject markup. */
(function () {
  "use strict";
  const HS = (window.HS = {});
  const portal = document.body.dataset.portal || "";
  HS.portal = portal;

  // ---------------------------------------------------------------- i18n --
  function storedLang() {
    try { return localStorage.getItem("hs_lang"); } catch (_) { return null; }
  }
  HS.lang = storedLang() || (portal === "student" ? "hi" : "en");
  HS.t = (key) => (window.HS_I18N[HS.lang] || {})[key] ?? window.HS_I18N.en[key] ?? key;
  HS.applyI18n = (root = document) => {
    root.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = HS.t(n.dataset.i18n); });
    root.querySelectorAll("[data-i18n-ph]").forEach((n) => { n.placeholder = HS.t(n.dataset.i18nPh); });
    document.documentElement.lang = HS.lang === "hi" ? "hi" : "en";
  };
  HS.setLang = (lang, persist = true) => {
    HS.lang = lang;
    try { localStorage.setItem("hs_lang", lang); } catch (_) { /* storage blocked */ }
    if (persist && HS.me) HS.api("/api/auth/language", { method: "POST", body: { language: lang } }).catch(() => {});
    HS.applyI18n();
    document.dispatchEvent(new CustomEvent("hs:lang"));
  };
  HS.pick = (en, hi) => (HS.lang === "hi" && hi ? hi : en);

  // ----------------------------------------------------------------- DOM --
  HS.el = function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.assign(node.dataset, v);
        else if (v === true) node.setAttribute(k, "");
        else node.setAttribute(k, String(v));
      }
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  };
  const el = HS.el;
  HS.clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); return node; };
  HS.mount = (node, ...children) => { HS.clear(node); children.flat().forEach((c) => c && node.append(c)); return node; };

  // ----------------------------------------------------------------- API --
  function cookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }
  HS.ApiError = ApiError;
  function detail(data, status) {
    if (!data) return `Request failed (${status})`;
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join("; ");
    return `Request failed (${status})`;
  }
  HS.api = async function api(path, opts = {}) {
    const method = opts.method || "GET";
    const headers = {};
    let body;
    if (method !== "GET") headers["X-CSRF-Token"] = cookie("hs_csrf");
    if (opts.form) body = opts.form;
    else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
    let res;
    try {
      res = await fetch(path, { method, headers, body, credentials: "same-origin" });
    } catch (e) {
      throw new ApiError(navigator.onLine ? "Network error. Please try again." : HS.t("offline"), 0);
    }
    const isJson = (res.headers.get("content-type") || "").includes("json");
    const data = isJson ? await res.json().catch(() => null) : null;
    if (res.status === 401 && !opts.allow401 && portal) {
      location.href = `/${portal}/login`;
      throw new ApiError("Session expired", 401);
    }
    if (!res.ok) throw new ApiError(detail(data, res.status), res.status);
    return data;
  };

  // ---------------------------------------------------------- formatting --
  HS.pct = (v, digits = 0) => (v === null || v === undefined ? "—" : (v * 100).toFixed(digits) + "%");
  HS.num = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN"));
  HS.date = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
    return d.toLocaleDateString(HS.lang === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  HS.period = (p) => {
    const [y, m] = p.split("-").map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString(HS.lang === "hi" ? "hi-IN" : "en-IN", { month: "short", year: "2-digit" });
  };
  HS.today = () => new Date().toISOString().slice(0, 10);

  HS.statusChip = (status) => el("span", { class: `chip st-${status}`, title: HS.t("st_" + status) }, HS.t("st_" + status));
  HS.aiChip = (rec) => el("span", { class: "chip ai-badge", title: rec && rec.generated_by }, rec && rec.generated_by && rec.generated_by.startsWith("rules") ? HS.t("rules_engine") : HS.t("ai_generated"));

  // Milestone progress grade A-D: letter + words, never colour alone.
  const GRADE_WORDS = { A: ["On track", "समय पर"], B: ["Slightly behind", "थोड़ा पीछे"], C: ["Behind plan", "योजना से पीछे"], D: ["Needs support", "सहायता आवश्यक"] };
  HS.gradeChip = (g) => g ? el("span", { class: `chip grade grade-${g}`, title: HS.pick(...GRADE_WORDS[g]) }, `${g} · ${HS.pick(...GRADE_WORDS[g])}`)
    : el("span", { class: "chip grade grade-none" }, HS.pick("No milestones due", "कोई लक्ष्य देय नहीं"));
  HS.gradeBar = (counts) => {
    const order = ["A", "B", "C", "D"];
    const total = order.reduce((a, k) => a + (counts[k] || 0), 0);
    const bar = el("div", { class: "statusbar gradebar", role: "img", "aria-label": order.map((k) => `${k}: ${counts[k] || 0}`).join(", ") });
    order.forEach((k) => {
      if (!counts[k]) return;
      const seg = el("span", { class: "gseg-" + k, title: `${k} · ${HS.pick(...GRADE_WORDS[k])}: ${counts[k]}` }, counts[k] / (total || 1) >= 0.08 ? k : "");
      seg.style.flex = String(counts[k] / (total || 1));
      bar.append(seg);
    });
    return bar;
  };
  HS.gradeLegend = (counts) => el("div", { class: "grade-legend" }, ["A", "B", "C", "D"].map((k) =>
    el("span", null, HS.gradeChip(k), " ", el("strong", { class: "num" }, String(counts[k] || 0)))));
  // Printable motivational certificate (not an official record).
  HS.certificate = ({ title, recipient, detail, reason, issuer }) => {
    const node = el("div", { class: "cert-print" }, el("div", { class: "cert" },
      el("div", { class: "cert-brand" }, "HAMAR SHIKSHA · हमर शिक्षा"),
      el("div", { class: "cert-kicker" }, "Certificate of Achievement · उपलब्धि प्रमाण-पत्र"),
      el("div", { class: "cert-title" }, title),
      el("div", { class: "cert-to" }, "Presented to · प्रदान किया गया"),
      el("div", { class: "cert-name" }, recipient),
      detail ? el("div", { class: "cert-detail" }, detail) : null,
      el("div", { class: "cert-reason" }, reason),
      el("div", { class: "cert-foot" }, el("span", null, new Date().toLocaleDateString("en-IN")), el("span", null, issuer || "")),
      el("div", { class: "cert-note" }, "Generated from learning records to encourage progress. Not an official certificate.")));
    document.body.append(node);
    document.body.classList.add("printing-cert");
    const done = () => { node.remove(); document.body.classList.remove("printing-cert"); window.removeEventListener("afterprint", done); };
    window.addEventListener("afterprint", done);
    window.print();
  };
  // Badge card: earned badges are bright; locked ones show progress toward the target.
  HS.badgeCard = (b, onCert) => {
    const pct = b.current === null || b.current === undefined ? 0 : Math.max(0, Math.min(1, b.current / b.target));
    const fill = el("div", { class: "bar-fill" + (b.earned ? " done" : "") });
    fill.style.width = Math.round(pct * 100) + "%";
    return el("div", { class: "badge-card" + (b.earned ? " earned" : " locked") },
      el("div", { class: "badge-icon", "aria-hidden": "true" }, b.icon),
      el("div", { class: "badge-body" },
        el("strong", null, (b.earned ? "✓ " : "") + HS.pick(b.title, b.title_hi)),
        el("div", { class: "small muted" }, b.why),
        b.earned ? null : el("div", { class: "bar-track", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100",
          "aria-valuenow": String(Math.round(pct * 100)), "aria-label": b.title }, fill),
        b.earned && onCert ? el("button", { type: "button", class: "small-btn", onclick: () => onCert(b) }, "🖨 " + HS.pick("Certificate", "प्रमाण-पत्र")) : null));
  };
  HS.loading = () => el("div", { class: "loading", role: "status" }, HS.t("loading"));
  HS.empty = (msg) => el("div", { class: "empty" }, msg || HS.t("nothing_here"));
  HS.errorBox = (err, retry) => el("div", { class: "error-box", role: "alert" }, err.message || String(err),
    retry ? el("div", { class: "row" }, el("button", { onclick: retry }, HS.t("retry"))) : null);

  /** Render async content into a container with loading / error states. Each
      call renders into a fresh slot, so a slower earlier load (e.g. after a
      quick tab switch) can never overwrite the newer view. */
  HS.load = async function load(container, fn) {
    const slot = el("div", { class: "load-slot" });
    HS.mount(container, slot);
    HS.mount(slot, HS.loading());
    try { await fn(slot); }
    catch (e) { if (e.status !== 401 && slot.isConnected) HS.mount(slot, HS.errorBox(e, () => load(container, fn))); }
  };

  let toastTimer;
  HS.toast = (msg, isErr = false) => {
    document.querySelectorAll(".toast").forEach((n) => n.remove());
    const n = el("div", { class: "toast" + (isErr ? " err" : ""), role: isErr ? "alert" : "status" }, msg);
    document.body.append(n);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => n.remove(), 4500);
  };

  HS.table = (columns, rows, opts = {}) => {
    const thead = el("thead", null, el("tr", null, columns.map((c) => el("th", { class: c.num ? "n" : null, scope: "col" }, c.label))));
    const tbody = el("tbody");
    rows.forEach((r) => {
      const tr = el("tr", opts.onRow ? { class: "clickable", tabindex: "0" } : null,
        columns.map((c) => {
          const v = c.render ? c.render(r) : r[c.key];
          return el("td", { class: c.num ? "n" : null }, v instanceof Node ? v : (v === null || v === undefined ? "—" : String(v)));
        }));
      if (opts.onRow) {
        tr.addEventListener("click", () => opts.onRow(r));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") opts.onRow(r); });
      }
      tbody.append(tr);
    });
    if (!rows.length) tbody.append(el("tr", null, el("td", { colspan: columns.length }, HS.empty(opts.empty))));
    return el("div", { class: "table-wrap" }, el("table", null, opts.caption ? el("caption", { class: "sr-only" }, opts.caption) : null, thead, tbody));
  };

  HS.evidence = (obj) => {
    const dl = el("dl");
    for (const [k, v] of Object.entries(obj || {})) {
      if (v === null || v === undefined) continue;
      dl.append(el("dt", null, k.replace(/_/g, " ")), el("dd", null, typeof v === "object" ? JSON.stringify(v) : String(v)));
    }
    return el("details", { class: "evidence" }, el("summary", null, HS.t("evidence")), dl);
  };

  HS.tabs = (container, tabs, onSelect) => {
    const bar = el("div", { class: "tabs", role: "tablist" });
    const buttons = tabs.map((tab) => el("button", {
      role: "tab", id: "tab-" + tab.id, "aria-selected": "false", "data-i18n": tab.i18n,
      onclick: () => select(tab.id),
    }, HS.t(tab.i18n)));
    bar.append(...buttons);
    bar.addEventListener("keydown", (e) => {
      const i = buttons.indexOf(document.activeElement);
      if (i < 0) return;
      if (e.key === "ArrowRight") buttons[(i + 1) % buttons.length].focus();
      if (e.key === "ArrowLeft") buttons[(i - 1 + buttons.length) % buttons.length].focus();
    });
    container.append(bar);
    function select(id) {
      buttons.forEach((b, i) => b.setAttribute("aria-selected", String(tabs[i].id === id)));
      try { sessionStorage.setItem("hs_tab_" + portal, id); } catch (_) { /* ignore */ }
      onSelect(id);
    }
    let initial = tabs[0].id;
    try { const s = sessionStorage.getItem("hs_tab_" + portal); if (tabs.some((t) => t.id === s)) initial = s; } catch (_) { /* ignore */ }
    return { select, initial };
  };

  HS.formData = (form) => {
    const out = {};
    new FormData(form).forEach((v, k) => { out[k] = typeof v === "string" ? v.trim() : v; });
    return out;
  };

  HS.download = (url) => { const a = el("a", { href: url, download: "" }); document.body.append(a); a.click(); a.remove(); };

  // --------------------------------------------------- chrome & session --
  function offlineBanner() {
    const b = el("div", { class: "banner banner-offline hidden", role: "status", "data-i18n": "offline" }, HS.t("offline"));
    document.body.prepend(b);
    const sync = () => b.classList.toggle("hidden", navigator.onLine);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    sync();
  }

  HS.passwordDialog = (forced) => new Promise((resolve) => {
    const err = el("div", { class: "form-error", role: "alert" });
    const form = el("form", null,
      el("h2", null, HS.t("change_password_title")),
      forced ? el("p", { class: "muted" }, HS.t("change_password_msg")) : null,
      el("div", { class: "field" }, el("label", { for: "cp-cur" }, HS.t("current_password")),
        el("input", { id: "cp-cur", name: "current_password", type: "password", required: true, autocomplete: "current-password" })),
      el("div", { class: "field" }, el("label", { for: "cp-new" }, HS.t("new_password")),
        el("input", { id: "cp-new", name: "new_password", type: "password", required: true, autocomplete: "new-password", minlength: portal === "student" ? 8 : 10 }),
        el("div", { class: "hint" }, portal === "admin" ? "At least 12 characters, letters with digits or symbols." :
          portal === "student" ? "At least 8 characters, letters with numbers." : "At least 10 characters, letters with digits or symbols.")),
      el("div", { class: "field" }, el("label", { for: "cp-rep" }, HS.t("repeat_password")),
        el("input", { id: "cp-rep", name: "repeat", type: "password", required: true, autocomplete: "new-password" })),
      err,
      el("div", { class: "row" }, el("button", { class: "primary", type: "submit" }, HS.t("save")),
        forced ? null : el("button", { type: "button", onclick: () => { dlg.close(); resolve(false); } }, HS.t("cancel"))));
    const dlg = el("dialog", { "aria-labelledby": "cp-title" }, form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      if (d.new_password !== d.repeat) { err.textContent = HS.t("passwords_differ"); return; }
      try {
        await HS.api("/api/auth/change-password", { method: "POST", body: { current_password: d.current_password, new_password: d.new_password } });
        dlg.close(); dlg.remove(); HS.toast("Password updated"); resolve(true);
      } catch (ex) { err.textContent = ex.message; }
    });
    dlg.addEventListener("cancel", (e) => { if (forced) e.preventDefault(); });
    document.body.append(dlg);
    dlg.showModal();
  });

  // -------------------------------------------------------- offline sync --
  // Store-and-forward: events are queued in IndexedDB with a unique id and
  // pushed to /api/sync/push when online. The server re-validates everything.
  HS.sync = (() => {
    const DB_NAME = "hs-offline", OUT = "outbox", CACHE = "cache";
    let dbp = null;
    const listeners = new Set();
    function idb() {
      if (!("indexedDB" in window)) return Promise.reject(new Error("no indexedDB"));
      if (!dbp) {
        dbp = new Promise((resolve, reject) => {
          const req = indexedDB.open(DB_NAME, 1);
          req.onupgradeneeded = () => {
            req.result.createObjectStore(OUT, { keyPath: "event_uid" });
            req.result.createObjectStore(CACHE, { keyPath: "key" });
          };
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error);
        });
      }
      return dbp;
    }
    async function tx(store, mode, fn) {
      const db = await idb();
      return new Promise((resolve, reject) => {
        const t = db.transaction(store, mode);
        const r = fn(t.objectStore(store));
        t.oncomplete = () => resolve(r && "result" in r ? r.result : undefined);
        t.onerror = () => reject(t.error);
      });
    }
    const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (_) { return null; } return null; };
    function uid() {
      const a = new Uint8Array(16);
      crypto.getRandomValues(a);
      return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
    }
    function deviceUid() {
      let d = ls("hs_device");
      if (!d) { d = "web-" + uid().slice(0, 24); ls("hs_device", d); }
      return d;
    }
    const owner = () => (HS.me ? HS.me.login_id : "anon");
    async function mine() {
      try { return (await tx(OUT, "readonly", (s) => s.getAll())).filter((e) => e.owner === owner()); }
      catch (_) { return []; }
    }
    const state = { lastSync: null, errors: [], syncing: false };
    function notify() { listeners.forEach((fn) => fn(state)); }

    async function queue(type, payload) {
      const ev = { event_uid: uid(), type, payload, created_at: new Date().toISOString(), owner: owner() };
      await tx(OUT, "readwrite", (s) => s.put(ev));
      notify();
      return ev;
    }
    async function flush() {
      if (!navigator.onLine || state.syncing || !HS.me) return;
      const events = await mine();
      if (!events.length) { notify(); return; }
      state.syncing = true; notify();
      try {
        const res = await HS.api("/api/sync/push", { method: "POST", body: {
          device_uid: deviceUid(), profile: "browser", app_version: "web-1",
          events: events.slice(0, 200).map(({ owner: _o, ...e }) => e) } });
        state.errors = res.results.filter((r) => r.status === "rejected" || r.status === "conflict");
        await tx(OUT, "readwrite", (s) => res.results.forEach((r) => s.delete(r.event_uid)));
        state.lastSync = new Date().toISOString();
        ls("hs_last_sync_" + owner(), state.lastSync);
        if (state.errors.length) HS.toast(`${state.errors.length} offline change(s) could not be applied - see sync status`, true);
        document.dispatchEvent(new CustomEvent("hs:synced"));
      } catch (_) { /* stay queued; retry later */ }
      finally { state.syncing = false; notify(); }
    }
    async function pull() {
      try {
        const data = await HS.api("/api/sync/pull");
        await tx(CACHE, "readwrite", (s) => s.put({ key: owner() + ":bundle", data, at: new Date().toISOString() }));
        return data;
      } catch (_) { return cached(); }
    }
    async function cached() {
      try { const r = await tx(CACHE, "readonly", (s) => s.get(owner() + ":bundle")); return r ? r.data : null; }
      catch (_) { return null; }
    }
    async function clear() {
      try { await tx(OUT, "readwrite", (s) => s.clear()); await tx(CACHE, "readwrite", (s) => s.clear()); } catch (_) { /* ignore */ }
    }
    /** Run onlineFn; when offline (or the network fails) queue the event instead. */
    async function submit(type, payload, onlineFn) {
      if (navigator.onLine) {
        try { return { online: true, result: await onlineFn() }; }
        catch (e) { if (e.status !== 0) throw e; }
      }
      await queue(type, payload);
      HS.toast(HS.t("saved_offline"));
      return { online: false, result: null };
    }
    function indicator() {
      const pill = el("button", { type: "button", class: "sync-pill", "aria-live": "polite" });
      const render = async () => {
        const n = (await mine()).length;
        const on = navigator.onLine;
        state.lastSync = state.lastSync || ls("hs_last_sync_" + owner());
        pill.className = "sync-pill " + (on ? (state.errors.length ? "warn" : "ok") : "off");
        pill.textContent = `${on ? "● " + HS.t("online") : "○ " + HS.t("offline_short")}` +
          (n ? ` · ${n} ${HS.t("pending")}` : "") + (state.syncing ? " · ⟳" : "");
        pill.title = `${HS.t("last_sync")}: ${state.lastSync ? new Date(state.lastSync).toLocaleString() : "—"}`;
      };
      pill.addEventListener("click", async () => {
        const n = (await mine()).length;
        const dlg = el("dialog", null, el("h2", null, HS.t("sync_status")),
          el("p", null, `${navigator.onLine ? HS.t("online") : HS.t("offline_short")} · ${n} ${HS.t("pending")}`),
          el("p", { class: "small muted" }, `${HS.t("last_sync")}: ${state.lastSync ? new Date(state.lastSync).toLocaleString() : "—"}`),
          state.errors.length ? el("ul", { class: "small" }, state.errors.map((e) => el("li", null, `${e.status}: ${e.detail || ""}`))) : null,
          el("div", { class: "row" }, el("button", { class: "primary", onclick: () => flush().then(render) }, HS.t("sync_now")),
            el("button", { onclick: () => { dlg.close(); dlg.remove(); } }, HS.t("close"))));
        document.body.append(dlg);
        dlg.showModal();
      });
      listeners.add(render);
      window.addEventListener("online", () => { render(); flush(); });
      window.addEventListener("offline", render);
      render();
      setInterval(flush, 60000);
      return pill;
    }
    return { queue, flush, pull, cached, clear, submit, indicator, deviceUid, state };
  })();

  HS.citations = (list) => {
    if (!list || !list.length) return null;
    return el("ul", { class: "citations", "aria-label": HS.t("sources") }, list.map((c) => el("li", null,
      el("span", { "aria-hidden": "true" }, "📖 "), c.ref ? el("strong", null, `[${c.ref}] `) : null, c.text || c.citation,
      c.is_demo ? el("span", { class: "chip demo-badge" }, "demo") : null)));
  };

  HS.logout = async () => {
    try { await HS.api("/api/auth/logout", { method: "POST" }); } catch (_) { /* already signed out */ }
    await HS.sync.clear(); // no personal data stays on shared devices
    try { Object.keys(localStorage).filter((k) => k.startsWith("hs_me_") || k.startsWith("hs_last_sync_") || k.startsWith("hs_student_"))
      .forEach((k) => localStorage.removeItem(k)); } catch (_) { /* ignore */ }
    location.href = `/${portal}/login`;
  };

  /** Dashboard bootstrap: header, banners, forced password change. */
  HS.boot = async function boot(subtitleFn) {
    offlineBanner();
    HS.applyI18n();
    let me;
    try {
      me = await HS.api("/api/auth/me");
      try { localStorage.setItem("hs_me_" + portal, JSON.stringify({ name: me.name, login_id: me.login_id, portal: me.portal,
        role: me.role, scope: me.scope, language: me.language, demo_mode: me.demo_mode })); } catch (_) { /* ignore */ }
    } catch (e) {
      if (e.status !== 0) return null;
      // Offline: continue with the last known (non-sensitive) profile; data comes from the sync cache.
      try { me = JSON.parse(localStorage.getItem("hs_me_" + portal) || "null"); } catch (_) { me = null; }
      if (!me) return null;
      HS.offlineMode = true;
    }
    if (me.portal !== portal) { location.href = `/${me.portal}/dashboard`; return null; }
    HS.me = me;
    if (me.language && !storedLang()) HS.setLang(me.language, false);
    if (me.demo_mode) {
      document.body.prepend(el("div", { class: "banner banner-demo", role: "note", "data-i18n": "demo_banner" }, HS.t("demo_banner")));
    }
    const who = document.getElementById("who");
    if (who) HS.mount(who, el("strong", null, me.name), el("br"), subtitleFn ? subtitleFn(me) : me.role);
    document.getElementById("btn-logout")?.addEventListener("click", HS.logout);
    const langBtn = document.getElementById("btn-lang");
    langBtn?.addEventListener("click", () => HS.setLang(HS.lang === "hi" ? "en" : "hi"));
    try { HS.platform = await HS.api("/api/platform"); } catch (_) { HS.platform = { modules: {} }; }
    HS.module = (k, fallback) => (HS.platform.modules || {})[k] || fallback;
    if (me.must_change_password && !HS.offlineMode) await HS.passwordDialog(true);
    if (langBtn && me.portal !== "admin") langBtn.before(HS.sync.indicator());
    HS.sync.flush();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    return me;
  };
})();
