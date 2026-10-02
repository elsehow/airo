/* ============================ FAQ (the third tab, 2026-09-08) ============================ */
// The "Why trust this?" tab became an FAQ on 2026-09-08. Copy is the FRI
// document "Auto-ARC: Should we trust these forecasts?" (Matt Reynolds and
// Bridget Williams), transcribed here, with the September 10 launch-review
// corrections applied. Every
// answer is collapsed by default. A figure mounts only while its item is
// open, so each chart measures a real column width (web/shared/responsive.jsx)
// and a chart never mounts while hidden.
//
// Dropped 2026-09-08 (Nick): "How good are AI models at forecasting rare
// events?" -- it repeated the second answer, Graph 4 included.
// Left out of the doc, and so off the page for now: the whitepaper link
// ("[LINK]"), the prompt details ("[TK]") and "Who made Auto-ARC?" ("[TK]").
// The coherence check (LiveCoherence, 30-live-graph2.jsx) closes the
// elicitation answer, under a paragraph of Nick's (2026-09-08). That answer
// and "Which models are in the ensemble?" read window.__METHOD__
// (redlines/views/method.py): the full prompt as sent on the latest run, and
// the current panel, so neither is typed here.

const METHOD = (typeof window !== "undefined" && window.__METHOD__) || null;

// ?tab=faq&faq=elicit,prompt: the item and disclosure ids to open on load.
function faqParam() {
  const q = new URLSearchParams(typeof location !== "undefined" ? location.search : "").get("faq");
  return (q || "").split(",").filter(Boolean);
}

// A disclosure inside an answer; same collapsed-by-default rule.
function FaqSub({ id, label, children }) {
  const [open, setOpen] = useState(() => faqParam().includes(id));
  return (
    <div className={"faq-sub" + (open ? " open" : "")}>
      <button className="faq-sub-q" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span>{label}</span>
        <svg className="faq-chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 6l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open ? <div className="faq-sub-a">{children}</div> : null}
    </div>
  );
}

// The prompt, verbatim: the system prompt, then the user prompt.
function PromptDisclosure() {
  const M = METHOD;
  if (!M) return null;
  const label = `Show the full prompt (${M.nQuestions} questions × ${M.cells > M.nQuestions ? Math.round(M.cells / M.nQuestions) : 1} horizons, `
    + `${M.k} conditions; ${M.promptRecorded ? "recorded on" : "preview dated"} ${M.today})`;
  return (
    <FaqSub id="prompt" label={label}>
      <div style={{ fontSize: 12.5, color: "var(--ink-faint)", margin: "2px 0 8px" }}>
        {M.promptRecorded ? "The recorded prompt from a current-version call." : "Preview of the revised instrument. A recorded current-version prompt is not available yet."}
        Protocol <span className="mono">{M.protocol}</span>.
      </div>
      <Eyebrow>System prompt</Eyebrow>
      <pre className="faq-pre">{M.system}</pre>
      <Eyebrow>User prompt</Eyebrow>
      <pre className="faq-pre">{M.prompt}</pre>
    </FaqSub>
  );
}

// "A, B, C and D", names in bold, ECI in the faint ink.
function PanelMembers() {
  const P = METHOD && METHOD.panel;
  if (!P || !P.members || !P.members.length) return null;
  const ms = P.members;
  return (
    <p>
      The ensemble at the moment, from the {P.snapshot} ECI snapshot:{" "}
      {ms.map((m, i) => (
        <React.Fragment key={m.label}>
          {i > 0 ? (i === ms.length - 1 ? " and " : ", ") : ""}
          <strong style={{ color: "var(--ink)" }}>{m.label}</strong>
          <span style={{ color: "var(--ink-faint)" }}> (ECI {Math.round(m.eci)})</span>
        </React.Fragment>
      ))}.
    </p>
  );
}

// A figure inside an answer: the same chart the panel used to draw on the
// old two-column grid, on a stone ground instead of its own card. The three
// panels take `embedded` and wrap themselves in this instead of <Panel>.
function FigFrame({ embedded, children }) {
  return embedded
    ? <div className="faq-fig">{children}</div>
    : <Panel style={{ padding: 24 }}>{children}</Panel>;
}

