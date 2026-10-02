/* ============================ Graph 1 · live (window.__GRAPH1__) ============================ */
const G1 = (typeof window !== "undefined" && window.__GRAPH1__) || null;

// A small rotated square, for human reference markers. Kept distinct from the
// models' filled circles so the two layers never read as one series.
const diamondPath = (cx, cy, r) => `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`;
// Display-only shortening. A lookup with a fallback to the raw value — it never
// decides whether a group is drawn, so an unfamiliar group still renders.
const GROUP_SHORT = { superforecaster: "supers", expert: "experts", public: "public", ai_researcher: "AI researchers" };
const groupShort = g => GROUP_SHORT[g] || g;


// Log-scale "risk term structure": cumulative P(outcome) vs horizon year. Each
// model is a DOT per horizon (no connecting line, since 2026-08-27: a model's
// forecasts at two horizons are two answers, not a trajectory), the ensemble
// median is the ink line, and behind each horizon a grey bar is the median's
// 95% CI — the same interval the Conditional-on tab draws as its band, so a
// reader can tell a dot's move between runs from re-asking noise. On the
// questions a prior panel answered, superforecaster medians are hollow
// diamonds (one per panel per horizon), coloured and labelled from the data
// (graph1.py::_human_series).
//
// Two kinds of row. A probability row plots percent on a 0.01–100% log axis
// (or linear, by the toggle). An expected-loss row — one per incident cause,
// the eight rungs folded to a floor on E[loss] — plots death-equivalents on
// graph 2's severity axis (SEVERITY_AXIS: rung ticks, dollars beneath at the
// ladder's rate, Extinction marked), log only, so a loss reads at its rung.
function HorizonChart({ q, models, scale }) {
  const loss = q.valueKind === "loss";
  // Laid out in the width the column gives it (web/shared/responsive.jsx);
  // under 620px the right-margin labels go (the legend and tooltip carry
  // them) and the horizon labels shorten.
  const box = React.useRef(null);
  const cw = useContainerWidth(box, 880);
  const narrow = cw < 620;
  const W = Math.max(320, cw), H = narrow ? 330 : 380;
  const pad = { l: loss ? 74 : 56, r: narrow ? 16 : 142, t: 18, b: 40 };
  const hs = q.horizons;
  // Horizons sit at log(time to resolution) from the run date, so "within 6
  // months" and "by 2100" share one axis without the near ones piling up at
  // the left edge (linear time would put four of six in the first 6% of the
  // width). Falls back to one slot per horizon if a date is missing.
  const inner = W - pad.l - pad.r, mid = (pad.l + W - pad.r) / 2;
  const asOf = Date.parse(G1.latest || "") || Date.now();
  const lg = h => Math.log10(Math.max(0.05, (Date.parse((q.resolvesOn || {})[h] || "") - asOf) / (365.25 * 864e5)));
  const lgs = hs.map(lg), lgMin = Math.min(...lgs), lgMax = Math.max(...lgs);
  const uniform = hs.length === 1 || lgs.some(v => !isFinite(v)) || lgMax === lgMin;
  const x = h => (hs.length === 1 ? mid
    : uniform ? pad.l + (hs.indexOf(h) / (hs.length - 1)) * inner
    : pad.l + ((lg(h) - lgMin) / (lgMax - lgMin)) * inner);
  const xs = hs.map(x);
  const minGap = hs.length > 1 ? Math.min(...xs.slice(1).map((v, i) => v - xs[i])) : Infinity;
  const hitL = i => (i === 0 ? pad.l : (xs[i - 1] + xs[i]) / 2);
  const hitR = i => (i === hs.length - 1 ? W - pad.r : (xs[i] + xs[i + 1]) / 2);
  const LO = loss ? SEVERITY_AXIS.lo : 0.01, HIY = loss ? SEVERITY_AXIS.hi : 100;
  const linear = !loss && scale === "linear";
  // The linear axis tops out just above the largest value drawn (models,
  // median, intervals, human panels), not at 100%: a 1-18% question would
  // otherwise sit in the bottom fifth.
  const linTop = linear ? linearTop([
    ...q.series.flatMap(s => hs.map(h => s.ps[h])),
    ...hs.map(h => q.median[h]),
    ...hs.flatMap(h => (q.ci || {})[h] || []),
    ...(q.human || []).flatMap(hm => hs.map(h => hm.ps[h])),
  ]) : HIY;
  const y = v => {
    const t = linear
      ? v / linTop
      : (Math.log10(Math.max(v, LO)) - Math.log10(LO)) / (Math.log10(HIY) - Math.log10(LO));
    return pad.t + (1 - Math.min(1, Math.max(0, t))) * (H - pad.t - pad.b);
  };
  const [hv, setHv] = useState(null);
  const fmtP = v => (v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2)) + "%";
  const fmtV = v => (loss ? cFmtBig(v) : fmtP(v));
  const path = ps => hs.filter(h => ps[h] != null).map((h, i) => (i === 0 ? "M" : "L") + x(h).toFixed(1) + " " + y(ps[h]).toFixed(1)).join(" ");
  // Loss rows tick at the ladder's rungs (from the blob, never typed here);
  // the Extinction reference comes from graph 2's marker data.
  const rungTicks = loss ? (G1.rungs || []).filter(r => r.deaths >= LO && r.deaths <= HIY) : [];
  const ticks = loss ? rungTicks.map(r => r.deaths) : linear ? linearTicks(linTop) : [0.01, 0.1, 1, 10, 100];
  const tickText = t => (loss ? (rungTicks.find(r => r.deaths === t) || {}).short : fmtTick(t) + "%");
  const tickSub = t => (loss ? cFmtBig(t * (G1.usdPerDeath || 2.2e6), "$") : null);
  const marks = loss && typeof HIST !== "undefined" && HIST
    ? HIST.events.filter(e => e.kind === "reference" && /extinction/i.test(e.label)).map(e => ({ v: e.central, label: e.short || e.label }))
    : (loss ? [{ v: 8.2e9, label: "Extinction" }] : []);
  // right-margin direct labels (models + median + any human panel), staggered apart when they collide
  const ends = q.series.map(s => {
    const last = hs.filter(h => s.ps[h] != null).slice(-1)[0];
    return last ? { label: s.label, color: s.color, ye: y(s.ps[last]), v: s.ps[last] } : null;
  }).filter(Boolean);
  const medLast = hs.filter(h => q.median[h] != null).slice(-1)[0];
  if (medLast) ends.push({ label: "Median", color: "var(--ink)", ye: y(q.median[medLast]), v: q.median[medLast], bold: true });
  // Human reference layer, drawn from the data-supplied panel/group names —
  // never a literal "Supers"/"Experts" typed here. Empty on every question but
  // the two catastrophe ones.
  (q.human || []).forEach(hm => {
    const last = hs.filter(h => hm.ps[h] != null).slice(-1)[0];
    if (last != null) ends.push({ label: hm.panel + " " + groupShort(hm.group), color: hm.color, ye: y(hm.ps[last]), v: hm.ps[last], human: true });
  });
  ends.sort((a, b) => a.ye - b.ye);
  for (let i = 1; i < ends.length; i++) if (ends[i].ye - ends[i - 1].ye < 13) ends[i].ye = ends[i - 1].ye + 13;

  return (
    <div ref={box} style={{ position: "relative", minWidth: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} onMouseLeave={() => setHv(null)}>
        {ticks.map((t, i) => (
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
        {hs.map(h => (
          <g key={h}>
            <line x1={x(h)} x2={x(h)} y1={pad.t} y2={H - pad.b} stroke="var(--line-soft)" />
            {/* "within 6 months (by 2027-02-27)" splits at the parenthesis:
                the horizon on one line, its resolution date beneath, so six
                horizons fit without the labels running into each other. */}
            {(() => {
              const full = (q.horizonLabels || {})[h] || ("by " + h);
              const m = full.match(/^(.*?)\s*\((.*)\)\s*$/);
              if (narrow) return <text x={x(h)} y={H - 14} textAnchor="middle" fontSize="10.5" fill="var(--ink-soft)" fontWeight="600">{shortHorizon(m ? m[1] : full)}</text>;
              // Six horizons in a column that also carries the right-margin
              // labels: under ~118px a slot, "within 6 months" and "within
              // 12 months" ran into each other (Eva, 2026-08-31), so the top
              // line takes the short form and the date line stays.
              const top = minGap < 118 ? shortHorizon(m ? m[1] : full) : (m ? m[1] : full);
              return m
                ? <><text x={x(h)} y={H - 22} textAnchor="middle" fontSize="11.5" fill="var(--ink-soft)" fontWeight="600">{top}</text>
                    <text x={x(h)} y={H - 9} textAnchor="middle" fontSize="10" fill="var(--ink-faint)" className="mono">{m[2]}</text></>
                : <text x={x(h)} y={H - 14} textAnchor="middle" fontSize="11.5" fill="var(--ink-soft)" fontWeight="600">{full}</text>;
            })()}
          </g>
        ))}
        {/* 95% CI of the median, one grey bar per horizon, drawn first so
            every mark sits on top of it. Absent (no bar) on a day with a
            single draw per model — the blob carries no interval then. */}
        {hs.filter(h => (q.ci || {})[h]).map(h => (
          <rect key={"ci" + h} x={x(h) - 9} width={18} y={y(q.ci[h][1])} height={Math.max(1.5, y(q.ci[h][0]) - y(q.ci[h][1]))}
            rx="2" fill="var(--ink-faint)" opacity="0.22" />
        ))}
        {q.series.map(s => (
          <g key={s.label}>
            {hs.filter(h => s.ps[h] != null).map(h => (
              <circle key={h} cx={x(h)} cy={y(s.ps[h])} r="4.5" fill={s.color} stroke="var(--panel)" strokeWidth="1.5" />
            ))}
          </g>
        ))}
        {Object.keys(q.median).length > 0 && (
          <g>
            <path d={path(q.median)} fill="none" stroke="var(--ink)" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
            {hs.filter(h => q.median[h] != null).map(h => (
              <circle key={h} cx={x(h)} cy={y(q.median[h])} r="4.5" fill="var(--ink)" stroke="var(--panel)" strokeWidth="1.5" />
            ))}
          </g>
        )}
        {(q.human || []).map(hm => (
          <g key={hm.panel + hm.group}>
            {hs.filter(h => hm.ps[h] != null).map(h => (
              <path key={h} d={diamondPath(x(h), y(hm.ps[h]), 4.5)} fill="var(--panel)" stroke={hm.color} strokeWidth="1.8" />
            ))}
          </g>
        ))}
        {!narrow && ends.map(e => (
          <text key={e.label} x={W - pad.r + 10} y={e.ye + 4} fontSize="10.5" fill={e.color} className="mono" fontWeight={e.bold ? 700 : 400} fontStyle={e.human ? "italic" : "normal"}>{e.human ? "◇ " : ""}{e.label} {fmtV(e.v)}</text>
        ))}
        {hv != null && <line x1={x(hv)} x2={x(hv)} y1={pad.t} y2={H - pad.b} stroke="var(--ink-faint)" strokeDasharray="3 3" opacity="0.6" />}
        {!narrow && !uniform && (
          <text x={W - 6} y={H - 9} textAnchor="end" fontSize="9.5" fill="var(--ink-faint)" className="mono">
            <title>Horizons are spaced by the log of the time to resolution from the run date</title>log time →
          </text>
        )}
        {hs.map((h, i) => (
          <rect key={"hit" + h} x={hitL(i)} y={pad.t} width={Math.max(1, hitR(i) - hitL(i))} height={H - pad.t - pad.b}
            fill="transparent" onMouseEnter={() => setHv(h)} />
        ))}
      </svg>
      {hv != null && (() => {
        const rows = q.series.filter(s => s.ps[hv] != null).map(s => ({ label: s.label, color: s.color, v: s.ps[hv] }));
        if (q.median[hv] != null) rows.push({ label: "Ensemble median", color: "var(--ink)", v: q.median[hv], bold: true });
        if ((q.ci || {})[hv]) rows.push({ label: "95% CI", color: "var(--ink-faint)", text: fmtV(q.ci[hv][0]) + "–" + fmtV(q.ci[hv][1]), ci: true });
        (q.human || []).forEach(hm => { if (hm.ps[hv] != null) rows.push({ label: hm.panel + " " + groupShort(hm.group), color: hm.color, v: hm.ps[hv], human: true }); });
        return (
          <div style={{ position: "absolute", top: 6, left: `${(x(hv) / W) * 100}%`, transform: x(hv) > W * 0.6 ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
            background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px",
            boxShadow: "var(--shadow)", pointerEvents: "none", minWidth: 170, maxWidth: "calc(100% - 16px)" }}>
            <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 5 }}>by end of {hv}{loss ? " · death-equivalents" : ""}</div>
            {rows.map(r => (
              <div key={r.label} style={{ display: "flex", justifyContent: "space-between", gap: 14, fontSize: 12, fontWeight: r.bold ? 600 : 400 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 9, height: 9, borderRadius: 2, transform: r.human ? "rotate(45deg)" : "none", background: r.human ? "var(--panel)" : r.color, border: r.human ? "1.5px solid " + r.color : "none", opacity: r.ci ? 0.35 : 1 }}></span>{r.label}</span>
                <span className="mono" style={{ fontWeight: 500 }}>{r.text != null ? r.text : (r.censored === "upper" ? "<" : r.censored === "lower" ? ">" : "") + fmtV(r.v)}</span>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}

function LiveGraph1() {
  if (!G1 || !G1.latest) return <ForecastUnavailable title="Forecasts by horizon" info={G1 && G1.instrumentInfo} />;
  return <LiveGraph1Current />;
}
function LiveGraph1Current() {
  // ?g1=<question id> opens the rail on that row (a shareable view; the
  // Conditional-on tab's ?q= does the same).
  const [qi, setQi] = useState(() => {
    const want = new URLSearchParams(window.location.search).get("g1");
    return Math.max(0, G1.questions.findIndex(x => x.id === want));
  });
  const [scale, setScale] = useState("linear");
  const q = G1.questions[qi];
  // Rail groups come from the blob; fall back to deriving them so a stale
  // __GRAPH1__ (injected before categories existed) still renders.
  const cats = G1.categories || [
    { key: "broad", label: "Total catastrophic risk", color: "#24292f" },
    { key: "AI", label: "AI-enabled risk", color: "#8250df" },
    { key: "Biorisk", label: "Biorisk", color: "#1b7c83" },
    { key: "Nuclear", label: "Nuclear", color: "#1a7f37" },
  ];
  const byCat = cats
    .map(c => ({ ...c, qs: G1.questions.filter(x => x.category === c.key) }))
    .filter(c => c.qs.length);
  // `latest` is null when nothing has been forecast yet — a fresh checkout, or
  // the window between retiring one question set and running the next. The
  // panel must say so rather than throw: an unguarded .slice() here blanked the
  // ENTIRE page, because one component throwing during render unmounts the
  // whole React tree and the rail, both graphs and every panel below go with it.
  const latest = (G1.latest || "").slice(0, 10);
  const hasRuns = G1.runs.length > 0;
  return (
    <Panel style={{ padding: 24, marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div>
          {/* The catastrophe definition rides IN the title (Jason, 2026-08-19)
              so every screenshot carries it. It is the general catastrophe
              question's own severity string — the threshold comes from the
              QUESTION, never typed here; a hand-typed copy of it was off by
              80x for months. */}
          <h2 style={{ fontSize: 22, marginTop: 0 }}>
            Catastrophic outcome forecasts
            {G1.questions[0] && G1.questions[0].severity &&
              <span style={{ fontWeight: 400, color: "var(--ink-soft)" }}> ({G1.questions[0].severity})</span>}
          </h2>
        </div>
        <div style={{ fontSize: 12, color: "var(--ink-faint)", textAlign: "right" }}>
          {hasRuns
            ? <>{G1.runs.length} run{G1.runs.length > 1 ? "s" : ""} · latest {latest} · search and news enabled</>
            : <>no forecasts yet · questions loaded, awaiting the first run</>}
        </div>
      </div>

      <div className="rail-grid" style={{ marginTop: 16 }}>
        {/* The rail is the shared QuestionRail (60-atoms.jsx): one row per
            question, sectioned by the rail module's groups, the category's
            colour dot on each. A multi-question category (none today; the
            rungs were folded into one loss row per cause) would list its
            rows under the category name. */}
        <QuestionRail title="Risk category" value={q.id}
          onChange={id => setQi(Math.max(0, G1.questions.findIndex(x => x.id === id)))}
          items={byCat.flatMap(c => c.qs.map(sq => ({ key: sq.id, color: c.color, group: c.group,
            label: c.qs.length === 1 ? c.label : c.label + " · " + (sq.railLabel || sq.short) })))} />

        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 4, alignItems: "center" }}>
            {G1.models.map(m => <LegendDot key={m.label} color={m.color} label={m.label} />)}
            <LegendDot color="var(--ink)" label="Ensemble median" />
            {Object.keys(q.ci || {}).length > 0 && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--ink-soft)" }}>
                <span style={{ width: 10, height: 14, borderRadius: 2, background: "var(--ink-faint)", opacity: 0.35, display: "inline-block" }}></span>
                95% CI
              </span>
            )}
            {/* Human panels, only for the selected question, from its own data.
                Hollow diamond marks them as a dated reference layer. */}
            {(q.human || []).map(hm => (
              <span key={hm.panel + hm.group} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--ink-soft)" }}>
                <svg width="12" height="12" style={{ display: "block", overflow: "visible" }}>
                  <path d={diamondPath(6, 6, 4)} fill="var(--panel)" stroke={hm.color} strokeWidth="1.5" />
                </svg>
                {hm.panel} {groupShort(hm.group)}
              </span>
            ))}
            {q.valueKind !== "loss" && <ScaleToggle value={scale} onChange={setScale} style={{ marginLeft: "auto" }} />}
          </div>
          <HorizonChart q={q} models={G1.models} scale={scale} />
          {q.valueKind === "loss" && <ExpectedLossNote />}
          {/* The question, in full, BELOW the chart. It sat above until
              2026-08-18; question text runs one to six lines depending on the
              rung, so every rail click shifted the chart down the page and the
              eye lost the curve it was comparing. Anchoring the chart to a
              fixed top edge and letting the prose reflow underneath keeps the
              plot area still. A probability is not interpretable without the
              wording it answers — nor without the rules it resolves under,
              which are Bridget's: the measurement window, the but-for
              standard, what counts as excess mortality. The block itself is
              QuestionBox (60-atoms.jsx), shared with the Timeline. */}
          <QuestionBox q={q} />
          {q.declined.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--warn-ink)", background: "var(--warn-bg)", border: "1px solid var(--warn-line)", borderRadius: 8, padding: "7px 11px", display: "inline-block" }}>
              ⚠ {q.declined.join(", ")} declined this question (returned no forecast) — excluded from the median.
            </div>
          )}
          <div style={{ display: "flex", gap: 22, marginTop: 12, paddingTop: 14, borderTop: "1px solid var(--line-soft)", flexWrap: "wrap" }}>
            {q.horizons.map(h => q.median[h] != null && (
              <Stat key={h} label={`Median — by ${h}`}
                value={q.valueKind === "loss" ? cFmtLoss(q.median[h]) : (q.median[h] >= 1 ? q.median[h].toFixed(1) : q.median[h].toFixed(2)) + "%"} color="var(--ink)" />
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}
