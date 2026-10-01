/* Original model explanations; no generated ensemble or revision narrative. */
const RATIONALES = window.__RATIONALES__ || { calls: {}, questions: {} };
// Horizon keys are shared with the severity ladder, whose labels carry the
// dated window ("within 12 months (by 2027-09-16)"); fall back to "by <key>".
const rationaleHorizonLabel = h => (((typeof G2 !== "undefined" && G2) || {}).horizonLabels || {})[h] || "by " + h;
const rationalePct = v => (v == null ? "—" : Number(v.toPrecision(4)) + "%");
function RationaleSources({ sources }) {
  if (!sources.length) return <p>No sources recorded for this explanation.</p>;
  return <ul style={{ paddingLeft: 20 }}>{sources.map((s, i) => {
    const url = typeof s === "string" ? s : s.url;
    const safe = typeof url === "string" && /^https?:\/\//i.test(url);
    return <li key={i} style={{ marginBottom: 6, overflowWrap: "anywhere" }}>
      {safe ? <a href={url} target="_blank" rel="noopener noreferrer">{url}</a> : String(url || "Source not recorded")}
      {s.contribution && <span> — {s.contribution}</span>}
    </li>;
  })}</ul>;
}
// The selected model's forecasts on every horizon, above its explanation: the
// explanation was recorded once per question, not once per horizon.
function RationaleForecastTable({ forecasts, model }) {
  const rows = forecasts.filter(f => (f.values || {})[model] != null);
  if (!rows.length) return null;
  return <div style={{ overflowX: "auto", marginTop: 12 }}>
    <table className="tv" style={{ width: "auto", minWidth: 260 }}>
      <thead><tr><th>Horizon</th><th>Forecast</th></tr></thead>
      <tbody>{rows.map(f => <tr key={f.key}>
        <td>{rationaleHorizonLabel(f.key)}</td>
        <td className="mono">{rationalePct(f.values[model])}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}
// `forecasts`: [{ key: horizon, values: { model label: probability } }], every
// horizon the question was asked on. `date` picks the calls shown (the
// elicitation whose forecasts the chart displays); it is not shown.
function ForecastRationales({ qid, context, forecasts = [], date, controls }) {
  const [selected, setSelected] = useState("");
  const entries = RATIONALES.questions[qid] || {};
  const models = Object.keys(entries).filter(m => forecasts.some(f => (f.values || {})[m] != null));
  const model = models.includes(selected) ? selected : models[0];
  const calls = (entries[model] || []).map(id => [id, RATIONALES.calls[id]])
    .filter(([, c]) => c && (!date || c.date === date));
  return <details style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line-soft)", fontSize: 13, lineHeight: 1.6 }}>
    <summary style={{ cursor: "pointer", fontWeight: 600, color: "var(--ink)" }}>Model rationale for its forecasts</summary>
    {controls}
    <p style={{ margin: "10px 0", fontWeight: 600 }}>{context}</p>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {models.map(m => <button key={m} aria-pressed={model === m} onClick={() => setSelected(m)}
        style={{ padding: "7px 10px", border: "1px solid var(--line)", borderRadius: 8, cursor: "pointer", background: model === m ? "var(--ink)" : "var(--panel)", color: model === m ? "white" : "var(--ink)" }}>
        {m}
      </button>)}
    </div>
    {model && <RationaleForecastTable forecasts={forecasts} model={model} />}
    {!calls.length && <p>No explanation recorded for this forecast.</p>}
    {calls.map(([id, c]) => {
      const explanation = (c.debriefs || {})[qid];
      return <div key={id} style={{ marginTop: 14 }}>
        <p style={{ fontSize: 12, color: "var(--ink-soft)" }}>{explanation ? "Model’s explanation for this question, recorded after its forecasts. Covers all horizons." : "Model’s original explanation for its full forecast batch; not specific to this question or horizon."}{calls.length > 1 ? " Each call contributes to the displayed model mean." : ""}</p>
        <p style={{ whiteSpace: "pre-wrap" }}>{(explanation && explanation.rationale) || c.rationale || "No written rationale recorded."}</p>
        {explanation && explanation.weakest_link && <p><strong>Weakest assumption: </strong>{explanation.weakest_link}</p>}
        <details><summary style={{ cursor: "pointer" }}>Sources cited by this model</summary>
          <RationaleSources sources={(explanation && explanation.key_sources) || c.sources} />
        </details>
        <details style={{ marginTop: 8 }}><summary style={{ cursor: "pointer" }}>Original batch explanation and provenance</summary>
          {explanation && <p style={{ whiteSpace: "pre-wrap" }}>{c.rationale}</p>}
          <p style={{ overflowWrap: "anywhere", color: "var(--ink-soft)" }}>Model: {c.modelId}<br />Elicited: {c.elicitedAt}<br />Run: {c.run}<br />Call: {id}<br />Instrument: {c.instrument}<br />Protocol: {c.protocol}<br />Condition: unconditional</p>
          <a href="redlines-data.zip" download="airo-data.zip">Download original forecasts, explanations and logs</a>
        </details>
      </div>;
    })}
  </details>;
}
function LadderRationales({ causes, date }) {
  const [causeKey, setCauseKey] = useState("ai");
  const [rungKey, setRungKey] = useState("1M");
  const cause = causes.find(c => c.key === causeKey) || causes[0];
  if (!cause) return null;
  const rung = cause.rungs.find(r => r.rung === rungKey) || cause.rungs[0];
  // The same cause and rung on every horizon the ladder was elicited on.
  const forecasts = G2.horizons.map(h => {
    const c = ((G2.byHorizon[h] || {}).causes || []).find(x => x.key === cause.key);
    const r = c && c.rungs.find(x => x.rung === rung.rung);
    return { key: h, values: (r && r.per_model) || {} };
  });
  const controls = <div className="rationale-controls">
    <label>Explain cause <select value={cause.key} onChange={e => setCauseKey(e.target.value)}>{causes.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>
    <label>Severity <select value={rung.rung} onChange={e => setRungKey(e.target.value)}>{cause.rungs.map(r => <option key={r.rung} value={r.rung}>{r.label}</option>)}</select></label>
  </div>;
  return <ForecastRationales qid={rung.qid} forecasts={forecasts} date={date} controls={controls}
    context={`${cause.label} · ${rung.label}`} />;
}
