/* ============================ app ============================ */
function App() {
  const [catKey, setCatKey] = useState("totcat");
  const [horizonKey, setHorizonKey] = useState("12mo");
  const [sevKey, setSevKey] = useState("10M");
  const [active, setActive] = useState({ model: true, super: true, hybrid: true });
  const [modal, setModal] = useState(false);
  // ?tab=capability / ?tab=conditional / ?tab=faq deep-link a tab (?tab=trust,
  // the FAQ tab's name until 2026-09-08, still lands there). "conditional"
  // (the Policy levers tab) was commented out for launch and is back since
  // 2026-09-16 (team meeting: the policy forecasts on their own tab).
  const tabRaw = new URLSearchParams(typeof location !== "undefined" ? location.search : "").get("tab");
  const tabParam = tabRaw === "trust" ? "faq" : tabRaw;
  const [mainTab, setMainTab] = useState(["forecasts", "capability", "conditional", "faq"].includes(tabParam) ? tabParam : "forecasts");

  const category = CATEGORIES.find(c => c.key === catKey);
  const panel = useMemo(() => buildPanel(category, horizonKey, 1), [catKey, horizonKey]);

  const sev = SEVERITY.find(s => s.key === sevKey);
  const totAi = CATEGORIES.find(c => c.key === "totai");
  const sevPanel = useMemo(() => buildPanel(totAi, horizonKey, sev.factor), [sevKey, horizonKey]);
  const latestByKey = useMemo(() => {
    const o = {};
    SEVERITY.forEach(s => { const p = buildPanel(totAi, horizonKey, s.factor); o[s.key] = p.model[p.model.length - 1]; });
    return o;
  }, [horizonKey]);

  const lastModel = panel.model[panel.model.length - 1];
  const lastSuper = panel.sup[panel.sup.length - 1].v;
  const lastHybrid = panel.hybrid[panel.hybrid.length - 1].v;

  return (
    <React.Fragment>
      {modal && <Modal onClose={() => setModal(false)} />}

      <header style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0, flex: "1 1 520px" }}>
        {/* The FRI lockup (web/img/fri-logo.svg: the site's own header mark,
            recoloured dark green for the stone ground), in place of the
            "Forecasting Research · Prototype" eyebrow since 2026-09-08. */}
        <a href="https://forecastingresearch.org" title="Forecasting Research Institute"><img className="brand-logo" src="web/img/fri-logo.svg" alt="Forecasting Research Institute" width="231" height="37" /></a>
        <h1 style={{ fontSize: "clamp(25px, 7.5vw, 33px)", marginTop: 8, marginBottom: 6 }}>AIRO (Automated AI Risk Outlook)</h1>
        <p style={{ color: "var(--ink-soft)", maxWidth: 760, margin: "0 0 10px" }}>
          Tracking the probability of catastrophic events at multiple horizons, as forecast by an ensemble of
          frontier LLMs. (Human panels are shown alongside when available.)
        </p>
        {/* The catastrophe definition rendered here until 2026-08-19, when
            Jason's notes moved it into Graph 1's own title, where a
            screenshot carries it. It stays hydrated from the question there
            (20-live-graph1.jsx) — a hand-typed copy in this header read
            "≥ 10 million deaths" for months beside a question asking about
            10% of humans alive, an eighty-fold error caught on 2026-08-17. */}
        <div style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>
          <button className="linkbtn" onClick={() => setModal(true)}>Definitions &amp; methodology →</button>
        </div>
        </div>
        {/* The dataset itself, top right (Nick, 2026-08-27: "a big 'download
            forecasts' button ... all forecasts from all models on all
            time"; 2026-09-08: "include everything we can, even if it
            requires a .zip"). Static files built beside the page by
            `redlines build --views csv` (redlines/export.py) and published
            with it: the zip holds forecasts.csv (every forecast from every
            model in every run, unconditional and conditional, one line
            each), rationales.csv (the model's written rationale and sources
            per call x question x condition), the raw JSONL logs with every
            search and page read, the retired per-question archive, the
            question and condition sets, and a README. The two CSVs are in
            the zip only: the "quick look" links beside the button went on
            2026-09-08 (Nick). */}
        <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          <a href="redlines-data.zip" download="airo-data.zip"
            title="everything: forecasts.csv, rationales.csv, the raw logs with every search and page read, the questions and conditions, a README"
            style={{ display: "inline-flex", alignItems: "center",
              background: "var(--ink)", color: "white", textDecoration: "none", borderRadius: 12,
              padding: "11px 18px", marginTop: 6, boxShadow: "var(--shadow)",
              fontSize: 15.5, fontWeight: 700, letterSpacing: "0.01em" }}>
            ⤓ Download forecasts
          </a>
        </div>
      </header>

      {/* Four tabs, not one long scroll: the page leads with the forecast
          -- the series over time first (19-live-timeline.jsx, folded in from
          its own page on 2026-09-08), then the latest reading -- then what
          capability would do to it, and the FAQ (79-faq.jsx; the
          calibration-and-skill story) waits behind a click. The POLICY LEVERS tab (ConditionalPanel,
          75-conditional.jsx; what a LEAP Wave 12 policy would do to the
          forecast) is COMMENTED OUT for launch (Nick, 2026-09-08): the
          paper uses it, the site does not yet. The cron keeps eliciting
          the conditions -- the single instrument answers them in the same
          call as the forecast -- and the blob is still built and injected,
          so restoring the tab is the option and the line below. The mock
          fallbacks render only when a blob is missing; on the built page
          all are present. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10, fontSize: 13, color: "var(--ink-soft)" }}>
        <span style={{ background: "var(--warn-bg)", border: "1px solid var(--warn-line)", borderRadius: 999, color: "var(--warn-ink)", fontWeight: 700, letterSpacing: "0.04em", padding: "3px 8px" }}>BETA!</span>
        <span>This dashboard is under active development.</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
        <Toggle options={[{ key: "forecasts", label: "Forecasts" }, { key: "capability", label: "Capability" }, { key: "conditional", label: "Policy levers" }, { key: "faq", label: "FAQ" }]}
          value={mainTab} onChange={setMainTab} />
        <a href="https://forecastingresearch.org/pdf/airo-working-paper.pdf" target="_blank" rel="noopener" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minHeight: 44, padding: "0 16px", border: "1px solid var(--line)", borderRadius: 12, color: "var(--ink)", textDecoration: "none", fontWeight: 600 }}>Whitepaper</a>
      </div>

      {mainTab === "conditional" && <ConditionalPanel />}
      {/* The Capability tab is CapabilityPanel alone for launch. AxesPanel
          (78-axes.jsx: forecasts conditional on lab revenue, the ECI and the
          AGI year, from LEAP's axes) is COMMENTED OUT (Nick, 2026-09-08);
          its blob is still built and injected, and the cron keeps
          eliciting those conditions. */}
      {mainTab === "capability" && <React.Fragment><CapabilityPanel onDefinitions={() => setModal(true)} />{/* <AxesPanel /> */}</React.Fragment>}

      {mainTab === "forecasts" && (
      <React.Fragment>

      {/* ---------- TIMELINE : the lead panel, live when __TIMELINE__ is injected; no mock ---------- */}
      {TL ? <TimelinePanel /> : null}

      {/* ---------- STATISTICAL LIVES LOST : the expected-loss row (LossPanel,
          19-live-timeline.jsx), under the headline and above the severity
          ladder it is folded from. On the page for the morning of
          2026-09-10, then COMMENTED OUT the same day (Nick). The row is still
          in the blob and the component still ships, so restoring it is this
          line:
      {TL ? <LossPanel /> : null}
      */}

      {/* ---------- GRAPH 1 : the per-horizon chart (LiveGraph1, 20-live-graph1.jsx),
          live when __GRAPH1__ is injected, else Jason's mock. COMMENTED OUT
          2026-09-08 (Nick): with every horizon a line on the Timeline above,
          it duplicated that panel. The blob is still built and injected, so
          restoring it is this block.
      {G1 ? <LiveGraph1 /> : (
      <Panel style={{ padding: 24, marginBottom: 24, filter: "grayscale(1)", opacity: 0.48 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
          <div>
            <Eyebrow>Graph 1 · Unresolved events · mock</Eyebrow>
            <h2 style={{ fontSize: 22, marginTop: 6 }}>Catastrophic outcome forecasts over time</h2>
          </div>
          <Toggle options={Object.entries(HORIZONS).map(([k, h]) => ({ key: k, label: h.label }))} value={horizonKey} onChange={setHorizonKey} />
        </div>

        <div className="rail-grid" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontSize: 11.5, color: "var(--ink-faint)", marginBottom: 4, fontWeight: 600 }}>RISK CATEGORY</div>
            {CATEGORIES.map(c => (
              <button key={c.key} onClick={() => setCatKey(c.key)} style={{ textAlign: "left",
                border: "1px solid " + (catKey === c.key ? "var(--line)" : "transparent"),
                background: catKey === c.key ? "var(--bg)" : "transparent", cursor: "pointer", padding: "8px 10px",
                borderRadius: 9, fontSize: 13, color: "var(--ink)", display: "flex", alignItems: "center", gap: 9, lineHeight: 1.25,
                borderTop: c.key === "cbrn" ? "1px solid var(--line-soft)" : undefined, marginTop: c.key === "cbrn" ? 4 : 0, paddingTop: c.key === "cbrn" ? 10 : 8 }}>
                <span style={{ width: 10, height: 10, borderRadius: 3, background: c.color, flexShrink: 0,
                  outline: c.baseline ? "1px dashed var(--ink-faint)" : "none", outlineOffset: 1 }}></span>
                <span style={{ fontWeight: catKey === c.key ? 600 : (c.emphasis ? 600 : 400) }}>{c.label}</span>
              </button>
            ))}
          </div>

          <div>
            <div style={{ marginBottom: 4 }}><ForecasterLegend active={active} setActive={setActive} /></div>
            <TimeSeriesChart panel={panel} active={active} />
            <div style={{ fontSize: 11.5, color: "var(--ink-faint)", marginTop: 2 }}>
              Solid line = monthly model runs. Hollow markers = quarterly superforecaster surveys &amp; hybrid revisions.
            </div>
            <div style={{ display: "flex", gap: 22, marginTop: 12, paddingTop: 14, borderTop: "1px solid var(--line-soft)", flexWrap: "wrap" }}>
              <Stat label="Latest — models" value={lastModel.toFixed(1) + "%"} color="var(--model)" />
              <Stat label="Latest — superforecasters" value={lastSuper.toFixed(1) + "%"} color="var(--super)" />
              <Stat label="Latest — hybrid" value={lastHybrid.toFixed(1) + "%"} color="var(--hybrid)" />
            </div>
          </div>
        </div>
      </Panel>
      )}
      */}

      {/* ---------- GRAPH 2 : the severity ladder (LiveGraph2, 30-live-graph2.jsx),
          live when __GRAPH2__ is injected, else Jason's mock. Back on the page
          2026-09-08 evening (Nick) in Graph 1's place. ---------- */}
      {G2 ? <LiveGraph2 onDefinitions={() => setModal(true)} /> : (
      <Panel style={{ padding: 24, marginBottom: 24, filter: "grayscale(1)", opacity: 0.48 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
          <div>
            <Eyebrow>Graph 2 · Severity ladder · mock</Eyebrow>
            <h2 style={{ fontSize: 22, marginTop: 6 }}>How risk scales with severity</h2>
          </div>
          <Toggle options={SEVERITY.map(s => ({ key: s.key, label: s.label }))} value={sevKey} onChange={setSevKey} />
        </div>
        <div style={{ marginTop: 18 }}>
          <div style={{ marginBottom: 4 }}><ForecasterLegend active={active} setActive={setActive} /></div>
          <TimeSeriesChart panel={sevPanel} active={active} />
          <div style={{ fontSize: 11.5, color: "var(--ink-faint)", marginTop: 2 }}>Total AI-enabled risk at threshold “{sev.label}”, {HORIZONS[horizonKey].label.toLowerCase()}.</div>
          <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--line-soft)", maxWidth: 660 }}>
            <SeverityLadder latestByKey={latestByKey} selKey={sevKey} />
          </div>
        </div>
      </Panel>
      )}

      {/* ---------- DATA BANK : live when __DATABANK__ is injected, else mock ---------- */}
      {DB ? <LiveDataBank /> : (
      <Panel style={{ padding: 24, filter: "grayscale(1)", opacity: 0.48 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
          <div><Eyebrow>Public data bank</Eyebrow><h2 style={{ fontSize: 20, marginTop: 6 }}>Forecasts &amp; resolutions</h2></div>
          <span style={{ fontSize: 12.5, color: "var(--ink-faint)" }}>showing 6 of 1,043 questions · mock</span>
        </div>
        <div style={{ overflowX: "auto", marginTop: 14 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--ink-faint)", fontSize: 11.5, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {["Question", "Category", "Horizon", "Models", "Superf.", "Hybrid", "Status", "Resolved"].map(h => (
                  <th key={h} style={{ padding: "8px 12px 8px 0", fontWeight: 600, borderBottom: "1px solid var(--line)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {DATA_BANK.map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--line-soft)" }}>
                  <td style={{ padding: "10px 12px 10px 0", maxWidth: 320 }}>{r.q}</td>
                  <td style={{ padding: "10px 12px 10px 0", color: "var(--ink-soft)", whiteSpace: "nowrap" }}>{r.cat}</td>
                  <td style={{ padding: "10px 12px 10px 0", color: "var(--ink-soft)" }}>{r.hz}</td>
                  <td style={{ padding: "10px 12px 10px 0" }} className="mono"><span style={{ color: "var(--model)" }}>{r.model}</span></td>
                  <td style={{ padding: "10px 12px 10px 0" }} className="mono"><span style={{ color: "var(--super)" }}>{r.super}</span></td>
                  <td style={{ padding: "10px 12px 10px 0" }} className="mono"><span style={{ color: "var(--hybrid)" }}>{r.hybrid}</span></td>
                  <td style={{ padding: "10px 12px 10px 0" }}>
                    <span style={{ fontSize: 11.5, padding: "2px 8px", borderRadius: 20, whiteSpace: "nowrap",
                      background: r.res === "Open" ? "var(--line-soft)" : r.res === "Yes" ? "#ffebe9" : "#dafbe1",
                      color: r.res === "Open" ? "var(--ink-soft)" : r.res === "Yes" ? "#a40e26" : "#116329" }}>{r.res === "Open" ? "Open" : r.res === "Yes" ? "Resolved Yes" : "Resolved No"}</span>
                  </td>
                  <td style={{ padding: "10px 12px 10px 0", color: "var(--ink-faint)", whiteSpace: "nowrap" }}>{r.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      )}

      </React.Fragment>
      )}

      {/* ---------- FAQ (79-faq.jsx): the questions, with Graphs 4, 5 and 6 inside their answers ---------- */}
      {mainTab === "faq" && <div style={{ marginBottom: 24 }}><FaqPanel onDefinitions={() => setModal(true)} /></div>}

      {/* The old footer ("Prototype for internal review · dimmed panels are
          illustrative mock data ...") came off on 2026-08-27 (Nick). The
          catastrophe threshold it repeated is still rendered from the
          question in Graph 1's title. The maintainer line below is the
          whole footer since 2026-09-08 (Nick); since 2026-09-10 it is the
          shared airo@ address, linked. The GitHub mark is an SVG with no
          text baseline, so a baseline-aligned flex row sits its bottom edge
          on the baseline and the icon rides high; the 4px nudge puts its
          centre on the text's cap height. */}
      <footer style={{ marginTop: 40, paddingTop: 14, borderTop: "1px solid var(--line-soft)", fontSize: 12.5, color: "var(--ink-faint)", display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <a href="https://github.com/forecastingresearch/airo" target="_blank" rel="noopener noreferrer" aria-label="AIRO on GitHub" title="AIRO on GitHub" style={{ display: "inline-flex", color: "var(--ink-soft)", transform: "translateY(4px)" }}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.58 2 12.23c0 4.52 2.87 8.35 6.84 9.7.5.1.68-.22.68-.49 0-.24-.01-1.05-.01-1.91-2.78.62-3.37-1.21-3.37-1.21-.45-1.19-1.11-1.5-1.11-1.5-.91-.64.07-.63.07-.63 1.01.07 1.54 1.07 1.54 1.07.9 1.57 2.35 1.12 2.92.86.09-.67.35-1.12.64-1.38-2.22-.26-4.56-1.15-4.56-5.1 0-1.13.39-2.05 1.03-2.77-.1-.26-.45-1.32.1-2.75 0 0 .84-.28 2.75 1.06A9.33 9.33 0 0 1 12 6.84c.85 0 1.71.12 2.51.35 1.91-1.34 2.75-1.06 2.75-1.06.55 1.43.2 2.49.1 2.75.64.72 1.03 1.64 1.03 2.77 0 3.96-2.35 4.84-4.58 5.09.36.32.68.93.68 1.88 0 1.36-.01 2.45-.01 2.79 0 .27.18.59.69.49A10.24 10.24 0 0 0 22 12.23C22 6.58 17.52 2 12 2Z" /></svg>
        </a>
        <a href="mailto:airo@forecastingresearch.org">airo@forecastingresearch.org</a>
        <span>This dashboard was developed in a <a href="https://forecastingresearch.org/pdf/airo-working-paper.pdf" target="_blank" rel="noopener noreferrer">joint collaboration</a> between FRI and external researchers. Funding was provided by a grant from <a href="https://coefficientgiving.org/" target="_blank" rel="noopener noreferrer">Coefficient Giving</a>.</span>
      </footer>
    </React.Fragment>
  );
}

const DATA_BANK = [
  { q: "AI-enabled biological event causing ≥10M deaths", cat: "CBRN", hz: "5 yr", model: "2.4%", super: "1.5%", hybrid: "1.9%", res: "Open", date: "—" },
  { q: "Frontier model exceeds 85% on CyberBench-Pro", cat: "Intermediate", hz: "6 mo", model: "61%", super: "54%", hybrid: "58%", res: "Yes", date: "Apr 2026" },
  { q: "Autonomous self-replication demonstrated in eval", cat: "Loss of control", hz: "12 mo", model: "1.3%", super: "0.7%", hybrid: "1.0%", res: "Open", date: "—" },
  { q: "WHO declares new PHEIC", cat: "Baseline", hz: "6 mo", model: "18%", super: "22%", hybrid: "20%", res: "No", date: "Mar 2026" },
  { q: "Taiwan Strait military blockade begins", cat: "Geopolitical", hz: "12 mo", model: "4.1%", super: "3.0%", hybrid: "3.4%", res: "Open", date: "—" },
  { q: "Kalshi: named storm makes US landfall in window", cat: "Rare (calib.)", hz: "1 mo", model: "3.0%", super: "1.8%", hybrid: "2.1%", res: "No", date: "Feb 2026" },
];

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
