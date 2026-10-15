/* Admin dashboard. All data comes from /api/admin/*, which enforces scope
   server-side; the UI only decides what to display. */
(async function () {
  "use strict";
  const HS = window.HS;
  const el = HS.el;
  const ROLE = { state_admin: "State Administrator", district_admin: "District Administrator", block_admin: "Block Administrator" };

  const me = await HS.boot((m) => ROLE[m.role] || m.role);
  if (!me) return;
  const scopeLabel = document.getElementById("scope-label");
  scopeLabel.textContent = me.role === "state_admin" ? "Chhattisgarh · " + ROLE[me.role]
    : me.role === "district_admin" ? `${HS.pick(me.scope.district.name, me.scope.district.name_hi)} · ${ROLE[me.role]}`
      : `${HS.pick(me.scope.block.name, me.scope.block.name_hi)} · ${ROLE[me.role]}`;
  const isState = me.role === "state_admin";

  const app = document.getElementById("app");
  const view = el("div", { id: "view" });
  const TABS = [
    { id: "overview", i18n: "tab_overview" }, { id: "map", i18n: "tab_map" }, { id: "command", i18n: "tab_command" }, { id: "schools", i18n: "tab_schools" },
    { id: "insights", i18n: "tab_insights" }, { id: "inbox", i18n: "tab_inbox" },
    { id: "reports", i18n: "tab_reports" }, { id: "kb", i18n: "tab_kb" }, { id: "manage", i18n: "tab_manage" },
  ];
  if (isState) TABS.push({ id: "audit", i18n: "tab_audit" });
  let current = "overview";
  const tabs = HS.tabs(app, TABS, (id) => { current = id; render(); });
  app.append(view);
  document.addEventListener("hs:lang", render);

  // Drill-down state shared between Overview links and the Schools tab.
  const root = isState ? { level: "state" }
    : me.role === "district_admin" ? { level: "district", id: me.scope.district.id }
      : { level: "block", id: me.scope.block.id };
  let nav = [root];
  function openNav(entry, reset = false) {
    nav = reset ? [root, entry] : [...nav, entry];
    tabs.select("schools");
  }

  function render() {
    const fns = { overview, map: mapView, command, schools, insights, inbox, reports, kb, manage, audit };
    HS.load(view, fns[current]);
  }

  // ------------------------------------------------------------ helpers --
  const kpi = (label, value, sub) => el("div", { class: "kpi" }, el("div", { class: "label" }, label),
    el("div", { class: "value num" }, value), sub ? el("div", { class: "sub" }, sub) : null);
  const card = (title, ...body) => el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", null, title)), ...body);
  const flagsCell = (flags) => flags && flags.length
    ? el("span", { class: "chip flag", title: flags.map((f) => f.reason).join("; ") }, `${flags.length}`) : "—";
  const subjName = (subjects, code) => subjects && subjects[code] ? HS.pick(subjects[code].name, subjects[code].name_hi) : code;

  function metricsColumns() {
    return [
      { label: HS.t("k_schools"), num: true, render: (r) => r.metrics.schools },
      { label: HS.t("k_current"), num: true, render: (r) => `${r.metrics.data_status.current}/${r.metrics.schools}` },
      { label: HS.t("student_attendance"), num: true, render: (r) => HS.pct(r.metrics.student_attendance_rate) },
      { label: HS.t("teacher_attendance"), num: true, render: (r) => HS.pct(r.metrics.teacher_attendance_rate) },
      { label: HS.t("avg_score"), num: true, render: (r) => HS.pct(r.metrics.avg_score_pct) },
      { label: HS.t("k_support"), num: true, render: (r) => r.needs_support },
    ];
  }

  function searchCard() {
    const input = el("input", { id: "code-search", inputmode: "search", autocomplete: "off", maxlength: "80", "data-i18n-ph": "search_code_ph", placeholder: HS.t("search_code_ph") });
    const out = el("div");
    const form = el("form", { class: "row", role: "search" },
      el("div", { class: "spacer" }, el("label", { for: "code-search" }, HS.t("search_code")), input),
      el("button", { class: "primary", type: "submit" }, HS.t("search")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) return;
      const qs = /^\d[\d\s]{9,}$/.test(v) ? "code=" + encodeURIComponent(v.replace(/\s/g, "")) : "q=" + encodeURIComponent(v);
      HS.mount(out, HS.loading());
      try {
        const rows = await HS.api("/api/admin/search/schools?" + qs);
        HS.mount(out, schoolTable(rows, (r) => openNav({ level: "school", id: r.id, label: r.name }, true)));
      } catch (ex) {
        HS.mount(out, el("p", { class: "form-error", role: "alert" },
          ex.status === 404 ? "No registered school with this code in your area." : ex.message));
      }
    });
    return el("section", { class: "card" }, form, out);
  }

  function schoolTable(rows, onRow) {
    return HS.table([
      { label: "UDISE", key: "official_code" },
      { label: HS.t("schools_title"), render: (r) => el("span", null, r.name, r.is_demo ? el("span", { class: "chip demo-badge" }, "Demo") : null) },
      { label: "Block", key: "block" },
      { label: "Data", render: (r) => r.status === "active" ? HS.statusChip(r.data_status) : el("span", { class: "chip st-missing" }, r.status) },
      { label: HS.t("student_attendance"), num: true, render: (r) => HS.pct(r.latest && r.data_status === "current" ? r.latest.student_attendance_rate : null) },
      { label: HS.t("avg_score"), num: true, render: (r) => HS.pct(r.latest && r.data_status === "current" ? r.latest.avg_score_pct : null) },
      { label: "Flags", render: (r) => flagsCell(r.flags) },
    ], rows, { onRow, caption: "Schools" });
  }

  // ----------------------------------------------------------- overview --
  async function overview(c) {
    const d = await HS.api("/api/admin/overview");
    const m = d.metrics, t = d.totals;
    const parts = [searchCard()];
    parts.push(el("div", { class: "kpis" },
      kpi(HS.t("k_schools"), HS.num(t.schools_active), t.schools_pending_activation ? `${t.schools_pending_activation} pending activation` : null),
      kpi(HS.t("k_districts") + " / " + HS.t("k_blocks"), `${t.districts} / ${t.blocks}`),
      kpi(HS.t("k_current"), `${m.schools_reporting_current}/${m.schools}`, m.metrics_basis),
      kpi(HS.t("k_teachers"), HS.num(t.teachers_verified)),
      kpi(HS.t("k_students"), HS.num(t.students_enrolled)),
      kpi(HS.t("k_support"), HS.num(t.schools_needing_support), "rule-based flags; see list below")));

    parts.push(card(HS.t("data_status_title"), HS.charts.statusBar(m.data_status),
      el("p", { class: "small muted" }, `Outcome metrics below use only schools with current data (${m.metrics_basis}). ` +
        "Stale = last report older than the freshness window; Missing = nothing reported.")));

    parts.push(el("div", { class: "kpis" },
      kpi(HS.t("student_attendance"), HS.pct(m.student_attendance_rate)),
      kpi(HS.t("teacher_attendance"), HS.pct(m.teacher_attendance_rate)),
      kpi(HS.t("participation"), HS.pct(m.assessment_participation)),
      kpi(HS.t("avg_score"), HS.pct(m.avg_score_pct))));

    const trend = d.trend;
    parts.push(el("div", { class: "grid grid-2" },
      card(HS.t("trend_title"), HS.charts.line({
        labels: trend.map((r) => r.period), ariaLabel: "Monthly attendance and score trend",
        series: [
          { label: HS.t("student_attendance"), short: "Att.", values: trend.map((r) => r.student_attendance_rate) },
          { label: HS.t("teacher_attendance"), short: "Tch.", values: trend.map((r) => r.teacher_attendance_rate) },
          { label: HS.t("avg_score"), short: "Score", values: trend.map((r) => r.avg_score_pct) },
        ],
      }), el("p", { class: "small muted" }, "Schools reporting per month: " + trend.map((r) => `${HS.period(r.period)} ${r.schools_reporting}`).join(" · "))),
      card(HS.t("subject_title"), Object.keys(m.subject_scores).length
        ? HS.charts.bars(Object.entries(m.subject_scores).sort((a, b) => a[1] - b[1]).map(([k, v]) => ({ label: subjName(d.subjects, k), value: v })),
          { threshold: 0.45, thresholdLabel: "45% support threshold", ariaLabel: "Average score by subject" })
        : HS.empty(HS.t("no_data")))));

    parts.push(card(HS.t("grade_title"), Object.keys(m.grade_scores).length
      ? HS.charts.bars(Object.entries(m.grade_scores).map(([g, v]) => ({ label: "Class " + g, value: v })), { threshold: 0.45, ariaLabel: "Average score by class" })
      : HS.empty(HS.t("no_data"))));

    if (isState) {
      const districts = await HS.api("/api/admin/districts");
      const holder = el("div");
      const sel = el("select", { "aria-label": "Map metric" },
        el("option", { value: "avg_score_pct" }, HS.t("avg_score")),
        el("option", { value: "student_attendance_rate" }, HS.t("student_attendance")),
        el("option", { value: "assessment_participation" }, HS.t("participation")));
      const draw = () => HS.mount(holder, HS.charts.tileMap(districts.map((dd) => ({
        name: HS.pick(dd.name, dd.name_hi), value: dd.metrics[sel.value],
        sub: `${dd.metrics.data_status.current}/${dd.metrics.schools} current · ${dd.needs_support} flagged`,
        onClick: () => openNav({ level: "district", id: dd.id, label: dd.name }, true),
      })), { metricLabel: sel.selectedOptions[0].textContent }));
      sel.addEventListener("change", draw);
      draw();
      parts.push(el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", null, HS.t("districts_title")), sel),
        el("p", { class: "small muted" }, HS.t("tilemap_note")), holder));
    }

    const support = await HS.api("/api/admin/needs-support");
    parts.push(card(HS.t("needs_support_title"),
      el("p", { class: "small muted" }, "Flags come from fixed, published thresholds (attendance < 75%, teacher attendance < 85%, participation < 60%, average score < 45%) and missing/stale reporting. They prompt follow-up, not judgement."),
      schoolTable(support.slice(0, 15), (r) => openNav({ level: "school", id: r.id, label: r.name }, true))));
    HS.mount(c, el("div", { class: "stack" }, parts));
  }

  // ------------------------------------------------- map & divisions --
  let geoCache = null;
  let mapMetric = "registry_schools";
  let mapDivision = null;
  const MAP_METRICS = {
    registry_schools: { en: "Schools in registry", hi: "रजिस्ट्री में स्कूल", count: true },
    schools_active: { en: "Schools onboarded", hi: "जुड़े हुए स्कूल", count: true },
    students: { en: "Students enrolled", hi: "नामांकित विद्यार्थी", count: true },
    teachers: { en: "Verified teachers", hi: "सत्यापित शिक्षक", count: true },
    avg_score_pct: { en: "Average score", hi: "औसत अंक" },
    student_attendance_rate: { en: "Student attendance", hi: "विद्यार्थी उपस्थिति" },
    on_track_share: { en: "Schools on track (grade A/B)", hi: "योजना पर स्कूल (A/B)" },
    digital_utilisation: { en: "Digital resource use (of target)", hi: "डिजिटल संसाधन उपयोग" },
    followup_rate: { en: "Children needing attendance follow-up", hi: "अनुवर्ती की ज़रूरत वाले बच्चे" },
    division: { en: "Colour by division", hi: "संभाग के अनुसार रंग" },
  };
  const metricOf = (r, k) => (MAP_METRICS[k].count ? r[k] : r.metrics[k]);
  const fmtMetric = (k, v) => (v === null || v === undefined ? "—" : MAP_METRICS[k].count ? HS.num(v) : HS.pct(v));

  async function mapView(c) {
    const [d, gj] = await Promise.all([HS.api("/api/admin/map"),
      geoCache ? Promise.resolve(geoCache) : fetch("/static/data/cg-districts.geojson").then((r) => r.json())]);
    geoCache = gj;
    const divIndex = Object.fromEntries(d.divisions.map((v, i) => [v.code, i + 1]));
    const divName = Object.fromEntries(d.divisions.map((v) => [v.code, HS.pick(v.name, v.name_hi)]));

    // Division summary cards (click to highlight a division on the map and in the table).
    const divCards = el("div", { class: "division-cards" }, d.divisions.map((v) => el("button", {
      type: "button", class: `division-card dv-${divIndex[v.code]}` + (mapDivision === v.code ? " active" : ""),
      "aria-pressed": String(mapDivision === v.code), onclick: () => { mapDivision = mapDivision === v.code ? null : v.code; render(); } },
    el("span", { class: "dv-name" }, HS.pick(`${v.name} division`, `${v.name_hi} संभाग`)),
    el("span", { class: "dv-big num" }, HS.num(v.registry_schools)), el("span", { class: "dv-label" }, HS.pick("schools in registry", "रजिस्ट्री में स्कूल")),
    el("span", { class: "dv-stats small" },
      `${v.districts} ${HS.pick("districts", "ज़िले")} · ${HS.num(v.schools_active)} ${HS.pick("onboarded", "जुड़े")} · ${HS.num(v.students)} ${HS.pick("students", "विद्यार्थी")} · ${HS.num(v.teachers)} ${HS.pick("teachers", "शिक्षक")}`),
    el("span", { class: "dv-stats small" }, `${HS.t("avg_score")} ${HS.pct(v.metrics.avg_score_pct)} · ${HS.t("student_attendance")} ${HS.pct(v.metrics.student_attendance_rate)}`))));

    const sel = el("select", { "aria-label": HS.pick("Map shows", "नक्शे में") }, Object.entries(MAP_METRICS).map(([k, m]) =>
      el("option", { value: k, selected: k === mapMetric || null }, HS.pick(m.en, m.hi))));
    sel.addEventListener("change", () => { mapMetric = sel.value; render(); });

    // Group districts by map polygon (2022 districts share their parent's polygon).
    const byShape = {};
    d.districts.forEach((r) => { if (r.map_shape) (byShape[r.map_shape] = byShape[r.map_shape] || []).push(r); });
    const shapeValue = (rows) => {
      if (mapMetric === "division") return null;
      if (MAP_METRICS[mapMetric].count) return rows.reduce((a, r) => a + (r[mapMetric] || 0), 0);
      const pairs = rows.map((r) => [r.metrics[mapMetric], r.students || 1]).filter(([v]) => v !== null && v !== undefined);
      const w = pairs.reduce((a, [, n]) => a + n, 0);
      return w ? pairs.reduce((a, [v, n]) => a + v * n, 0) / w : null;
    };
    const vals = Object.values(byShape).map(shapeValue).filter((v) => v !== null);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const step = (v) => (v === null ? 0 : hi - lo < 1e-9 ? 4 : 1 + Math.round(((v - lo) / (hi - lo)) * 6));

    // Equirectangular projection with cos(latitude) correction.
    let minX = 180, maxX = -180, minY = 90, maxY = -90;
    gj.features.forEach((f) => f.geometry.coordinates.forEach((poly) => poly[0].forEach(([x, y]) => {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); })));
    const kx = Math.cos(((minY + maxY) / 2) * Math.PI / 180);
    const W = 520, pad = 10, scale = (W - 2 * pad) / ((maxX - minX) * kx), H = Math.round((maxY - minY) * scale + 2 * pad);
    const px = (x) => pad + (x - minX) * kx * scale, py = (y) => pad + (maxY - y) * scale;
    const NS = "http://www.w3.org/2000/svg";
    const mk = (tag, a) => { const n = document.createElementNS(NS, tag); Object.entries(a).forEach(([k, v]) => v !== null && n.setAttribute(k, v)); return n; };
    const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, class: "cgmap", role: "img",
      "aria-label": HS.pick(`Map of Chhattisgarh districts: ${MAP_METRICS[mapMetric].en}`, `छत्तीसगढ़ के ज़िलों का नक्शा: ${MAP_METRICS[mapMetric].hi}`) });
    const box = el("div", { class: "chart map-box" }, svg);
    const tip = el("div", { class: "tooltip hidden", role: "presentation" });
    box.append(tip);
    const labels = [];
    gj.features.forEach((f) => {
      const rows = byShape[f.properties.shape] || [];
      const div = rows[0] ? rows[0].division : null;
      const v = shapeValue(rows);
      const path = f.geometry.coordinates.map((poly) => poly.map((ring) => "M" + ring.map(([x, y]) => `${px(x).toFixed(1)},${py(y).toFixed(1)}`).join("L") + "Z").join("")).join("");
      const cls = ["shape", mapMetric === "division" ? `dv-fill-${divIndex[div] || 0}` : (rows.length && v !== null ? `seq-${step(v)}` : "no-data")];
      if (mapDivision && div !== mapDivision) cls.push("dim");
      if (!rows.length) cls.push("out-of-scope");
      const p = mk("path", { d: path, class: cls.join(" "), tabindex: rows.length ? "0" : null,
        "aria-label": rows.map((r) => `${r.name}: ${fmtMetric(mapMetric === "division" ? "registry_schools" : mapMetric, mapMetric === "division" ? r.registry_schools : metricOf(r, mapMetric))}`).join("; ") || f.properties.shape });
      const show = (evt) => {
        if (!rows.length) return;
        const rect = svg.getBoundingClientRect();
        HS.mount(tip, el("div", { class: "t-head" }, `${divName[div] || ""} ${HS.pick("division", "संभाग")}`),
          ...rows.map((r) => el("div", null, el("strong", null, HS.pick(r.name, r.name_hi) + (r.created_2022 ? " *" : "")), " — ",
            `${HS.num(r.registry_schools)} ${HS.pick("registry", "रजिस्ट्री")} · ${HS.num(r.schools_active)} ${HS.pick("onboarded", "जुड़े")} · ${HS.num(r.students)} ${HS.pick("students", "विद्यार्थी")} · ${HS.num(r.teachers)} ${HS.pick("teachers", "शिक्षक")}`,
            el("br"), `${HS.t("avg_score")} ${HS.pct(r.metrics.avg_score_pct)} · ${HS.t("student_attendance")} ${HS.pct(r.metrics.student_attendance_rate)}`)));
        tip.classList.remove("hidden");
        const x = evt.clientX !== undefined ? evt.clientX - rect.left : rect.width / 2;
        const y = evt.clientY !== undefined ? evt.clientY - rect.top : rect.height / 3;
        tip.style.left = Math.min(Math.max(0, x + 12), Math.max(0, box.clientWidth - tip.offsetWidth)) + "px";
        tip.style.top = Math.max(0, y - tip.offsetHeight - 10) + "px";
        p.classList.add("hover");
      };
      p.addEventListener("mousemove", show);
      p.addEventListener("focus", show);
      p.addEventListener("mouseleave", () => { tip.classList.add("hidden"); p.classList.remove("hover"); });
      p.addEventListener("blur", () => { tip.classList.add("hidden"); p.classList.remove("hover"); });
      const open = () => { if (rows.length === 1) openNav({ level: "district", id: rows[0].id, label: rows[0].name }, true); };
      p.addEventListener("click", open);
      p.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      svg.append(p);
      // label at the bounding-box centre of the largest ring
      const ring = f.geometry.coordinates.map((poly) => poly[0]).sort((a, b) => b.length - a.length)[0];
      const xs = ring.map((q) => px(q[0])), ys = ring.map((q) => py(q[1]));
      labels.push([(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2, rows[0] ? HS.pick(rows.find((r) => !r.created_2022)?.name || rows[0].name, rows.find((r) => !r.created_2022)?.name_hi || rows[0].name_hi) : ""]);
    });
    labels.forEach(([x, y, t]) => {
      const n = mk("text", { x: x.toFixed(1), y: y.toFixed(1), class: "map-label", "text-anchor": "middle" });
      n.textContent = t.length > 14 ? t.split(/[- ]/)[0] : t;
      svg.append(n);
    });

    const legend = mapMetric === "division"
      ? el("div", { class: "legend" }, d.divisions.map((v) => el("span", null, el("span", { class: `sw box dv-bg-${divIndex[v.code]}` }), HS.pick(v.name, v.name_hi))))
      : el("div", { class: "ramp" }, el("span", { class: "num" }, fmtMetric(mapMetric, vals.length ? lo : null)),
        el("span", { class: "steps" }, [1, 2, 3, 4, 5, 6, 7].map((n) => el("span", { class: "seq-" + n }))),
        el("span", { class: "num" }, fmtMetric(mapMetric, vals.length ? hi : null)), el("span", null, HS.pick(MAP_METRICS[mapMetric].en, MAP_METRICS[mapMetric].hi)));

    // Ranking of districts for the chosen metric (bars), and the full table.
    const rankKey = mapMetric === "division" ? "registry_schools" : mapMetric;
    const shown = d.districts.filter((r) => !mapDivision || r.division === mapDivision);
    const ranking = HS.charts.bars(shown.map((r) => ({ label: HS.pick(r.name, r.name_hi), value: metricOf(r, rankKey),
      sub: divName[r.division] })).sort((a, b) => (b.value ?? -1) - (a.value ?? -1)).slice(0, 12),
    MAP_METRICS[rankKey].count ? { format: (v) => (v === null ? "—" : HS.num(v)), max: Math.max(1, ...shown.map((r) => metricOf(r, rankKey) || 0)),
      ariaLabel: "Districts ranked" } : { ariaLabel: "Districts ranked" });
    const makeTable = () => HS.table([
      { label: HS.pick("Division", "संभाग"), render: (r) => el("span", { class: `chip dv-chip-${divIndex[r.division] || 0}` }, divName[r.division] || "—") },
      { label: HS.pick("District", "ज़िला"), render: (r) => HS.pick(r.name, r.name_hi) + (r.created_2022 ? " *" : "") },
      { label: HS.pick("Registry", "रजिस्ट्री"), num: true, render: (r) => HS.num(r.registry_schools) },
      { label: HS.pick("Onboarded", "जुड़े"), num: true, render: (r) => HS.num(r.schools_active) },
      { label: HS.t("k_teachers"), num: true, render: (r) => HS.num(r.teachers) },
      { label: HS.t("k_students"), num: true, render: (r) => HS.num(r.students) },
      { label: HS.t("student_attendance"), num: true, render: (r) => HS.pct(r.metrics.student_attendance_rate) },
      { label: HS.t("avg_score"), num: true, render: (r) => HS.pct(r.metrics.avg_score_pct) },
      { label: HS.t("k_support"), num: true, render: (r) => r.needs_support },
    ], [...shown].sort((a, b) => (divIndex[a.division] || 9) - (divIndex[b.division] || 9) || a.name.localeCompare(b.name)),
    { onRow: (r) => openNav({ level: "district", id: r.id, label: r.name }, true), caption: "Districts by division" });
    const table = makeTable();

    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "row" }, el("h2", null, HS.pick("Chhattisgarh: divisions, districts and schools", "छत्तीसगढ़: संभाग, ज़िले और स्कूल")),
        el("span", { class: "spacer" }), d.demo ? el("span", { class: "chip demo-badge" }, HS.pick("Demonstration data", "डेमो डेटा")) : null),
      d.demo ? el("p", { class: "small muted" }, HS.pick("District and division names are real; every school, person and number here is generated demo data, not official UDISE+ statistics.",
        "ज़िलों और संभागों के नाम वास्तविक हैं; यहाँ सभी स्कूल, व्यक्ति और आँकड़े डेमो डेटा हैं, आधिकारिक UDISE+ आँकड़े नहीं।")) : null,
      divCards,
      el("div", { class: "map-layout" },
        el("section", { class: "card" }, el("div", { class: "card-head" }, el("h3", null, HS.pick("District map", "ज़िला नक्शा")), sel),
          HS.charts.withTable(el("div", null, box, legend), makeTable()),
          el("p", { class: "small muted" }, d.boundary_note + " * = " + HS.pick("district created in 2022", "2022 में बना ज़िला"))),
        el("section", { class: "card" }, el("div", { class: "card-head" }, el("h3", null,
          HS.pick(`Top districts: ${MAP_METRICS[rankKey].en}`, `शीर्ष ज़िले: ${MAP_METRICS[rankKey].hi}`) + (mapDivision ? ` · ${divName[mapDivision]}` : ""))), ranking)),
      card(HS.pick("All districts by division", "संभागवार सभी ज़िले"), table)));
  }

  // ----------------------------------------------------- Command Centre --
  // Command Centre sections.
  let commandSection = "overview";
  async function command(c) {
    const SECTIONS = [["overview", "📊", "Overview"], ["grades", "🗓️", "Progress grades"], ["attendance", "📅", "Attendance follow-up"],
      ["digital", "💻", "Digital infrastructure"], ["recognition", "🏅", "Recognition"]];
    const seg = el("div", { class: "segmented", role: "tablist", "aria-label": "Command Centre sections" }, SECTIONS.map(([k, ic, label]) =>
      el("button", { type: "button", role: "tab", "aria-selected": String(commandSection === k), onclick: () => { commandSection = k; render(); } },
        el("span", { "aria-hidden": "true" }, ic), " ", label)));
    const body = el("div");
    HS.mount(c, el("div", { class: "stack" }, el("h2", null, HS.module("admin", "Command Centre")), seg, body));
    await HS.load(body, { overview: commandOverview, grades: commandGrades, attendance: commandAttendance,
      digital: commandDigital, recognition: commandRecognition }[commandSection]);
  }

  async function commandGrades(c) {
    const d = await HS.api("/api/admin/command/progress-grades");
    const behind = d.schools.filter((s) => s.grade === "C" || s.grade === "D");
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "kpis" }, ["A", "B", "C", "D"].map((g) => el("div", { class: "kpi" }, el("div", { class: "label" }, HS.gradeChip(g)),
        el("div", { class: "value num" }, HS.num(d.counts[g])), el("div", { class: "sub" }, "schools")))),
      card(`Schools by progress grade, per ${d.level}`, el("p", { class: "small muted" }, d.definition),
        el("div", { class: "grade-units" }, d.units.map((u) => el("div", { class: "progress-row" },
          el("div", null, el("div", { class: "small" }, el("strong", null, u.name), ` · ${u.schools} schools`), HS.gradeBar(u.counts)),
          el("span", { class: "small num" }, `${u.counts.C + u.counts.D} behind`)))),
        HS.gradeLegend(d.counts)),
      card(`Schools behind plan (${behind.length}${behind.length > 40 ? ", most behind first; 40 shown" : ""}) — suggested corrective action`, behind.length ? HS.table([
        { label: "UDISE", key: "official_code" }, { label: "School", key: "school" }, { label: "Grade", render: (s) => HS.gradeChip(s.grade) },
        { label: "Taught", num: true, render: (s) => HS.pct(s.taught_rate) }, { label: "Learned", num: true, render: (s) => HS.pct(s.learned_rate) },
        { label: "Action", render: (s) => el("span", { class: "small" }, s.action || "—") }], behind.slice(0, 40),
      { onRow: (s) => openNav({ level: "school", id: s.school_id, label: s.school }, true) }) : HS.empty("No school is behind plan."))));
  }

  async function commandAttendance(c) {
    const d = await HS.api("/api/admin/command/attendance-risk");
    const t = d.total;
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "kpis" }, kpi("Students", HS.num(t.students)), kpi("Follow up now", HS.num(t.counts.high), HS.pct(t.counts.high / (t.students || 1), 1)),
        kpi("Keep watch", HS.num(t.counts.watch), HS.pct(t.counts.watch / (t.students || 1), 1))),
      el("p", { class: "small muted" }, "Counts only. Names are visible to the child's own teachers, who make the follow-up call or visit."),
      el("div", { class: "grid grid-2" },
        card(`Children needing follow-up, by ${d.level}`, HS.charts.bars(d.rows.map((r) => ({ label: r.name, value: r.students ? r.high / r.students : null,
          sub: `${r.high} now · ${r.watch} watch of ${r.students}` })), { max: Math.max(0.05, ...d.rows.map((r) => (r.students ? r.high / r.students : 0))), ariaLabel: "Share needing follow-up now" })),
        card("Attendance and learning", el("p", { class: "small muted" }, d.band_note),
          HS.charts.bars(t.by_band.map((b) => ({ label: `Attendance ${b.band}`, value: b.avg_score, sub: `${b.students} students` })), { ariaLabel: "Average score by attendance band" }))),
      el("details", null, el("summary", { class: "small" }, "Definitions"), el("p", { class: "small muted" }, d.definition))));
  }

  async function commandDigital(c) {
    const d = await HS.api("/api/admin/command/digital");
    const GAP = { not_working: "not working", unused: "unused", under_used: "under-used" };
    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "kpis" }, kpi("Resources", HS.num(d.resources), `${d.working} working`),
        kpi("Schools with resources", `${d.schools_with_resources}/${d.schools_in_scope}`),
        kpi(`Sessions (${d.window_weeks} weeks)`, HS.num(d.sessions)), kpi("Linked to a learning outcome", HS.pct(d.aligned_rate)),
        kpi("Utilisation gaps", HS.num(d.gaps.length))),
      el("div", { class: "grid grid-2" },
        card("Utilisation by resource type", HS.charts.bars(d.by_kind.map((k) => ({ label: HS.pick(k.label, k.label_hi), value: k.utilisation,
          sub: `${k.working}/${k.resources} working · ${k.sessions} sessions` })), { max: Math.max(1, ...d.by_kind.map((k) => k.utilisation || 0)), threshold: 0.5, thresholdLabel: "50% of target", ariaLabel: "Utilisation by type" })),
        card(`Utilisation by ${d.level}`, HS.charts.bars(d.units.map((u) => ({ label: u.name, value: u.utilisation, sub: `${u.resources} resources · ${u.gaps} gaps` })),
          { max: Math.max(1, ...d.units.map((u) => u.utilisation || 0)), threshold: 0.5, ariaLabel: "Utilisation by area" }))),
      el("div", { class: "grid grid-2" },
        card("Sessions by subject", d.by_subject.length ? HS.charts.bars(d.by_subject.map((s) => ({ label: HS.pick(s.subject, s.subject_hi), value: s.sessions })),
          { format: (v) => (v === null ? "—" : String(v)), max: Math.max(...d.by_subject.map((s) => s.sessions)), ariaLabel: "Sessions by subject" }) : HS.empty()),
        card("Use and learning results", el("p", { class: "small muted" }, d.impact.note),
          HS.table([{ label: "Classes with", key: "label" }, { label: "Classes", key: "classes", num: true },
            { label: "Average score", num: true, render: (g) => HS.pct(g.avg_score) }], d.impact.groups))),
      card(`Utilisation gaps (${d.gaps.length})`, el("p", { class: "small muted" }, d.definition), d.gaps.length ? HS.table([
        { label: "UDISE", key: "official_code" }, { label: "School", key: "school" }, { label: "Resource", render: (g) => `${g.label}` },
        { label: "Gap", render: (g) => el("span", { class: "chip " + (g.gap === "not_working" ? "flag" : "st-stale") }, GAP[g.gap]) },
        { label: "Sessions", key: "sessions", num: true }, { label: "Of target", num: true, render: (g) => HS.pct(g.utilisation) },
        { label: "Note", render: (g) => el("span", { class: "small" }, g.status_note || "") }], d.gaps.slice(0, 60)) : HS.empty("No gaps."))));
  }

  async function commandRecognition(c) {
    const d = await HS.api("/api/admin/command/recognition");
    const appreciate = (t) => {
      const f = el("form", { class: "row" }, el("select", { name: "category", "aria-label": "Category" }, d.categories.map((k) => el("option", { value: k.key }, HS.pick(k.label, k.label_hi)))),
        el("input", { name: "message", maxlength: "300", placeholder: "Message (optional)", "aria-label": "Message" }),
        el("button", { class: "primary", type: "submit" }, "🌟 Appreciate"));
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await HS.api(`/api/admin/teachers/${t.user_id}/appreciate`, { method: "POST", body: HS.formData(f) }); HS.toast(`Appreciation sent to ${t.name}`); f.reset(); }
        catch (ex) { HS.toast(ex.message, true); }
      });
      return f;
    };
    HS.mount(c, el("div", { class: "stack" },
      el("p", { class: "small muted" }, d.note),
      card("Most improved schools", d.improved_schools.length ? HS.table([{ label: "UDISE", key: "official_code" }, { label: "School", key: "school" },
        { label: "Average score gain", num: true, render: (s) => el("span", { class: "chip st-current" }, `+${s.change_points} points`) },
        { label: "Period", render: (s) => `${HS.period(s.from_period)} → ${HS.period(s.to_period)}` }], d.improved_schools)
        : HS.empty("No school shows a clear improvement yet.")),
      card("Teachers in the most improved schools", d.teachers.length ? el("ul", { class: "list" }, d.teachers.map((t) => el("li", null,
        el("div", { class: "row" }, el("strong", null, t.name), el("span", { class: "small muted" }, t.school), el("span", { class: "spacer" }),
          t.badges.map((b) => el("span", { class: "badge-pill", title: b.title }, `${b.icon} ${HS.pick(b.title, b.title_hi)}`))),
        el("details", null, el("summary", { class: "small" }, "🌟 Appreciate"), appreciate(t))))) : HS.empty())));
  }

  async function commandOverview(c) {
    const [ptl, gaps, corr, part, devs] = await Promise.all([
      HS.api("/api/admin/command/ptl"), HS.api("/api/admin/command/expertise-gaps"), HS.api("/api/admin/command/correlation"),
      HS.api("/api/admin/command/participation"), HS.api("/api/admin/command/devices")]);
    const t = ptl.total;
    const ptlRows = el("div", { class: "ptl" }, ptl.rows.flatMap((r) => [
      el("span", { class: "small" }, r.name),
      el("div", null, HS.charts.meter(r.taught_rate, "taught"), HS.charts.meter(r.learned_rate, "learned")),
      el("span", { class: "small num" }, `${HS.pct(r.taught_rate)} / ${HS.pct(r.learned_rate)}`)]));

    // Attendance vs score scatter (single series; table view available).
    const W = 520, H = 260, m = 36;
    const svgNS = "http://www.w3.org/2000/svg";
    const mk = (tag, a) => { const n = document.createElementNS(svgNS, tag); Object.entries(a).forEach(([k, v]) => n.setAttribute(k, v)); return n; };
    const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Attendance versus average score by school" });
    const sx = (v) => m + v * (W - 2 * m), sy = (v) => H - m - v * (H - 2 * m);
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      svg.append(mk("line", { x1: m, x2: W - m, y1: sy(v), y2: sy(v), class: "gridline" }));
      const tx = mk("text", { x: m - 6, y: sy(v) + 4, class: "axis-label", "text-anchor": "end" }); tx.textContent = HS.pct(v); svg.append(tx);
      const ty = mk("text", { x: sx(v), y: H - m + 16, class: "axis-label", "text-anchor": "middle" }); ty.textContent = HS.pct(v); svg.append(ty);
    });
    corr.points.forEach((p) => {
      const dot = mk("circle", { cx: sx(p.attendance), cy: sy(p.avg_score), r: 5, class: "mk mk-1" });
      const title = document.createElementNS(svgNS, "title");
      title.textContent = `${p.school}: attendance ${HS.pct(p.attendance)}, score ${HS.pct(p.avg_score)}`;
      dot.append(title); svg.append(dot);
    });
    const scatter = HS.charts.withTable(el("div", { class: "chart" }, svg,
      el("div", { class: "legend" }, el("span", null, "x: " + HS.t("student_attendance")), el("span", null, "y: " + HS.t("avg_score")))),
    HS.table([{ label: "School", key: "school" }, { label: HS.t("student_attendance"), num: true, render: (p) => HS.pct(p.attendance) },
      { label: HS.t("avg_score"), num: true, render: (p) => HS.pct(p.avg_score) }], corr.points));

    HS.mount(c, el("div", { class: "stack" },
      el("div", { class: "kpis" },
        kpi("Outcomes planned to date", HS.num(t.planned_due)),
        kpi("Taught", HS.pct(t.taught_rate), `${t.taught} of ${t.planned_due}`),
        kpi("Learned (of taught & assessed)", HS.pct(t.learned_rate), `${t.learned} of ${t.assessed}`),
        kpi("Teachers active (7 days)", `${part.teachers_active}/${part.teachers}`),
        kpi("Students learning (7 days)", `${part.students_active_learning}/${part.students}`)),
      card(`Planned → taught → learned, by ${ptl.level}`, el("p", { class: "small muted" }, ptl.definition),
        el("p", { class: "small" }, "Each row: upper bar = taught share of planned outcomes; lower bar = learned share of taught outcomes."), ptlRows),
      el("div", { class: "grid grid-2" },
        card("Attendance and learning", el("p", { class: "small muted" },
          `Pearson r = ${corr.pearson_r ?? "—"} across ${corr.n} schools with current data. ${corr.note}`), scatter),
        card("Subject expertise gaps", el("p", { class: "small muted" }, gaps.definition),
          Object.keys(gaps.by_subject).length ? HS.charts.bars(Object.entries(gaps.by_subject).map(([k, v]) => ({ label: k, value: v })),
            { format: (v) => (v === null ? "—" : String(v)), max: Math.max(...Object.values(gaps.by_subject)), ariaLabel: "Schools with gaps by subject" }) : HS.empty(),
          el("details", null, el("summary", null, "Schools"), HS.table([{ label: "UDISE", key: "official_code" }, { label: "School", key: "school" },
            { label: "Subject", key: "subject" }, { label: "Classes", render: (g) => g.classes.join(", ") }], gaps.schools)))),
      card("Devices and synchronisation", el("p", { class: "small muted" }, "Devices that used offline mode in your area. Revoke a lost or shared device to block further sync."),
        HS.table([{ label: "Device", key: "label" }, { label: "Profile", key: "profile" }, { label: "School", key: "school" },
          { label: "Last sync", render: (d) => d.last_sync_at ? new Date(d.last_sync_at).toLocaleString("en-IN") : "—" },
          { label: "Problems (7d)", key: "sync_problems_7d", num: true }, { label: "Status", key: "status" },
          { label: "", render: (d) => d.status === "active" ? el("button", { class: "danger", onclick: async () => {
            if (!confirm("Revoke this device?")) return;
            try { await HS.api(`/api/admin/command/devices/${d.id}/revoke`, { method: "POST" }); render(); } catch (ex) { HS.toast(ex.message, true); }
          } }, "Revoke") : null }], devs))));
  }

  // ------------------------------------------------- curriculum & AI ----
  async function kb(c) {
    const [st, docs] = await Promise.all([HS.api("/api/kb/status"), HS.api("/api/kb/documents")]);
    const slm = st.slm;
    const testOut = el("div");
    const test = el("form", { class: "row" }, el("input", { name: "q", placeholder: "Try a curriculum question…", "aria-label": "Search", required: true }),
      el("input", { name: "grade", type: "number", min: "1", max: "12", placeholder: "Class", "aria-label": "Class" }),
      el("button", { type: "submit" }, HS.t("search")));
    test.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(test);
      const r = await HS.api(`/api/kb/search?q=${encodeURIComponent(d.q)}${d.grade ? "&grade=" + d.grade : ""}`);
      HS.mount(testOut, el("p", { class: "small" }, r.supported ? "✓ Supported by approved material" : "✗ No supporting passage — the tutor will say it cannot verify"),
        HS.table([{ label: "Citation", key: "citation" }, { label: "BM25", key: "bm25", num: true }, { label: "Vector", key: "vector", num: true },
          { label: "Text", render: (h) => h.text.slice(0, 160) + "…" }], r.hits));
    });
    const parts = [
      el("div", { class: "kpis" },
        kpi(HS.module("slm", "Gyan SLM"), slm.ok ? "● online" : "○ offline", `${slm.configured_runtime} · ${slm.configured_model}`),
        kpi("Retrieval", slm.embedding_model ? "Hybrid" : "Keyword", slm.embedding_model || "BM25 only"),
        kpi("Approved documents", HS.num(st.documents), `${HS.num(st.chunks)} indexed passages`),
        kpi("Languages", slm.languages.join(", "), `roadmap: ${slm.roadmap_languages.join(", ")} (after validation)`)),
      card("Test retrieval", test, testOut),
      card("Curriculum documents", HS.table([
        { label: "Title", render: (d) => el("span", null, d.title, d.is_demo ? el("span", { class: "chip demo-badge" }, "demo - not SCERT") : null) },
        { label: "Type", key: "doc_type" }, { label: "Class", key: "grade" }, { label: "Lang", key: "language" },
        { label: "Version", key: "curriculum_version" }, { label: "Publisher", key: "publisher" },
        { label: "Passages", key: "chunks", num: true }, { label: "Status", key: "approval_status" },
        { label: "", render: (d) => isState && d.approval_status === "approved" ? el("button", { class: "danger", onclick: async () => {
          if (!confirm(`Withdraw "${d.title}"? The tutor will stop citing it.`)) return;
          await HS.api(`/api/kb/documents/${d.id}/withdraw`, { method: "POST" }); render();
        } }, "Withdraw") : null }], docs))];
    if (isState) {
      const out = el("div");
      const up = el("form", null, el("div", { class: "inline-fields" },
        el("div", null, el("label", null, "File (PDF with text layer, TXT or MD)"), el("input", { type: "file", name: "file", accept: ".pdf,.txt,.md", required: true })),
        el("div", null, el("label", null, "Title"), el("input", { name: "title", required: true, minlength: "3" })),
        el("div", null, el("label", null, "Type"), el("select", { name: "doc_type" }, ["textbook", "syllabus", "lo_framework", "lesson_material", "question_paper", "training"].map((t) => el("option", null, t)))),
        el("div", null, el("label", null, "Subject code"), el("select", { name: "subject" }, el("option", { value: "" }, "—"), ["HIN", "ENG", "MATH", "EVS", "SCI", "SST"].map((s) => el("option", null, s)))),
        el("div", null, el("label", null, "Class"), el("input", { name: "grade", type: "number", min: "1", max: "12" })),
        el("div", null, el("label", null, "Language"), el("select", { name: "language" }, el("option", { value: "hi" }, "Hindi"), el("option", { value: "en" }, "English"))),
        el("div", null, el("label", null, "Curriculum version"), el("input", { name: "curriculum_version", required: true, placeholder: "SCERT 2026-27" })),
        el("div", null, el("label", null, "Publisher"), el("input", { name: "publisher", required: true, value: "SCERT Chhattisgarh" }))),
      el("button", { class: "primary", type: "submit" }, "Ingest"));
      up.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(up);
        ["subject", "grade"].forEach((k) => { if (!fd.get(k)) fd.delete(k); });
        HS.mount(out, HS.loading());
        try { const r = await HS.api("/api/kb/documents", { method: "POST", form: fd }); HS.mount(out, el("p", null, `${r.created ? "Ingested" : "Already present"}: ${r.chunks} passages.`)); render(); }
        catch (ex) { HS.mount(out, el("p", { class: "form-error" }, ex.message)); }
      });
      parts.push(card("Ingest authorised material", el("p", { class: "small muted" },
        "Only material approved for use (SCERT textbooks, syllabi, LO frameworks, approved TLM). Scanned PDFs without a text layer need OCR first."), up, out));
    }
    HS.mount(c, el("div", { class: "stack" }, parts));
  }

  // ------------------------------------------------------------ schools --
  function crumbs() {
    const names = { state: "Chhattisgarh" };
    const bar = el("nav", { class: "crumbs", "aria-label": "Breadcrumb" });
    nav.forEach((n, i) => {
      if (i) bar.append(el("span", { class: "sep", "aria-hidden": "true" }, "›"));
      const label = n.label || names[n.level] || n.level;
      if (i === nav.length - 1) bar.append(el("strong", { "aria-current": "page" }, label));
      else bar.append(el("button", { type: "button", onclick: () => { nav = nav.slice(0, i + 1); render(); } }, label));
    });
    return bar;
  }

  async function schools(c) {
    const here = nav[nav.length - 1];
    const body = el("div", { class: "stack" });
    if (here.level === "state") {
      const ds = await HS.api("/api/admin/districts");
      body.append(card(HS.t("districts_title"), HS.table([{ label: HS.t("districts_title"), render: (r) => HS.pick(r.name, r.name_hi) }, ...metricsColumns()],
        ds, { onRow: (r) => openNav({ level: "district", id: r.id, label: r.name }) })));
    } else if (here.level === "district") {
      const d = await HS.api(`/api/admin/districts/${here.id}/blocks`);
      here.label = d.district.name;
      body.append(card(`${HS.pick(d.district.name, d.district.name_hi)} — ${HS.t("blocks_title")}`,
        HS.table([{ label: HS.t("blocks_title"), render: (r) => HS.pick(r.name, r.name_hi) }, ...metricsColumns()],
          d.blocks, { onRow: (r) => openNav({ level: "block", id: r.id, label: r.name }) })));
    } else if (here.level === "block") {
      const d = await HS.api(`/api/admin/blocks/${here.id}/schools`);
      here.label = d.block.name;
      body.append(card(`${HS.pick(d.block.name, d.block.name_hi)} — ${HS.t("schools_title")}`,
        schoolTable(d.schools, (r) => openNav({ level: "school", id: r.id, label: r.name }))));
    } else if (here.level === "school") {
      body.append(await schoolView(here));
    } else if (here.level === "class") {
      body.append(await classView(here));
    }
    HS.mount(c, crumbs(), body);
  }

  async function schoolView(here) {
    const s = await HS.api(`/api/admin/schools/${here.id}`);
    here.label = s.name;
    const latest = s.latest;
    const current = s.data_status === "current";
    const profile = el("dl", { class: "small" });
    [["Official code (UDISE+)", s.official_code], ["District", s.district], ["Block", s.block], ["Locality", `${s.locality} (${s.locality_type})`],
      ["Category", s.category], ["Medium", s.medium], ["Classes", s.classes], ["Platform status", s.status]]
      .forEach(([k, v]) => profile.append(el("dt", { class: "muted" }, k), el("dd", null, v)));
    const head = el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", null, s.name),
        el("span", { class: "row" }, s.is_demo ? el("span", { class: "chip demo-badge" }, "Demo data") : null, HS.statusChip(s.data_status))),
      el("p", { class: "small muted" }, latest ? `Latest data: ${HS.period(latest.period)}, as of ${HS.date(latest.as_of)} · source: ${latest.source}` : HS.t("no_data")),
      profile);
    const parts = [head];
    if (s.flags.length) {
      parts.push(el("section", { class: "card" }, el("h3", null, "Signals"), el("ul", null, s.flags.map((f) =>
        el("li", null, el("span", { class: "chip flag" }, f.type), " ", f.reason, f.value !== undefined ? ` (${HS.pct(f.value)})` : "")))));
    }
    parts.push(el("div", { class: "kpis" },
      kpi(HS.t("k_students"), latest ? HS.num(latest.student_count) : "—"),
      kpi(HS.t("k_teachers"), HS.num(s.teachers.verified || 0), s.teachers.pending ? `${s.teachers.pending} awaiting verification` : null),
      kpi(HS.t("student_attendance"), HS.pct(current ? latest.student_attendance_rate : null), current ? null : HS.t("st_" + s.data_status)),
      kpi(HS.t("teacher_attendance"), HS.pct(current ? latest.teacher_attendance_rate : null)),
      kpi(HS.t("participation"), HS.pct(current ? latest.assessment_participation : null)),
      kpi(HS.t("avg_score"), HS.pct(current ? latest.avg_score_pct : null))));
    if (s.history.length) {
      parts.push(el("div", { class: "grid grid-2" },
        card(HS.t("trend_title"), HS.charts.line({ labels: s.history.map((h) => h.period), ariaLabel: "School trend",
          series: [{ label: HS.t("student_attendance"), short: "Att.", values: s.history.map((h) => h.student_attendance_rate) },
            { label: HS.t("avg_score"), short: "Score", values: s.history.map((h) => h.avg_score_pct) }] })),
        card(HS.t("subject_title"), latest && Object.keys(latest.subject_scores).length
          ? HS.charts.bars(Object.entries(latest.subject_scores).map(([k, v]) => ({ label: k, value: v })), { threshold: 0.45 })
          : HS.empty(HS.t("no_data")))));
    }
    parts.push(card("Classes", HS.table([
      { label: "Class", key: "label" }, { label: "Year", key: "academic_year" }, { label: HS.t("k_students"), key: "students", num: true },
    ], s.classes, { onRow: (r) => openNav({ level: "class", id: r.id, label: r.label }) })));
    if (s.reports.length) {
      parts.push(card("Recent teacher reports", HS.table([{ label: "Title", key: "title" }, { label: "Period", key: "period" },
        { label: "Status", key: "status" }, { label: "Submitted", render: (r) => HS.date(r.submitted_at) }], s.reports)));
    }
    return el("div", { class: "stack" }, parts);
  }

  async function classView(here) {
    const d = await HS.api(`/api/admin/classes/${here.id}`);
    const parts = [el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", null, `${d.label} · ${d.school.name}`), el("span", { class: "muted small" }, d.academic_year)),
      el("p", { class: "small muted" }, "Aggregated learning progress only — individual student records are not shown in the administrator portal."),
      d.suppressed ? el("p", { class: "error-box" }, d.suppression_note) : null,
      el("div", { class: "kpis" }, kpi(HS.t("k_students"), d.students), kpi(HS.t("student_attendance") + " (30d)", HS.pct(d.attendance_rate_30d))))];
    d.subjects.forEach((s) => {
      parts.push(card(`${s.name} — ${HS.t("avg_score")} ${HS.pct(s.avg_score_pct)} · ${HS.t("participation")} ${HS.pct(s.participation)}`,
        s.topics.length ? HS.charts.bars(s.topics.map((t) => ({ label: t.topic, value: t.avg_mastery, sub: `${t.students} students · ${t.attempts} answers` })),
          { threshold: 0.6, thresholdLabel: "60% mastery", ariaLabel: `${s.name} topic mastery` })
          : HS.empty("Topic data hidden or not available.")));
    });
    return el("div", { class: "stack" }, parts);
  }

  // ----------------------------------------------------------- insights --
  function recCard(r, reviewUrl, after) {
    const note = el("input", { placeholder: "Review note (optional)", maxlength: "1000", "aria-label": "Review note" });
    const act = async (decision) => {
      try { await HS.api(reviewUrl(r.id), { method: "POST", body: { decision, note: note.value } }); HS.toast(HS.t(decision === "approve" ? "approved" : "dismissed")); after(); }
      catch (ex) { HS.toast(ex.message, true); }
    };
    return el("li", null,
      el("div", { class: "row" }, el("strong", null, r.title), HS.aiChip(r), el("span", { class: "chip " + (r.status === "pending_review" ? "st-stale" : "ok-badge") }, r.status.replace("_", " "))),
      el("p", null, r.summary),
      HS.evidence({ ...r.evidence, data_sources: r.data_sources, generated_by: r.generated_by, created_at: r.created_at }),
      r.status === "pending_review" ? el("div", { class: "row" }, note,
        el("button", { class: "primary", onclick: () => act("approve") }, HS.t("approve")),
        el("button", { onclick: () => act("dismiss") }, HS.t("dismiss"))) : (r.review_note ? el("p", { class: "small muted" }, "Note: " + r.review_note) : null));
  }

  async function insights(c) {
    const filter = el("select", { "aria-label": "Status filter" }, ["", "approved", "dismissed"].map((s) => el("option", { value: s }, s || "Open")));
    const list = el("ul", { class: "list" });
    const load = async () => {
      HS.mount(list, HS.loading());
      const recs = await HS.api("/api/admin/insights" + (filter.value ? "?status=" + filter.value : ""));
      HS.mount(list, recs.length ? recs.map((r) => recCard(r, (id) => `/api/admin/insights/${id}/review`, load)) : HS.empty());
    };
    filter.addEventListener("change", () => load().catch((e) => HS.mount(list, HS.errorBox(e))));
    const refresh = el("button", { onclick: async () => {
      refresh.disabled = true;
      try { const r = await HS.api("/api/admin/insights/refresh", { method: "POST" }); HS.toast(`${r.generated_or_updated} insights updated`); await load(); }
      catch (ex) { HS.toast(ex.message, true); } finally { refresh.disabled = false; }
    } }, HS.t("refresh"));
    HS.mount(c, el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", null, HS.t("tab_insights")), el("div", { class: "row" }, filter, refresh)),
      el("p", { class: "small muted" }, "Suggestions are generated from aggregated school data with the evidence shown. They are not decisions: review each one and record your judgement. No suggestion changes any record automatically."),
      list));
    await load();
  }

  // -------------------------------------------------------------- inbox --
  async function inbox(c) {
    const rows = await HS.api("/api/admin/school-reports");
    const list = el("ul", { class: "list" }, rows.map((r) => el("li", null,
      el("div", { class: "row" }, el("strong", null, r.title), el("span", { class: "muted small" }, `${r.school} · ${r.period} · ${HS.date(r.submitted_at)}`),
        el("span", { class: "chip " + (r.status === "acknowledged" ? "ok-badge" : "st-stale") }, r.status)),
      el("p", null, r.body),
      HS.evidence(r.metrics),
      r.status === "submitted" ? el("button", { onclick: async () => {
        try { await HS.api(`/api/admin/school-reports/${r.id}/acknowledge`, { method: "POST" }); render(); } catch (ex) { HS.toast(ex.message, true); }
      } }, "Acknowledge") : null)));
    HS.mount(c, card(HS.t("tab_inbox"), rows.length ? list : HS.empty()));
  }

  // ------------------------------------------------------------ reports --
  async function reports(c) {
    const geo = await HS.api("/api/admin/geography");
    const kinds = [["coverage", "School coverage"], ["performance", "School performance"], ["district-summary", "District & block summary"],
      ["interventions", "Learning gaps & interventions"], ["data-quality", "Data quality & completeness"]];
    const dSel = el("select", { name: "district_id", id: "r-d" }, el("option", { value: "" }, "All in my scope"),
      geo.map((d) => el("option", { value: d.id }, HS.pick(d.name, d.name_hi))));
    const bSel = el("select", { name: "block_id", id: "r-b" }, el("option", { value: "" }, "All"));
    dSel.addEventListener("change", () => {
      const d = geo.find((x) => String(x.id) === dSel.value);
      HS.mount(bSel, el("option", { value: "" }, "All"), (d ? d.blocks : []).map((b) => el("option", { value: b.id }, HS.pick(b.name, b.name_hi))));
    });
    const form = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", { for: "r-kind" }, "Report"), el("select", { id: "r-kind", name: "kind" }, kinds.map(([v, l]) => el("option", { value: v }, l)))),
      el("div", null, el("label", { for: "r-fmt" }, "Format"), el("select", { id: "r-fmt", name: "format" }, ["csv", "xlsx", "pdf"].map((f) => el("option", { value: f }, f.toUpperCase())))),
      el("div", null, el("label", { for: "r-d" }, "District"), dSel),
      el("div", null, el("label", { for: "r-b" }, "Block"), bSel),
      el("div", null, el("button", { class: "primary", type: "submit" }, HS.t("download")))));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const d = HS.formData(form);
      const qs = new URLSearchParams({ format: d.format });
      if (d.district_id) qs.set("district_id", d.district_id);
      if (d.block_id) qs.set("block_id", d.block_id);
      HS.download(`/api/admin/reports/${d.kind}?${qs}`);
    });
    HS.mount(c, card(HS.t("tab_reports"), el("p", { class: "small muted" },
      "Reports contain only schools in your administrative area and aggregated figures (no student names). Every export is recorded in the audit log. PDF uses Latin script only; use CSV/XLSX for Hindi names."), form));
  }

  // ------------------------------------------------------------- manage --
  function resultBox() { return el("div", { class: "small", role: "status" }); }
  function showSecret(box, title, rows) {
    HS.mount(box, el("div", { class: "card" }, el("strong", null, title),
      rows.map(([k, v]) => el("div", null, el("span", { class: "muted" }, k + ": "), el("span", { class: "secret" }, v))),
      el("p", { class: "small muted" }, "Shown once. Hand over through an approved channel; the user must change it at first sign-in.")));
  }

  async function manage(c) {
    const parts = [];

    // 1. Register school (Workflow A)
    const regOut = resultBox();
    const lookup = el("form", { class: "inline-fields" },
      el("div", null, el("label", { for: "reg-code" }, "Official school code (UDISE+)"),
        el("input", { id: "reg-code", name: "code", inputmode: "numeric", maxlength: "11", required: true, pattern: "\\d{11}" })),
      el("div", null, el("button", { type: "submit" }, "Look up in registry")));
    lookup.addEventListener("submit", async (e) => {
      e.preventDefault();
      const code = HS.formData(lookup).code;
      try {
        const r = await HS.api(`/api/admin/registry/${encodeURIComponent(code)}`);
        const form = el("form", { class: "inline-fields" },
          el("div", null, el("label", null, "Medium"), el("select", { name: "medium" }, ["Hindi", "English", "Chhattisgarhi", "Gondi", "Halbi"].map((m) => el("option", null, m)))),
          el("div", null, el("label", null, "Lowest class"), el("input", { name: "lowest_class", type: "number", min: "1", max: "12", value: "1" })),
          el("div", null, el("label", null, "Highest class"), el("input", { name: "highest_class", type: "number", min: "1", max: "12", value: "8" })),
          el("div", null, el("label", null, "Area"), el("select", { name: "locality_type" }, el("option", { value: "rural" }, "Rural"), el("option", { value: "urban" }, "Urban"))),
          el("div", null, el("button", { class: "primary", type: "submit", disabled: r.registered_school_id || r.registry_status !== "active" ? true : null }, "Register school")));
        form.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const d = HS.formData(form);
          try {
            const res = await HS.api("/api/admin/schools", { method: "POST", body: { official_code: r.code, medium: d.medium,
              lowest_class: Number(d.lowest_class), highest_class: Number(d.highest_class), locality_type: d.locality_type } });
            HS.mount(regOut, el("p", { class: "ok-badge chip" }, `Registered (status: ${res.status}). Another administrator must activate it.`));
          } catch (ex) { HS.mount(regOut, el("p", { class: "form-error" }, ex.message)); }
        });
        HS.mount(regOut, HS.evidence({ code: r.code, school_name: r.school_name, district_code: r.district_code, block_code: r.block_code,
          locality: r.locality, category: r.category, registry_status: r.registry_status, source: r.source,
          source_reference: r.source_reference, already_registered: r.registered_school_id ? "yes" : "no" }), form);
        regOut.querySelector("details").open = true;
      } catch (ex) { HS.mount(regOut, el("p", { class: "form-error" }, ex.status === 404 ? "Code not found in the official registry (or outside your area)." : ex.message)); }
    });
    parts.push(card("Register a school", el("p", { class: "small muted" }, "Only codes present and active in the imported government registry can be registered. Codes cannot be typed in freely."), lookup, regOut));

    // 2. Pending activations
    const pend = await HS.api("/api/admin/schools?status=pending");
    parts.push(card("Schools awaiting activation", HS.table([
      { label: "UDISE", key: "official_code" }, { label: "School", key: "name" }, { label: "Block", key: "block" },
      { label: "", render: (r) => me.role === "block_admin" ? el("span", { class: "muted small" }, "District/state approval") :
        el("button", { class: "primary", disabled: r.created_by_me && !isState ? true : null, onclick: async () => {
          try { await HS.api(`/api/admin/schools/${r.id}/activate`, { method: "POST" }); HS.toast("School activated"); render(); }
          catch (ex) { HS.toast(ex.message, true); }
        } }, "Activate") },
    ], pend)));

    // 3. Teacher verification (Workflow B)
    const tq = await HS.api("/api/admin/teachers/pending");
    parts.push(card("Teachers awaiting verification", el("p", { class: "small muted" }, "Verify identity and posting against service records before approving."),
      HS.table([{ label: "Employee ID", key: "employee_id" }, { label: "Name", key: "name" }, { label: "School", key: "school" },
        { label: "", render: (r) => el("span", { class: "row" },
          el("button", { class: "primary", onclick: () => verify(r.user_id, true) }, HS.t("approve")),
          el("button", { class: "danger", onclick: () => verify(r.user_id, false) }, "Reject")) }], tq)));
    async function verify(id, approve) {
      try { await HS.api(`/api/admin/teachers/${id}/verify`, { method: "POST", body: { approve } }); HS.toast(approve ? "Teacher verified" : "Teacher rejected"); render(); }
      catch (ex) { HS.toast(ex.message, true); }
    }

    // 4. Invite teacher
    const invOut = resultBox();
    const inv = el("form", null, el("div", { class: "inline-fields" },
      el("div", null, el("label", null, "School code (UDISE+)"), el("input", { name: "code", required: true, inputmode: "numeric", maxlength: "11" })),
      el("div", null, el("label", null, "Employee ID"), el("input", { name: "employee_id", required: true, maxlength: "40" })),
      el("div", null, el("label", null, "Full name"), el("input", { name: "full_name", required: true, maxlength: "150" })),
      el("div", null, el("label", null, "Designation"), el("input", { name: "designation", value: "Assistant Teacher", maxlength: "80" })),
      el("div", null, el("label", null, "Mobile"), el("input", { name: "phone", inputmode: "tel", maxlength: "20" })),
      el("div", null, el("button", { class: "primary", type: "submit" }, "Invite"))));
    inv.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = HS.formData(inv);
      try {
        const [school] = await HS.api("/api/admin/search/schools?code=" + encodeURIComponent(d.code));
        const r = await HS.api(`/api/admin/schools/${school.id}/teachers`, { method: "POST",
          body: { employee_id: d.employee_id, full_name: d.full_name, designation: d.designation, phone: d.phone || null } });
        showSecret(invOut, "Teacher invited — pending verification", [["Login ID", r.login_id], ["Temporary password", r.temporary_password]]);
        inv.reset();
      } catch (ex) { HS.mount(invOut, el("p", { class: "form-error" }, ex.status === 404 ? "School not found in your area." : ex.message)); }
    });
    parts.push(card("Invite a teacher", inv, invOut));

    // 5. Admin accounts (state only)
    if (isState) {
      const admins = await HS.api("/api/admin/admins");
      const geo = await HS.api("/api/admin/geography");
      const accOut = resultBox();
      const roleSel = el("select", { name: "role" }, el("option", { value: "district_admin" }, "District administrator"), el("option", { value: "block_admin" }, "Block administrator"));
      const areaSel = el("select", { name: "area" });
      const fillArea = () => HS.mount(areaSel, roleSel.value === "district_admin"
        ? geo.map((d) => el("option", { value: d.id }, d.name))
        : geo.flatMap((d) => d.blocks.map((b) => el("option", { value: b.id }, `${d.name} › ${b.name}`))));
      roleSel.addEventListener("change", fillArea);
      fillArea();
      const af = el("form", null, el("div", { class: "inline-fields" },
        el("div", null, el("label", null, "Login ID"), el("input", { name: "login_id", required: true, minlength: "3", maxlength: "120" })),
        el("div", null, el("label", null, "Full name"), el("input", { name: "full_name", required: true, maxlength: "150" })),
        el("div", null, el("label", null, "Official e-mail"), el("input", { name: "email", type: "email", maxlength: "200" })),
        el("div", null, el("label", null, "Role"), roleSel), el("div", null, el("label", null, "Area"), areaSel),
        el("div", null, el("button", { class: "primary", type: "submit" }, "Create"))));
      af.addEventListener("submit", async (e) => {
        e.preventDefault();
        const d = HS.formData(af);
        const body = { login_id: d.login_id, full_name: d.full_name, email: d.email || null, role: d.role };
        body[d.role === "district_admin" ? "district_id" : "block_id"] = Number(d.area);
        try { const r = await HS.api("/api/admin/admins", { method: "POST", body }); showSecret(accOut, "Administrator created", [["Login ID", r.login_id], ["Temporary password", r.temporary_password]]); }
        catch (ex) { HS.mount(accOut, el("p", { class: "form-error" }, ex.message)); }
      });
      parts.push(card("Administrator accounts", HS.table([
        { label: "Name", key: "name" }, { label: "Login", key: "login_id" }, { label: "Role", render: (r) => ROLE[r.role] },
        { label: "Area", render: (r) => r.block || r.district || "State" }, { label: "MFA", render: (r) => (r.mfa_enabled ? "✓ on" : "off") },
        { label: "Active", render: (r) => (r.active ? "yes" : "revoked") },
        { label: "", render: (r) => r.active && r.role !== "state_admin" ? el("button", { class: "danger", onclick: async () => {
          if (!confirm(`Revoke ${r.name}'s access?`)) return;
          try { await HS.api(`/api/admin/admins/${r.assignment_id}/revoke`, { method: "POST" }); render(); } catch (ex) { HS.toast(ex.message, true); }
        } }, "Revoke") : null },
      ], admins), el("h3", null, "Create administrator"), af, accOut));

      // 6. Registry import
      const impOut = resultBox();
      const imp = el("form", null, el("div", { class: "inline-fields" },
        el("div", null, el("label", null, "UDISE+ CSV extract"), el("input", { type: "file", name: "file", accept: ".csv,text/csv", required: true })),
        el("div", null, el("label", null, "Source"), el("input", { name: "source", required: true, placeholder: "UDISE+ 2025-26", minlength: "3" })),
        el("div", null, el("label", null, "Authorisation reference"), el("input", { name: "source_reference", required: true, placeholder: "Letter/file no.", minlength: "3" })),
        el("div", null, el("button", { class: "primary", type: "submit" }, "Import"))));
      imp.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const r = await HS.api("/api/admin/registry/import", { method: "POST", form: new FormData(imp) });
          HS.mount(impOut, el("p", null, `Created ${r.created}, updated ${r.updated}, rejected ${r.rejected.length}.`),
            r.rejected.length ? HS.table([{ label: "Line", key: "line", num: true }, { label: "Code", key: "code" }, { label: "Reasons", render: (x) => x.reasons.join("; ") }], r.rejected) : null);
        } catch (ex) { HS.mount(impOut, el("p", { class: "form-error" }, ex.message)); }
      });
      parts.push(card("Import official school registry", el("p", { class: "small muted" },
        "Columns: udise_code, school_name, district_code, district_name, block_code, block_name (+ optional district_name_hi, block_name_hi, locality, category, management, status). Rows with invalid, duplicate or mismatched codes are rejected and listed."), imp, impOut));
    }

    // 7. Account security
    const secOut = resultBox();
    const sec = el("div", { class: "row" },
      el("button", { onclick: () => HS.passwordDialog(false) }, "Change password"),
      me.mfa_enabled ? el("span", { class: "chip ok-badge" }, "Two-step verification on") : el("button", { class: "primary", onclick: async () => {
        try {
          const r = await HS.api("/api/auth/mfa/setup", { method: "POST" });
          const f = el("form", { class: "row" }, el("input", { name: "code", inputmode: "numeric", maxlength: "6", placeholder: "6-digit code", "aria-label": "Verification code" }),
            el("button", { class: "primary", type: "submit" }, "Enable"));
          f.addEventListener("submit", async (e) => {
            e.preventDefault();
            try { await HS.api("/api/auth/mfa/enable", { method: "POST", body: { code: HS.formData(f).code } }); HS.toast("Two-step verification enabled"); me.mfa_enabled = true; render(); }
            catch (ex) { HS.toast(ex.message, true); }
          });
          HS.mount(secOut, el("p", null, "Add this key to an authenticator app (manual entry), then enter the 6-digit code:"),
            el("div", { class: "secret" }, r.secret), el("p", { class: "small muted" }, r.otpauth_uri), f);
        } catch (ex) { HS.toast(ex.message, true); }
      } }, "Set up two-step verification"));
    parts.push(card("Account security", sec, secOut));

    HS.mount(c, el("div", { class: "stack" }, parts));
  }

  // -------------------------------------------------------------- audit --
  async function audit(c) {
    const form = el("form", { class: "inline-fields" },
      el("div", null, el("label", null, "Action starts with"), el("input", { name: "action", placeholder: "login, report, school…" })),
      el("div", null, el("label", null, "Outcome"), el("select", { name: "outcome" }, ["", "success", "denied", "failure"].map((o) => el("option", { value: o }, o || "Any")))),
      el("div", null, el("button", { type: "submit" }, HS.t("search"))));
    const out = el("div");
    const load = async () => {
      const d = HS.formData(form);
      const qs = new URLSearchParams({ limit: "200" });
      if (d.action) qs.set("action", d.action);
      if (d.outcome) qs.set("outcome", d.outcome);
      const rows = await HS.api("/api/admin/audit-logs?" + qs);
      HS.mount(out, HS.table([
        { label: "Time", render: (r) => new Date(r.at).toLocaleString("en-IN") }, { label: "Actor", render: (r) => `${r.actor_user_id ?? "—"} (${r.actor_role ?? "—"})` },
        { label: "Action", key: "action" }, { label: "Entity", render: (r) => r.entity_type ? `${r.entity_type} ${r.entity_id ?? ""}` : "—" },
        { label: "Outcome", render: (r) => el("span", { class: "chip " + (r.outcome === "success" ? "ok-badge" : "flag") }, r.outcome) },
        { label: "Details", render: (r) => JSON.stringify(r.details) }, { label: "IP", key: "ip" },
      ], rows));
    };
    form.addEventListener("submit", (e) => { e.preventDefault(); HS.load(out, load); });
    HS.mount(c, card(HS.t("tab_audit"), form, out));
    await load();
  }

  tabs.select(tabs.initial);
})();
