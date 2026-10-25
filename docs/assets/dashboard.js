// Interactive dashboard for docs/index.html. Reads docs/data/dashboard.json,
// written daily by scripts_notebooks/export_dashboard_data.py.
(async function () {
  "use strict";

  const DAY = 864e5;
  const MAX_SPECIES = 8; // categorical slots; the rest fold into "Other"
  const STALE_LATE = 3; // days behind before a source is flagged
  const STALE_BAD = 8;

  const state = { site: "jacksonville_fl_32259", days: 90, phases: false, corrActivity: "detections", corrField: "tempMean", trackSpecies: null, hourMode: "count" };
  try {
    const saved = JSON.parse(localStorage.getItem("by-filters") || "{}");
    Object.assign(state, saved);
  } catch (e) { /* storage unavailable */ }

  const data = await fetch("data/dashboard.json").then((r) => r.json());
  const rows = (block) => block.rows.map((r) => Object.fromEntries(block.cols.map((c, i) => [c, r[i]])));
  const feederDaily = rows(data.feederDaily);
  const feederHourly = rows(data.feederHourly);
  const stationDaily = rows(data.stationDaily);
  const stationSpecies = rows(data.stationSpecies);
  const countyDaily = rows(data.countyDaily);
  const migration = rows(data.migration);
  const phases = rows(data.phases);
  const weatherDaily = rows(data.weatherDaily);
  const sensorDaily = rows(data.sensorDaily);
  const speciesDaily = rows(data.stationSpeciesDaily);
  const parse = d3.utcParse("%Y-%m-%d");
  for (const set of [feederDaily, feederHourly, stationDaily, countyDaily]) for (const r of set) r.d = parse(r.date);
  for (const r of migration) r.d = parse(r.night);
  const flywayNightly = rows(data.flywayNightly);
  for (const r of flywayNightly) r.d = parse(r.night);
  const migrationSpecies = rows(data.migrationSpecies);
  for (const r of phases) r.d = parse(r.start);
  for (const set of [weatherDaily, sensorDaily]) for (const r of set) r.d = parse(r.date);
  for (const r of speciesDaily) { r.d = parse(r.date); r.name = data.speciesNames[r.species]; }

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = d3.format(",");
  const fmtDate = d3.utcFormat("%b %-d, %Y");
  const fmtBirds = (d) => d3.format("~s")(d).replace("G", "B");
  const today = d3.utcDay.floor(new Date());

  // ---- filters ------------------------------------------------------------
  const siteSelect = document.getElementById("site");
  for (const [key, s] of Object.entries(data.sites)) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = s.name;
    siteSelect.append(opt);
  }
  if (!data.sites[state.site]) state.site = "jacksonville_fl_32259";
  siteSelect.value = state.site;
  siteSelect.addEventListener("change", () => update({ site: siteSelect.value }));

  const rangeButtons = document.querySelectorAll(".range button");
  rangeButtons.forEach((b) => b.addEventListener("click", () => update({ days: +b.dataset.days })));
  const phaseToggle = document.getElementById("phases");
  phaseToggle.checked = state.phases;
  phaseToggle.addEventListener("change", () => update({ phases: phaseToggle.checked }));
  document.querySelectorAll("#corr-activity button").forEach((b) =>
    b.addEventListener("click", () => update({ corrActivity: b.dataset.activity })));
  document.querySelectorAll("#hour-mode button").forEach((b) =>
    b.addEventListener("click", () => update({ hourMode: b.dataset.mode })));

  function update(patch) {
    Object.assign(state, patch);
    try { localStorage.setItem("by-filters", JSON.stringify(state)); } catch (e) { /* ignore */ }
    render();
  }

  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);

  // ---- helpers -------------------------------------------------------------
  function domain() {
    const end = d3.utcDay.offset(today, 1);
    if (state.days) return [d3.utcDay.offset(today, -state.days), end];
    const siteDates = feederDaily.filter((r) => r.site === state.site).map((r) => r.d);
    stationsFor(state.site).forEach((s) => stationDaily.forEach((r) => r.station === s && siteDates.push(r.d)));
    return [d3.min(siteDates) || d3.utcDay.offset(today, -365), end];
  }
  const inRange = ([a, b]) => (r) => r.d >= a && r.d < b;
  const stationsFor = (site) => Object.keys(data.stations).filter((k) => data.stations[k].site === site);
  const countiesFor = (site) => Object.keys(data.counties).filter((k) => data.counties[k].site === site);
  const regionsFor = (site) => Object.keys(data.birdcastRegions).filter((k) => data.birdcastRegions[k].site === site);
  const daysBehind = (iso) => (iso ? Math.round((today - parse(iso)) / DAY) : Infinity);
  // Charts leave room on the right for their phase legend when phases are shown
  const PHASE_ASIDE = 190;
  const asideOn = () => state.phases && window.innerWidth >= 760;
  const width = (el) => Math.max(320, el.clientWidth - (asideOn() ? PHASE_ASIDE : 0));

  function empty(el, text) {
    el.replaceChildren();
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = text;
    el.append(p);
  }

  function legend(items, kind) {
    const div = document.createElement("div");
    div.className = "legend";
    for (const { label, color } of items) {
      const span = document.createElement("span");
      const key = document.createElement("i");
      if (kind === "line") key.className = "line";
      key.style.background = color;
      span.append(key, document.createTextNode(label));
      div.append(span);
    }
    return div;
  }

  function baseOptions(el, extra) {
    return {
      width: width(el),
      marginLeft: 52,
      style: { background: "transparent", color: css("--ink-2"), fontSize: "12px" },
      marginRight: 20,
      x: { type: "utc", domain: domain(), label: null },
      ...extra,
    };
  }

  function phaseSpans(site = state.site) {
    // Number phases over the site's whole record so numbers stay stable as the range changes
    const [a, b] = domain();
    const ph = phases.filter((p) => p.site === site).sort((x, y) => x.d - y.d);
    return ph.map((p, i) => ({ ...p, n: i + 1, x1: p.d, x2: i + 1 < ph.length ? ph[i + 1].d : b }))
      .filter((s) => s.x2 > a && s.x1 < b)
      .map((s) => ({ ...s, x1: new Date(Math.max(s.x1, a)), x2: new Date(Math.min(s.x2, b)) }));
  }

  // Each food condition keeps one shade everywhere; extinction is the unshaded baseline
  const PHASE_SHADES = {
    "Seed": "--s3",
    "Low Dove Mix": "--s4",
    "Low Dove Mix (One Side)": "--s7",
    "Low Dove Mix (Both Sides)": "--s5",
    "Low Dove Mix (Split Sides)": "--s1",
    "Feeder Removed": "--muted",
  };
  const phaseShade = (description) => {
    const token = PHASE_SHADES[(description || "").trim()];
    return token ? css(token) : null;
  };

  function phaseMarks() {
    if (!state.phases) return [];
    const shaded = phaseSpans().filter((s) => phaseShade(s.description));
    return [
      Plot.rect(shaded, {
        x1: "x1", x2: "x2", fill: (s) => phaseShade(s.description), fillOpacity: 0.16,
        title: (s) => `${s.description}\n${fmtDate(s.d)}${s.ratio ? `\n${s.ratio}` : ""}`,
      }),
    ];
  }

  function phaseLegendItems(spans) {
    const present = new Set(spans.map((s) => (s.description || "").trim()));
    return ["Extinction", ...Object.keys(PHASE_SHADES)].filter((c) => present.has(c))
      .concat([...present].filter((c) => c !== "Extinction" && !(c in PHASE_SHADES)));
  }

  function phaseSwatch(condition) {
    const swatch = document.createElement("i");
    swatch.className = "phase-swatch";
    const shade = phaseShade(condition);
    if (shade) { swatch.style.background = `color-mix(in srgb, ${shade} 30%, transparent)`; swatch.style.borderColor = shade; }
    return swatch;
  }

  // Wrap a chart so the phases it shows are named in the space beside it
  function withPhases(...nodes) {
    if (!state.phases) return nodes.length === 1 ? nodes[0] : stack(nodes);
    const spans = phaseSpans();
    const row = document.createElement("div");
    row.className = "plot-row";
    const aside = document.createElement("div");
    aside.className = "phase-aside";
    if (spans.length) {
      const title = document.createElement("div");
      title.className = "phase-aside-title";
      title.textContent = "Study phase";
      aside.append(title);
      for (const c of phaseLegendItems(spans)) {
        const item = document.createElement("div");
        item.append(phaseSwatch(c), document.createTextNode(c));
        aside.append(item);
      }
    }
    row.append(nodes.length === 1 ? nodes[0] : stack(nodes), aside);
    return row;
  }

  function stack(nodes) {
    const div = document.createElement("div");
    div.append(...nodes);
    return div;
  }

  // Heatmaps get a thin strip above instead of a wash, so cell density stays readable
  function phaseStrip(el, marginLeft) {
    if (!state.phases) return null;
    const shaded = phaseSpans().filter((s) => phaseShade(s.description));
    return Plot.plot({
      width: width(el), height: 14, marginLeft, marginRight: 20, marginTop: 2, marginBottom: 2,
      style: { background: "transparent" },
      x: { type: "utc", domain: domain(), axis: null },
      marks: [
        Plot.rect(shaded, { x1: "x1", x2: "x2", fill: (s) => phaseShade(s.description), fillOpacity: 0.7, inset: 0.5,
          title: (s) => `${s.description}\n${fmtDate(s.d)}${s.ratio ? `\n${s.ratio}` : ""}` }),
      ],
    });
  }

  function renderPhaseKey() {
    const el = document.getElementById("phase-key");
    const spans = state.phases ? phaseSpans() : [];
    el.hidden = !spans.length;
    el.replaceChildren();
    if (!spans.length) return;
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Study phase dates";
    const ol = document.createElement("ol");
    const allPhases = phases.filter((p) => p.site === state.site).sort((x, y) => x.d - y.d);
    for (const s of spans) {
      const next = allPhases[s.n];
      const li = document.createElement("li");
      const text = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = s.description;
      const until = next ? ` to ${fmtDate(d3.utcDay.offset(next.d, -1))}` : " onward";
      text.append(strong, document.createTextNode(`, ${fmtDate(s.d)}${until}${s.ratio ? `. ${s.ratio}` : ""}`));
      li.append(phaseSwatch(s.description), text);
      ol.append(li);
    }
    details.append(summary, ol);
    el.append(details);
  }

  // ---- data health ---------------------------------------------------------
  function renderHealth() {
    const ul = document.getElementById("health");
    ul.replaceChildren();
    const relevant = data.freshness.filter((s) => s.site === state.site);
    for (const s of relevant) {
      const behind = daysBehind(s.last);
      const li = document.createElement("li");
      li.className = behind < STALE_LATE ? "ok" : behind < STALE_BAD ? "late" : "stale";
      const status = behind < STALE_LATE ? "Current" : behind === Infinity ? "No data" : `${behind} days behind`;
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.setAttribute("aria-hidden", "true");
      // One text span so the chip's flex gap only separates the dot
      const text = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = s.group;
      const name = s.group.startsWith("Feeder") ? "" : ` (${s.name})`;
      text.append(strong, document.createTextNode(`${name}: ${status}`));
      li.append(dot, text);
      li.title = s.last ? `Last data ${fmtDate(parse(s.last))}` : "No data";
      ul.append(li);
    }

    // A phase dated well outside the site's records is almost always a typo in the sheet
    const siteDates = feederDaily.filter((r) => r.site === state.site).map((r) => r.d);
    const first = d3.min(siteDates);
    if (!first) return;
    const suspect = phases.filter((p) => p.site === state.site &&
      (p.d < d3.utcDay.offset(first, -60) || p.d > d3.utcDay.offset(today, 1)));
    for (const p of suspect) {
      const li = document.createElement("li");
      li.className = "late";
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = "Check phase date";
      text.append(strong, document.createTextNode(`: ${p.description} dated ${fmtDate(p.d)}`));
      li.append(dot, text);
      li.title = "This phase is dated outside the site's records. Check the date in the phase sheet.";
      ul.append(li);
    }
  }

  // ---- summary tiles -------------------------------------------------------
  function tile(label, value, note) {
    const div = document.createElement("div");
    div.className = "tile";
    for (const [cls, text] of [["label", label], ["value", value], ["note", note]]) {
      const el = document.createElement("div");
      el.className = cls;
      el.textContent = text;
      div.append(el);
    }
    return div;
  }

  function lastWeek(set, key, field) {
    const last = d3.max(set, (r) => r.d);
    if (!last) return null;
    const start = d3.utcDay.offset(last, -6);
    const week = set.filter((r) => r.d >= start && r.d <= last);
    return { last, week, total: d3.sum(week, (r) => r[field]), unique: new Set(week.map((r) => r[key])).size };
  }

  function renderTiles() {
    const el = document.getElementById("tiles");
    el.replaceChildren();
    const feeder = lastWeek(feederDaily.filter((r) => r.site === state.site), "species", "visits");
    if (feeder) {
      el.append(tile("Feeder visits, last 7 days", fmt(feeder.total), `Week ending ${fmtDate(feeder.last)}`));
      el.append(tile("Species at the feeder, last 7 days", fmt(feeder.unique), `Week ending ${fmtDate(feeder.last)}`));
    }
    for (const sid of stationsFor(state.site)) {
      const st = stationSpecies.filter((r) => r.station === sid && r.last7 > 0);
      const lastDay = d3.max(stationDaily.filter((r) => r.station === sid), (r) => r.d);
      if (lastDay) el.append(tile("Species heard, last 7 days", fmt(st.length), `${data.stations[sid].name} PUC, through ${fmtDate(lastDay)}`));
    }
    for (const code of regionsFor(state.site)) {
      const m = migration.filter((r) => r.region === code);
      const latest = m.length ? m.reduce((a, b) => (a.d > b.d ? a : b)) : null;
      if (latest) el.append(tile("Birds migrating overhead", d3.format(".3~s")(latest.birds).replace("G", "B"),
        `${data.birdcastRegions[code].name}, night of ${fmtDate(latest.d)}`));
    }
  }

  // ---- feeder visits by species --------------------------------------------
  function speciesColors(siteRows) {
    // Color follows the species: rank by all-time visits at this site, not by the visible range
    const totals = d3.rollups(siteRows, (v) => d3.sum(v, (r) => r.visits), (r) => r.species)
      .sort((a, b) => d3.descending(a[1], b[1]));
    const top = totals.slice(0, MAX_SPECIES).map((d) => d[0]);
    const colors = new Map(top.map((s, i) => [s, css(`--s${i + 1}`)]));
    return { top, colors };
  }

  function renderFeeder() {
    const el = document.getElementById("feeder-chart");
    const siteRows = feederDaily.filter((r) => r.site === state.site);
    const { top, colors } = speciesColors(siteRows);
    const visible = siteRows.filter(inRange(domain()))
      .map((r) => ({ ...r, group: top.includes(r.species) ? r.species : "Other" }));
    const sub = document.getElementById("feeder-sub");
    const last = d3.max(siteRows, (r) => r.d);
    sub.textContent = last ? `Hand-entered from the Birdfy camera. Latest entry ${fmtDate(last)}.` : "";
    if (!visible.length) {
      empty(el, last ? `No feeder data in this range. The latest entry is ${fmtDate(last)}.` : "No feeder data for this site.");
      renderFeederTable([]);
      return;
    }
    const groups = [...top.filter((s) => visible.some((r) => r.group === s)), ...(visible.some((r) => r.group === "Other") ? ["Other"] : [])];
    const color = (g) => (g === "Other" ? css("--other") : colors.get(g));
    const daily = d3.flatRollup(visible, (v) => d3.sum(v, (r) => r.visits), (r) => +r.d, (r) => r.group)
      .map(([t, group, visits]) => ({ d: new Date(t), group, visits }));
    const chart = Plot.plot(baseOptions(el, {
      height: 300,
      y: { label: "Visits per day", grid: true },
      color: { domain: groups, range: groups.map(color) },
      marks: [
        ...phaseMarks(),
        Plot.rectY(daily, Plot.stackY({
          x: "d", interval: "day", y: "visits", fill: "group", order: groups,
          inset: 0.5, tip: { format: { x: (d) => fmtDate(d), fill: true, y: true } },
          title: (d) => `${d.group}\n${fmt(d.visits)} visits\n${fmtDate(d.d)}`,
        })),
        Plot.ruleY([0], { stroke: css("--axis") }),
      ],
    }));
    el.replaceChildren(legend(groups.map((g) => ({ label: g, color: color(g) }))), withPhases(chart));
    renderFeederTable(visible);
  }

  function renderFeederTable(visible) {
    const el = document.getElementById("feeder-table");
    el.replaceChildren();
    if (!visible.length) return;
    const totals = d3.rollups(visible, (v) => ({ visits: d3.sum(v, (r) => r.visits), days: new Set(v.map((r) => r.date)).size }), (r) => r.species)
      .sort((a, b) => d3.descending(a[1].visits, b[1].visits));
    el.append(table(["Species", "Visits", "Days seen"], totals.map(([s, t]) => [s, fmt(t.visits), fmt(t.days)]), [false, true, true]));
  }

  function table(headers, body, numeric) {
    const t = document.createElement("table");
    const thead = t.createTHead().insertRow();
    headers.forEach((h, i) => {
      const th = document.createElement("th");
      th.textContent = h;
      if (numeric[i]) th.className = "num";
      thead.append(th);
    });
    const tb = t.createTBody();
    for (const row of body) {
      const tr = tb.insertRow();
      row.forEach((v, i) => {
        const td = tr.insertCell();
        if (v instanceof Node) td.append(v); else td.textContent = v;
        if (numeric[i]) td.className = "num";
      });
    }
    return t;
  }

  // ---- time of day heatmap -------------------------------------------------
  function renderHours() {
    const el = document.getElementById("hour-chart");
    const share = state.hourMode === "share";
    document.querySelectorAll("#hour-mode button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.hourMode)));
    document.getElementById("hour-sub").textContent = share
      ? "Each cell is one hour of one day, as a share of that day's visits, so busy and quiet days compare evenly."
      : "Each cell is one hour of one day. Stronger color means more visits.";
    let visible = feederHourly.filter((r) => r.site === state.site).filter(inRange(domain()));
    if (!visible.length) { empty(el, "No feeder data in this range."); return; }
    if (share) {
      const dayTotals = d3.rollup(visible, (v) => d3.sum(v, (r) => r.visits), (r) => +r.d);
      visible = visible.map((r) => ({ ...r, value: r.visits / dayTotals.get(+r.d) }));
    } else {
      visible = visible.map((r) => ({ ...r, value: r.visits }));
    }
    const chart = Plot.plot(baseOptions(el, {
      height: 280,
      y: { domain: [24, 0], label: "Hour of day", ticks: [0, 6, 12, 18, 24], tickFormat: (h) => `${String(h).padStart(2, "0")}:00` },
      color: { type: "linear", range: [css("--seq-lo"), css("--seq-hi")], label: share ? "Share of the day's visits" : "Visits in the hour",
        tickFormat: share ? "%" : undefined },
      marks: [
        Plot.rect(visible, {
          x: "d", interval: "day", y1: "hour", y2: (r) => r.hour + 1, fill: "value", inset: 0.25,
          tip: true, title: (r) => `${share ? `${d3.format(".0%")(r.value)} of the day (${fmt(r.visits)} visits)` : `${fmt(r.visits)} visits`}\n${fmtDate(r.d)}, ${String(r.hour).padStart(2, "0")}:00`,
        }),
      ],
    }));
    el.replaceChildren(withPhases(...[chart.legend("color"), phaseStrip(el, 52), chart].filter(Boolean)));
  }

  // ---- acoustic + migration small multiples --------------------------------
  function lineChart(el, series, yLabel, under = [], zero = true) {
    // series: [{label, color, rows: [{d, value}]}]
    const all = series.flatMap((s) => s.rows.map((r) => ({ ...r, label: s.label })));
    if (!all.length) return false;
    const multi = series.length > 1;
    const chart = Plot.plot(baseOptions(el, {
      height: 170,
      y: { label: yLabel, grid: true, nice: true, tickFormat: "~s" },
      color: { domain: series.map((s) => s.label), range: series.map((s) => s.color) },
      marks: [
        ...phaseMarks(),
        ...(zero ? [Plot.ruleY([0], { stroke: css("--axis") })] : []),
        ...under,
        // Gaps in the data stay gaps rather than being bridged by a line
        Plot.lineY(all, { x: "d", y: "value", z: "label", stroke: "label", strokeWidth: 2, curve: "linear"}),
        Plot.dot(all, Plot.pointerX({ x: "d", y: "value", fill: "label", r: 4, stroke: css("--surface"), strokeWidth: 2 })),
        Plot.ruleX(all, Plot.pointerX({ x: "d", stroke: css("--muted"), strokeWidth: 1 })),
        Plot.tip(all, Plot.pointerX({ x: "d", y: "value",
          title: (r) => `${fmt(r.value)} ${yLabel.toLowerCase()}\n${r.label}\n${fmtDate(r.d)}` })),
      ],
    }));
    el.replaceChildren(...(multi ? [legend(series.map((s) => ({ label: s.label, color: s.color })), "line")] : []), withPhases(chart));
    return true;
  }

  function withGaps(rows, field, [a, b]) {
    // Insert nulls for missing days so lines break where a station was offline
    const byDay = new Map(rows.map((r) => [+r.d, r[field]]));
    if (!rows.length) return [];
    const start = new Date(Math.max(a, d3.min(rows, (r) => r.d)));
    const end = new Date(Math.min(b, +d3.max(rows, (r) => r.d) + DAY));
    return d3.utcDays(start, end).map((d) => ({ d, value: byDay.has(+d) ? byDay.get(+d) : null }));
  }

  function renderAcoustic() {
    const dom = domain();
    const stationEl = document.getElementById("station-chart");
    const stations = stationsFor(state.site);
    const ok1 = lineChart(stationEl, stations.map((sid, i) => ({
      label: `${data.stations[sid].name} PUC`, color: css(`--s${i + 1}`),
      rows: withGaps(stationDaily.filter((r) => r.station === sid), "detections", dom),
    })), "Detections");
    if (!ok1) empty(stationEl, stations.length ? "No station data in this range." : "No PUC station at this site.");

    const countyEl = document.getElementById("county-chart");
    const counties = countiesFor(state.site);
    const ok2 = lineChart(countyEl, counties.map((c, i) => ({
      label: data.counties[c].name, color: css(`--s${i + 1}`),
      rows: withGaps(countyDaily.filter((r) => r.county === c), "detections", dom),
    })), "Detections");
    if (!ok2) empty(countyEl, counties.length ? "No county data in this range." : "No county data for this site.");

    const migEl = document.getElementById("migration-chart");
    const regions = regionsFor(state.site);
    const nights = migration.filter((r) => regions.includes(r.region)).filter(inRange(dom));
    if (!nights.length) {
      empty(migEl, regions.length ? "No migration estimates in this range. BirdCast publishes during spring and fall migration." : "No BirdCast region for this site.");
    } else {
      migEl.replaceChildren(withPhases(Plot.plot(baseOptions(migEl, {
        height: 170,
        y: { label: "Birds", grid: true, tickFormat: fmtBirds },
        marks: [
          ...phaseMarks(),
          Plot.rectY(nights, { x: "d", interval: "day", y: "birds", fill: css("--s1"), inset: 0.5, rx2: 2,
            tip: true, title: (r) => `${fmt(r.birds)} birds\n${data.birdcastRegions[r.region].name}\nNight of ${fmtDate(r.d)}` }),
          Plot.ruleY([0], { stroke: css("--axis") }),
        ],
      }))));
    }
  }

  // ---- weather -------------------------------------------------------------
  function renderWeather() {
    const dom = domain();
    const weather = weatherDaily.filter((r) => r.site === state.site);
    const sid = stationsFor(state.site)[0];
    const sensor = sid ? sensorDaily.filter((r) => r.station === sid) : [];
    const lastW = d3.max(weather, (r) => r.d);
    const lastS = d3.max(sensor, (r) => r.d);
    document.getElementById("weather-sub").textContent = [
      sensor.length ? `Temperature at the feeder from the ${data.stations[sid].name} PUC's own sensor${lastS ? ` (through ${fmtDate(lastS)})` : ""}. It reads a few degrees warm in daytime sun, and has gaps where the station lost power.` : "",
      `Rain and wind are modeled by Open-Meteo for ${data.sites[state.site].name}${lastW ? ` (through ${fmtDate(lastW)})` : ""}, which also covers days the PUC was offline.`,
    ].join(" ");

    const tempEl = document.getElementById("temp-chart");
    const series = [];
    if (sensor.length) {
      series.push({ label: "Backyard PUC sensor", color: css("--s1"), rows: withGaps(sensor, "tempMax", dom) });
    }
    series.push({ label: "Open-Meteo regional", color: css("--s2"), rows: withGaps(weather, "tempMax", dom) });
    if (!lineChart(tempEl, series, "°C", [], false)) empty(tempEl, "No weather data in this range.");

    const rainEl = document.getElementById("rain-chart");
    const rain = weather.filter(inRange(dom));
    if (!rain.length) empty(rainEl, "No weather data in this range.");
    else rainEl.replaceChildren(withPhases(Plot.plot(baseOptions(rainEl, {
      height: 140,
      y: { label: "mm", grid: true },
      marks: [
        ...phaseMarks(),
        Plot.rectY(rain, { x: "d", interval: "day", y: "rainMm", fill: css("--s1"), inset: 0.5,
          tip: true, title: (r) => `${d3.format(".1f")(r.rainMm)} mm\n${fmtDate(r.d)}` }),
        Plot.ruleY([0], { stroke: css("--axis") }),
      ],
    }))));

    const windEl = document.getElementById("wind-chart");
    if (!lineChart(windEl, [{ label: "Open-Meteo regional", color: css("--s1"), rows: withGaps(weather, "windMean", dom) }], "m/s")) {
      empty(windEl, "No weather data in this range.");
    }
  }

  // ---- activity vs weather -------------------------------------------------
  function pearson(pairs) {
    const n = pairs.length;
    if (n < 3) return null;
    const mx = d3.mean(pairs, (p) => p.x), my = d3.mean(pairs, (p) => p.y);
    let sxy = 0, sxx = 0, syy = 0;
    for (const { x, y } of pairs) { sxy += (x - mx) * (y - my); sxx += (x - mx) ** 2; syy += (y - my) ** 2; }
    return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
  }

  const CORR_FIELDS = [
    { field: "tempMean", label: "Mean temperature", unit: "°C" },
    { field: "tempMax", label: "High temperature", unit: "°C" },
    { field: "rainMm", label: "Rain", unit: "mm" },
    { field: "windMean", label: "Wind", unit: "m/s" },
    { field: "humidity", label: "Humidity", unit: "%" },
    { field: "clouds", label: "Cloud cover", unit: "%" },
    { field: "migration", label: "Migration, night before", unit: "log\u2081\u2080 birds" },
  ];

  // BirdCast counts birds flying overnight; pair night N with the morning of day N + 1
  function migrationByMorning() {
    const regions = regionsFor(state.site);
    return new Map(migration.filter((r) => regions.includes(r.region))
      .map((r) => [+d3.utcDay.offset(r.d, 1), Math.log10(r.birds + 1)]));
  }

  function corrPairs(field) {
    const dom = domain();
    let daily;
    if (state.corrActivity === "detections") {
      const sid = stationsFor(state.site)[0];
      daily = sid ? stationDaily.filter((r) => r.station === sid).map((r) => ({ d: r.d, y: r.detections })) : [];
    } else {
      daily = d3.rollups(feederDaily.filter((r) => r.site === state.site), (v) => d3.sum(v, (r) => r.visits), (r) => +r.d)
        .map(([t, y]) => ({ d: new Date(t), y }));
    }
    const weather = field === "migration" ? migrationByMorning()
      : new Map(weatherDaily.filter((r) => r.site === state.site).map((r) => [+r.d, r[field]]));
    return daily.filter(inRange(dom)).filter((r) => weather.get(+r.d) != null)
      .map((r) => ({ d: r.d, x: weather.get(+r.d), y: r.y }));
  }

  function describe(r) {
    const a = Math.abs(r);
    if (a < 0.1) return "no clear relationship";
    const strength = a < 0.3 ? "a weak" : a < 0.5 ? "a moderate" : "a strong";
    return `${strength} ${r > 0 ? "positive" : "negative"} relationship`;
  }

  function renderCorrelation() {
    const el = document.getElementById("corr-chart");
    const stat = document.getElementById("corr-stat");
    const note = document.getElementById("corr-note");
    const list = document.getElementById("corr-list");
    document.querySelectorAll("#corr-activity button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.activity === state.corrActivity)));
    const activityLabel = state.corrActivity === "detections" ? "PUC detections" : "Feeder visits";
    const activityText = state.corrActivity === "detections" ? "PUC detections" : "feeder visits";

    // One row per weather measure: r, a diverging bar (blue positive, red negative), click to plot
    const results = CORR_FIELDS.map((f) => { const pairs = corrPairs(f.field); return { ...f, pairs, r: pearson(pairs) }; });
    if (!results.some((x) => x.field === state.corrField)) state.corrField = "tempMean";
    list.replaceChildren();
    for (const res of results) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(res.field === state.corrField));
      btn.disabled = res.r == null;
      const name = document.createElement("span");
      name.className = "corr-name";
      name.textContent = res.label;
      const bar = document.createElement("span");
      bar.className = "corr-bar";
      if (res.r != null) {
        const fill = document.createElement("i");
        fill.style.width = `${Math.abs(res.r) * 50}%`;
        fill.style[res.r >= 0 ? "left" : "right"] = "50%";
        fill.style.background = css(res.r >= 0 ? "--s1" : "--s8");
        bar.append(fill);
      }
      const value = document.createElement("span");
      value.className = "corr-r";
      value.textContent = res.r == null ? "n/a" : d3.format("+.2f")(res.r).replace("-", "\u2212");
      btn.append(name, bar, value);
      btn.addEventListener("click", () => update({ corrField: res.field }));
      li.append(btn);
      list.append(li);
    }

    const sel = results.find((x) => x.field === state.corrField);
    stat.replaceChildren();
    note.textContent = "";
    if (!sel || sel.r == null) {
      empty(el, `Not enough days with both ${activityText} and weather in this range.`);
      return;
    }
    const strong = document.createElement("strong");
    strong.textContent = `r = ${d3.format(".2f")(sel.r).replace("-", "\u2212")}`;
    const desc = describe(sel.r);
    stat.append(strong, document.createTextNode(`${desc[0].toUpperCase()}${desc.slice(1)} between ${activityText} and ${sel.label.toLowerCase()}, across ${fmt(sel.pairs.length)} days.`));
    note.textContent = `Each dot is one day. The line is a least-squares fit with its 95% confidence band. ` +
      (sel.field === "migration"
        ? "Migration is BirdCast's count for the night before, on a log scale, and only covers migration seasons. "
        : `Weather is Open-Meteo for ${data.sites[state.site].name}. `) +
      "Bars: blue is positive, red is negative; longer is stronger.";

    // Square, so neither variable is visually stretched
    const size = Math.min(el.clientWidth || 520, 680);
    el.replaceChildren(Plot.plot({
      width: size,
      height: size,
      marginLeft: 52,
      marginRight: 20,
      style: { background: "transparent", color: css("--ink-2"), fontSize: "12px" },
      x: { label: `${sel.label} (${sel.unit})`, grid: true },
      y: { label: activityLabel, grid: true, tickFormat: "~s" },
      marks: [
        // clip keeps the confidence band inside the frame at extreme values
        Plot.linearRegressionY(sel.pairs, { x: "x", y: "y", stroke: css("--s2"), fill: css("--s2"), fillOpacity: 0.1,
          strokeWidth: 2, clip: true }),
        Plot.dot(sel.pairs, { x: "x", y: "y", r: 4, fill: css("--s1"), stroke: css("--surface"), strokeWidth: 2,
          tip: true, title: (p) => `${fmtDate(p.d)}\n${fmt(p.y)} ${activityText}\n${d3.format(".1f")(p.x)} ${sel.unit}` }),
      ],
    }));
  }

  // ---- migration -----------------------------------------------------------
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

  function weightedMedian(items, value, weight) {
    const sorted = items.filter((x) => value(x) != null).sort((a, b) => value(a) - value(b));
    const total = d3.sum(sorted, weight);
    let acc = 0;
    for (const x of sorted) { acc += weight(x); if (acc >= total / 2) return value(x); }
    return null;
  }

  function renderMigration() {
    const dom = domain();
    const studyRegions = Object.keys(data.birdcastRegions).filter((k) => data.birdcastRegions[k].site);
    const label = (code) => {
      const r = data.birdcastRegions[code];
      return `${r.name} (${data.sites[r.site] ? data.sites[r.site].name.split(",")[0] : ""} site)`;
    };
    const selected = regionsFor(state.site);

    const sitesEl = document.getElementById("migration-sites");
    const nights = migration.filter((r) => studyRegions.includes(r.region)).filter(inRange(dom))
      .map((r) => ({ ...r, facet: label(r.region) }));
    if (!nights.length) {
      empty(sitesEl, "No migration estimates in this range. BirdCast publishes during spring and fall migration.");
    } else {
      const facets = studyRegions.map(label);
      sitesEl.replaceChildren(Plot.plot(baseOptions(sitesEl, {
        width: Math.max(320, sitesEl.clientWidth),
        height: facets.length * 120 + 30,
        y: { label: "Birds", grid: true, tickFormat: fmtBirds, ticks: 3 },
        // One row per site; names sit inside each row rather than off the right edge
        fy: { domain: facets, axis: null, padding: 0.18 },
        marks: [
          Plot.text(facets, { fy: (d) => d, text: (d) => d, frameAnchor: "top-left", dx: 4, dy: -12,
            fill: css("--ink-2"), fontWeight: 600, fontSize: 12 }),
          Plot.rectY(nights, { x: "d", interval: "day", y: "birds", fy: "facet", inset: 0.5,
            fill: (r) => (selected.includes(r.region) ? css("--s1") : css("--other")),
            tip: true, title: (r) => `${fmt(r.birds)} birds\n${data.birdcastRegions[r.region].name}\nNight of ${fmtDate(r.d)}` }),
          Plot.ruleY([0], { stroke: css("--axis") }),
        ],
      })));
    }

    const flywayKey = data.siteFlyways[state.site];
    const flywayEl = document.getElementById("flyway-chart");
    const flyTitle = document.getElementById("flyway-title");
    const fly = flywayKey ? flywayNightly.filter((r) => r.flyway === flywayKey).filter(inRange(dom)) : [];
    flyTitle.textContent = flywayKey
      ? `Whole ${data.flyways[flywayKey]} flyway, birds per night (${fmt(d3.max(fly, (r) => r.regions) || 0)} counties)`
      : "Whole flyway, birds per night";
    if (!fly.length) empty(flywayEl, flywayKey ? "No flyway estimates in this range." : "No flyway data for this site.");
    else flywayEl.replaceChildren(Plot.plot(baseOptions(flywayEl, {
      width: Math.max(320, flywayEl.clientWidth),
      height: 150,
      y: { label: "Birds", grid: true, tickFormat: fmtBirds },
      marks: [
        Plot.rectY(fly, { x: "d", interval: "day", y: "birds", fill: css("--s1"), inset: 0.5,
          tip: true, title: (r) => `${fmt(r.birds)} birds across ${fmt(r.regions)} counties\nNight of ${fmtDate(r.d)}` }),
        Plot.ruleY([0], { stroke: css("--axis") }),
      ],
    })));

    const dirEl = document.getElementById("flight-direction");
    const tilesEl = document.getElementById("flight-tiles");
    const regionNights = migration.filter((r) => selected.includes(r.region)).filter(inRange(dom));
    document.getElementById("flight-title").textContent = selected.length
      ? `How they flew over ${data.birdcastRegions[selected[0]].name}`
      : "How they flew";
    tilesEl.replaceChildren();
    if (!regionNights.length) { empty(dirEl, "No migration estimates for this site in this range."); return; }
    const withDir = regionNights.filter((r) => COMPASS.includes(r.direction));
    const totalDir = d3.sum(withDir, (r) => r.birds);
    const share = COMPASS.map((dir) => ({ dir, share: totalDir ? d3.sum(withDir.filter((r) => r.direction === dir), (r) => r.birds) / totalDir : 0 }));
    dirEl.replaceChildren(Plot.plot({
      width: Math.min(dirEl.clientWidth || 480, 560), height: 200, marginLeft: 44,
      style: { background: "transparent", color: css("--ink-2"), fontSize: "12px" },
      x: { domain: COMPASS, label: "Heading", tickSize: 0 },
      y: { label: "Share of birds", tickFormat: "%", grid: true },
      marks: [
        Plot.barY(share, { x: "dir", y: "share", fill: css("--s1"), inset: 2, rx: 2,
          tip: true, title: (d) => `Heading ${d.dir}\n${d3.format(".0%")(d.share)} of birds` }),
        Plot.ruleY([0], { stroke: css("--axis") }),
      ],
    }));
    const biggest = regionNights.reduce((a, b) => (a.birds > b.birds ? a : b));
    const alt = weightedMedian(regionNights, (r) => r.altitudeFt, (r) => r.birds);
    const speed = weightedMedian(regionNights, (r) => r.speedMph, (r) => r.birds);
    tilesEl.append(
      tile("Birds over the county in this range", d3.format(".3~s")(d3.sum(regionNights, (r) => r.birds)).replace("G", "B"), `${fmt(regionNights.length)} nights with estimates`),
      tile("Biggest night", d3.format(".3~s")(biggest.birds).replace("G", "B"), `Night of ${fmtDate(biggest.d)}`),
      tile("Typical altitude", alt != null ? `${fmt(Math.round(alt))} ft` : "n/a", "Bird-weighted median"),
      tile("Typical speed", speed != null ? `${Math.round(speed)} mph` : "n/a", "Bird-weighted median"),
    );
  }

  // ---- species that track migration ---------------------------------------
  const MAX_TRACK = 12;

  function renderTrack() {
    const list = document.getElementById("track-list");
    const sub = document.getElementById("track-sub");
    const note = document.getElementById("track-note");
    const spEl = document.getElementById("track-species-chart");
    const migEl = document.getElementById("track-migration-chart");
    const titleEl = document.getElementById("track-species-title");
    list.replaceChildren();
    const sid = stationsFor(state.site)[0];
    const scores = sid ? migrationSpecies.filter((r) => r.station === sid).sort((a, b) => b.r - a.r).slice(0, MAX_TRACK) : [];
    if (!scores.length) {
      sub.textContent = "";
      note.textContent = "";
      titleEl.textContent = "";
      empty(spEl, "Needs a PUC station and BirdCast estimates for this site.");
      migEl.replaceChildren();
      return;
    }
    sub.textContent = `Species whose next-morning detections at the ${data.stations[sid].name} PUC rise and fall with ` +
      "the night's migration overhead, after removing the shared seasonal trend. Click a species to compare.";
    note.textContent = `r compares each day with its surrounding week for both series, over the ${fmt(scores[0].days)} mornings ` +
      "that have a BirdCast estimate. It is exploratory: with dozens of species, a few will score high by chance.";
    if (!scores.some((x) => data.speciesNames[x.species] === state.trackSpecies)) state.trackSpecies = data.speciesNames[scores[0].species];

    for (const res of scores) {
      const name = data.speciesNames[res.species];
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(name === state.trackSpecies));
      const label = document.createElement("span");
      label.className = "corr-name";
      label.textContent = name;
      const bar = document.createElement("span");
      bar.className = "corr-bar";
      const fill = document.createElement("i");
      fill.style.width = `${Math.abs(res.r) * 50}%`;
      fill.style[res.r >= 0 ? "left" : "right"] = "50%";
      fill.style.background = css(res.r >= 0 ? "--s1" : "--s8");
      bar.append(fill);
      const value = document.createElement("span");
      value.className = "corr-r";
      value.textContent = d3.format("+.2f")(res.r).replace("-", "\u2212");
      btn.append(label, bar, value);
      btn.addEventListener("click", () => update({ trackSpecies: name }));
      li.append(btn);
      list.append(li);
    }

    // Two aligned panels: the species by day, and the night before's migration on the same morning
    const dom = domain();
    titleEl.textContent = `${state.trackSpecies} detections per day`;
    const sp = speciesDaily.filter((r) => r.station === sid && r.name === state.trackSpecies).filter(inRange(dom));
    if (!sp.length) empty(spEl, "Not detected in this range.");
    else spEl.replaceChildren(Plot.plot(baseOptions(spEl, {
      width: Math.max(320, spEl.clientWidth),
      height: 150,
      y: { label: "Detections", grid: true, tickFormat: "~s" },
      marks: [
        Plot.rectY(sp, { x: "d", interval: "day", y: "detections", fill: css("--s3"), inset: 0.5,
          tip: true, title: (r) => `${fmt(r.detections)} detections\n${fmtDate(r.d)}` }),
        Plot.ruleY([0], { stroke: css("--axis") }),
      ],
    })));
    const regions = regionsFor(state.site);
    const mornings = migration.filter((r) => regions.includes(r.region))
      .map((r) => ({ ...r, morning: d3.utcDay.offset(r.d, 1) })).filter((r) => r.morning >= dom[0] && r.morning < dom[1]);
    if (!mornings.length) empty(migEl, "No migration estimates in this range.");
    else migEl.replaceChildren(Plot.plot(baseOptions(migEl, {
      width: Math.max(320, migEl.clientWidth),
      height: 150,
      y: { label: "Birds", grid: true, tickFormat: fmtBirds },
      marks: [
        Plot.rectY(mornings, { x: "morning", interval: "day", y: "birds", fill: css("--s1"), inset: 0.5,
          tip: true, title: (r) => `${fmt(r.birds)} birds overhead\nNight of ${fmtDate(r.d)}` }),
        Plot.ruleY([0], { stroke: css("--axis") }),
      ],
    })));
  }

  // ---- species heard -------------------------------------------------------
  const MAX_HEATMAP_SPECIES = 25;

  function renderSpecies() {
    const el = document.getElementById("species-chart");
    const sub = document.getElementById("species-sub");
    const newEl = document.getElementById("species-new");
    const tableEl = document.getElementById("species-table");
    newEl.replaceChildren();
    tableEl.replaceChildren();
    const sid = stationsFor(state.site)[0];
    if (!sid) { sub.textContent = ""; empty(el, "No PUC station at this site."); return; }

    const dom = domain();
    const all = speciesDaily.filter((r) => r.station === sid);
    const visible = all.filter(inRange(dom));
    if (!visible.length) { sub.textContent = ""; empty(el, "No detections in this range."); return; }

    const totals = d3.rollups(visible, (v) => ({ detections: d3.sum(v, (r) => r.detections), days: v.length,
      first: d3.min(v, (r) => r.d), last: d3.max(v, (r) => r.d) }), (r) => r.name)
      .sort((x, y) => d3.descending(x[1].detections, y[1].detections));
    const top = totals.slice(0, MAX_HEATMAP_SPECIES).map((t) => t[0]);
    const [a, b] = dom;
    const weekly = (b - a) / DAY > 120;
    const bin = weekly ? d3.utcWeek : d3.utcDay;
    const cells = d3.flatRollup(visible.filter((r) => top.includes(r.name)), (v) => d3.sum(v, (r) => r.detections),
      (r) => r.name, (r) => +bin.floor(r.d)).map(([name, t, n]) => ({ name, d: new Date(t), n }));

    const lastDay = d3.max(all, (r) => r.d);
    sub.textContent = `The ${top.length} most-detected species at the ${data.stations[sid].name} PUC in this range, ` +
      `${weekly ? "by week" : "by day"}. Stronger color means more detections. ${totals.length} species detected in all.`;

    // New arrivals: first ever detection in the last 14 days, once the station has a season of history
    const firstSeen = d3.rollup(all, (v) => d3.min(v, (r) => r.d), (r) => r.name);
    const history = (lastDay - d3.min(all, (r) => r.d)) / DAY;
    const arrivals = [...firstSeen].filter(([, d]) => history > 90 && d >= d3.utcDay.offset(lastDay, -13))
      .sort((x, y) => y[1] - x[1]);
    if (arrivals.length) {
      newEl.append(document.createTextNode("First detected in the last 14 days:"));
      for (const [name, d] of arrivals) {
        const chip = document.createElement("span");
        chip.className = "badge";
        chip.textContent = `${name}, ${d3.utcFormat("%b %-d")(d)}`;
        newEl.append(chip);
      }
    }

    const chart = Plot.plot(baseOptions(el, {
      height: top.length * 20 + 50,
      marginLeft: 170,
      y: { domain: top, label: null, tickSize: 0 },
      color: { type: "log", range: [css("--seq-lo"), css("--seq-hi")],
        label: weekly ? "Detections per week" : "Detections per day" },
      marks: [
        // barX: a time span per cell on a categorical (species) axis
        Plot.barX(cells, {
          x1: "d", x2: (c) => bin.offset(c.d, 1), y: "name", fill: "n", inset: 0.5,
          tip: true, title: (c) => `${c.name}\n${fmt(c.n)} detections\n${weekly ? "Week of " : ""}${fmtDate(c.d)}`,
        }),
      ],
    }));
    el.replaceChildren(withPhases(...[chart.legend("color"), phaseStrip(el, 170), chart].filter(Boolean)));

    tableEl.append(table(["Species", "Detections", "Days detected", "First in range", "Last in range"],
      totals.map(([name, t]) => [name, fmt(t.detections), fmt(t.days), fmtDate(t.first), fmtDate(t.last)]),
      [false, true, true, false, false]));
  }

  // ---- render --------------------------------------------------------------
  function render() {
    rangeButtons.forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.days === state.days)));
    renderHealth();
    renderPhaseKey();
    renderTiles();
    renderFeeder();
    renderHours();
    renderAcoustic();
    renderWeather();
    renderMigration();
    renderCorrelation();
    renderSpecies();
    renderTrack();
    if (window.BYAnalyses) window.BYAnalyses.render();
  }

  // Shared with assets/analyses.js, which draws the study analyses below
  window.BY = {
    state, data, phases, today, DAY, parse, css, fmt, fmtDate, fmtBirds, domain, inRange, width, asideOn,
    baseOptions, empty, legend, table, tile, pearson, update, stationsFor,
    phaseSpans, phaseShade, phaseSwatch, phaseLegendItems, phaseMarks, phaseStrip, withPhases, PHASE_SHADES,
  };

  document.getElementById("generated").textContent = new Date(data.generated).toLocaleString();
  render();
})();
