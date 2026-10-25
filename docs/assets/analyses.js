// Study analyses for docs/index.html, recomputed for the selected site and
// date range. Reads docs/data/analyses.json (scripts_notebooks/export_analyses.py)
// and reuses the dashboard's filters, phases, and helpers from window.BY.
(function () {
  "use strict";

  let A = null;
  const fitCache = new Map();
  const SQUIRREL = "Eastern Gray Squirrel";
  // Each site keeps one color wherever sites are compared
  const SITE_COLORS = {
    jacksonville_fl_32259: "--s1",
    essex_fells_nj_07021: "--s2",
    southampton_uk: "--s3",
    auburn_al_36830: "--s4",
  };

  // Chart containers in the study analyses cards, for loading and error messages
  const CHART_IDS = ["mb-chart", "bm-trend", "bm-species", "div-chart", "vw-grid", "vw-species-chart", "bout-chart", "seed-chart", "peck-chart"];

  function showStatus(text) {
    for (const id of CHART_IDS) {
      const el = document.getElementById(id);
      if (!el) continue;
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = text;
      el.replaceChildren(p);
    }
  }

  showStatus("Loading the study analyses\u2026");
  fetch("data/analyses.json")
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then((d) => { A = prepare(d); render(); })
    .catch((err) => {
      console.error("Study analyses data unavailable:", err);
      showStatus("The study analyses data isn't available yet. It's created by the daily dashboard update; check back after the next run.");
    });
  window.BYAnalyses = { render };

  function prepare(d) {
    const epoch = Date.parse(`${d.epoch}T00:00:00Z`);
    const rows = (block) => block.rows.map((r) => Object.fromEntries(block.cols.map((c, i) => [c, r[i]])));
    const dayOf = (minute) => new Date(Math.floor((epoch + minute * 60000) / 864e5) * 864e5);
    const visits = rows(d.visits).map((v) => ({ site: d.sites[v.site], species: d.species[v.species], minute: v.minute, d: dayOf(v.minute) }));
    const daily = rows(d.dailySummaries).map((r) => ({
      site: d.sites[r.site], d: new Date(`${r.date}T00:00:00Z`), species: d.species[r.species], visits: r.visits }));
    const weather = new Map(rows(d.visitWeather).map((w) => [`${d.sites[w.site]}|${w.hour}`, w]));
    const pecks = rows(d.pecks).map((p) => ({
      species: d.species[p.species], minute: p.minute, d: dayOf(p.minute), left: p.left, right: p.right,
      leftSeed: p.leftSeed == null ? null : d.seeds[p.leftSeed], rightSeed: p.rightSeed == null ? null : d.seeds[p.rightSeed],
    }));
    const momentum = d.momentum.map((m) => ({ ...m, startD: new Date(`${m.start}T00:00:00Z`), endD: new Date(`${m.end}T00:00:00Z`) }));
    const momentumSpecies = d.momentumSpecies.map((m) => ({ ...m, species: d.species[m.species] }));
    return { visits, daily, weather, pecks, momentum, momentumSpecies, seeds: d.seeds };
  }

  // ---- shared helpers --------------------------------------------------------
  const siteName = (site) => BY.data.sites[site]?.name || site;
  const siteColor = (site) => BY.css(SITE_COLORS[site] || "--other");

  // The phase in force on a day; before a site's first phase it is the seed baseline
  function phaseAt(site, d) {
    const ph = BY.phases.filter((p) => p.site === site && p.d <= d).sort((a, b) => b.d - a.d)[0];
    return ph ? ph.description.trim() : "Before study phases";
  }
  const hasFood = (description) => !/extinct|removed/i.test(description);

  function setOptions(select, options, value) {
    const current = value ?? select.value;
    select.replaceChildren(...options.map(([v, label]) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = label;
      return o;
    }));
    select.value = options.some(([v]) => v === current) ? current : options[0]?.[0] ?? "";
    return select.value;
  }

  function bindOnce(id, event, handler) {
    const el = document.getElementById(id);
    if (!el.dataset.bound) { el.addEventListener(event, handler); el.dataset.bound = "1"; }
    return el;
  }

  function phaseRects(site, extra = {}) {
    return BY.phaseSpans(site).filter((s) => BY.phaseShade(s.description)).map((s) => ({ ...s, ...extra }));
  }

  function render() {
    if (!A || !window.BY) return;
    renderMultipleBaseline();
    renderMomentum();
    renderDiversity();
    renderVisitWeather();
    renderBouts();
    renderSeedPreference();
  }

  // ---- all sites across study phases ---------------------------------------
  function renderMultipleBaseline() {
    const el = document.getElementById("mb-chart");
    const log = bindOnce("mb-log", "change", (e) => BY.update({ mbLog: e.target.checked }));
    const fits = bindOnce("mb-fits", "change", (e) => BY.update({ mbFits: e.target.checked }));
    log.checked = BY.state.mbLog ?? true;
    fits.checked = BY.state.mbFits ?? true;
    const dom = BY.domain();
    const sites = Object.keys(SITE_COLORS);
    const label = (site) => siteName(site);
    const totals = sites.flatMap((site) => d3.rollups(A.daily.filter((r) => r.site === site).filter(BY.inRange(dom)),
      (v) => d3.sum(v, (r) => r.visits), (r) => +r.d).map(([t, visits]) => ({ site, row: label(site), d: new Date(t), visits })));
    if (!totals.length) { BY.empty(el, "No daily summaries in this range."); return; }
    // Break the line across missing days rather than bridging them
    const lines = sites.flatMap((site) => {
      const byDay = new Map(totals.filter((r) => r.site === site).map((r) => [+r.d, r.visits]));
      if (!byDay.size) return [];
      const days = d3.utcDays(new Date(Math.min(...byDay.keys())), new Date(Math.max(...byDay.keys()) + BY.DAY));
      return days.map((d) => ({ site, row: label(site), d, visits: byDay.has(+d) ? byDay.get(+d) : null }));
    });
    // Stop each site's shading where its data ends (Southampton and Auburn ended in January)
    const lastDay = d3.rollup(totals, (v) => d3.max(v, (r) => +r.d) + BY.DAY, (r) => r.site);
    const rects = sites.filter((s) => lastDay.has(s)).flatMap((site) => phaseRects(site, { row: label(site) })
      .map((r) => ({ ...r, x2: new Date(Math.min(+r.x2, lastDay.get(site))) })).filter((r) => r.x2 > r.x1));
    const curves = fits.checked ? A.momentum.filter((m) => m.fit2 && m.endD > dom[0] && m.startD < dom[1]).flatMap((m) => {
      const span = Math.round((m.endD - m.startD) / BY.DAY);
      return d3.range(0, span + 0.01, 0.5).map((t) => ({
        row: label(m.site), key: `${m.site}-${m.transition}`, d: new Date(+m.startD + t * BY.DAY),
        visits: m.fit2.B0 * Math.exp(-m.fit2.b * t), b: m.fit2.b }));
    }) : [];
    const rows = sites.filter((s) => totals.some((r) => r.site === s)).map(label);
    const chart = Plot.plot(BY.baseOptions(el, {
      height: rows.length * 130 + 40,
      y: log.checked ? { type: "log", label: "Visits per day", grid: true, domain: [0.8, 2000], tickFormat: "~s" }
        : { label: "Visits per day", grid: true, tickFormat: "~s" },
      fy: { domain: rows, axis: null, padding: 0.2 },
      marks: [
        Plot.rect(rects, { x1: "x1", x2: "x2", fy: "row", fill: (s) => BY.phaseShade(s.description), fillOpacity: 0.16,
          title: (s) => `${s.description}\n${BY.fmtDate(s.d)}` }),
        Plot.text(rows, { fy: (d) => d, text: (d) => d, frameAnchor: "top-left", dx: 4, dy: -12,
          fill: BY.css("--ink-2"), fontWeight: 600, fontSize: 12 }),
        Plot.lineY(lines, { x: "d", y: "visits", fy: "row", stroke: BY.css("--ink-2"), strokeWidth: 1 }),
        Plot.dot(totals, { x: "d", y: "visits", fy: "row", r: 2, fill: (r) => siteColor(r.site),
          tip: true, title: (r) => `${BY.fmt(r.visits)} visits\n${siteName(r.site)}\n${BY.fmtDate(r.d)}\n${phaseAt(r.site, r.d)}` }),
        Plot.lineY(curves, { x: "d", y: "visits", z: "key", fy: "row", stroke: BY.css("--s8"), strokeWidth: 2, clip: true }),
      ],
    }));
    const sitesShown = sites.filter((s) => totals.some((r) => r.site === s));
    el.replaceChildren(phaseAsideFor(chart, sitesShown, fits.checked));
  }

  // Phase legend for charts that span several sites
  function phaseAsideFor(chart, sites, withFits) {
    const spans = sites.flatMap((s) => BY.phaseSpans(s));
    const row = document.createElement("div");
    row.className = "plot-row";
    const aside = document.createElement("div");
    aside.className = "phase-aside";
    const title = document.createElement("div");
    title.className = "phase-aside-title";
    title.textContent = "Study phase";
    aside.append(title);
    for (const c of BY.phaseLegendItems(spans)) {
      const item = document.createElement("div");
      item.append(BY.phaseSwatch(c), document.createTextNode(c));
      aside.append(item);
    }
    if (withFits) {
      const item = document.createElement("div");
      const key = document.createElement("i");
      key.className = "phase-swatch";
      key.style.cssText = `border:0;height:2px !important;background:${BY.css("--s8")}`;
      item.append(key, document.createTextNode("Momentum fit"));
      aside.append(item);
    }
    row.append(chart, aside);
    return row;
  }

  // ---- behavioral momentum -------------------------------------------------
  function renderMomentum() {
    const fmt3 = d3.format(".3f"), fmt1 = d3.format(".1f");
    const fitted = A.momentum.filter((m) => m.fit2);
    const trendEl = document.getElementById("bm-trend");
    const sites = [...new Set(fitted.map((m) => m.site))];
    trendEl.replaceChildren(BY.legend(sites.map((s) => ({ label: siteName(s), color: siteColor(s) })), "line"),
      Plot.plot({
        width: Math.max(320, trendEl.clientWidth), height: 220, marginLeft: 52, marginRight: 20,
        style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
        x: { label: "Extinction phase (in order)", ticks: d3.range(1, d3.max(fitted, (m) => m.transition) + 1), tickFormat: "d" },
        y: { label: "b (per day)", grid: true, nice: true },
        color: { domain: sites, range: sites.map(siteColor) },
        marks: [
          Plot.ruleY([0], { stroke: BY.css("--axis") }),
          Plot.lineY(fitted, { x: "transition", y: (m) => m.fit2.b, stroke: "site", strokeWidth: 2 }),
          Plot.dot(fitted, { x: "transition", y: (m) => m.fit2.b, fill: "site", r: 5, stroke: BY.css("--surface"), strokeWidth: 2,
            tip: true, title: (m) => `${siteName(m.site)}, extinction ${m.transition}\n${m.start} to ${m.end}\nb = ${fmt3(m.fit2.b)}, R² = ${fmt3(m.fit2.R2)}\n${m.fit2.n} days with visits` }),
        ],
      }));

    const tableEl = document.getElementById("bm-table");
    const cell = (f, three) => (f ? `B₀ ${fmt1(f.B0)} · b ${fmt3(f.b)}${three ? ` · c ${fmt1(f.c)}` : ""} · R² ${fmt3(f.R2)} · AICc ${f.AICc == null ? "n/a" : fmt1(f.AICc)}` : "No fit (under 4 days with visits)");
    const t = BY.table(["Site", "Extinction", "Dates", "Days fitted", "B(t) = B₀e^(−bt)", "B(t) = B₀e^(−bt) + c"],
      A.momentum.map((m) => [siteName(m.site), String(m.transition), `${m.start} to ${m.end}`, m.fit2 ? String(m.fit2.n) : "0",
        cell(m.fit2, false), cell(m.fit3, true)]), [false, true, false, true, false, false]);
    t.classList.add("bm-table");
    tableEl.replaceChildren(t);

    const spEl = document.getElementById("bm-species");
    const sp = A.momentumSpecies.filter((m) => m.species !== SQUIRREL && m.b > 1e-5);
    const order = d3.groupSort(sp, (v) => d3.median(v, (m) => m.b), (m) => m.species);
    const spSites = [...new Set(sp.map((m) => m.site))];
    spEl.replaceChildren(BY.legend(spSites.map((s) => ({ label: siteName(s), color: siteColor(s) }))),
      Plot.plot({
        width: Math.max(320, spEl.clientWidth), height: order.length * 22 + 50, marginLeft: 170, marginRight: 20,
        style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
        x: { type: "log", label: "b (per day, log scale)", grid: true, tickFormat: (d) => d3.format("~g")(d) },
        y: { domain: order, label: null, tickSize: 0 },
        color: { domain: spSites, range: spSites.map(siteColor) },
        marks: [
          Plot.dot(sp, { x: "b", y: "species", fill: "site", r: 5, stroke: BY.css("--surface"), strokeWidth: 1.5,
            tip: true, title: (m) => `${m.species}\n${siteName(m.site)}, extinction ${m.transition}\nb = ${fmt3(m.b)}, R² = ${fmt3(m.R2)}\n${m.n} days with visits` }),
        ],
      }));
  }

  // ---- ecological diversity ------------------------------------------------
  const METRICS = [
    { key: "shannon", label: "Shannon H", note: "−Σ p ln p over the day's visits" },
    { key: "richness", label: "Species richness", note: "species seen that day" },
    { key: "u", label: "U value", note: "Shannon H ÷ ln(species seen so far at the site)" },
    { key: "weekly", label: "Weekly Sørensen dissimilarity", note: "this week's species vs the previous recorded week" },
    { key: "rolling", label: "Rolling Sørensen dissimilarity", note: "species in the last 3 days vs 7 to 9 days earlier" },
  ];

  function diversity(site) {
    const byDay = d3.group(A.daily.filter((r) => r.site === site), (r) => +r.d);
    const days = [...byDay.keys()].sort((a, b) => a - b);
    const seen = new Set();
    const presence = new Map();
    const out = days.map((t) => {
      const rs = byDay.get(t);
      const total = d3.sum(rs, (r) => r.visits);
      const species = new Set(rs.map((r) => r.species));
      presence.set(t, species);
      species.forEach((s) => seen.add(s));
      const shannon = -d3.sum(rs, (r) => { const p = r.visits / total; return p > 0 ? p * Math.log(p) : 0; });
      return { d: new Date(t), shannon, richness: species.size, u: seen.size > 1 ? shannon / Math.log(seen.size) : null };
    });
    const sorensen = (a, b) => (a.size + b.size ? 1 - (2 * [...a].filter((x) => b.has(x)).length) / (a.size + b.size) : null);
    const union = (sets) => { const u = new Set(); sets.forEach((s) => s.forEach((x) => u.add(x))); return u; };
    // Calendar days, not row offsets, so missing days do not shift the windows
    for (const o of out) {
      const t = +o.d;
      const a = [7, 8, 9].map((k) => presence.get(t - k * BY.DAY)).filter(Boolean);
      const b = [0, 1, 2].map((k) => presence.get(t - k * BY.DAY)).filter(Boolean);
      o.rolling = a.length && b.length ? sorensen(union(a), union(b)) : null;
    }
    // ISO year and week together, so 2025 and 2026 weeks stay apart
    const isoWeek = d3.utcFormat("%G-%V");
    const weeks = d3.group(out, (o) => isoWeek(o.d));
    const keys = [...weeks.keys()].sort();
    keys.forEach((k, i) => {
      const value = i ? sorensen(union(weeks.get(keys[i - 1]).map((o) => presence.get(+o.d))),
        union(weeks.get(k).map((o) => presence.get(+o.d)))) : null;
      weeks.get(k).forEach((o) => { o.weekly = value; });
    });
    return out;
  }

  function renderDiversity() {
    const el = document.getElementById("div-chart");
    const site = BY.state.site;
    const dom = BY.domain();
    const all = diversity(site);
    const days = all.filter(BY.inRange(dom));
    document.getElementById("div-sub").textContent =
      `Computed each day from ${siteName(site)}'s daily summaries. ` + METRICS.map((m) => `${m.label}: ${m.note}`).join(". ") + ". Days with no visits are left out.";
    if (!days.length) {
      BY.empty(el, "No daily summaries for this site in this range.");
      document.getElementById("div-matrix").replaceChildren();
      document.getElementById("div-scatter").replaceChildren();
      return;
    }
    // One small chart per metric: their scales differ too much to share an axis
    const charts = METRICS.flatMap((m) => {
      const pts = days.filter((o) => o[m.key] != null);
      const title = document.createElement("h3");
      title.className = "panel-title";
      title.textContent = m.label;
      if (!pts.length) return [title, noteEl("Not enough data in this range.")];
      return [title, Plot.plot(BY.baseOptions(el, {
        height: 130,
        y: { label: null, grid: true, nice: true },
        marks: [
          ...BY.phaseMarks(),
          Plot.lineY(pts, { x: "d", y: m.key, stroke: BY.css("--s1"), strokeWidth: 1.5 }),
          Plot.dot(pts, { x: "d", y: m.key, r: 2, fill: BY.css("--s1"),
            tip: true, title: (o) => `${m.label}: ${d3.format(".3f")(o[m.key])}\n${BY.fmtDate(o.d)}\n${phaseAt(site, o.d)}` }),
        ],
      }))];
    });
    el.replaceChildren(BY.withPhases(...charts));

    // Correlation matrix: Pearson r over days with all five metrics
    const complete = days.filter((o) => METRICS.every((m) => o[m.key] != null));
    const matrixEl = document.getElementById("div-matrix");
    const note = document.getElementById("div-note");
    const pair = BY.state.divPair || [0, 1];
    const r = (i, j) => BY.pearson(complete.map((o) => ({ x: o[METRICS[i].key], y: o[METRICS[j].key] })));
    const color = (v) => (v == null ? BY.css("--grid")
      : d3.interpolateRgb(BY.css("--grid"), BY.css(v >= 0 ? "--s1" : "--s8"))(Math.min(1, Math.abs(v))));
    const grid = document.createElement("div");
    grid.className = "div-matrix";
    grid.style.gridTemplateColumns = `110px repeat(${METRICS.length}, 1fr)`;
    grid.append(document.createElement("span"));
    METRICS.forEach((m) => { const h = document.createElement("span"); h.className = "div-head"; h.textContent = m.label.replace(" dissimilarity", ""); grid.append(h); });
    METRICS.forEach((mi, i) => {
      const h = document.createElement("span");
      h.className = "div-head row";
      h.textContent = mi.label.replace(" dissimilarity", "");
      grid.append(h);
      METRICS.forEach((mj, j) => {
        const btn = document.createElement("button");
        btn.type = "button";
        const v = i === j ? null : r(i, j);
        btn.textContent = i === j ? "" : v == null ? "n/a" : d3.format("+.2f")(v).replace("-", "−");
        btn.style.background = i === j ? "transparent" : color(v);
        btn.disabled = i === j;
        btn.setAttribute("aria-pressed", String((pair[0] === i && pair[1] === j) || (pair[0] === j && pair[1] === i)));
        btn.title = i === j ? "" : `${mi.label} vs ${mj.label}`;
        btn.addEventListener("click", () => BY.update({ divPair: [j, i] }));
        grid.append(btn);
      });
    });
    matrixEl.replaceChildren(grid);
    note.textContent = `Pearson r across ${BY.fmt(complete.length)} days with all five metrics. Blue is positive, red is negative. Click a cell to plot that pair, colored by study phase.`;

    const scatterEl = document.getElementById("div-scatter");
    const [xi, yi] = pair;
    const pts = complete.map((o) => ({ x: o[METRICS[xi].key], y: o[METRICS[yi].key], d: o.d, phase: phaseAt(site, o.d) }));
    const phasesSeen = [...new Set(pts.map((p) => p.phase))];
    // The baseline before any phase is drawn open so it reads apart from extinction
    const fill = (ph) => (ph === "Before study phases" ? "none" : BY.phaseShade(ph) || BY.css("--other"));
    const stroke = (ph) => (ph === "Before study phases" ? BY.css("--ink-2") : BY.css("--surface"));
    const size = Math.min(scatterEl.clientWidth || 480, 560);
    const key = BY.legend(phasesSeen.map((ph) => ({ label: ph, color: fill(ph) === "none" ? "transparent" : fill(ph) })));
    key.querySelectorAll("i").forEach((i, n) => { if (phasesSeen[n] === "Before study phases") i.style.border = `1px solid ${BY.css("--ink-2")}`; });
    scatterEl.replaceChildren(key, Plot.plot({
      width: size, height: size, marginLeft: 52, marginRight: 20,
      style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
      x: { label: METRICS[xi].label, grid: true, nice: true },
      y: { label: METRICS[yi].label, grid: true, nice: true },
      marks: [
        Plot.dot(pts, { x: "x", y: "y", fill: (p) => fill(p.phase), r: 4, stroke: (p) => stroke(p.phase), strokeWidth: 1,
          tip: true, title: (p) => `${BY.fmtDate(p.d)}\n${p.phase}\n${METRICS[xi].label}: ${d3.format(".3f")(p.x)}\n${METRICS[yi].label}: ${d3.format(".3f")(p.y)}` }),
      ],
    }));
  }

  // ---- feeder visits and weather -------------------------------------------
  function renderVisitWeather() {
    const site = BY.state.site;
    const dom = BY.domain();
    const visits = A.visits.filter((v) => v.site === site).filter(BY.inRange(dom))
      .map((v) => ({ ...v, w: A.weather.get(`${site}|${Math.floor(v.minute / 60)}`) })).filter((v) => v.w && v.w.wind != null);
    const counts = d3.rollups(visits, (v) => v.length, (v) => v.species).sort((a, b) => b[1] - a[1]);
    const select = bindOnce("vw-species", "change", (e) => BY.update({ vwSpecies: e.target.value }));
    const chosen = setOptions(select, [["", "All species"], ...counts.filter(([, n]) => n >= 50).map(([s, n]) => [s, `${s} (${BY.fmt(n)})`])], BY.state.vwSpecies || "");
    document.getElementById("vw-sub").textContent =
      `${BY.fmt(visits.length)} visits at ${siteName(site)} in this range, each matched to the weather in that local clock hour (Open-Meteo and OpenWeather).`;
    const gridEl = document.getElementById("vw-grid");
    const sel = chosen ? visits.filter((v) => v.species === chosen) : visits;
    if (!sel.length) { BY.empty(gridEl, "No visits with weather in this range."); document.getElementById("vw-species-chart").replaceChildren(); return; }
    const cells = d3.rollups(sel, (v) => v.length, (v) => Math.floor(v.w.temp / 2) * 2, (v) => Math.floor(v.w.wind))
      .flatMap(([t, ws]) => ws.map(([w, n]) => ({ t, w, share: n / sel.length, n })));
    const size = Math.min(gridEl.clientWidth || 480, 560);
    gridEl.replaceChildren(Plot.plot({
      width: size, height: size, marginLeft: 52, marginRight: 20,
      style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
      x: { label: "Temperature (°C)", grid: true },
      y: { label: "Wind (m/s)", grid: true },
      color: { type: "sqrt", range: [BY.css("--seq-lo"), BY.css("--seq-hi")], legend: true, label: "Share of visits", tickFormat: "%" },
      marks: [
        Plot.rect(cells, { x1: "t", x2: (c) => c.t + 2, y1: "w", y2: (c) => c.w + 1, fill: "share", inset: 0.5,
          tip: true, title: (c) => `${d3.format(".1%")(c.share)} of visits (${BY.fmt(c.n)})\n${c.t} to ${c.t + 2} °C\n${c.w} to ${c.w + 1} m/s wind` }),
      ],
    }));

    // Species by temperature band, each row as that species' share of visits
    const spEl = document.getElementById("vw-species-chart");
    const top = counts.filter(([, n]) => n >= 50).slice(0, 20).map(([s]) => s);
    const rows = top.map((s) => {
      const vs = visits.filter((v) => v.species === s);
      return { species: s, mean: d3.mean(vs, (v) => v.w.temp), bands: d3.rollups(vs, (v) => v.length, (v) => Math.floor(v.w.temp / 2) * 2).map(([t, n]) => ({ t, share: n / vs.length, n })) };
    }).sort((a, b) => a.mean - b.mean);
    const spCells = rows.flatMap((r) => r.bands.map((b) => ({ ...b, species: r.species })));
    if (!spCells.length) { BY.empty(spEl, "Needs species with at least 50 visits in this range."); return; }
    spEl.replaceChildren(Plot.plot({
      width: Math.max(320, spEl.clientWidth), height: rows.length * 22 + 70, marginLeft: 170, marginRight: 20,
      style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
      x: { label: "Temperature (°C)", grid: true },
      y: { domain: rows.map((r) => r.species), label: null, tickSize: 0 },
      color: { range: [BY.css("--seq-lo"), BY.css("--seq-hi")], legend: true, label: "Share of the species' visits", tickFormat: "%" },
      marks: [
        Plot.barX(spCells, { x1: "t", x2: (c) => c.t + 2, y: "species", fill: "share", inset: 0.5,
          tip: true, title: (c) => `${c.species}\n${d3.format(".0%")(c.share)} of its visits at ${c.t} to ${c.t + 2} °C`, }),
        Plot.dot(rows, { x: "mean", y: "species", r: 3, fill: BY.css("--s2"), stroke: BY.css("--surface"),
          tip: true, title: (r) => `${r.species}\nAverage visit temperature ${d3.format(".1f")(r.mean)} °C` }),
      ],
    }), noteEl("Rows are ordered from the coolest to the warmest average visit temperature (orange dot)."));
  }

  function noteEl(text) {
    const p = document.createElement("p");
    p.className = "sub";
    p.textContent = text;
    return p;
  }

  // ---- bout analysis --------------------------------------------------------
  // Survivor curves and fits follow the study: P(IVI > t) on a log axis, fitted in log space
  function dexpS(t, p) { return p[0] * Math.exp(-p[1] * t) + p[2] * Math.exp(-p[3] * t); }

  function lnGamma(x) {
    const g = [676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
      12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - lnGamma(1 - x);
    x -= 1;
    let a = 0.99999999999980993;
    const t = x + 7.5;
    for (let i = 0; i < 8; i++) a += g[i] / (x + i + 1);
    return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
  }

  // Regularized lower incomplete gamma P(a, x)
  function gammaP(a, x) {
    if (x <= 0) return 0;
    const lg = lnGamma(a);
    if (x < a + 1) {
      let sum = 1 / a, term = sum, ap = a;
      for (let n = 0; n < 200; n++) { ap += 1; term *= x / ap; sum += term; if (Math.abs(term) < Math.abs(sum) * 1e-12) break; }
      return Math.min(1, sum * Math.exp(-x + a * Math.log(x) - lg));
    }
    let b = x + 1 - a, c = 1e300, d = 1 / b, h = d;
    for (let i = 1; i < 200; i++) {
      const an = -i * (i - a);
      b += 2;
      d = an * d + b; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = b + an / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d;
      const del = d * c;
      h *= del;
      if (Math.abs(del - 1) < 1e-12) break;
    }
    return Math.max(0, 1 - Math.exp(-x + a * Math.log(x) - lg) * h);
  }

  function dgammaS(t, p) {
    const [Q, kb, thb, kw, thw] = p;
    const cdf = Q * gammaP(kb, Math.max(t, 0) / thb) + (1 - Q) * gammaP(kw, Math.max(t, 0) / thw);
    return Math.min(1, Math.max(1e-10, 1 - cdf));
  }

  function solve(M, v) {
    const n = v.length, a = M.map((row, i) => [...row, v[i]]);
    for (let i = 0; i < n; i++) {
      let max = i;
      for (let r = i + 1; r < n; r++) if (Math.abs(a[r][i]) > Math.abs(a[max][i])) max = r;
      [a[i], a[max]] = [a[max], a[i]];
      if (Math.abs(a[i][i]) < 1e-300) return null;
      for (let r = i + 1; r < n; r++) { const f = a[r][i] / a[i][i]; for (let c = i; c <= n; c++) a[r][c] -= f * a[i][c]; }
    }
    const x = new Array(n).fill(0);
    for (let i = n - 1; i >= 0; i--) { let s = a[i][n]; for (let c = i + 1; c < n; c++) s -= a[i][c] * x[c]; x[i] = s / a[i][i]; }
    return x;
  }

  // Levenberg-Marquardt least squares with box bounds
  function fitLM(f, p0, xs, ys, lo, hi) {
    const clamp = (p) => p.map((v, i) => Math.min(hi[i], Math.max(lo[i], v)));
    const sse = (p) => { let s = 0; for (let i = 0; i < xs.length; i++) { const r = ys[i] - f(xs[i], p); s += r * r; } return s; };
    let p = clamp(p0), best = sse(p), lambda = 1e-2;
    for (let iter = 0; iter < 150 && Number.isFinite(best); iter++) {
      const k = p.length, r = xs.map((x, i) => ys[i] - f(x, p));
      const J = xs.map((x) => p.map((v, j) => {
        const h = 1e-6 * Math.max(Math.abs(v), 1e-6);
        const q = p.slice(); q[j] = v + h;
        return (f(x, q) - f(x, p)) / h;
      }));
      const JtJ = Array.from({ length: k }, (_, a) => Array.from({ length: k }, (_, b) => d3.sum(J, (row) => row[a] * row[b])));
      const Jtr = Array.from({ length: k }, (_, a) => d3.sum(J, (row, i) => row[a] * r[i]));
      let improved = false;
      for (let tries = 0; tries < 8; tries++) {
        const M = JtJ.map((row, a) => row.map((v, b) => (a === b ? v * (1 + lambda) + 1e-12 : v)));
        const step = solve(M, Jtr);
        if (!step) { lambda *= 10; continue; }
        const q = clamp(p.map((v, i) => v + step[i]));
        const s = sse(q);
        if (s < best) {
          const gain = (best - s) / Math.max(best, 1e-300);
          p = q; best = s; lambda = Math.max(lambda / 3, 1e-9); improved = true;
          if (gain < 1e-9) return { p, sse: best };
          break;
        }
        lambda *= 4;
      }
      if (!improved) break;
    }
    return { p, sse: best };
  }

  // Empirical P(IVI > t): y_i = (n - i) / n for the i-th smallest interval
  function survivor(ivis) {
    const sorted = ivis.slice().sort((a, b) => a - b);
    const n = sorted.length;
    const at = (idx) => [...new Set(idx)].sort((a, b) => a - b).map((i) => ({ t: sorted[i], s: (n - i) / n }));
    // Fit on points evenly spaced in rank: the same weighting as fitting every interval,
    // as the study does, without fitting tens of thousands of points
    const fit = at(d3.range(Math.min(n, 400)).map((k) => Math.round((k * (n - 1)) / Math.max(1, Math.min(n, 400) - 1))));
    // Plot points evenly spaced in log-survival so the long tail stays visible
    const shown = at([0, n - 1, ...d3.range(300).map((k) => Math.min(n - 1, Math.max(0, n - Math.round(n * Math.pow(n, -k / 299)))))]);
    return { fit, shown };
  }

  function fitSurvivor(points, model, meanIvi) {
    const xs = points.map((p) => p.t), ys = points.map((p) => Math.log(p.s));
    const m = Math.max(meanIvi, 1e-3);
    let spec;
    if (model === "dgamma") {
      spec = {
        S: dgammaS, lo: [0, 0.1, 0.01, 0.1, 0.01], hi: [1, 10, 100, 10, 10],
        starts: [[0.5, 1.5, 2.0, 1.0, 0.5], [0.3, 1, Math.min(100, m), 1, 0.5], [0.5, 0.5, Math.min(100, m / 2), 0.8, 1]],
      };
    } else {
      spec = {
        S: dexpS, lo: [1e-4, 1e-6, 1e-4, 1e-7], hi: [2, 50, 2, 10],
        starts: [[0.4, 0.5, 0.6, 0.02], [0.8, 1 / m, 0.2, 0.01 / m], [0.6, 0.5 / m, 0.4, 0.05 / m], [0.9, 2 / m, 0.1, 0.001 / m], [0.5, 0.1 / m, 0.5, 0.1 / m]],
      };
    }
    const f = (t, p) => Math.log(Math.max(spec.S(t, p), 1e-10));
    let best = null;
    for (const p0 of spec.starts) {
      const res = fitLM(f, p0, xs, ys, spec.lo, spec.hi);
      if (Number.isFinite(res.sse) && (!best || res.sse < best.sse)) best = res;
    }
    if (!best) return null;
    let p = best.p;
    // Report the fast (within-bout) component first
    if (model === "dexp" && p[3] > p[1]) p = [p[2], p[3], p[0], p[1]];
    const pred = points.map((pt) => spec.S(pt.t, p));
    const mean = d3.mean(points, (pt) => pt.s);
    const ssRes = d3.sum(points, (pt, i) => (pt.s - pred[i]) ** 2), ssTot = d3.sum(points, (pt) => (pt.s - mean) ** 2);
    return { p, S: spec.S, r2: ssTot ? 1 - ssRes / ssTot : null, mae: d3.mean(points, (pt, i) => Math.abs(pt.s - pred[i])) };
  }

  function boutIntervals(site, species, sameDay, dom) {
    const vs = A.visits.filter((v) => v.site === site && (!species || v.species === species));
    const out = [];
    for (let i = 1; i < vs.length; i++) {
      const a = vs[i - 1], b = vs[i];
      if (a.d < dom[0] || b.d >= dom[1]) continue;
      if (sameDay && +a.d !== +b.d) continue;
      // An interval belongs to the condition on the later visit's day, as in the study
      out.push({ ivi: b.minute - a.minute, food: hasFood(phaseAt(site, b.d)) });
    }
    return out;
  }

  function renderBouts() {
    const site = BY.state.site;
    const dom = BY.domain();
    const speciesSel = bindOnce("bout-species", "change", (e) => BY.update({ boutSpecies: e.target.value }));
    const modelSel = bindOnce("bout-model", "change", (e) => BY.update({ boutModel: e.target.value }));
    const sameDayEl = bindOnce("bout-sameday", "change", (e) => BY.update({ boutSameDay: e.target.checked }));
    const splitEl = bindOnce("bout-split", "change", (e) => BY.update({ boutSplit: e.target.checked }));
    const counts = d3.rollups(A.visits.filter((v) => v.site === site).filter(BY.inRange(dom)), (v) => v.length, (v) => v.species)
      .sort((a, b) => b[1] - a[1]);
    const species = setOptions(speciesSel, [["", "All species pooled"], ...counts.filter(([, n]) => n >= 30).map(([s, n]) => [s, `${s} (${BY.fmt(n)} visits)`])], BY.state.boutSpecies || "");
    const model = modelSel.value = BY.state.boutModel || "dexp";
    const sameDay = sameDayEl.checked = !!BY.state.boutSameDay;
    const split = splitEl.checked = !!BY.state.boutSplit;

    const el = document.getElementById("bout-chart");
    const paramsEl = document.getElementById("bout-params");
    const note = document.getElementById("bout-note");
    const key = [site, +dom[0], +dom[1], species, model, sameDay, split].join("|");
    let result = fitCache.get(key);
    if (!result) {
      const ivis = boutIntervals(site, species, sameDay, dom);
      const groups = split
        ? [{ label: "Food available", color: "--s1", ivis: ivis.filter((x) => x.food).map((x) => x.ivi) },
          { label: "No food", color: "--s8", ivis: ivis.filter((x) => !x.food).map((x) => x.ivi) }]
        : [{ label: species || "All species", color: "--s1", ivis: ivis.map((x) => x.ivi) }];
      result = groups.filter((g) => g.ivis.length >= 5).map((g) => {
        const curve = survivor(g.ivis);
        return { ...g, n: g.ivis.length, points: curve.shown, fit: fitSurvivor(curve.fit, model, d3.mean(g.ivis)) };
      });
      fitCache.set(key, result);
    }
    if (!result.length) {
      BY.empty(el, "Fewer than 5 intervals in this range.");
      paramsEl.replaceChildren();
      note.textContent = "";
      return;
    }
    const maxT = d3.max(result, (g) => d3.max(g.points, (p) => p.t));
    const pts = result.flatMap((g) => g.points.map((p) => ({ ...p, label: g.label })));
    const curves = result.filter((g) => g.fit).flatMap((g) => d3.range(0, 201).map((i) => {
      const t = (maxT * i) / 200;
      return { t, s: g.fit.S(t, g.fit.p), label: g.label };
    }));
    const size = Math.min(el.clientWidth || 520, 680);
    const labels = result.map((g) => g.label), colors = result.map((g) => BY.css(g.color));
    el.replaceChildren(...(result.length > 1 ? [BY.legend(result.map((g) => ({ label: g.label, color: BY.css(g.color) })))] : []), Plot.plot({
      width: size, height: Math.round(size * 0.8), marginLeft: 56, marginRight: 20,
      style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
      x: { label: "Elapsed time, t (minutes)", grid: true },
      y: { type: "log", label: "Proportion of intervals > t", grid: true, domain: [Math.min(...result.map((g) => 1 / g.n)) * 0.8, 1.05],
        tickFormat: (d) => d3.format("~g")(d) },
      color: { domain: labels, range: colors },
      marks: [
        Plot.dot(pts, { x: "t", y: "s", stroke: "label", r: 2.5, strokeWidth: 1,
          tip: true, title: (p) => `${d3.format(".2%")(p.s)} of intervals longer than ${BY.fmt(Math.round(p.t))} min\n${p.label}` }),
        Plot.line(curves, { x: "t", y: (c) => Math.max(c.s, 1e-6), z: "label", stroke: "label", strokeWidth: 2, clip: true }),
      ],
    }));

    const f2 = d3.format(".2f"), f3 = d3.format(".3f"), f4 = d3.format(".4f");
    const header = model === "dexp"
      ? ["", "Intervals", "A₁", "λ₁ (/min)", "A₂", "λ₂ (/min)", "Within-bout mean (min)", "Between-bout mean (min)", "R²", "MAE"]
      : ["", "Intervals", "Q", "k_b", "θ_b", "k_w", "θ_w", "R²", "MAE"];
    const body = result.map((g) => {
      if (!g.fit) return [g.label, BY.fmt(g.n), ...header.slice(2).map(() => "n/a")];
      const p = g.fit.p;
      const tail = [g.fit.r2 == null ? "n/a" : f3(g.fit.r2), f3(g.fit.mae)];
      return model === "dexp"
        ? [g.label, BY.fmt(g.n), f2(p[0]), f4(p[1]), f2(p[2]), f4(p[3]), d3.format(",.1f")(1 / p[1]), d3.format(",.0f")(1 / p[3]), ...tail]
        : [g.label, BY.fmt(g.n), f2(p[0]), f2(p[1]), f2(p[2]), f2(p[3]), f2(p[4]), ...tail];
    });
    // Transpose so parameters read down a narrow column
    const t = BY.table(["", ...body.map((b) => b[0])], header.slice(1).map((h, i) => [h, ...body.map((b) => b[i + 1])]),
      [false, ...body.map(() => true)]);
    paramsEl.replaceChildren(t);
    note.textContent = (model === "dexp"
      ? "P(IVI > t) = A₁e^(−λ₁t) + A₂e^(−λ₂t). 1/λ is the mean interval of each process. "
      : "P(IVI > t) = 1 − [Q·Γ(k_b, t/θ_b) + (1 − Q)·Γ(k_w, t/θ_w)], a mix of two gamma processes. ") +
      `Intervals between consecutive visits at ${siteName(site)}${species ? ` by ${species}` : ", all species pooled"}` +
      (sameDay ? ", same-day only" : ", including overnight gaps") +
      `. Fitted on 400 points evenly spaced along the curve (equivalent to weighting every interval equally, as the study does) from several starting values, keeping the best. R² and MAE are on the linear scale.` +
      (split ? " Food available covers Seed and Low Dove Mix phases and the baseline before the first phase; No food covers Extinction and Feeder Removed." : "");
  }

  // ---- seed and side preference --------------------------------------------
  const JAX = "jacksonville_fl_32259";

  function renderSeedPreference() {
    const dom = BY.domain();
    const sub = document.getElementById("seed-sub");
    const el = document.getElementById("seed-chart");
    const pecks = A.pecks.filter(BY.inRange(dom));
    const atJax = BY.state.site === JAX;
    if (!pecks.length) {
      sub.textContent = "Pecks are recorded at Jacksonville only.";
      BY.empty(el, "No peck counts in this range.");
      document.getElementById("peck-chart").replaceChildren();
      return;
    }
    const mode = (vals) => d3.greatest(d3.rollups(vals.filter(Boolean), (v) => v.length, (v) => v), (a) => a[1])?.[0] || "None";
    const daily = d3.flatRollup(pecks.filter((p) => p.species !== SQUIRREL), (v) => ({
      left: d3.sum(v, (p) => p.left || 0), right: d3.sum(v, (p) => p.right || 0),
      leftSeed: mode(v.map((p) => p.leftSeed)), rightSeed: mode(v.map((p) => p.rightSeed)),
    }), (p) => p.species, (p) => +p.d).map(([species, t, s]) => ({ species, d: new Date(t), ...s, ratio: Math.log((s.left + 1) / (s.right + 1)) }));
    const bySpecies = d3.groups(daily, (r) => r.species).filter(([, v]) => v.length >= 5).sort((a, b) => b[1].length - a[1].length);
    sub.textContent = `${atJax ? "" : "Pecks are recorded at Jacksonville only, so this shows Jacksonville. "}` +
      "Each point is one day: the natural log of (left pecks + 1) ÷ (right pecks + 1). Above zero, more pecks on the left feeder; below, more on the right. " +
      "Species with at least 5 days of peck counts in this range; the squirrel is left out, as in the study.";
    const maxAbs = d3.max(daily, (r) => Math.abs(r.ratio)) || 1;
    const rects = phaseRects(JAX);
    const cards = bySpecies.map(([species, rowsRaw]) => {
      const rows = rowsRaw.sort((a, b) => a.d - b.d);
      const div = document.createElement("div");
      const h = document.createElement("h4");
      h.textContent = `${species} (${rows.length} days)`;
      const byDay = new Map(rows.map((r) => [+r.d, r]));
      const lineRows = d3.utcDays(rows[0].d, new Date(+rows[rows.length - 1].d + BY.DAY)).map((d) => ({ d, ratio: byDay.get(+d)?.ratio ?? null }));
      div.append(h, Plot.plot({
        width: 300, height: 170, marginLeft: 36, marginRight: 8, marginTop: 10,
        style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "11px" },
        x: { type: "utc", domain: dom, ticks: 4 },
        y: { domain: [-maxAbs, maxAbs], grid: true, label: null, ticks: 5, nice: true },
        marks: [
          Plot.rect(rects, { x1: "x1", x2: "x2", fill: (s) => BY.phaseShade(s.description), fillOpacity: 0.16 }),
          Plot.ruleY([0], { stroke: BY.css("--axis") }),
          Plot.text(["Left"], { frameAnchor: "top-left", dx: 3, dy: 2, fill: BY.css("--muted"), fontSize: 10 }),
          Plot.text(["Right"], { frameAnchor: "bottom-left", dx: 3, dy: -2, fill: BY.css("--muted"), fontSize: 10 }),
          Plot.lineY(lineRows, { x: "d", y: "ratio", stroke: BY.css("--s1"), strokeWidth: 1.5 }),
          Plot.dot(rows, { x: "d", y: "ratio", r: 2.5, fill: BY.css("--s1"),
            tip: true, title: (r) => `${BY.fmtDate(r.d)}\nLeft ${BY.fmt(r.left)} pecks (${r.leftSeed})\nRight ${BY.fmt(r.right)} pecks (${r.rightSeed})` }),
        ],
      }));
      return div;
    });
    if (cards.length) el.replaceChildren(...cards);
    else BY.empty(el, "No species with 5 or more days of peck counts in this range.");

    // Pecks per visit, by the seed on the side that was pecked
    const peckSel = bindOnce("peck-species", "change", (e) => BY.update({ peckSpecies: e.target.value }));
    const counts = d3.rollups(pecks, (v) => v.length, (p) => p.species).sort((a, b) => b[1] - a[1]);
    const chosen = setOptions(peckSel, [["", "All species"], ...counts.filter(([s, n]) => n >= 10 && s !== SQUIRREL).map(([s, n]) => [s, `${s} (${BY.fmt(n)})`])], BY.state.peckSpecies || "");
    const sel = pecks.filter((p) => (chosen ? p.species === chosen : p.species !== SQUIRREL));
    const sides = sel.flatMap((p) => [{ seed: p.leftSeed, pecks: p.left }, { seed: p.rightSeed, pecks: p.right }])
      .filter((s) => s.seed && s.pecks > 0);
    const peckEl = document.getElementById("peck-chart");
    if (!sides.length) { BY.empty(peckEl, "No pecks recorded for this selection."); return; }
    const seeds = A.seeds.filter((s) => sides.some((x) => x.seed === s));
    const dist = d3.groups(sides, (s) => s.seed).flatMap(([seed, v]) =>
      d3.rollups(v, (g) => g.length, (s) => s.pecks).map(([pecksN, n]) => ({ seed, pecks: pecksN, n, share: n / v.length })));
    const seedColor = (s) => BY.css(`--s${(A.seeds.indexOf(s) % 8) + 1}`);
    peckEl.replaceChildren(BY.legend(seeds.map((s) => ({ label: s, color: seedColor(s) })), "line"), Plot.plot({
      width: Math.max(320, peckEl.clientWidth), height: 300, marginLeft: 56, marginRight: 20,
      style: { background: "transparent", color: BY.css("--ink-2"), fontSize: "12px" },
      x: { label: "Pecks in the visit", domain: [1, 40], grid: true },
      y: { type: "log", label: "Share of visits to that seed", grid: true, tickFormat: "%" },
      color: { domain: seeds, range: seeds.map(seedColor) },
      marks: [
        Plot.line(dist.filter((d) => d.pecks <= 40), { x: "pecks", y: "share", stroke: "seed", strokeWidth: 2, sort: "pecks" }),
        Plot.dot(dist.filter((d) => d.pecks <= 40), { x: "pecks", y: "share", fill: "seed", r: 3,
          tip: true, title: (d) => `${d.seed}\n${d.pecks} pecks: ${d3.format(".1%")(d.share)} of visits (${BY.fmt(d.n)})` }),
      ],
    }), noteEl("Each visit's left and right pecks count toward the seed on that side; visits with zero pecks on a side are left out, as in the study."));
  }
})();
