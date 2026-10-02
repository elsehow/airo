/* ============================ Graph 2 · live (window.__GRAPH2__) ============================ */
// Shape-guarded: a stale/partial blob falls back to the mock panel rather than
// throwing during render (which blanks the whole page).
const G2_RAW = (typeof window !== "undefined" && window.__GRAPH2__) || null;
const G2 = (G2_RAW && Array.isArray(G2_RAW.rungs) && G2_RAW.byHorizon &&
  Object.values(G2_RAW.byHorizon).every(v => Array.isArray(v.causes)))
  ? G2_RAW : null;

// Historical severity markers, shape-guarded like the blob itself: an older
// hydration that predates data/historical_events.json simply draws no bands
// rather than throwing mid-render and blanking the page.
const HIST = (G2 && G2.historical && Array.isArray(G2.historical.events) &&
  G2.historical.events.length) ? G2.historical : null;

// Full severity ladder: every cause asked at every rung, so each curve spans the
// whole severity axis and causes are comparable at equal severity.
//
// The diamonds are the two EXTINCTION questions (an addendum, 2026-09-15; the
// project lead asked for them on this chart), drawn at the Extinction
// reference mark: hollow for extinction of any cause, filled for AI-caused.
// They are NOT rungs and are never joined to a curve -- XPT's wording, a
// population floor (below 5,000) rather than a deaths-or-damages threshold,
// no onset window, and AI attribution by XPT's rule rather than the ladder's.
// What they are comes from the blob (G2.anchorsNote), not from prose here.
// They are our own live forecasts, so they move between runs; the catastrophe
// questions (10% of population) stay off this chart (removed 2026-08-18).
const g2Diamond = (cx, cy, r) => `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`;
// The two marks share one x (the whole population); a small fixed offset keeps
// both legible, any-cause to the left of the mark, AI-caused to the right.
const anchorX = (x, a) => x(a.deaths) + (a.ai ? 7 : -7);
//
// Coherence violations (P rising with severity — logically impossible) are
// ringed. They are REPORTED, never corrected: the models are told nothing about
// how these questions relate. See G2.coherence.
// The severity axis domain, in deaths: a hair under the 1k rung to a hair past
// Extinction (8.2B). One definition, two charts -- graph 2's curves and the
// Conditional-on tab's expected-loss rows, which must line up with this
// axis so a loss reads at its rung.
const SEVERITY_AXIS = (G2_RAW && G2_RAW.severityAxis) || { lo: 800, hi: 1.4e10 };   // from redlines.questions.SEVERITY_AXIS

// The reference marks' axis captions. The Black Death share mark is drawn at
// 25% of TODAY'S population, not a toll (Eva, 2026-08-31: "Black Death 25%
// needs clarity"), so its caption says so; every other mark keeps its short name.
const histShort = e => (e.id === "black-death-share" ? "Black Death (pop. weighted)" : (e.short || e.label));

