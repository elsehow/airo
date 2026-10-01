# AIRO — Automated AI Risk Outlook

AIRO is a standing panel of frontier language models that forecasts AI-related
catastrophic-risk questions, re-elicited on a twice-weekly schedule so the forecasts
form a time series rather than a snapshot. It is a project of the
[Forecasting Research Institute](https://forecastingresearch.org) (FRI). The
live dashboard is at **https://airo.forecastingresearch.org**, and an accompanying white paper
(linked from the dashboard's FAQ) describes the method and results. The
questions are FRI's Auto-ARC set; the models answer them under grounded,
agentic web search, and the same models are benchmarked for calibration and
skill on ForecastBench and on two simulators, and asked for forecasts
conditional on policy and capability scenarios. The project was called
"Redlines" and then "Auto-ARC" before it became AIRO, so the Python package is
still named `redlines` and some file and blob names carry the old names.

## What's here

One page, `index.html`, assembled from the chunks under `web/demo/`. Its panels:

- **Timeline** — the lead panel of the Forecasts tab: how the bottom-line
  forecasts move between elicitation dates, one dot per model per date plus the
  ensemble median. The series starts at the agentic-harness cutover on
  2026-09-02 (`redlines/runlog.py::SERIES_START`); earlier elicitations stay in
  the run log and the download but are not drawn on the same axis. A model that
  leaves the panel keeps its points, drawn in gray.
- **Graph 1** — the current forecasts by horizon: the cross-cutting questions
  (general catastrophe, AI catastrophe, human disempowerment) and one
  expected-loss row per AI-related incident cause, with prior human panels
  (XPT, LEAP) as hollow diamonds where a comparable question exists.
- **Graph 2** — the incident severity ladders: probability against a
  deaths-or-damages threshold for four AI-related incident causes, plus a
  resolution-free coherence check (P of a stronger event must never exceed P of
  a weaker event it implies).
- **Data bank** — the bottom-line forecasts collated with their resolution
  criteria; the download bundle (every forecast and rationale) is linked here
  and from the page header.
- **Capability** — the same questions conditional on the level of the frontier
  Epoch Capabilities Index (ECI): the model first forecasts its own p25/p50/p75
  for the frontier ECI at a target date, then conditions on each.
- **Policy levers** — the same questions conditional on each LEAP Wave 12
  policy scenario (built and elicited every run; hidden from the launch page).
- **Graph 3** — calibration and resolution against ForecastBench, one round
  with a human superforecaster arm (`docs/methodology.md` explains why one).
- **Graph 4** — calibration and skill on rare (1–9%) events, a two-simulator
  average (FreeCiv and a Starsim pandemic) correlated with ECI.
- **Graph 5** — observational conditionals: told "suppose A happened" about
  paired weather questions, does the conditional shift track the association in
  the resolution data? Rank correlation with ECI, under the noise ceiling.
- **Graph 6** — causal conditionals: given a vaccination campaign in a simulated
  epidemic, does the forecast move the way the simulator does? CRPS skill vs
  ECI, from the locked Starsim causal dataset.
- **FAQ** — the questions readers ask, with the elicitation prompt as it was
  actually sent, and Graphs 4, 5 and 6 inside the relevant answers.

## Reproduce

Two runtime tiers, and the split is deliberate. **Rebuilding** every dashboard
blob from the committed inputs is stdlib-only, needs no keys and no network,
and is checked byte-for-byte against the tracked output by the golden tests.
**Eliciting** new forecasts needs one third-party dependency, litellm, and API
keys (next section).

```bash
python3 -m redlines build            # rebuild all 14 views and mirror them to results/*.json
python3 -m redlines build --views g1 # any subset: g1,g2,g3,g4,observational,causal,databank,
                                     #   timeline,conditional,capability,axes,method,rationales,csv
python3 -m redlines build --list     # list view names and exit
python3 -m redlines assemble         # rebuild index.html from web/demo/ chunks + fresh blobs
python3 -m redlines export-fb        # the provisional ForecastBench-2.0 ingest artifact
python3 -m redlines paper            # paper/fig/*.pdf + paper/numbers.tex (needs matplotlib:
                                     #   pip install -e '.[paper]'; --backend agg needs no TeX)
```

`build` and `assemble` round-trip to the same tracked bytes (see
`docs/architecture.md`). Graph 3 and Graph 4 are derived from external inputs
(the ForecastBench forecast sets and the `forecastbench-sim` corpus); when
those are absent the build reads the tracked mirrors `results/graph3_data.json`
and `results/graph4_combined.json`, so a fresh clone rebuilds and assembles the
page without sibling checkouts. Re-deriving them needs `FB_DATASETS_ROOT` /
`FBSIM_ROOT` and `results/eval_full.json` (see "Data provenance").

Tests:

```bash
pip install -e '.[test]'
pytest
```

## Elicit new forecasts

```bash
pip install -e '.[acquire]'                      # litellm, and nothing else
python code/run_unified.py --joint --dry-run     # print the prompt, call nothing
python code/run_unified.py --joint --repeats 1 --workers 2 \
    --conditions data/combined_conditions.json --out results/runs/<stamp>.jsonl
```

Keys go in `~/.config/redlines/env` (mode 600), one `KEY=value` per line:
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`,
`XAI_API_KEY`, `TAVILY_API_KEY`. A repo-local `.env` is read as a fallback;
`REDLINES_ENV_FILE=<path>` pins the run to exactly one file. An already-set
environment variable always beats every file. `code/cron_run.sh` sources the
same file, and `tests/test_llm.py` pins the two parsers to agree.

`TAVILY_API_KEY` is required rather than optional: without it every model still
answers, from parametric memory with no current evidence, and the run looks
identical from the outside, so the runner refuses instead;
`--allow-ungrounded` makes that an explicit choice.

**The published protocol** (since 2026-08-27; rows are tagged with a protocol
id, currently `unified-joint-combined-v6`, see `redlines/conditional.py`) is the
single instrument: `--joint` is one call per model that answers every question ×
horizon cell unconditionally *and* under each condition in one submission, with
no coherence relation stated in the prompt (coherence is measured afterwards).
The prompt is 37 questions (four AI incident types × 8 severity rungs, plus
five cross-cutting questions: the two 10%-of-population catastrophe questions,
human disempowerment, and since 2026-09-15 the two extinction questions in
XPT's wording, `docs/extinction-questions-2026-09-15.md`) over six horizons,
two of them rolling. Since
2026-09-02 each model is asked once per run (`--repeats 1`); the same-day
repeats that preceded it bought a re-asking spread, and their budget went to
the agentic search harness instead, so the views draw no interval on a
single-draw day. The model panel is the top four runnable models by ECI in the
newest Epoch snapshot, one seat per model family (`redlines.registry.panel()`,
`docs/model-set.md`). The unconditional slice lands in
`results/runs/<stamp>.jsonl`, the series every panel reads; the whole
instrument is appended to `results/conditional_runs*.jsonl`.
`--conditions <file>` picks the condition set: `data/combined_conditions.json`
(the LEAP policies plus the model's own capability percentiles, what the weekly
run uses), `data/eci_conditions.json` (fixed ECI levels),
`data/axes_conditions.json` (risk against an x-axis quantity). See
`docs/conditional-forecasts.md`. A cron on the serving box runs
`code/cron_run.sh` (Wednesdays and Fridays 12:00 UTC), which runs the combined
instrument and publishes the rebuilt page with `code/publish_dashboard.sh`.
Each call ends with a debrief turn (since 2026-09-15): per question group, the
sources that mattered most, the most compelling arguments, the most likely
pathway to catastrophe and the base rate, in the model's own words, exported
as `results/debriefs.csv`. The
axes instruments left the schedule on 2026-09-14; run them by hand with
`--conditions data/axes_conditions.json` when a fresh axes date is wanted.

### The question set

The Auto-ARC question workbook and its definitions under `data/auto-arc/` are
the single source: `code/make_autoarc_questions.py` generates
`data/autoarc_ladder.json` and `data/autoarc_crosscutting.json` from them, the
runner and every panel read only the generated files, and
`tests/test_autoarc_generator.py` fails if either is hand-edited. Definition
changes are versioned as instruments: the 2026-09-10 counting rules
(`docs/counting-rules-specification-2026-09-10.md`) are instrument
`airo-incidents-prospective-v1`, the previous instrument is archived under
`data/instruments/legacy-2026-08-31/`, and rows carry the instrument id so a
view never answers a revised question with an older probability.

### Rebuild the Graph 4 corpus (deterministic; needs the forecastbench-sim checkout)

From inside the `forecastbench-sim` checkout:

```bash
cp /path/to/this-repo/code/mine_lowprob_corpus.py worlds/freeciv/scripts/
uv run python worlds/freeciv/scripts/mine_lowprob_corpus.py \
    --data-dir data/games --snapshot-turn 40 \
    --rate-lo 0.01 --rate-hi 0.09 --min-n 40 --workers 8 \
    --out-dir data/lowprob
```

Produces `data/lowprob/{lowprob_classes,lowprob_selected_classes,lowprob_questions}.json`.
The reference run (1,019 games, snapshot turn 40) yields 425,270 binary
questions in 564 classes, of which 35 tail classes (1–9%) with 25,919 resolved
instances feed Graph 4; `data/lowprob_classes.json` records `min_n: 40`. The
pandemic side is `code/pandemic_build_corpus.py` and `code/pandemic_smoke.py`
in the same environment; the model eval is `code/run_eval.py` (API keys +
`FBSIM_ROOT`).

## Layout

```
index.html                  BUILD ARTIFACT: the one page; `redlines build`/`assemble` write it
web/
  demo/                     the page's source: numbered chunks + manifest.json (Timeline is 19-live-timeline.jsx)
  shared/                   question-rail.jsx, responsive.jsx — helpers the chunks share
  img/                      the FRI logo and the ForecastBench parity figure (web/fonts/ is ignored:
                            Season Sans is licensed for the live site only; clones use the fallback stack)
redlines/                   the pipeline package (stdlib only; litellm only inside llm.py at call time)
  __main__.py               CLI: build / assemble / export-fb / paper
  config.py                 paths (env-overridable), round pins, thresholds
  registry.py               the single model table (ids, labels, ECI, colors) + panel()
  eci.py                    the Epoch Capabilities Index snapshots: which exist, which is newest
  questions.py              schema-checked loaders for the Auto-ARC question set
  instrument.py             question-version boundaries and dated incident onset windows
  runlog.py                 run-log loading, the series start, replicate pooling
  coherence.py              every coherence constraint the question set implies
  conditional.py            per-model deltas under a condition vs the same-call baseline
  historical.py, rail.py, roster.py   historical severity markers; the shared question rail; the bench roster
  stats.py                  deciles / brier / bss / spearman / wilson — one implementation each
  hydrate.py, pages.py      window.__NAME__ blob injection; manifest-driven page assembly
  export.py                 forecasts.csv, rationales.csv, the download bundle, the ForecastBench export
  llm.py, tools.py          ACQUISITION ONLY: key loading + the agentic tool-use loop; the Tavily tools
  views/                    one pure build() per panel: graph1..graph4, observational, causal,
                            databank, timeline, conditional, capability, axes, method
  paper/                    the paper's figures (graph1, graph3, graph4, incident_ladders,
                            conditional, capability, causal) and numbers.tex; style.py
code/                       acquisition scripts, generators and thin shims (see each docstring)
  run_unified.py            THE forecast runner; --joint, --repeats, --conditions, --dry-run
  cron_run.sh, publish_dashboard.sh   the weekly run and the box-side publish
  make_autoarc_questions.py the question generator: data/auto-arc/* -> data/autoarc_*.json
  make_*_conditions.py      the condition sets (LEAP policies, ECI levels, self-elicited, axes, combined)
  make_eci_trend*.py, eci_projection_metrgraph.py   the ECI trend / projection inputs
  validate_launch_run.py, audit_cyber.py, check_counting_comprehension.py   launch-run audits
  run_eval.py, mine_lowprob_corpus.py, pandemic_*.py   the Graph 4 corpus and eval (need forecastbench-sim)
  graph3_comparability.py   the Graph 3 methodology decomposition (needs FB_DATASETS_ROOT)
  observational/            Graph 5: the observational bench, vendored (spec.md, runners, scoring)
  causal/                   Graph 6: the Starsim causal bench's generating code, frozen at causal-v4-locked
  pi_harness/               an alternative agent harness for one forecasting call (experimental)
data/
  auto-arc/                 the Auto-ARC question workbook (.xlsx) and definitions (.md) by date
  autoarc_ladder.json, autoarc_crosscutting.json   the generated question sets (never hand-edited)
  instruments/              the previous instrument's definitions and question sets, archived by date
  epoch_capabilities_index_<date>.csv   Epoch ECI snapshots (2026-07-07 pinned for Graph 4; newest picks the panel;
                            fetched before every scheduled run since 2026-10-01)
  eci_projection_*.json, eci_trend_*.json   the ECI trend inputs
  live_metr_eci_frontier.json   the METR frontier the capability prompt quoted 2026-09-10 .. 09-18 (record only)
  leap_policies.json, leap_reference.json   the LEAP-derived condition set and panel aggregates (the
                            survey documents and raw pull under data/leap/ are internal, gitignored)
  *_conditions.json         the condition sets the runner takes (--conditions)
  human_baselines.json      prior human-panel forecasts of comparable questions (XPT, LEAP)
  historical_events.json, recent_incidents_2026-09.json   severity-axis markers; recent-incident context
  lowprob_classes.json, lowprob_selected_classes.json   the FreeCiv question classes (564) and the 35 tail classes
  observational/            Graph 5 inputs: pairs_selected.json, noise_ceiling.json, candidate provenance
  causal/                   Graph 6: the LOCKED Starsim causal dataset (README, MANIFEST.sha256, models.csv)
results/
  runs/                     the unconditional series, one dated .jsonl per run
  forecast_runs_unified.jsonl   the historical run log before per-run files
  conditional_runs*.jsonl   the whole instrument per condition set; *_runs/ the per-run copies
  *_data.json, graph4_combined.json   the tracked view blobs (mirrors of what the page embeds)
  eval_panel2/, pandemic/, observational/   Graph 4 and Graph 5 eval outputs and logs
  experiments/, validation/ held arms (e.g. the ECI top-4 arm) and the launch-run audits
  coherence_experiment.json the joint-elicitation experiment (docs/coherence-experiment.md)
paper/                      figures, numbers.tex and dashboard screenshots for the white paper
tests/                      golden tests for build/assemble/paper, the generators, the runner's guards
docs/                       see below
archive/                    dead scripts, retired question sets and forecasts, superseded runs (archive/README.md)
archive/jason-demo.html     the original mock dashboard the live page grew from (Jason Abaluck)
```

## Data provenance

- **Epoch Capabilities Index.** `data/epoch_capabilities_index_<date>.csv` are
  snapshots of Epoch AI's ECI leaderboard. `redlines/eci.py` is the one reader:
  the 2026-07-07 vintage is pinned for Graph 4, the newest picks the panel, and
  a snapshot older than 31 days raises a warning.
- **ForecastBench** (Karger et al., ICLR 2025), CC BY-SA 4.0. Graph 3 reads the
  processed forecast sets published on forecastbench.org; `docs/methodology.md`
  gives the download and why the numbers move when it is re-pulled.
- **forecastbench-sim** (`forecastingresearch/forecastbench-sim`, pinned at
  commit `24d88de`) supplies the FreeCiv worlds, the question generator and
  resolver, the Starsim pandemic world and the model eval harness behind
  Graph 4 and Graph 6. `code/mine_lowprob_corpus.py` and the eval scripts run
  inside that repo's `uv` environment. The 1,019 recorded games and the 25.9k
  instance corpus are regenerated deterministically there, not committed here;
  the small class files under `data/` and the eval outputs under `results/`
  are.
- **LEAP** survey conditions. The LEAP survey documents and the raw pull of
  panel answers are internal to FRI and are not in this repository
  (`data/leap/` is gitignored). What is tracked is derived from them:
  `data/leap_policies.json` (the Wave 12 policy conditions the models are
  prompted with, verbatim in the prompt shown on the FAQ),
  `data/leap_reference.json` (each panel's n and median per asked percentile
  for the questions the page draws as reference lines, extracted by
  `code/make_leap_reference.py`), and the axes condition sets. The generators
  that read the internal files exit with a message when they are absent, and
  their tests skip.
- **Internal sources, not published.** The 31-model ECI table was first
  transcribed from an internal FRI analysis; the runner's LLM layer was
  vendored on 2026-08-28 from an internal FRI checkout (`redlines/llm.py`,
  `redlines/tools.py`), so nothing in the run path depends on it; the Graph 6
  dataset was locked from FRI's ForecastBench-Sim ICLR work. Where a doc names
  one of those checkouts it is describing history, not a dependency.
- **The download.** The page's "Download forecasts" button serves
  `results/forecasts.csv`, `results/rationales.csv` and the bundle
  `results/redlines-data.zip` (both CSVs, the raw logs, the questions and
  conditions, a README), all built by `python3 -m redlines build --views csv`
  (`redlines/export.py`) and not tracked. One line per (call, question,
  horizon, condition) for every model in every run; the `protocol` column
  separates the elicitations (the combined instrument's `unified-joint-combined-v*`
  tags, the earlier joint and batch pilots) — do not pool across them.

## Docs

- `docs/architecture.md` — the acquire → artifact → build → render pipeline, its invariants, external boundaries and open items.
- `docs/methodology.md` — Graph 3 comparability (why one ForecastBench round), the grounding tools, the simulator corpora and the Graph 4 subsetting.
- `docs/model-set.md` — model selection: the top-k-by-ECI panel, one seat per family, reachability and Graph 4's roster.
- `docs/conditional-forecasts.md` — the LEAP Wave 12 policy conditionals, the capability and self-elicited capability conditionals, the combined and axes instruments.
- `docs/conditional-benches.md` — Graphs 5 and 6: can the models forecast conditionals? (observational weather pairs; Starsim interventions).
- `docs/coherence-experiment.md` — joint elicitation vs one question per call, and why the constraints are measured, not stated.
- `docs/question-swap.md` — the design record of the move to the Auto-ARC question set.
- `docs/extinction-questions-2026-09-15.md` — the extinction pair: why, whose wording, what it compares with, what changed, what is still the team's call.
- `docs/eci-top4-arm.md` — the ECI-ranked panel: where the selection rule came from and what it changed.
- `docs/counting-rules-specification-2026-09-10.md` — the incident counting rules (onset windows, cyber campaign boundaries) behind instrument `airo-incidents-prospective-v1`.
- `docs/cyber-validation-2026-09-10.md`, `docs/cyber-validation-prospective-2026-09-10.md`, `docs/cyber-source-review-prospective-2026-09-10.md` — the September 2026 audits of the cyber forecasts and their sources (with `.json` evidence files beside them).

## License

Code is MIT; the data, documentation and figures are CC BY 4.0 (cite "AIRO,
Forecasting Research Institute, https://airo.forecastingresearch.org"). Three
things are not covered: `code/causal/` (a frozen copy from
`forecastbench-sim`, GPL-3.0), the Epoch Capabilities Index snapshots (Epoch
AI's), and the Season Sans web fonts, which are not in the repository (licensed for the live site only).
See `LICENSE` (MIT) and `LICENSE-DATA` (CC BY 4.0 and the carve-outs).
