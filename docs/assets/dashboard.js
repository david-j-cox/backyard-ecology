// Interactive dashboard for docs/index.html. Reads docs/data/dashboard.json,
// written daily by scripts_notebooks/export_dashboard_data.py.
(async function () {
  "use strict";

  const DAY = 864e5;
  const MAX_SPECIES = 8; // categorical slots; the rest fold into "Other"
  const STALE_LATE = 3; // days behind before a source is flagged
  const STALE_BAD = 8;

  const state = { site: "jacksonville_fl_32259", days: 90, phases: false };
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
  const parse = d3.utcParse("%Y-%m-%d");
  for (const set of [feederDaily, feederHourly, stationDaily, countyDaily]) for (const r of set) r.d = parse(r.date);
  for (const r of migration) r.d = parse(r.night);
  for (const r of phases) r.d = parse(r.start);
  for (const set of [weatherDaily, sensorDaily]) for (const r of set) r.d = parse(r.date);

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = d3.format(",");
  const fmtDate = d3.utcFormat("%b %-d, %Y");
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
  const corrActivity = document.getElementById("corr-activity");
  const corrWeather = document.getElementById("corr-weather");
  for (const sel of [corrActivity, corrWeather]) sel.addEventListener("change", renderCorrelation);

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
  const width = (el) => Math.max(320, el.clientWidth);

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
      x: { type: "utc", domain: domain(), label: null },
      ...extra,
    };
  }

  function phaseMarks() {
    if (!state.phases) return [];
    const ph = phases.filter((p) => p.site === state.site).filter(inRange(domain()));
    return [
      Plot.ruleX(ph, { x: "d", stroke: css("--muted"), strokeDasharray: "3,3", strokeWidth: 1 }),
      Plot.text(ph, { x: "d", frameAnchor: "top", text: "description", dx: 4, textAnchor: "start",
        fill: css("--ink-2"), fontSize: 11, lineWidth: 10 }),
    ];
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
        Plot.rectY(daily, Plot.stackY({
          x: "d", interval: "day", y: "visits", fill: "group", order: groups,
          inset: 0.5, tip: { format: { x: (d) => fmtDate(d), fill: true, y: true } },
          title: (d) => `${d.group}\n${fmt(d.visits)} visits\n${fmtDate(d.d)}`,
        })),
        Plot.ruleY([0], { stroke: css("--axis") }),
        ...phaseMarks(),
      ],
    }));
    el.replaceChildren(legend(groups.map((g) => ({ label: g, color: color(g) }))), chart);
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
    const visible = feederHourly.filter((r) => r.site === state.site).filter(inRange(domain()));
    if (!visible.length) { empty(el, "No feeder data in this range."); return; }
    el.replaceChildren(Plot.plot(baseOptions(el, {
      height: 280,
      y: { domain: [24, 0], label: "Hour of day", ticks: [0, 6, 12, 18, 24], tickFormat: (h) => `${String(h).padStart(2, "0")}:00` },
      color: { type: "linear", range: [css("--seq-lo"), css("--seq-hi")], legend: true, label: "Visits in the hour" },
      marks: [
        Plot.rect(visible, {
          x: "d", interval: "day", y1: "hour", y2: (r) => r.hour + 1, fill: "visits", inset: 0.25,
          tip: true, title: (r) => `${fmt(r.visits)} visits\n${fmtDate(r.d)}, ${String(r.hour).padStart(2, "0")}:00`,
        }),
        ...phaseMarks(),
      ],
    })));
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
        ...(zero ? [Plot.ruleY([0], { stroke: css("--axis") })] : []),
        ...under,
        // Gaps in the data stay gaps rather than being bridged by a line
        Plot.lineY(all, { x: "d", y: "value", z: "label", stroke: "label", strokeWidth: 2, curve: "linear"}),
        Plot.dot(all, Plot.pointerX({ x: "d", y: "value", fill: "label", r: 4, stroke: css("--surface"), strokeWidth: 2 })),
        Plot.ruleX(all, Plot.pointerX({ x: "d", stroke: css("--muted"), strokeWidth: 1 })),
        Plot.tip(all, Plot.pointerX({ x: "d", y: "value",
          title: (r) => `${fmt(r.value)} ${yLabel.toLowerCase()}\n${r.label}\n${fmtDate(r.d)}` })),
        ...phaseMarks(),
      ],
    }));
    el.replaceChildren(...(multi ? [legend(series.map((s) => ({ label: s.label, color: s.color })), "line")] : []), chart);
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
      migEl.replaceChildren(Plot.plot(baseOptions(migEl, {
        height: 170,
        y: { label: "Birds", grid: true, tickFormat: "~s" },
        marks: [
          Plot.rectY(nights, { x: "d", interval: "day", y: "birds", fill: css("--s1"), inset: 0.5, rx2: 2,
            tip: true, title: (r) => `${fmt(r.birds)} birds\n${data.birdcastRegions[r.region].name}\nNight of ${fmtDate(r.d)}` }),
          Plot.ruleY([0], { stroke: css("--axis") }),
          ...phaseMarks(),
        ],
      })));
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
    else rainEl.replaceChildren(Plot.plot(baseOptions(rainEl, {
      height: 140,
      y: { label: "mm", grid: true },
      marks: [
        Plot.rectY(rain, { x: "d", interval: "day", y: "rainMm", fill: css("--s1"), inset: 0.5,
          tip: true, title: (r) => `${d3.format(".1f")(r.rainMm)} mm\n${fmtDate(r.d)}` }),
        Plot.ruleY([0], { stroke: css("--axis") }),
        ...phaseMarks(),
      ],
    })));

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

  function renderCorrelation() {
    const el = document.getElementById("corr-chart");
    const stat = document.getElementById("corr-stat");
    const dom = domain();
    const activity = corrActivity.value;
    const field = corrWeather.value;
    const fieldLabel = corrWeather.selectedOptions[0].textContent;
    const activityLabel = corrActivity.selectedOptions[0].textContent;

    let daily;
    if (activity === "detections") {
      const sid = stationsFor(state.site)[0];
      daily = sid ? stationDaily.filter((r) => r.station === sid).map((r) => ({ d: r.d, y: r.detections })) : [];
    } else {
      daily = d3.rollups(feederDaily.filter((r) => r.site === state.site), (v) => d3.sum(v, (r) => r.visits), (r) => +r.d)
        .map(([t, y]) => ({ d: new Date(t), y }));
    }
    const weather = new Map(weatherDaily.filter((r) => r.site === state.site).map((r) => [+r.d, r[field]]));
    const pairs = daily.filter(inRange(dom)).filter((r) => weather.get(+r.d) != null)
      .map((r) => ({ d: r.d, x: weather.get(+r.d), y: r.y }));

    const r = pearson(pairs);
    stat.replaceChildren();
    if (r == null) {
      stat.textContent = "";
      empty(el, `Not enough days with both ${activityLabel.toLowerCase()} and weather in this range.`);
      return;
    }
    const strength = Math.abs(r) < 0.1 ? "no clear relationship" : Math.abs(r) < 0.3 ? "a weak" : Math.abs(r) < 0.5 ? "a moderate" : "a strong";
    const direction = Math.abs(r) < 0.1 ? "" : r > 0 ? " positive relationship" : " negative relationship";
    const strong = document.createElement("strong");
    strong.textContent = `r = ${d3.format(".2f")(r)}`;
    stat.append(strong, document.createTextNode(`${strength}${direction}, across ${fmt(pairs.length)} days`));

    const unit = { tempMean: "°C", tempMax: "°C", rainMm: "mm", windMean: "m/s", humidity: "%", clouds: "%" }[field];
    el.replaceChildren(Plot.plot({
      width: width(el),
      height: 300,
      marginLeft: 52,
      style: { background: "transparent", color: css("--ink-2"), fontSize: "12px" },
      x: { label: `${fieldLabel} (${unit})`, grid: true },
      y: { label: activityLabel, grid: true, tickFormat: "~s" },
      marks: [
        Plot.linearRegressionY(pairs, { x: "x", y: "y", stroke: css("--s2"), fill: css("--s2"), fillOpacity: 0.1, strokeWidth: 2 }),
        Plot.dot(pairs, { x: "x", y: "y", r: 4, fill: css("--s1"), stroke: css("--surface"), strokeWidth: 2,
          tip: true, title: (p) => `${fmtDate(p.d)}\n${fmt(p.y)} ${activityLabel.toLowerCase()}\n${d3.format(".1f")(p.x)} ${unit}` }),
      ],
    }));
  }

  // ---- heard recently ------------------------------------------------------
  function renderSpecies() {
    const el = document.getElementById("species-table");
    const sub = document.getElementById("species-sub");
    const stations = stationsFor(state.site);
    if (!stations.length) { sub.textContent = ""; empty(el, "No PUC station at this site."); return; }
    const sid = stations[0];
    const lastDay = d3.max(stationDaily.filter((r) => r.station === sid), (r) => r.d);
    const recent = stationSpecies.filter((r) => r.station === sid && r.last30 > 0)
      .sort((a, b) => d3.descending(a.last7, b.last7) || d3.descending(a.last30, b.last30));
    sub.textContent = `${data.stations[sid].name} PUC detections in the 7 and 30 days through ${fmtDate(lastDay)}. "New" marks species first detected in the last 14 days.`;
    const newSince = d3.utcDay.offset(lastDay, -13);
    const body = recent.map((r) => {
      const name = document.createElement("span");
      name.textContent = r.species;
      if (parse(r.first) >= newSince) {
        const b = document.createElement("span");
        b.className = "badge";
        b.textContent = "New";
        name.append(b);
      }
      return [name, fmt(r.last7), fmt(r.last30), fmtDate(parse(r.first))];
    });
    el.replaceChildren(table(["Species", "Last 7 days", "Last 30 days", "First detected"], body, [false, true, true, false]));
  }

  // ---- render --------------------------------------------------------------
  function render() {
    rangeButtons.forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.days === state.days)));
    renderHealth();
    renderTiles();
    renderFeeder();
    renderHours();
    renderAcoustic();
    renderWeather();
    renderCorrelation();
    renderSpecies();
  }

  document.getElementById("generated").textContent = new Date(data.generated).toLocaleString();
  render();
})();