function SeverityChart({ d, h, showModels, scale }) {
  // Width is measured (web/shared/responsive.jsx); under 620px the curve-end
  // labels go (the legend names the causes) and the rung labels shrink.
  const box = React.useRef(null);
  const cw = useContainerWidth(box, 880);
  const narrow = cw < 620;
  const W = Math.max(320, cw), H = narrow ? 360 : 420;
  const pad = { l: 58, r: narrow ? 16 : 132, t: 18, b: 72 };
  const XLO = Math.min(SEVERITY_AXIS.lo, ...G2.rungs.map(r => r.deaths * 0.8));
  const XHI = SEVERITY_AXIS.hi, YLO = 0.003, YHI = 100;
  const linear = scale === "linear";
  const x = v => pad.l + (Math.log10(v) - Math.log10(XLO)) / (Math.log10(XHI) - Math.log10(XLO)) * (W - pad.l - pad.r);
  const y = v => pad.t + (1 - (linear
    ? v / YHI
    : (Math.log10(Math.max(v, YLO)) - Math.log10(YLO)) / (Math.log10(YHI) - Math.log10(YLO)))) * (H - pad.t - pad.b);
  const [hov, setHov] = useState(null);
  const [hist, setHist] = useState(null);
  const fmtP = v => (v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v >= 0.1 ? v.toFixed(2) : v.toFixed(3)) + "%";
  const fmtN = v => v >= 1e6 ? (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(v >= 1e4 ? 0 : 1) + "k" : String(Math.round(v));
  const fmtUSD = v => "$" + (v >= 1e12 ? (v / 1e12).toFixed(v >= 1e13 ? 0 : 1) + "T" : v >= 1e9 ? (v / 1e9).toFixed(v >= 1e10 ? 0 : 1) + "B" : v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : String(Math.round(v)));
  const yticks = linear ? [0, 20, 40, 60, 80, 100] : [0.01, 0.1, 1, 10, 100];
  // Rung ticks come from the blob (r.rung), so a question-set change relabels
  // the axis without touching this file.

  const ends = d.causes.map(c => {
    const last = c.rungs[c.rungs.length - 1];
    return { label: c.label, color: c.color, xe: x(last.deaths), ye: y(last.median), actualY: y(last.median) };
  }).sort((a, b) => a.ye - b.ye);
  for (let i = 1; i < ends.length; i++) if (ends[i].ye - ends[i - 1].ye < 13) ends[i].ye = ends[i - 1].ye + 13;
  // Keep crowded endpoint labels above the paired severity tick labels.
  const labelOverflow = ends.length ? Math.max(0, ends[ends.length - 1].ye - (H - pad.b - 6)) : 0;
  ends.forEach(e => { e.ye -= labelOverflow; });

  return (
    <div ref={box} style={{ position: "relative", minWidth: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {yticks.map(t => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--line-soft)" />
            <text x={pad.l - 9} y={y(t) + 4} textAnchor="end" fontSize="10.5" fill="var(--ink-faint)" className="mono">{t >= 1 || t === 0 ? t : t.toFixed(t >= 0.1 ? 1 : 2)}%</text>
          </g>
        ))}
        {G2.rungs.map((r, i) => (
          <g key={r.rung}>
            <title>{r.label}</title>
            <line x1={x(r.deaths)} x2={x(r.deaths)} y1={pad.t} y2={H - pad.b} stroke="var(--line-soft)" />
            {(!narrow || i % 2 === 0 || i === G2.rungs.length - 1) && <>
              <text x={x(r.deaths)} y={H - pad.b + 16} textAnchor="middle" fontSize={narrow ? 8.5 : 9.5} fill="var(--ink-soft)">{r.damages == null ? "" : cFmtBig(r.damages, "$")}</text>
              <text x={x(r.deaths)} y={H - pad.b + 30} textAnchor="middle" fontSize={narrow ? 9 : 10} fill="var(--ink-soft)">{r.damages == null ? "Extinction" : r.rung}</text>
            </>}
          </g>
        ))}
        <text x={(pad.l + W - pad.r) / 2} y={H - 18} textAnchor="middle" fontSize={narrow ? 9 : 10.5} fill="var(--ink-soft)">Economic damages OR deaths (or equivalent morbidity)</text>
        <text x={(pad.l + W - pad.r) / 2} y={H - 4} textAnchor="middle" fontSize="9.5" fill="var(--ink-faint)">Cumulative severity · log scale →</text>

        {/* Historical events, as SHADED BANDS not dashed lines. Requested by
            Jason on 2026-08-17 so a reader can tell whether a threshold is
            frightening. The band is the range across published estimates —
            the Black Death spans 25-50M depending on the assumed mortality
            rate — and drawing a single line would assert a precision the
            historiography does not have.

            NotPetya (Nick, 2026-09-10) is the one damages-leg mark: no
            deaths, so its position is dollars / VSL and its tooltip reads in
            dollars. It is a point, so it too draws as a line.

            Two kind="reference" marks (Jason's 2026-08-19 notes) share this
            layer: Black Death as a share of today's population, and
            Extinction. They are definitions, not tolls, so they are points —
            the band rect degenerates to a sliver and only the dashed line
            and label read. They anchor the top decade of the axis, which no
            historical toll reaches.

            Drawn BEFORE the curves so the curves sit on top: these are
            context for the axis, not data competing with the forecasts. They
            are also not comparable to the curves at all (non-AI, accumulated
            over years) — see the caveat rendered under the chart, which comes
            from the data, not from prose typed here. */}
        {HIST && HIST.events.map(e => {
          const xl = x(e.low), xh = x(e.high), xc = x(e.central);
          const on = hist && hist.id === e.id;
          return (
            <g key={e.id} style={{ cursor: "pointer" }}
              onMouseEnter={() => setHist(e)} onMouseLeave={() => setHist(null)}>
              <rect x={xl} y={pad.t} width={Math.max(xh - xl, 2)} height={H - pad.t - pad.b}
                fill="var(--ink-faint)" opacity={on ? 0.17 : 0.09} />
              <line x1={xc} x2={xc} y1={pad.t} y2={H - pad.b} stroke="var(--ink-faint)"
                strokeWidth="1" strokeDasharray="4 3" opacity={on ? 1 : 0.7} />
              {/* Label rides a panel-coloured chip. Without it the text is
                  illegible wherever a curve crosses it, and at long horizons
                  every curve crosses this band. Chip width is estimated from
                  the string — exact enough at 10px, and it avoids a
                  measure-then-render pass. */}
              <g transform={`translate(${xc - 4}, ${pad.t + 5}) rotate(-90)`} style={{ pointerEvents: "none" }}>
                <rect x={-(histShort(e).length * 5.5) - 4} y={-8.5} width={histShort(e).length * 5.5 + 7} height={11.5}
                  rx="2" fill="var(--panel)" opacity="0.86" />
                <text textAnchor="end" fontSize="10" fill="var(--ink-soft)"
                  fontWeight={on ? 700 : 500}>{histShort(e)}</text>
              </g>
            </g>
          );
        })}

        {/* Individual models: one small dot per model per rung, in the
            MODEL's signature colour — not a line (Nick, 2026-08-27: same
            rule as Graph 1; a model's rungs are separate answers, not a
            curve). The model legend appears with them. */}
        {showModels && d.causes.map(c => G2.models.map(m =>
          c.rungs.filter(r => r.per_model[m.label] != null).map(r => (
            <circle key={c.key + m.label + r.rung} cx={x(r.deaths)} cy={y(r.per_model[m.label])} r="3.2"
              fill={m.color} opacity="0.7" stroke="var(--panel)" strokeWidth="0.8">
              <title>{m.label} · {c.label} · {r.label}: {fmtP(r.per_model[m.label])}</title>
            </circle>
          ))
        ))}
        {showModels && (d.anchors || []).map(a => G2.models.filter(m => a.per_model[m.label] != null).map(m => (
          <circle key={a.qid + m.label} cx={anchorX(x, a)} cy={y(a.per_model[m.label])} r="3.2"
            fill={m.color} opacity="0.7" stroke="var(--panel)" strokeWidth="0.8">
            <title>{m.label} · {a.label}: {fmtP(a.per_model[m.label])}</title>
          </circle>
        )))}

        {d.causes.map(c => (
          <g key={c.key}>
            <path d={c.rungs.map((r, i) => (i ? "L" : "M") + x(r.deaths).toFixed(1) + " " + y(r.median).toFixed(1)).join(" ")}
              fill="none" stroke={c.color} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />
            {c.rungs.map(r => {
              const nbad = (d.violations || []).filter(v => v.cause === c.label && v.narrower === r.rung);
              return (
                <g key={r.rung}>
                  {/* 95% CI of the median at this point (r.ci; graph2.py::point_ci),
                      a whisker in the cause's colour, drawn under the dot. */}
                  {r.ci && r.ci[1] > r.ci[0] && (
                    <g stroke={c.color} strokeWidth="1.5" opacity="0.6">
                      <line x1={x(r.deaths)} x2={x(r.deaths)} y1={y(r.ci[1])} y2={y(r.ci[0])} />
                      <line x1={x(r.deaths) - 3.5} x2={x(r.deaths) + 3.5} y1={y(r.ci[1])} y2={y(r.ci[1])} />
                      <line x1={x(r.deaths) - 3.5} x2={x(r.deaths) + 3.5} y1={y(r.ci[0])} y2={y(r.ci[0])} />
                    </g>
                  )}
                  {nbad.length > 0 && <circle cx={x(r.deaths)} cy={y(r.median)} r="9" fill="none" stroke="var(--warn-ink)" strokeWidth="1.6" strokeDasharray="2 2" />}
                  <circle cx={x(r.deaths)} cy={y(r.median)} r="4.6" fill={c.color} stroke="var(--panel)" strokeWidth="1.5"
                    style={{ cursor: "pointer" }} onMouseEnter={() => setHov({ ...r, cause: c.label, color: c.color, bad: nbad })} onMouseLeave={() => setHov(null)} />
                </g>
              );
            })}
          </g>
        ))}

        {/* The extinction diamonds (see the header comment): one per
            question at the Extinction mark, with the same CI whisker a rung
            gets, hollow = any cause, filled = AI-caused. Drawn after the
            curves and never joined to one. */}
        {(d.anchors || []).map(a => {
          const cx = anchorX(x, a), cy = y(a.median);
          return (
            <g key={a.qid}>
              {a.ci && a.ci[1] > a.ci[0] && (
                <g stroke="var(--ink)" strokeWidth="1.5" opacity="0.6">
                  <line x1={cx} x2={cx} y1={y(a.ci[1])} y2={y(a.ci[0])} />
                  <line x1={cx - 3.5} x2={cx + 3.5} y1={y(a.ci[1])} y2={y(a.ci[1])} />
                  <line x1={cx - 3.5} x2={cx + 3.5} y1={y(a.ci[0])} y2={y(a.ci[0])} />
                </g>
              )}
              <path d={g2Diamond(cx, cy, 6)} fill={a.ai ? "var(--ink)" : "var(--panel)"} stroke="var(--ink)" strokeWidth="1.8"
                style={{ cursor: "pointer" }}
                onMouseEnter={() => setHov({ ...a, cause: a.label, label: a.severity, color: "var(--ink)", bad: [], extinction: true })}
                onMouseLeave={() => setHov(null)} />
            </g>
          );
        })}

        {/* End labels ride the same estimated-width chip as the rotated
            marker labels: the reference marks' dashed lines run through this
            zone, and bare text over a dashed line is illegible. */}
        {!narrow && ends.map(e => (
          <g key={e.label}>
            {Math.abs(e.ye - e.actualY) > 2 && <line x1={e.xe + 4} y1={e.actualY} x2={e.xe + 9} y2={e.ye}
              stroke={e.color} strokeWidth="0.8" opacity="0.65" />}
            <rect x={e.xe + 7} y={e.ye - 5.5} width={e.label.length * 6.4 + 6} height={12.5} rx="2" fill="var(--panel)" opacity="0.86" />
            <text x={e.xe + 10} y={e.ye + 4} fontSize="10.5" fill={e.color} className="mono">{e.label}</text>
          </g>
        ))}
      </svg>
      {hist && (
        <div style={{ position: "absolute", top: 8, left: `${(x(hist.central) / W) * 100}%`,
          transform: x(hist.central) > W * 0.55 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, padding: "9px 11px",
          boxShadow: "var(--shadow)", pointerEvents: "none", minWidth: 210, maxWidth: "min(300px, calc(100% - 16px))" }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 1 }}>{hist.label}</div>
          <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 6 }}>{hist.span} · {hist.basis}</div>
          <div style={{ fontSize: 12, marginBottom: 6 }}>
            {hist.kind === "reference"
              ? <><span className="mono">{fmtN(hist.central)}</span>
                  <span style={{ color: "var(--ink-faint)" }}> — definitional, at today’s population</span></>
              : hist.leg === "damages"
              ? <><span className="mono">{fmtUSD(hist.damagesUsd)}</span>
                  <span style={{ color: "var(--ink-faint)" }}> in damages ≈ </span>
                  <span className="mono">{fmtN(hist.central)}</span>
                  <span style={{ color: "var(--ink-faint)" }}> death-equivalents at {fmtUSD((HIST.conversion || {}).vsl_usd || 0)} per statistical life</span></>
              : <><span className="mono">{fmtN(hist.low)}–{fmtN(hist.high)}</span>
                  <span style={{ color: "var(--ink-faint)" }}> across published estimates</span></>}
          </div>
          <div style={{ fontSize: 11, color: "var(--ink-soft)", lineHeight: 1.5 }}>{hist.note}</div>
          <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 6, paddingTop: 5, borderTop: "1px solid var(--line-soft)" }}>
            {hist.source}
          </div>
        </div>
      )}
      {hov && !hov.anchor && (
        <div style={{ position: "absolute", top: 8, left: `${(x(hov.deaths) / W) * 100}%`,
          transform: x(hov.deaths) > W * 0.55 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, padding: "9px 11px",
          boxShadow: "var(--shadow)", pointerEvents: "none", minWidth: 195, maxWidth: "min(265px, calc(100% - 16px))" }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 1 }}>{hov.cause}</div>
          <div style={{ fontSize: 11, color: "var(--ink-faint)", marginBottom: 6 }}>
            {hov.label} · <strong>{(G2.horizonLabels || {})[h] || "by " + h}</strong>
          </div>
          {G2.models.map(m => hov.per_model[m.label] != null && (
            <div key={m.label} style={{ display: "flex", justifyContent: "space-between", gap: 14, fontSize: 12 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: m.color }}></span>{m.label}</span>
              <span className="mono">{fmtP(hov.per_model[m.label])}</span>
            </div>
          ))}
          <div style={{ display: "flex", justifyContent: "space-between", gap: 14, fontSize: 12, fontWeight: 600, marginTop: 4, paddingTop: 4, borderTop: "1px solid var(--line-soft)" }}>
            <span>Median</span><span className="mono">{fmtP(hov.median)}</span>
          </div>
          {hov.ci && (
            <div style={{ display: "flex", justifyContent: "space-between", gap: 14, fontSize: 12, color: "var(--ink-soft)" }}>
              <span>95% CI</span><span className="mono">{fmtP(hov.ci[0])}–{fmtP(hov.ci[1])}</span>
            </div>
          )}
          {hov.extinction && (
            <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 6, paddingTop: 5, borderTop: "1px solid var(--line-soft)" }}>
              A separate question in the Existential Risk Persuasion Tournament's wording (population below 5,000), not a rung of any curve.
            </div>
          )}
          {hov.bad && hov.bad.length > 0 && (
            <div style={{ fontSize: 11, color: "var(--warn-ink)", marginTop: 6, paddingTop: 5, borderTop: "1px solid var(--line-soft)" }}>
              ⚠ incoherent: {hov.bad.map(v => v.model).join(", ")} rate this above the weaker “{hov.bad[0].broader}” event.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// One collapsed warning summarising every data-quality issue for the current
// horizon; expands to the itemised list.
function IssuesPanel({ viol, declines }) {
  const [open, setOpen] = useState(false);
  const decl = Object.entries(declines);
  const n = viol.length + decl.length;
  if (!n) return null;
  const bits = [];
  if (viol.length) bits.push(`${viol.length} coherence violation${viol.length > 1 ? "s" : ""}`);
  if (decl.length) bits.push(`${decl.length} model${decl.length > 1 ? "s" : ""} declined some questions`);
  return (
    <div style={{ background: "var(--warn-bg)", border: "1px solid var(--warn-line)", borderRadius: 10, marginTop: 4 }}>
      <button onClick={() => setOpen(o => !o)} style={{ width: "100%", textAlign: "left", background: "transparent",
        border: "none", cursor: "pointer", padding: "9px 12px", fontSize: 13, color: "var(--warn-ink)",
        display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .12s", fontSize: 11 }}>▶</span>
        <span>⚠ <strong>{bits.join(" · ")}</strong></span>
        <span style={{ marginLeft: "auto", fontSize: 11.5, opacity: 0.75 }}>{open ? "hide" : "show details"}</span>
      </button>
      {open && (
        <div style={{ padding: "0 12px 11px 32px" }}>
          {viol.map((v, i) => (
            <div key={i} style={{ fontSize: 12.5, color: "var(--warn-ink)", paddingTop: 5,
              borderTop: i ? "1px solid var(--warn-line)" : "none", marginTop: i ? 5 : 0 }}>
              <strong>{v.model}</strong> · {v.cause}: “{v.narrower}” at <span className="mono">{v.p_narrower}%</span> exceeds
              the weaker “{v.broader}” at <span className="mono">{v.p_broader}%</span>.
            </div>
          ))}
          {decl.length > 0 && (
            <div style={{ fontSize: 12.5, color: "var(--warn-ink)", marginTop: viol.length ? 9 : 0,
              paddingTop: viol.length ? 8 : 0, borderTop: viol.length ? "1px solid var(--warn-line)" : "none" }}>
              <strong>Declined to forecast</strong> (excluded from those medians): {decl.map(([m, c]) => `${m} — ${c} rung${c > 1 ? "s" : ""}`).join("; ")}.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LiveGraph2({ onDefinitions }) {
  if (!G2 || !Object.values(G2.byHorizon).some(v => v.causes.length)) return <ForecastUnavailable title="How risk scales with severity" info={G2 && G2.instrumentInfo} onDefinitions={onDefinitions} />;
  return <LiveGraph2Current onDefinitions={onDefinitions} />;
}
function LiveGraph2Current({ onDefinitions }) {
  // Opens on 2030 like every other horizon toggle (Nick, 2026-08-27).
  const [h, setH] = useState(G2.horizons.includes("2030") ? "2030" : G2.horizons[G2.horizons.length - 1]);
  const [scale, setScale] = useState("linear");
  // ?models=1 opens the per-model dots (deep link, same family as ?g1= and ?q=).
  const [showModels, setShowModels] = useState(() => new URLSearchParams(location.search).get("models") === "1");
  // Isolate one cause. Null = show all; clicking the selected cause clears it.
  const [only, setOnly] = useState(null);
  const all = G2.byHorizon[h];
  const windows = ((G2.instrumentInfo || {}).countingWindows || {})[h] || [];
  // Everything downstream reads `d`, so filtering here filters the curve, the
  // per-model faint lines, the supers diamonds, the ringed violations AND the
  // coherence stats together. Leaving the stats global while the chart showed
  // one cause would put a number next to a picture it does not describe.
  const d = useMemo(() => {
    const c = only && all.causes.find(x => x.key === only);
    if (!c) return all;
    return {
      ...all,
      causes: [c],
      // Anchors are cross-cutting: they belong to no cause, so isolating one
      // cause must not hide them.

      violations: (all.violations || []).filter(v => v.cause === c.label),
      // Same arithmetic as redlines/views/graph2.py: adjacent pairs per cause,
      // times the models. One cause here, so no sum.
      pairsChecked: (c.rungs.length - 1) * G2.models.length,
    };
  }, [all, only]);
  const viol = d.violations || [];
  const A = G2.audit && G2.audit.n ? G2.audit : null;
  const btn = (on, fn, label) => (
    <button onClick={fn} style={{ border: "1px solid var(--line)", background: on ? "var(--bg)" : "transparent",
      borderRadius: 7, cursor: "pointer", padding: "3px 9px", fontSize: 11.5, color: "var(--ink-soft)" }}>{label}</button>
  );
  return (
    <Panel style={{ padding: 24, marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 22, marginTop: 0 }}>How risk scales with severity</h2>
        </div>
        <Toggle options={G2.horizons.map(hh => ({ key: hh, label: ((G2.horizonLabels || {})[hh] || "by " + hh).replace(/ \(by .*\)$/, "") }))} value={h} onChange={setH} />
      </div>

      <div style={{ marginTop: 14 }}>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 6, alignItems: "center" }}>
          {all.causes.map(c => (
            <LegendDot key={c.key} color={c.color} label={c.label}
              onClick={() => setOnly(o => (o === c.key ? null : c.key))}
              dim={only != null && only !== c.key}
              title={only === c.key ? "Show all causes" : "Show only " + c.label} />
          ))}
          {all.causes.some(c => c.rungs.some(r => r.ci)) && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, color: "var(--ink-soft)" }}>
              <svg width="15" height="15" style={{ display: "block" }} stroke="var(--ink-soft)" strokeWidth="1.5">
                <line x1="7.5" x2="7.5" y1="2" y2="13" /><line x1="4" x2="11" y1="2" y2="2" /><line x1="4" x2="11" y1="13" y2="13" />
              </svg>
              95% CI
            </span>
          )}
          {viol.length > 0 && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, color: "var(--ink-soft)" }}>
              <svg width="15" height="15" style={{ display: "block" }}>
                <circle cx="7.5" cy="7.5" r="6" fill="none" stroke="var(--warn-ink)" strokeWidth="1.6" strokeDasharray="2 2" />
                <circle cx="7.5" cy="7.5" r="2.6" fill="var(--ink-faint)" />
              </svg>
              coherence violation
            </span>
          )}
          {(d.anchors || []).map(a => (
            <span key={a.qid} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, color: "var(--ink-soft)" }}>
              <svg width="15" height="15" style={{ display: "block" }}>
                <path d={g2Diamond(7.5, 7.5, 5.5)} fill={a.ai ? "var(--ink)" : "var(--panel)"} stroke="var(--ink)" strokeWidth="1.6" />
              </svg>
              {a.label}{a.ai ? "" : " (any cause)"}
            </span>
          ))}
          {only && btn(true, () => setOnly(null), "show all causes")}
          {btn(showModels, () => setShowModels(s => !s), (showModels ? "hide" : "show") + " individual models")}
          <ScaleToggle value={scale} onChange={setScale} style={{ marginLeft: "auto" }} />
        </div>
        {showModels && (
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 6, alignItems: "center" }}>
            {G2.models.map(m => <LegendDot key={m.label} color={m.color} label={m.label} />)}
          </div>
        )}
        <SeverityChart d={d} h={h} showModels={showModels} scale={scale} />
        <QuestionBox q={{ text: "What is the probability that one or more [incident: AI-related incident / AI-related human-caused epidemic / AI-related cyber incident / misaligned AI incident] cumulatively causes [severity: the death of more than X million people (or equivalent morbidity) or $Y economic damages] by [date: each of the following resolution years]?" }} />
        <p style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-soft)", margin: "8px 0 0" }}>
          Each of the four curves shows forecasts from asking the ensemble model to predict the likelihood of one or more qualifying incidents of the given severity level and time horizon. Severity is measured in any combination of deaths (or equivalent morbidity) <strong>OR</strong> economic damages. In other words, a cyber-attack causing economic damage of the relevant scale would count, as would a mortality event. Event types are not exclusive, so an event could fit multiple categories. That is why the sub-event types do not necessarily sum to the overall forecast.
        </p>
        {G2.anchorsNote && (d.anchors || []).length > 0 && (
          <p style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-soft)", margin: "8px 0 0" }}>{G2.anchorsNote}</p>
        )}
        <details style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-soft)", marginTop: 6 }}>
          <summary style={{ cursor: "pointer" }}>Time windows and reference markers</summary>
          <p style={{ margin: "6px 0" }}>The selected horizon is an incident-onset deadline. Harm is counted over the three years after onset, so it can extend beyond that deadline. Dollar thresholds use 2026 USD. Historical and extinction markers show mortality, except NotPetya, a damages figure converted at the ladder’s value of a statistical life; they are context for the thresholds, not forecasts of the combined deaths-or-damages outcome.</p>
          {windows.map((w, i) => <p key={i} style={{ margin: "6px 0" }}>Eligible incident onset: {w.start} through {w.end}, inclusive ({w.timezone}). The start advances with each run, including for fixed-year deadlines.</p>)}
        </details>
        {onDefinitions && <button className="linkbtn" onClick={onDefinitions} style={{ fontSize: 12, marginTop: 6 }}>Definitions and full severity ladder →</button>}
        <LadderRationales causes={d.causes} date={G2.instrumentInfo.runDate} />
      </div>
    </Panel>
  );
}



