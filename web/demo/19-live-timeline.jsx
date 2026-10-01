/* ============================ Timeline · live (window.__TIMELINE__) ============================ */
// How the AI-catastrophe forecast MOVES between elicitation dates: one dot
// per model per date, the ensemble median as the ink line, at the horizon
// the picker selects (2030 to open). The lead panel of the Forecasts tab
// since 2026-09-08 (Nick: the series is the first thing a visitor sees, not
// a link to it) -- it was a standalone timeline.html from 2026-08-11 until
// then. One question since 2026-09-09 (Nick): the risk-category rail went,
// so the chart takes the panel's full width, as Graph 2's does; the blob
// (redlines/views/timeline.py, which reads the run log from
// redlines.runlog.SERIES_START on: one call per model per run, no re-run
// bands) still carries every bottom-line question, and this file reads the
// one row, catastrophe:ai.
const TL = (typeof window !== "undefined" && window.__TIMELINE__) || null;

// Formatters, tl-prefixed: this page is one script, and Graph 1 (cFmtBig,
// cFmtLoss) and the mock (niceMax, TimeSeriesChart) already own the plain names.
const tlFmt = v => (v == null ? "—" : v < 10 ? v.toFixed(2) + "%" : v.toFixed(1) + "%");
const tlFmtD = d => (d == null ? "—" : (d > 0 ? "+" : d < 0 ? "−" : "±") + Math.abs(d).toFixed(2) + " pp");
// Death-equivalents for the expected-loss rows: 2.44M, $24.4T.
const tlFmtBig = (v, prefix) => {
  if (v == null) return "—";
  const p = prefix || "";
  const units = [[1e15, "Q"], [1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "k"]];
  for (const [cut, suf] of units) if (Math.abs(v) >= cut) return p + Number((v / cut).toPrecision(3)) + suf;
  return p + Number(v.toPrecision(3));
};
const tlFmtLoss = v => (v == null ? "—" : tlFmtBig(v) + " (" + tlFmtBig(v * ((TL && TL.usdPerDeath) || 2.2e6), "$") + ")");
const tlFmtRatio = r => (r == null || !isFinite(r) ? "—" : "×" + (r >= 10 ? r.toFixed(0) : r.toFixed(2)));
// One formatter per row kind.
const tlFmtFor = q => (q && q.value_kind === "loss" ? tlFmtBig : tlFmt);