// Graph 4 (ForecastBench-Sim): the rare-events scatter. Moved here from
// 80-app.jsx, where it was inline on the trust grid, so the FAQ can place it.
function Graph4Panel({ embedded }) {
  return (
    <FigFrame embedded={embedded}>
      <Eyebrow>Graph 4 · ForecastBench-Sim{G4 && G4.preliminary ? " · preliminary" : ""}</Eyebrow>
      <h2 style={{ fontSize: 20, marginTop: 6, marginBottom: 4 }}>Rare events (simulated)</h2>
      <p style={{ color: "var(--ink-soft)", fontSize: 13, marginTop: 0, marginBottom: 8 }}>
        Forecasting skill on low-probability events from ForecastBench-Sim. Tests forecasting skill on a large corpus of tail events.
      </p>
      {G4 && G4_SC.length ? <ECIScatter points={G4_SC} /> : null}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line-soft)" }}>
        <Stat label={G4_BEST ? `Best tail skill — ${G4_BEST.label}` : "Best tail skill"} value={G4_BEST ? (G4_BEST.bss >= 0 ? "+" : "") + G4_BEST.bss.toFixed(2) : "—"} color={G4_FRONTIER ? G4_FRONTIER.color : "var(--model)"} />
        {/* full-set vs clean-subset ρ now rendered inside ECIScatter's own stat row */}
      </div>
      <div style={{ fontSize: 12, color: "var(--warn-ink)", marginTop: 10 }}>
        Brier <strong>skill score</strong> against each question's true probability (its class base rate in the
        simulator): 0 = forecasting the true probability; 1 = knowing the outcome.{G4_SC.length && G4_SC.every(p => p.bss < 0) ? " Every model is below 0 here: on rare events, none of them does as well as the true probability." : ""}
      </div>
    </FigFrame>
  );
}

function FaqItem({ id, q, open, onToggle, children }) {
  return (
    <div className={"faq-item" + (open ? " open" : "")} id={"faq-" + id}>
      <button className="faq-q" aria-expanded={open} aria-controls={"faq-a-" + id} onClick={onToggle}>
        <span>{q}</span>
        <svg className="faq-chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 6l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open ? <div className="faq-a" id={"faq-a-" + id}>{children}</div> : null}
    </div>
  );
}