// ── Coherence, as its own panel ─────────────────────────────────────────────
//
// This sat under the severity chart, which put the project's headline
// methodological claim inside a chart panel about something else. It belongs
// with the other "why should you believe this" evidence, so it renders at the
// bottom of the Why-trust-this tab (Nick, 2026-08-18).
//
// It reads G2.audit, which spans every constraint, model and horizon — not the
// selected horizon the chart happens to show — so it no longer depends on
// which tab or horizon a reader is looking at.
function LiveCoherence({ embedded }) {
  const G2 = window.__GRAPH2__;
  const A = G2 && G2.audit && G2.audit.n ? G2.audit : null;
  if (!A) return null;
  // Three rows, from the blob (audit.rows). CROSS and BRACKET are pooled
  // into SUBSET there — they are special-case orderings too — so the rows
  // still sum to the headline. Copy: project decision, 2026-08-27; the
  // earlier intro ("no resolution required", "measured, not imposed") is in
  // this chunk's git history.
  const rows = A.rows || [];
  const bad = rows.filter(r => r.bad);
  return (
    <FigFrame embedded={embedded}>
      <Eyebrow>Coherence</Eyebrow>
      <h2 style={{ fontSize: 20, marginTop: 6, marginBottom: 4 }}>Coherence check</h2>
      <p style={{ fontSize: 13, color: "var(--ink-soft)", margin: "0 0 12px", maxWidth: 780 }}>
        We measure models' forecasts to see if they are logically coherent. This serves as a measure of overall forecast
        quality (less internally coherent forecasts imply lower quality forecasts).
      </p>
      <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 12 }}>
        <Stat label="Orderings checked" value={A.n.toLocaleString()} color="var(--ink)" />
        <Stat label="Violations" value={String(A.bad)} color={A.bad ? "var(--warn-ink)" : "var(--ink)"} />
        <Stat label="Coherence rate" value={A.rate === null ? "—" : A.rate.toFixed(2) + "%"}
          color={A.bad ? "var(--warn-ink)" : "var(--ink)"} />
      </div>
      <div style={{ overflowX: "auto", marginBottom: bad.length ? 12 : 0 }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12.5, fontVariantNumeric: "tabular-nums" }}>
          <tbody>
            {rows.map(r => (
              <tr key={r.key} style={{ borderTop: "1px solid var(--line-soft)" }}>
                <td style={{ padding: "4px 14px 4px 0", fontWeight: 600, color: r.bad ? "var(--warn-ink)" : "var(--ink-soft)", verticalAlign: "top" }}>{r.key}</td>
                <td style={{ padding: "4px 14px 4px 0", color: "var(--ink-faint)", maxWidth: 480, whiteSpace: "normal", lineHeight: 1.45 }}>{r.title}</td>
                <td style={{ padding: "4px 14px 4px 0", color: "var(--ink-soft)", textAlign: "right" }}>{r.bad}/{r.n}</td>
                <td style={{ padding: "4px 0", color: r.bad ? "var(--warn-ink)" : "var(--ink-faint)", textAlign: "right" }}>
                  {r.rate === null ? "—" : r.rate.toFixed(1) + "%"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {bad.length > 0 && (
        <div style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--warn-ink)", background: "var(--warn-bg)", border: "1px solid var(--warn-line)", borderRadius: 8, padding: "9px 12px" }}>
          {bad.map(r => (
            <div key={r.key} style={{ marginBottom: 4 }}>
              <strong>{r.key}</strong>{r.examples.map((e, i) => <div key={i} style={{ paddingLeft: 12 }}>{e}</div>)}
            </div>
          ))}
        </div>
      )}
    </FigFrame>
  );
}