/* ---------------- time-series chart ---------------- */
// One dot per model per date -- no connecting lines since 2026-08-27: like
// Graph 1, a model's forecasts on two dates are two answers, not a
// trajectory -- and the ensemble median as the ink line, for the ONE horizon
// the panel's picker selects (Nick, 2026-09-09: a horizon picker, Graph 2's,
// in place of the six shaded lines of the day before; with one line the
// model dots always draw). Expected-loss rows plot death-equivalents on the
// shared severity axis (rung ticks, dollars beneath, Extinction marked), log
// only. Any per-date interval the blob carries (a date with more than one
// draw per model) is drawn as a grey bar behind the median; on the current
// one-call-per-run series there is none.
function TimelineChart({ q, snapshots, horizon, scale }) {
  const loss = q.value_kind === "loss";
  // Laid out in the width the panel gives it (web/shared/responsive.jsx);
  // under 620px the right-margin label goes — the tooltip carries it.
  const box = React.useRef(null);
  const cw = useContainerWidth(box, 880);
  const narrow = cw < 620;
  const W = Math.max(320, cw), H = narrow ? 340 : 400;
  const pad = { l: loss ? 74 : 54, r: narrow ? 16 : 128, t: 18, b: 44 };
  const n = snapshots.length;
  // Runs sit where they fall in calendar time -- a two-day gap is a third of
  // a six-day span -- never one slot per run. Labels that would collide give
  // way (the first and the latest always show); the hover reaches every run.
  const days = snapshots.map(s => Date.UTC(+s.date.slice(0, 4), +s.date.slice(5, 7) - 1, +s.date.slice(8, 10)) / 864e5);
  // Give the first chart a fixed year-to-date frame: the recent readings sit
  // in the left portion of the axis, making their small movement legible while
  // leaving room for subsequent assessments through December 31.
  const yearEnd = days.length ? Date.UTC(+snapshots[0].date.slice(0, 4), 11, 31) / 864e5 : 0;
  const axisEnd = n > 1 ? Math.max(days[n - 1], yearEnd) : yearEnd;
  const span = axisEnd > days[0] ? axisEnd - days[0] : 0;
  const xDay = day => (span === 0 ? (pad.l + W - pad.r) / 2 : pad.l + ((day - days[0]) / span) * (W - pad.l - pad.r));
  const x = i => xDay(days[i]);
  const xs = snapshots.map((_, i) => x(i));
  const futureTicks = [];
  if (n > 0 && axisEnd > days[n - 1]) {
    const last = new Date(days[n - 1] * 864e5);
    const year = last.getUTCFullYear();
    for (let month = last.getUTCMonth() + 1; month < 12; month++) {
      const day = Date.UTC(year, month, 1) / 864e5;
      if (day <= axisEnd) futureTicks.push({ day, label: new Date(day * 864e5).toLocaleString("en-US", { month: "short", timeZone: "UTC" }) + " 1" });
    }
  }
  const labelGap = narrow ? 34 : 46;
  const labelled = new Set(n ? [n - 1] : []);
  for (let i = 0, lastX = -Infinity; i < n - 1; i++) {
    if (xs[i] - lastX >= labelGap && xs[n - 1] - xs[i] >= labelGap) { labelled.add(i); lastX = xs[i]; }
  }
  const replicated = snapshots.some(s => s.draws > 1);

  const h = horizon;
  const med = q.median[h] || [];
  const fmtV = tlFmtFor(q);
  const [hv, setHv] = useState(null);                 // hovered snapshot index
  const series = q.series.map(s => ({ ...s, vals: s.ps[h] || [], cis: (s.ci || {})[h] || [] }));
  const ci = (q.ci || {})[h] || [];

  let y, yticks, tickText, tickSub;
  if (loss) {
    const LO = (TL.severityAxis || {}).lo || 800, HI = (TL.severityAxis || {}).hi || 1.4e10;
    y = v => pad.t + (1 - Math.min(1, Math.max(0,
      (Math.log10(Math.max(v, LO)) - Math.log10(LO)) / (Math.log10(HI) - Math.log10(LO))))) * (H - pad.t - pad.b);
    const rungs = (TL.rungs || []).filter(r => r.deaths >= LO && r.deaths <= HI);
    yticks = rungs.map(r => r.deaths);
    tickText = t => (rungs.find(r => r.deaths === t) || {}).short;
    tickSub = t => tlFmtBig(t * (TL.usdPerDeath || 2.2e6), "$");
  } else if (scale === "linear") {
    // Linear (the default since 2026-09-08), topped just above the largest
    // value on the line or any model dot at this horizon, as Graph 1's
    // linear axis is.
    const top = linearTop([
      ...med,
      ...series.flatMap(s => s.vals),
      ...ci.flatMap(c => c || []),
    ]);
    y = v => pad.t + (1 - Math.min(1, Math.max(0, v / top))) * (H - pad.t - pad.b);
    yticks = linearTicks(top);
    tickText = t => fmtTick(t) + "%";
    tickSub = () => null;
  } else {
    // Log axis, 0.01-100%, the same as Graph 1's: the view for the tails.
    const LO = 0.01, HI = 100;
    y = v => pad.t + (1 - Math.min(1, Math.max(0,
      (Math.log10(Math.max(v, LO)) - Math.log10(LO)) / (Math.log10(HI) - Math.log10(LO))))) * (H - pad.t - pad.b);
    yticks = [0.01, 0.1, 1, 10, 100];
    tickText = t => fmtTick(t) + "%";
    tickSub = () => null;
  }
  const marks = loss ? (TL.marks || []) : [];

  // Draw the median only across consecutive non-null points.
  const segs = vals => {
    const out = [];
    let cur = [];
    vals.forEach((v, i) => {
      if (v == null) { if (cur.length) out.push(cur); cur = []; }
      else cur.push({ i, v });
    });
    if (cur.length) out.push(cur);
    return out;
  };
  const path = pts => pts.map((p, k) => (k === 0 ? "M" : "L") + x(p.i).toFixed(1) + " " + y(p.v).toFixed(1)).join(" ");
  const whisker = (i, lo, hi, color, width, opacity, cap) => (
    <g stroke={color} strokeWidth={width} opacity={opacity} strokeLinecap="round">
      <line x1={x(i)} x2={x(i)} y1={y(lo)} y2={y(hi)} />
      <line x1={x(i) - cap} x2={x(i) + cap} y1={y(lo)} y2={y(lo)} />
      <line x1={x(i) - cap} x2={x(i) + cap} y1={y(hi)} y2={y(hi)} />
    </g>
  );
  const li = med.map((v, i) => (v != null ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
  // Right-margin label: the latest median, kept above the date labels.
  const endLabel = li >= 0 ? { v: med[li], y: Math.min(y(med[li]), H - pad.b - 2), xi: li } : null;
  const range = c => fmtV(c[0]) + "–" + fmtV(c[1]);
  const anchor = i => (narrow && n > 1 ? (i === 0 ? "start" : i === n - 1 ? "end" : "middle") : "middle");

  // The nearest run by x.
  const locate = e => {
    const svg = e.currentTarget.ownerSVGElement || e.currentTarget;
    const r = svg.getBoundingClientRect();
    if (!r.width || !r.height || !n) return null;
    const px = (e.clientX - r.left) * W / r.width;
    let i = 0;
    for (let k = 1; k < n; k++) if (Math.abs(xs[k] - px) < Math.abs(xs[i] - px)) i = k;
    return i;
  };

  return (
    <div ref={box} style={{ position: "relative", minWidth: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} onMouseLeave={() => setHv(null)}>
        {yticks.map((t, i) => (
          <g key={i}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--line-soft)" />
            <text x={pad.l - 9} y={y(t) + (loss ? 0 : 4)} textAnchor="end" fontSize="11" fill="var(--ink-faint)" className="mono">{tickText(t)}</text>
            {tickSub(t) && <text x={pad.l - 9} y={y(t) + 11} textAnchor="end" fontSize="9.5" fill="var(--ink-faint)" className="mono">{tickSub(t)}</text>}
          </g>
        ))}
        {marks.map(m => (
          <g key={m.label}>
            <line x1={pad.l} x2={W - pad.r} y1={y(m.v)} y2={y(m.v)} stroke="var(--ink-faint)" strokeWidth="1" strokeDasharray="4 3" opacity="0.7" />
            <text x={pad.l - 9} y={y(m.v) + 4} textAnchor="end" fontSize="10" fill="var(--ink-soft)">{m.label}</text>
          </g>
        ))}

        {snapshots.map((s, i) => (
          <g key={s.date}>
            <line x1={x(i)} x2={x(i)} y1={pad.t} y2={H - pad.b} stroke="var(--line)" strokeWidth="1" opacity={labelled.has(i) ? 0.55 : 0.3} />
            {labelled.has(i) && <text x={x(i)} y={H - (replicated ? 24 : 18)} textAnchor={anchor(i)} fontSize="12" fill="var(--ink-soft)" fontWeight="600">{s.label}</text>}
            {replicated && labelled.has(i) && (
              <text x={x(i)} y={H - 10} textAnchor={anchor(i)} fontSize="10" fill="var(--ink-faint)" className="mono">
                {s.draws} draw{s.draws === 1 ? "" : "s"}/model
              </text>
            )}
          </g>
        ))}
        {futureTicks.map(t => (
          <g key={t.day}>
            <line x1={xDay(t.day)} x2={xDay(t.day)} y1={pad.t} y2={H - pad.b} stroke="var(--line)" strokeWidth="1" strokeDasharray="3 4" opacity="0.55" />
            <text x={xDay(t.day)} y={H - (replicated ? 24 : 18)} textAnchor="middle" fontSize="12" fill="var(--ink-faint)" fontWeight="600">{t.label}</text>
          </g>
        ))}
        {axisEnd > days[n - 1] && <text x={W - pad.r} y={H - (replicated ? 24 : 18)} textAnchor="end"
          fontSize="12" fill="var(--ink-faint)" fontWeight="600">Dec 31</text>}
        {/* An interval of the median, one grey bar per date, under every mark. */}
        {ci.map((c, i) => c && c[1] > c[0] ? (
          <rect key={"ci" + i} x={x(i) - 9} width={18} y={y(c[1])} height={Math.max(1.5, y(c[0]) - y(c[1]))}
            rx="2" fill="var(--ink-faint)" opacity="0.22" />
        ) : null)}

        {/* The median line, with a halo, and its marks. */}
        {segs(med).map((pts, k) => pts.length > 1 ? (
          <g key={k}>
            <path d={path(pts)} fill="none" stroke="var(--ink)" strokeWidth="9" strokeOpacity="0.1" strokeLinejoin="round" strokeLinecap="round" />
            <path d={path(pts)} fill="none" stroke="var(--ink)" strokeWidth="3.2" strokeLinejoin="round" strokeLinecap="round" />
          </g>
        ) : null)}
        {med.map((v, i) => v == null ? null : (
          <circle key={"m" + i} cx={x(i)} cy={y(v)} r="5" fill="var(--panel)" stroke="var(--ink)" strokeWidth="2.6" />
        ))}

        {/* Every model, every date: one line, so the dots always draw. */}
        {series.map(s => (
          <g key={s.label}>
            {s.cis.map((c, i) => c ? <g key={"w" + i}>{whisker(i, c[0], c[1], s.color, 1.3, 0.55, 3.5)}</g> : null)}
            {s.vals.map((v, i) => v == null ? null : (
              <circle key={"d" + i} cx={x(i)} cy={y(v)} r="4" fill={s.color} stroke="var(--panel)" strokeWidth="1.5" />
            ))}
          </g>
        ))}

        {!narrow && endLabel && (
          <text x={x(endLabel.xi) + 10} y={endLabel.y + 4} fontSize="11.5" fill="var(--ink)" className="mono" fontWeight="700">
            by {h} {fmtV(endLabel.v)}
          </text>
        )}

        {hv != null && <line x1={x(hv)} x2={x(hv)} y1={pad.t} y2={H - pad.b} stroke="var(--ink-faint)" strokeDasharray="3 3" opacity="0.6" />}
        {hv != null && med[hv] != null && (
          <circle cx={x(hv)} cy={y(med[hv])} r="8" fill="none" stroke="var(--ink)" strokeOpacity="0.35" strokeWidth="2" />
        )}
        <rect x={pad.l} y={pad.t} width={Math.max(1, W - pad.l - pad.r)} height={H - pad.t - pad.b} fill="transparent"
          style={{ cursor: "crosshair" }}
          onMouseMove={e => setHv(locate(e))} />
      </svg>

      {hv != null && (
        <div style={{ position: "absolute", top: 8, left: `${(x(hv) / W) * 100}%`,
          transform: x(hv) > W * 0.6 ? "translateX(calc(-100% - 8px))" : "translateX(10px)",
          background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, padding: "9px 11px",
          boxShadow: "var(--shadow)", pointerEvents: "none", minWidth: 210, maxWidth: "calc(100% - 16px)" }}>
          <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 6 }}>
            {snapshots[hv].date} · <span style={{ color: "var(--ink)", fontWeight: 600 }}>by {h}</span>
            {snapshots[hv].draws > 1 ? ` · ${snapshots[hv].draws} draws per model · point = mean, range = 95% CI` : ""}{loss ? " · death-equivalents" : ""}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 14, fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>
            <span>Ensemble median</span>
            <span className="mono">
              {fmtV(med[hv])}
              {ci[hv] && <span style={{ color: "var(--ink-faint)", fontWeight: 400 }}> {range(ci[hv])}</span>}
            </span>
          </div>
          {series.filter(s => s.vals[hv] != null).map(s => (
            <div key={s.label} style={{ display: "flex", justifyContent: "space-between", gap: 14, fontSize: 12 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 9, height: 9, borderRadius: 2, background: s.color }}></span>{s.label}
                {s.legacy && <span style={{ color: "var(--ink-faint)" }}>· earlier panel</span>}
              </span>
              <span className="mono">
                {fmtV(s.vals[hv])}
                {s.cis[hv] && <span style={{ color: "var(--ink-faint)" }}> {range(s.cis[hv])}</span>}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- table view ---------------- */
function TimelineTable({ q, horizon, snapshots }) {
  const loss = q.value_kind === "loss";
  const fmtV = tlFmtFor(q);
  const ci = (q.ci || {})[horizon] || [];
  const rows = [
    { label: "Ensemble median", color: "var(--ink)", vals: q.median[horizon] || [],
      ranges: ci.map(c => c || null), bold: true },
    ...q.series.map(s => ({
      label: s.label, color: s.color, vals: s.ps[horizon] || [],
      // The model's own interval, only where it had more than one draw that day.
      ranges: ((s.ci || {})[horizon] || []).map(c => c || null),
    })),
  ];
  // Change first -> last: percentage points for a probability, a ratio for a loss.
  const change = v => {
    const a = v[0], b = v[v.length - 1];
    if (a == null || b == null || v.length < 2) return "—";
    return loss ? tlFmtRatio(b / a) : tlFmtD(b - a);
  };
  return (
    <div style={{ overflowX: "auto" }}>
    <table className="tv">
      <thead>
        <tr>
          <th>Forecaster</th>
          {snapshots.map(s => <th key={s.date}>{s.label}</th>)}
          <th>Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.label}>
            <td style={{ fontWeight: r.bold ? 600 : 400 }}>
              <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: r.color, marginRight: 7 }}></span>
              {r.label}
            </td>
            {r.vals.map((v, i) => (
              <td key={i} className="mono">
                {fmtV(v)}
                {r.ranges[i] && <div style={{ fontSize: 10.5, color: "var(--ink-faint)" }}>{fmtV(r.ranges[i][0])}–{fmtV(r.ranges[i][1])}</div>}
              </td>
            ))}
            <td className="mono" style={{ color: "var(--ink-soft)" }}>{change(r.vals)}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

/* ---------------- the panel ---------------- */
// The AI-catastrophe row alone (Nick, 2026-09-09): the headline is one
// number moving, not a rail of seven. The other bottom-line questions stay
// in the blob and in the data bank.
const TL_HEADLINE = "catastrophe:ai";

// The same panel, one row each: the headline (catastrophe:ai) and, since
// 2026-09-10 (Nick), the expected-loss row loss:ai as "Statistical lives
// lost" -- the eight ladder rungs folded to a floor on E[loss], in
// death-equivalents, on the shared severity axis (see the LossPanel below
// and redlines/views/timeline.py::_loss_row).
function TimelinePanel(props = {}) {
  const q = TL && TL.questions.find(q => q.id === (props.qid || TL_HEADLINE));
  if (!q || !q.horizons.length || !TL.snapshots.length) return <ForecastUnavailable title={props.title || "Probability of an AI catastrophe"} info={TL && TL.instrumentInfo} />;
  return <TimelinePanelCurrent {...props} />;
}
function TimelinePanelCurrent({ qid = TL_HEADLINE, title = "Probability of an AI catastrophe", sub = "Forecasts over time" } = {}) {
  const snapshots = TL.snapshots;
  const q = TL.questions.find(x => x.id === qid) || TL.questions[0];
  // The horizon picker, Graph 2's toggle: opens on 2030 like every other
  // horizon toggle (Nick, 2026-08-27), and is what the line, the dots, the
  // numbers below and the table all read.
  const [hz, setHz] = useState(q.horizons.includes("2030") ? "2030" : q.horizons[q.horizons.length - 1]);
  const [showTable, setShowTable] = useState(false);
  const [scale, setScale] = useState("linear");     // Graph 1's switch, the same default

  const med = q.median[hz] || [];
  const first = med.find(v => v != null);
  // Series can be ragged (a question not re-asked in the newest run), so
  // every "latest" statistic keys off the most recent snapshot in which THIS
  // question has data, not the most recent snapshot -- otherwise a stale
  // question reads "0 of 4 reporting" next to a live median.
  const li = med.map((v, i) => (v != null ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
  const latest = li >= 0 ? med[li] : null;
  const loss = q.value_kind === "loss";
  const fmtV = loss ? tlFmtLoss : tlFmt;
  // Change since the first snapshot: pp for a probability, a ratio for a loss.
  const delta = first != null && latest != null && med.length > 1 ? (loss ? latest / first : latest - first) : null;
  const up = delta != null && (loss ? delta > 1 : delta > 0), flat = delta == null || (loss ? delta === 1 : delta === 0);
  // Flagged when this question was not re-asked in the newest run.
  const staleAt = li >= 0 && li < snapshots.length - 1 ? snapshots[li].label : null;

  // The current panel and the departed: a model that left the panel keeps
  // its points, in gray, and the legend and tooltip say who it was.
  const currentModels = TL.models.filter(m => !m.legacy);
  const legacyModels = TL.models.filter(m => m.legacy);

  // Who declined, per date, for the chip under the question -- Graph 1's
  // chip is per model; here a model can decline on one date and not another.
  const declined = Object.entries(q.declined).filter(([, ls]) => ls.length);

  return (
    <Panel style={{ padding: 24, marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div>
          {/* Headline and subhead (Nick, 2026-09-09), no eyebrow: the number
              first, the series second. */}
          <h2 style={{ fontSize: 22, marginTop: 0, marginBottom: 4 }}>{title}</h2>
          <p style={{ color: "var(--ink-soft)", fontSize: 13.5, margin: 0 }}>{sub}</p>
        </div>
        <Toggle options={q.horizons.map(h => ({ key: h, label: "by " + h }))} value={hz} onChange={setHz} />
      </div>

      {/* No rail: the chart takes the panel's full width, as Graph 2's does. */}
      <div style={{ marginTop: 16, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 6, alignItems: "center" }}>
          {currentModels.map(m => <LegendDot key={m.label} color={m.color} label={m.label} />)}
          {legacyModels.length > 0 && (
            <LegendDot color={legacyModels[0].color} label="Earlier panel members (hover for names)"
              title={legacyModels.map(m => m.label).join(", ")} />
          )}
          <LegendDot color="var(--ink)" label="Ensemble median" />
          {(q.ci && (q.ci[hz] || []).some(Boolean)) && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--ink-soft)" }}>
              <span style={{ width: 10, height: 14, borderRadius: 2, background: "var(--ink-faint)", opacity: 0.35, display: "inline-block" }}></span>
              95% CI
            </span>
          )}
          {/* The scale switch at the legend row's right end, where Graph 2 keeps its own. */}
          {!loss && <ScaleToggle value={scale} onChange={setScale} style={{ marginLeft: "auto" }} />}
        </div>

        <TimelineChart q={q} snapshots={snapshots} horizon={hz} scale={scale} />
        {q.display_note && <p style={{ fontSize: 12, color: "var(--ink-soft)", margin: "8px 0 0" }}>{q.display_note}</p>}
        <InstrumentNotice info={TL.instrumentInfo} />
        {loss && <>
          <CountingWindow info={TL.instrumentInfo} horizon={hz} />
          <p style={{ fontSize: 12, color: "var(--ink-soft)" }}>Each run starts its incident window on its own elicitation date. A fixed-year forecast therefore covers a changing interval; movement is not solely a change of belief about the same event.</p>
        </>}

        {/* The question, in full, below the chart -- Graph 1's block, shared. */}
        <QuestionBox q={q} />
        {declined.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--warn-ink)", background: "var(--warn-bg)", border: "1px solid var(--warn-line)", borderRadius: 8, padding: "7px 11px", display: "inline-block" }}>
            ⚠ Declined this question (returned no forecast), excluded from that date's median: {declined.map(([d, ls]) => `${d} — ${ls.join(", ")}`).join(" · ")}
          </div>
        )}

        <div style={{ display: "flex", gap: 22, marginTop: 12, paddingTop: 14, borderTop: "1px solid var(--line-soft)", flexWrap: "wrap", alignItems: "flex-start" }}>
          <Stat label={(staleAt ? "As of " + staleAt : "Latest") + " — ensemble median, by " + hz} value={fmtV(latest)} color="var(--ink)" />
          <Stat label={"Change since " + snapshots[0].label} value={loss ? tlFmtRatio(delta) : tlFmtD(delta)} color={flat ? "var(--ink-soft)" : (up ? "var(--model)" : "var(--super)")} />
          <div style={{ marginLeft: "auto" }}>
            <button className="linkbtn" onClick={() => setShowTable(v => !v)}>
              {showTable ? "Hide table" : "Show as table"}
            </button>
          </div>
        </div>

        {!loss && <ForecastRationales qid={q.id} context={q.short || title}
          date={li >= 0 ? snapshots[li].date : null}
          forecasts={q.horizons.map(h => ({ key: h, values: Object.fromEntries(q.series.map(s => [s.label, (s.ps[h] || [])[li]])) }))} />}
        {showTable && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line-soft)" }}>
            <TimelineTable q={q} horizon={hz} snapshots={snapshots} />
          </div>
        )}
      </div>
    </Panel>
  );
}

// "Statistical lives lost": the loss:ai row, between the headline and the
// severity ladder (Nick, 2026-09-10; the shared "AI risk dashboard" mockup's
// panel 2, which was computed from this row). Nothing new is elicited: the
// ladder's eight rungs are P(cumulative loss >= x) at eight points, and the
// row is that survival function integrated with every band valued at its
// lower rung -- a floor, in death-equivalents at the ladder's own $2.2M rate.
function LossPanel() {
  // No explainer box under the chart (Nick, 2026-09-10): the question text
  // the blob carries already says what the fold is, and ExpectedLossNote
  // rides the Definitions modal and Graph 1's loss rows.
  return (
    <TimelinePanel qid="loss:ai"
      title="Statistical lives lost"
      sub="Expected loss from AI-related incidents, in death-equivalents · a lower bound" />
  );
}
