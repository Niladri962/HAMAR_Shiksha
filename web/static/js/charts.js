/* Lightweight SVG charts (no library download). Colours come from CSS
   classes so light/dark themes apply automatically. Every chart can be
   swapped for a table view. */
(function () {
  "use strict";
  const HS = window.HS;
  const el = HS.el;
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, ...kids) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
    kids.forEach((k) => k && n.append(k));
    return n;
  };
  const text = (x, y, s, cls, anchor = "start") => {
    const t = svg("text", { x, y, class: cls, "text-anchor": anchor });
    t.textContent = s;
    return t;
  };

  function tooltip(container) {
    const tip = el("div", { class: "tooltip hidden", role: "presentation" });
    container.append(tip);
    return {
      show(x, y, head, lines) {
        HS.mount(tip, el("div", { class: "t-head" }, head), ...lines.map((l) => el("div", null, l)));
        tip.classList.remove("hidden");
        const cw = container.clientWidth;
        const left = Math.min(Math.max(0, x + 12), Math.max(0, cw - tip.offsetWidth));
        tip.style.left = left + "px";
        tip.style.top = Math.max(0, y - tip.offsetHeight - 8) + "px";
      },
      hide() { tip.classList.add("hidden"); },
    };
  }

  /** Card body with chart + "show table" toggle. */
  function withTable(chartNode, tableNode) {
    const wrap = el("div");
    const tbl = el("div", { class: "hidden" }, tableNode);
    const btn = el("button", { class: "link table-toggle", type: "button", "aria-expanded": "false" }, HS.t("show_table"));
    btn.addEventListener("click", () => {
      const showing = tbl.classList.toggle("hidden") === false;
      chartNode.classList.toggle("hidden", showing);
      btn.textContent = showing ? HS.t("show_chart") : HS.t("show_table");
      btn.setAttribute("aria-expanded", String(showing));
    });
    wrap.append(chartNode, tbl, el("div", { class: "row" }, btn));
    return wrap;
  }

  // ------------------------------------------------------------ line ----
  function line({ labels, series, format = HS.pct, yMax = 1, ariaLabel }) {
    const W = 640, H = 240, m = { t: 14, r: 96, b: 28, l: 40 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const x = (i) => m.l + (labels.length <= 1 ? iw / 2 : (i * iw) / (labels.length - 1));
    const y = (v) => m.t + ih - (v / yMax) * ih;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": ariaLabel || "Line chart" });
    for (let k = 0; k <= 4; k++) {
      const v = (yMax * k) / 4, yy = y(v);
      root.append(svg("line", { x1: m.l, x2: m.l + iw, y1: yy, y2: yy, class: k === 0 ? "baseline" : "gridline" }));
      root.append(text(m.l - 6, yy + 4, format(v), "axis-label", "end"));
    }
    labels.forEach((lb, i) => root.append(text(x(i), H - 8, HS.period(lb), "axis-label", "middle")));
    series.forEach((s, si) => {
      let d = "", pen = false;
      s.values.forEach((v, i) => {
        if (v === null || v === undefined) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      if (d) root.append(svg("path", { d, class: `ln ln-${si + 1}`, fill: "none" }));
      s.values.forEach((v, i) => {
        if (v !== null && v !== undefined) root.append(svg("circle", { cx: x(i), cy: y(v), r: 4, class: `mk mk-${si + 1}` }));
      });
      // Direct label at the last point with data (<= 4 series).
      const last = s.values.map((v, i) => [v, i]).filter(([v]) => v !== null && v !== undefined).pop();
      if (last && series.length <= 4) root.append(text(x(last[1]) + 8, y(last[0]) + 4, `${s.short || s.label} ${format(last[0])}`, "value-label"));
    });
    const cross = svg("line", { y1: m.t, y2: m.t + ih, class: "crosshair hidden-line", visibility: "hidden" });
    root.append(cross);
    const hit = svg("rect", { x: m.l - 10, y: m.t, width: iw + 20, height: ih, fill: "transparent" });
    root.append(hit);

    const box = el("div", { class: "chart" }, root);
    const tip = tooltip(box);
    const legend = el("div", { class: "legend" }, series.map((s, si) =>
      el("span", null, el("span", { class: `sw sw-${si + 1}` }), s.label)));
    function at(evt) {
      const rect = root.getBoundingClientRect();
      const px = ((evt.clientX - rect.left) / rect.width) * W;
      let i = Math.round(((px - m.l) / iw) * (labels.length - 1));
      i = Math.max(0, Math.min(labels.length - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      tip.show((x(i) / W) * rect.width, (m.t / H) * rect.height + 30, HS.period(labels[i]),
        series.map((s) => `${s.label}: ${format(s.values[i])}`));
    }
    hit.addEventListener("mousemove", at);
    hit.addEventListener("mouseleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
    const chartNode = el("div", null, box, series.length > 1 ? legend : null);

    const table = HS.table([{ label: "Month", key: "p" }, ...series.map((s, si) => ({ label: s.label, key: "v" + si, num: true }))],
      labels.map((lb, i) => Object.fromEntries([["p", HS.period(lb)], ...series.map((s, si) => ["v" + si, format(s.values[i])])])));
    return withTable(chartNode, table);
  }

  // ------------------------------------------------------------ bars ----
  function bars(rows, { format = HS.pct, max = 1, threshold, thresholdLabel, ariaLabel } = {}) {
    const W = 640, rowH = 30, labelW = 170, valueW = 56;
    const H = rows.length * rowH + 22;
    const iw = W - labelW - valueW;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": ariaLabel || "Bar chart" });
    root.append(svg("line", { x1: labelW, x2: labelW, y1: 0, y2: rows.length * rowH, class: "baseline" }));
    const box = el("div", { class: "chart" }, root);
    const tip = tooltip(box);
    rows.forEach((r, i) => {
      const y0 = i * rowH + 7, h = rowH - 14;
      root.append(text(labelW - 8, y0 + h / 2 + 4, r.label, "axis-label", "end"));
      if (r.value === null || r.value === undefined) {
        root.append(text(labelW + 6, y0 + h / 2 + 4, HS.t("no_data"), "axis-label"));
        return;
      }
      const w = Math.max(2, (Math.min(r.value, max) / max) * iw);
      const rad = Math.min(4, w / 2);
      const d = `M${labelW},${y0} h${w - rad} a${rad},${rad} 0 0 1 ${rad},${rad} v${h - 2 * rad} a${rad},${rad} 0 0 1 -${rad},${rad} h-${w - rad} z`;
      const bar = svg("path", { d, class: r.below ? "bar bar-below" : "bar" });
      root.append(bar);
      root.append(text(labelW + w + 6, y0 + h / 2 + 4, format(r.value), "value-label"));
      const hit = svg("rect", { x: 0, y: i * rowH, width: W, height: rowH, fill: "transparent" });
      hit.addEventListener("mousemove", (e) => {
        const rect = root.getBoundingClientRect();
        tip.show(e.clientX - rect.left, e.clientY - rect.top, r.label, [format(r.value), r.sub].filter(Boolean));
      });
      hit.addEventListener("mouseleave", tip.hide);
      root.append(hit);
    });
    if (threshold !== undefined) {
      const tx = labelW + (threshold / max) * iw;
      root.append(svg("line", { x1: tx, x2: tx, y1: 0, y2: rows.length * rowH, class: "threshold" }));
      root.append(text(tx, H - 6, thresholdLabel || format(threshold), "axis-label", "middle"));
    }
    const table = HS.table([{ label: "Item", key: "label" }, { label: "Value", key: "v", num: true }, { label: "", key: "sub" }],
      rows.map((r) => ({ label: r.label, v: format(r.value), sub: r.sub || "" })));
    return withTable(box, table);
  }

  // ------------------------------------------------------ status bar ----
  function statusBar(counts) {
    const order = ["current", "stale", "missing", "estimated"];
    const total = order.reduce((a, k) => a + (counts[k] || 0), 0) || 1;
    const bar = el("div", { class: "statusbar", role: "img",
      "aria-label": order.map((k) => `${HS.t("st_" + k)}: ${counts[k] || 0}`).join(", ") });
    order.forEach((k) => {
      if (!counts[k]) return;
      const seg = el("span", { class: "seg-" + k, title: `${HS.t("st_" + k)}: ${counts[k]}` });
      seg.style.flex = String(counts[k] / total);
      bar.append(seg);
    });
    const legend = el("div", { class: "legend" }, order.filter((k) => counts[k] !== undefined).map((k) =>
      el("span", null, HS.statusChip(k), " ", el("strong", { class: "num" }, String(counts[k] || 0)))));
    return el("div", null, bar, legend);
  }

  // -------------------------------------------------------- tile map ----
  function tileMap(items, { format = HS.pct, metricLabel }) {
    const vals = items.map((i) => i.value).filter((v) => v !== null && v !== undefined);
    const lo = Math.min(...vals, 1), hi = Math.max(...vals, 0);
    const step = (v) => (hi - lo < 1e-6 ? 4 : 1 + Math.round(((v - lo) / (hi - lo)) * 6));
    const grid = el("div", { class: "tilemap" });
    items.forEach((it) => {
      const s = it.value === null || it.value === undefined ? 0 : step(it.value);
      const tile = el("button", { class: `tile ${s ? "seq-" + s : "seq-none"}`, type: "button",
        "aria-label": `${it.name}: ${metricLabel} ${format(it.value)}`, onclick: it.onClick },
      el("span", { class: "t-name" }, it.name),
      el("span", { class: "t-val num" }, format(it.value)),
      el("span", { class: "t-sub" }, it.sub || ""));
      grid.append(tile);
    });
    const ramp = el("div", { class: "ramp" }, el("span", { class: "num" }, format(vals.length ? lo : null)),
      el("span", { class: "steps" }, [1, 2, 3, 4, 5, 6, 7].map((n) => el("span", { class: "seq-" + n }))),
      el("span", { class: "num" }, format(vals.length ? hi : null)), el("span", null, metricLabel));
    const table = HS.table([{ label: "Name", key: "name" }, { label: metricLabel, key: "v", num: true }, { label: "", key: "sub" }],
      items.map((i) => ({ name: i.name, v: format(i.value), sub: i.sub })), { onRow: (r) => items.find((i) => i.name === r.name)?.onClick?.() });
    return withTable(el("div", null, grid, ramp), table);
  }

  // ---------------------------------------------------- mastery bar ----
  function meter(value, label) {
    const fill = el("div", { class: "bar-fill" + (value !== null && value < 0.6 ? " low" : "") });
    fill.style.width = (value === null || value === undefined ? 0 : Math.round(value * 100)) + "%";
    return el("div", { role: "meter", "aria-valuemin": "0", "aria-valuemax": "100",
      "aria-valuenow": value === null ? null : Math.round(value * 100), "aria-label": label || "" },
    el("div", { class: "bar-track" }, fill));
  }

  HS.charts = { line, bars, statusBar, tileMap, meter, withTable };
})();