function FaqPanel({ onDefinitions }) {
  // ?tab=faq&faq=rare,conditions opens those items on load (ids below).
  const [open, setOpen] = useState(() => { const o = {}; faqParam().forEach(id => { o[id] = true; }); return o; });
  const toggle = id => setOpen(o => ({ ...o, [id]: !o[id] }));
  // A cross-reference inside an answer ("See: ...") opens the target item and
  // scrolls to it.
  const jump = id => {
    setOpen(o => ({ ...o, [id]: true }));
    setTimeout(() => { const el = document.getElementById("faq-" + id); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }, 0);
  };
  const item = (id, q, body) => <FaqItem key={id} id={id} q={q} open={!!open[id]} onToggle={() => toggle(id)}>{body}</FaqItem>;

  return (
    <Panel style={{ padding: "24px 28px 8px" }}>
      <div className="faq">
        <h2 style={{ fontSize: 22, marginTop: 6, marginBottom: 6 }}>About AIRO</h2>
        <p style={{ color: "var(--ink-soft)", fontSize: 14, marginTop: 0, marginBottom: 18, lineHeight: 1.55 }}>
          Questions about AIRO's forecasts, methods and limitations. For more detail, read the <a href="https://forecastingresearch.org/pdf/airo-working-paper.pdf">white paper</a>.
        </p>

        {item("what", "What is AIRO?", <React.Fragment>
          <p>Automated AI Risk Outlook (AIRO) is a dashboard that tracks the probability of catastrophic events as forecast by an ensemble of frontier LLMs. The dashboard tracks multiple kinds of catastrophic events across domains and time horizons.</p>
        </React.Fragment>)}

        {item("can-ai", "Can AI really forecast catastrophic risks?", <React.Fragment>
          <p>AI forecasting is promising, but no one has yet established the accuracy of automated forecasts of catastrophic risks. We see this dashboard as a prototype that will improve over time as AI capabilities and forecasting methods improve.</p>
          <p>There is evidence that AI forecasting abilities have improved alongside other AI capabilities. In July 2026, FRI reported that several AI forecasting systems were <a href="https://forecastingresearch.substack.com/p/ai-models-have-likely-reached-parity">statistically indistinguishable from superforecasters on ForecastBench</a>. The superforecaster comparison used an earlier set of questions, and the tested forecasting systems can differ from AIRO's.</p>
          <p>The forecasts shown on this dashboard differ from those evaluated in ForecastBench in three important ways. First, they concern very rare events. It is difficult to measure accuracy when forecasting rare events because they happen so infrequently. However, we can ask AI models to make thousands of predictions about events in simulated worlds.</p>
          <figure className="faq-img">
            <img src="web/img/forecastbench-parity.png" alt="ForecastBench leaderboard: Brier index by model release date, July 2023 to July 2026, with the superforecaster line and a linear trend through state-of-the-art models" width="937" height="444" loading="lazy" />
            <figcaption>ForecastBench: Brier index by model release date. The dashed grey line is the 2024 superforecaster baseline.</figcaption>
          </figure>
          <p><a href="https://arxiv.org/abs/2606.18686">ForecastBench-Sim</a> evaluates forecasts in simulated worlds: a model receives a report of the current state, predicts future outcomes, and is scored against what happens as the simulation continues. The <a href="https://github.com/forecastingresearch/forecastbench-sim">benchmark code</a> supports a strategy-game world and an epidemic world. In these rare-event evaluations, greater capability is associated with better forecasting skill, although the relationship can depend on the task and scoring method.</p>
          <Graph4Panel embedded />
          <p>Second, AIRO includes forecasts conditional on model capabilities. The accompanying white paper also explores preliminary policy scenarios. These questions test how models adjust their forecasts when considering hypothetical changes to the state of the world. (See: <button className="linkbtn" onClick={() => jump("conditions")}>How good are AI models at counterfactual forecasting?</button>)</p>
          <p>Third, AIRO includes long-range forecasts. We do not yet have strong evidence about the accuracy of AI forecasts on long time horizons, and will collect more evidence through ForecastBench and other projects. (See: <button className="linkbtn" onClick={() => jump("horizons")}>How should I interpret forecasts for 2050 and 2100?</button>)</p>
        </React.Fragment>)}

        {item("horizons", "How should I interpret forecasts for 2050 and 2100?", <React.Fragment>
          <p>These long-horizon forecasts are especially uncertain. Future capabilities, institutions, policy and defensive responses can differ substantially from today's assumptions, and there are few comparable outcomes against which to check accuracy. Precise displayed percentages should not be read as precise knowledge.</p>
          <p>Use these forecasts alongside other evidence and scenario analysis. Disagreement across models can reveal different assumptions, but their spread is not a calibrated uncertainty interval: models can share blind spots. Forecasting methods may improve as more evidence becomes available; improvement is not guaranteed.</p>
        </React.Fragment>)}

        {item("questions", "Where do the catastrophic risk questions come from?", <React.Fragment>
          <p>We have elicited catastrophic risk forecasts from domain experts and superforecasters across many studies. In some cases, the questions we pose to our AI models are the same ones we have asked human forecasters, with small updates, allowing for some degree of comparison between frontier AI models and human forecasters.</p>
          <p>Our main definition of a catastrophe is an event that kills at least 10% of the global population alive at the start of the measurement window. We used the same definition of catastrophe in the <a href="https://forecastingresearch.org/research/existential-risk-persuasion-tournament">Existential Risk Persuasion Tournament in 2022</a> and the <a href="https://leap.forecastingresearch.org/reports/wave9">Longitudinal Expert AI Panel</a> in mid-2026. We introduce a new question asking about the probability of human disempowerment from AI. Since September 2026 we also ask two questions about human extinction (a global population below 5,000), in the wording of the Existential Risk Persuasion Tournament, so that the models' answers can be set beside the superforecasters and domain experts who answered the same question there, and beside the 2023 <a href="https://arxiv.org/abs/2401.02843">Expert Survey on Progress in AI</a>, which asked AI researchers a close but not identical question (extinction <em>or similarly permanent and severe disempowerment</em>, within 100 years).</p>
          <p>We also ask AI models to forecast the risk of harmful AI-related incidents, including incidents in specific domains — biosecurity, cybersecurity, and misalignment. For these domain-specific forecasts we ask models to forecast the probability of events of different magnitudes, measured in mortality or economic losses. These questions are adapted from our prior work on AI-associated <a href="https://forecastingresearch.org/research/llm-enabled-biorisk">biosecurity risks</a> and <a href="https://forecastingresearch.org/research/ai-cyber-risks-capabilities">cybersecurity risks</a>.</p>
          {onDefinitions && <p><button className="linkbtn" onClick={onDefinitions}>Definitions, resolution criteria and severity ladder →</button></p>}
        </React.Fragment>)}

        {item("disempowerment", "What does human disempowerment mean?", <HumanDisempowermentDefinition />)}

        {item("models", "Which models are in the ensemble?", <React.Fragment>
          <p>We select the four highest-scoring eligible models on the Epoch Capabilities Index (ECI), keeping one model per family (e.g., if Fable 5.1 is ranked 2 and Fable 5 is ranked 3, we select only Fable 5.1). Each model gives one forecast per question and condition in a run. Current charts require a complete four-model run on one elicitation date. We show each model's forecast and their unweighted median.</p>
          <p>Conditional multipliers take the median of the models' log-ratios, then exponentiate it. With four models, this is the geometric midpoint of the two middle ratios. Probability and ECI summaries use the ordinary median.</p>
          <PanelMembers />
          <p>We will periodically update the models we use on this dashboard as the top-ECI models change.</p>
          <p>The forecasting graphs use this current panel. Earlier timeline points from models that have left the panel remain visible in grey. Benchmark figures use the models evaluated in those studies, so their model sets can differ.</p>
        </React.Fragment>)}

        {item("selection", "Why select models using the ECI rather than ForecastBench?", <React.Fragment>
          <p>We use the ECI to define a current, consistently updated frontier panel. ForecastBench evaluates forecasting accuracy, and its results are important evidence for assessing this approach, but its task mix, evaluation timing and historical coverage do not directly identify which models will be best suited to these rare catastrophic-risk questions.</p>
          <p>We will use additional benchmark evidence to refine model selection and aggregation. Any resulting gains in accuracy will need to be demonstrated.</p>
        </React.Fragment>)}

        {item("elicit", "How do you elicit the forecasts?", <React.Fragment>
          <p>Each model answers all questions in one forecasting session, which can include multiple research and submission turns. Models run in an agentic harness with access to a web search tool (Tavily).</p>
          <PromptDisclosure />
          <p>We give the models a single elicitation because, in our testing, it reduced logical inconsistencies between forecasts. Some inconsistencies remain, including conditional probabilities that exceed those of their broader parent events. The check below covers the unconditional forecasts; it does not certify all conditional forecasts. Passing logical checks does not establish forecasting accuracy:</p>
          <LiveCoherence embedded />
        </React.Fragment>)}

        {item("conditions", "How good are AI models at counterfactual forecasting?", <React.Fragment>
          <p>Counterfactual forecasting — predicting how alternative actions may change outcomes — requires implicit causal assumptions. For an introduction to causal and counterfactual reasoning, see Judea Pearl and Dana Mackenzie’s <i>The Book of Why</i>.</p>
          <p>We assess both how models update on correlated information and how well they forecast cause-and-effect relationships.</p>
          <p>To understand the first (correlative skill) question, we looked at real-world ForecastBench weather questions on pairs that are closely related (are nearby one another geographically), correlated (have shared weather systems), and independent (different weather systems). We compared results to the “noise ceiling” (that is, the fully recoverable signal, modulo natural variation).</p>
          {OBS ? <ObservationalPanel embedded /> : null}
          <p>To evaluate causal forecasting, we used ForecastBench-Sim's epidemic world and asked models to forecast new infections with and without a vaccination campaign. We compared their forecasts with the simulation's outcome distributions across matched runs. The figure below shows how skill in this controlled setting relates to capability; it does not validate the effects of real-world AI policies.</p>
          {CAUSAL ? <CausalPanel embedded /> : null}
        </React.Fragment>)}

        {item("trust", "Should we trust AI models to assess risk from AI?", <React.Fragment>
          <p>AI forecasting is promising, but no one has yet established the accuracy of automated forecasts of catastrophic risks. We see this dashboard as a prototype that will improve over time as AI capabilities and forecasting methods improve.</p>
          <p>Taken together, the evidence above suggests that AI systems are improving at forecasting across domains. AI-generated forecasts also have advantages relative to human-produced forecasts: they can be elicited week after week without survey fatigue.</p>
          <p>Predicting the future remains very hard. AI forecasts, like human forecasts, may be miscalibrated or lack resolution. Relative rankings of risks, and changes in risks over time, may be more informative than absolute levels. In any decision-making process, forecasts should be one input among many.</p>
          <p>There are also risks in relying on AI forecasts of AI risk. Published forecasts may enter future models’ training corpora and become self-reinforcing. As evidence of AI-model deception emerges, forecasts could be influenced by strategic behavior: a highly capable but misaligned model may understate risks to avoid causing alarm. Similar sandbagging could arise if companies post-train models to underplay AI-caused harms.</p>
          <p>We are developing benchmarks to improve forecast aggregation and, where possible, detect and counteract these risks. Our aim is to make forecasts inspectable, track changes over time, and improve the method through further evaluation.</p>
        </React.Fragment>)}
      </div>
    </Panel>
  );
}
