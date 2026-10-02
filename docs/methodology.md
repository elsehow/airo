# Methodology

## Graph 3 — why one ForecastBench round, and no model-vintage lines

**The ask.** The 2026-08-10 project call asked for 2025 and 2026 model lines on
Graph 3, so the calibration curve would visibly move toward the diagonal as
models improve.

**The finding.** Most of that movement would be the benchmark, not the models.
Three things differ between the `2024-07-21` line and any later line, and a
cross-round chart credits all three to capability. Measured separately by
`code/graph3_comparability.py`, which writes `results/graph3_comparability.json`:

| source of variation | effect on Brier | how it was measured |
|---|---|---|
| prompt config | **0.002** | same round, same questions, scaffold varied |
| round (question set + horizon mix) | **0.035** | *the same model*, scored across rounds |
| model vintage | **0.013** | one round, one question set, older models vs frontier |

The confound is about three times the signal.

### These numbers move. Re-run before citing.

Data current to the **2026-08-11** refresh. The processed forecast sets are not
in the git repo — the repo tracks question sets and resolution sets only. Pull
them separately:

```
curl -L -o pfs.tar.gz \
  https://www.forecastbench.org/assets/data/processed-forecast-sets/processed_forecast_sets.tar.gz
```

then extract over `~/Projects/forecastbench-datasets/processed_forecast_sets/`.

This matters more than it sounds. On the earlier 2026-03-05 snapshot the vintage
effect measured **0.003** and the round effect 0.031 — a 10x margin. The refresh
resolved long horizons on eleven more rounds and moved vintage to **0.013**
against a round effect of 0.035, a 3x margin. The conclusion held. The margin
did not. Anyone re-opening this should refresh first and expect different
numbers.

### Config is not the problem

`scratchpad_with_news` — ForecastBench's headline config, and the one this panel
draws — exists only in the 2024-07-21 round. Rounds through 2025-08-31 carry
`scratchpad`; from 2025-10-26 the benchmark runs `zero_shot` only. That break is
harmless. On the same questions the LLM crowd scores 0.1799 (scratchpad+news, 12
models), 0.1801 (scratchpad, 16), 0.1779 (zero-shot, 17) — a 0.002 spread. If
Graph 3 is ever extended, zero-shot is the config that spans every round at no
cost to the 2024 story.

### The round is the problem

ForecastBench re-runs some models in later rounds, which supplies the control for
free: a fixed model's score change is pure question luck. GPT-4.1-2025-04-14
appears in 20 rounds and swings 0.053 Brier; Claude-Haiku-4-5 swings 0.058;
GPT-5-Mini 0.033; Claude-Sonnet-4-5 0.025. Mean swing **0.035**, with no change
to the model.

**The best-matched pair still fails.** `2024-07-21` and `2025-08-03` share a
config and nearly the same horizon maturity — 61% and 59% of resolved rows at 90
days or more. That is as close to a controlled cross-round comparison as this
benchmark offers. Claude-3-5-Sonnet-20240620 ran in both and still swings
**0.014** between them, which is larger than the entire vintage effect.

### Horizon maturity, and why this argument expires

Recent rounds have not had time to resolve their long questions. A round's
resolved rows fill in from the short horizons upward:

| round | resolved rows | ≥90-day |
|---|---|---|
| 2024-07-21 | 1,507 | 61% |
| 2025-08-03 | 1,442 | 59% |
| 2025-11-23 | 1,074 | 47% |
| 2026-02-15 | 784 | 34% |
| 2026-06-21 | 579 | 0% |

This is the calendar, not a design change. Every round eventually matures. The
2026-08-11 refresh alone moved 2026-02-15 from 205 rows and 0% long-horizon to
784 rows and 34%.

So of the three arguments here, **only the round effect is durable**. The horizon
argument expires on its own schedule and has already partly expired.

### The vintage effect, measured cleanly

Inside a single round the questions, config and horizon mix are identical for
every model, so an older-vs-frontier split isolates capability:

| round | older | frontier | gap | spread between individual models |
|---|---|---|---|---|
| 2025-11-23 | 0.1810 | 0.1645 | +0.017 | 0.059 |
| 2026-02-15 | 0.1443 | 0.1391 | +0.005 | 0.085 |
| 2026-06-21 | 0.1834 | 0.1663 | +0.017 | 0.050 |

The gap is real and positive in all three rounds. It is also smaller than the
spread between individual models of the *same* vintage in the same round. Which
models you pick still matters more than what year they are from.

### Version bumps do not reliably improve forecasting

The tightest test available: one lab, one tier, consecutive versions, same
round, same questions. Nothing varies but the model generation.

| version bump (2026-06-21) | Brier | change |
|---|---|---|
| GPT-5.4-2026-03-05 → GPT-5.5-2026-04-23 | 0.1969 → 0.1738 | **+0.023** |
| Claude-Sonnet-4-5 → Claude-Sonnet-4-6 | 0.1739 → 0.1728 | +0.001 |
| Grok-4.20-Reasoning → Grok-4.3 | 0.1665 → 0.1679 | −0.001 |
| Claude-Opus-4-7 → Claude-Opus-4-8 | 0.1772 → 0.1888 | **−0.012** |

Mean **+0.003**, and two of four went backwards. Newer is not dependably better
at this task, even holding the lab and the tier fixed. This is the sharpest
evidence in the file and it is worth the paper's attention.

### The question-type split

ForecastBench holds two kinds of question, and they behave nothing alike.

- **Dataset questions** are auto-generated from public series (ACLED, FRED,
  yfinance, Wikipedia, dbnomics). Largely persistence and trend.
- **Market questions** come from Polymarket, Manifold, Metaculus and Infer.
  Judgmental, news-driven — far closer to what this dashboard asks.

Scored bare (zero-shot, no retrieval), pooled over every dashboard model and
round: dataset Brier 0.156 on 10,753 rows, market Brier 0.238 on 2,019. In the
tail the bare models call market events 3.1% that happen 22.9% of the time — a
sevenfold under-forecast, and all four models show it separately.

**A trap worth recording.** An earlier version of this panel cut every series to
7- and 30-day horizons, to match the young 2026 rounds. Only dataset questions
resolve on those exact days — market questions resolve whenever the market
closes — so the filter silently deleted 136 of 141 market questions and made the
models look near-perfectly calibrated. **Any horizon filter on ForecastBench is
also a question-type filter.** Graph 3 no longer filters; it reports the mix.

### On market questions, the only measure that means anything is skill over the price

Market questions come with a market. ForecastBench records the price at freeze
time and withholds it from the base configs — that is what the
`_with_freeze_values` variants exist for. A forecaster that retrieves the price
is looking up an answer, and its raw Brier measures retrieval, not judgement.

Scored against that same price on identical rows:

| | Brier | price's Brier | edge | corr w/ price | median gap |
|---|---|---|---|---|---|
| tournament entries (retrieval) | 0.1043 | 0.1038 | **−0.001** | 0.947 | 2.4 pts |
| superforecasters | 0.0830 | 0.1003 | **+0.017** | 0.959 | 3.9 pts |
| our models, bare | 0.2281 | 0.1152 | −0.113 | 0.454 | 15.7 pts |

Everyone who can see a market anchors on it. **Superforecasters anchor and then
beat it. The grounded systems anchor and add nothing** — their forecasts sit
within 2.4 points of the price and score what the price scores. The strong
market-question numbers in the row above are a lookup.

This retires an earlier reading in this file, which treated the tournament
systems' market-question Brier of 0.104 as evidence that retrieval fixes the
tail. It fixes the *score*; it does not demonstrate forecasting skill. What
survives is narrower and still useful: bare models are far worse than the market
(−0.113) and barely track it (r=0.45), so they are not usable unaided on
judgmental questions.

### Why our own pipeline is not scored here

It grounded on Tavily news and Metaculus (the Metaculus lookup left the toolset
on 2026-09-02 -- see "Grounding" below -- which closes channel 2 for any future
entry but changes nothing about the runs scored here), and 79 of the 500
questions in the current round *are* Metaculus questions carried with their URL
and community prediction. Three contamination channels:

1. **Resolution leakage** — run retrospectively on resolved questions, news
   retrieval finds the outcome. Fatal, and unfixable by date-filtering, since
   the filters are imperfect and the model's own training may cover the period.
2. **Withheld-price leakage** — Metaculus grounding reads the very
   `freeze_datetime_value` the benchmark hides. This one *survives* running
   prospectively, and it affects half the question set.
3. **Memorisation** — older rounds sit inside frontier training windows.
   Avoidable by using recent rounds only.

Only a prospective tournament entry, with Metaculus blocked during grounding,
would measure anything. Worth doing; not doable before Sep 1.

### Decision

Graph 3 shows two series: the same model families inside retrieval systems, and
the 2024 superforecasters as the human reference. The 2024-era LLM crowd was
dropped (it validated a model set nobody uses) and so was the bare line (we do
not run models bare). Bare numbers survive as a footnote, because they are the
reason the pipeline has retrieval at all.

The panel's centre of gravity is the skill-over-price table: on judgmental
questions, humans beat the market and the machine systems do not.

No cross-round *progress* line is drawn, for the reasons above. Model progress
over time belongs on Graph 4's capability axis, which has the room to show it
honestly. Each decile carries a 95% Wilson interval, because the series have
very different per-decile samples and the small-sample zigzag reads as
miscalibration without one.

### Series composition

Moved here from the Graph 3 panel on 2026-08-14. The panel now shows the chart,
the legend and four numbers; the caveats live in this file, which is what a
reader who wants them should be pointed at.

Source: ForecastBench (Karger et al., ICLR 2025), CC BY-SA 4.0.

**Our models + retrieval** — *not this dashboard's own pipeline.* These are the
model makers' own tournament entries (Gemini, Grok 4.20 Beta A–D, Grok 4.20
Preview), built on the same base models we run, over 8 rounds and 7,141
question-horizons. Most of the tournament ships under codenames that cannot be
traced to a base model; those are excluded rather than guessed at. Fable 5 is
not in the benchmark at all.

**Superforecasters** — the 2024-07-21 round, the only one ForecastBench has ever
run with a human arm. 578 question-horizons, 358 of them at 90 days or longer.
They answered inside a long survey, under time pressure, and their market sample
is small (57 rows).

**Different rounds.** The two series do not share a question set and their rounds
are two years apart; a model that does not change swings 0.035 Brier between
rounds. See `code/graph3_comparability.py`.

**Favorite-longshot bias.** On calls under 10% the superforecasters averaged
1.0% and *none* of the 235 resolved yes — humans over-forecast rare events,
which is the bias this whole project is about. It costs them nothing against the
market: see the skill-over-price table above.

### Rejected alternative

Re-running current frontier models on the frozen 2024 question set would give a
clean comparison, and it is cheap — 161 distinct questions across 5 horizons. It
was rejected for leakage. Those questions resolved between July 2024 and July
2025, inside every frontier model's training window, and they resolve against
ACLED, FRED, yfinance, Wikipedia and dbnomics — public time series a model may
have memorised. Leakage would manufacture the improvement the chart is meant to
measure, and we could not tell the two apart. Only about 30 of the 161 question
ids recur in later rounds, so there is no free partial version.

---

### The panel's selection rule, replayed (2026-09-02)

Graph 3's green curve used to be the maker-submitted Grok 4.20 and Gemini tournament
entries, labelled "our models + retrieval". They are not our panel: none of the
current four (Fable 5, Opus 5, GPT-5.5 Pro, GPT-5.6 Sol) has run on ForecastBench,
and the panel changes whenever Epoch's index does. What can be scored is the RULE
the panel is picked by. `redlines/views/graph3.py::panel_rule_series` replays it:
at every ForecastBench round, take the four highest-ECI models among the bench's own
bare configs that round (one config per model, the plainest name; the pinned
2026-07-07 ECI snapshot for every round; ties by name), median-pool them, and score
the pool on that round's resolved questions, keeping ForecastBench's own 5% imputed
cutoff. 33 rounds, 2024-07-21 to 2026-07-19, ~35.9k resolved forecasts, Brier 0.157,
resolution 0.079 -- worse than the superforecasters (0.118) and the maker systems
(0.133), which stay on the chart as a muted line for the retrieval comparison. The
replay is zero-shot with no retrieval, so it is a floor for the pipeline, not a
measurement of it; the market-question split (Brier 0.157 vs the market's 0.077)
says the same thing the bare series always did.

## Grounding — the agentic harness (2026-09-02)

Every panel model has always answered inside one tool-use loop
(`redlines/llm.py::call_tools`): the model calls tools, the loop feeds results
back, and the answer is a structured `submit_forecast` call. What changed on
2026-09-02 is what the loop offers and what the prompt asks for.

**Before.** Two tools, `web_search` (Tavily, one shared backend for every model
so the comparison is not confounded by each vendor's native search) and
`metaculus_lookup` (the community median on a matching open Metaculus question,
"as a cross-check, never copy it"). The prompt said *one search pass covers
every cause — you do not need to search per cause or per question*, and the
loop allowed eight turns. Models typically searched once or twice and submitted.
The cron re-asked each model five times and drew the spread as a grey band.

**After.** Two tools, `web_search` and `read_page` (Tavily extract: the text
of one page, in 7,000-character windows the model pages through). The prompt
asks for research *in rounds* — search per cause of catastrophe, read the
pages that matter, search again on what they said — and one sentence more:
check what has happened recently on each cause before estimating, for which
`web_search` takes a `recent_days` the model sets against the date in its
prompt (Tavily's news index, bounded by exact dates; each result carries its
publication date). The loop allows forty turns (`MAX_ROUNDS`) as a termination
guard the prompt never mentions, forcing submission on the last. The loop also
enforces a **research floor** (`MIN_RESEARCH`, ten calls): `submit_forecast`
is not offered until that many searches or page reads have returned, and a
premature call is answered with the count remaining. The floor exists because
the prompt alone did nothing: the first smoke of the new prompt (Fable 5,
2026-09-02) searched four times, read no page and submitted, exactly as under
the old prompt. Since 2026-09-11 the loop also enforces **coverage**:
`web_search` takes a `cause` (the question group, an enum drawn from the
batch), and submission is withheld until every group has had a `recent_days`
search tagged with it, a premature call naming the groups still missing. The
floor counts calls; coverage says what they must span. It came from comparing
three GPT-6 Astra draws of the same instrument: the one that ran no
misalignment search put its loss-of-control forecasts at half the other two's,
which had each read a loss-of-control incident report. The turn guard still
wins, with a warning in the run log naming what went uncovered. Reasoning runs at each provider's top rung
(`redlines.llm.REASONING`: Anthropic `max`, OpenAI `xhigh`; Anthropic's effort
level also governs how many tool calls the model makes), and the loop carries
Anthropic's signed thinking blocks across tool turns, which the API requires.
Each model is asked once; the ensemble forecast is the panel median, and the
views draw no interval on a single-draw day.

**Why the Metaculus lookup went.** It came with the vendored code: the
canaries project used it to sanity-anchor low-probability forecasts against a
public crowd. On the 2026-08-31 call the team decided against giving the models a
Metaculus-specific search. On these questions the lookup mostly
surfaces Metaculus's own long-horizon catastrophe questions, so what it hands
the model is a number rather than evidence: the forecast becomes partly a copy
of the crowd, one platform is privileged over every other source a search could
reach, and (above) it reads the very community prices a prospective benchmark
withholds. It bought critique without buying information.

**Why iterative search.** Decided on the same call: on a fixed budget, trade the *n*
repeated runs for agentic search — a model that can
follow a lead is more likely to find the best information, and its evidence
log (`evidence[]` on every row: each query, each page, each result) is legible
in a way a single snapshot search is not. The cost per call goes up; the
number of calls goes from twenty to four.

**Provenance.** Rows elicited the new way carry protocol
`unified-joint-combined-v2` (`code/make_combined_conditions.py`); the old
tag stays on the old rows, the views show the newest tag present and fall
back to the old one until the first v2 run lands
(`redlines.conditional.PROTOCOL_LINEAGE`), and the panels' grounding line
follows the tag (`redlines.runlog.grounding`). Nothing is pooled across the
bump.

### v3, the same evening: pieces, a real thinking budget, advanced search

Three things the 2026-09-02 smokes taught, folded into the loop before the
first cron run under it (protocol `unified-joint-combined-v3`; the axes sets
`unified-joint-axes-v2` / `-paperaxes-v2`):

- **The grid is delivered in pieces.** Every harness that seems to escape the
  per-turn output cap (Claude Code, pi) does so by never emitting one large
  output: each turn is a small tool call. Ours did the same for research and
  then demanded 2,520 probabilities in one `submit_forecast` call, most of a
  64k-token turn shared with the thinking budget. Now `submit_cells` is
  offered beside `submit_forecast` after the research floor; the model sends
  any subset of cells per call, as often as it likes (a later call for a cell
  replaces the earlier one), the runner keeps them and answers with what is
  still missing, and `submit_forecast` carries the rationale, the sources and
  any remaining cells. Rows record `delivery` (pieces, cells in the final).
- **"max" is max after all.** A first reading of litellm's constants said
  `reasoning_effort="max"` was an alias for a 16,384-token thinking budget.
  Probing the box's litellm (`AnthropicConfig.map_openai_params`) showed
  that alias applies only to models without adaptive thinking; for the
  Claude 5 family "max" is sent as `thinking: {type: adaptive}` plus
  `output_config: {effort: max}` -- Anthropic's own top setting, the model
  choosing how much to think each turn. So the setting stands. An explicit
  fixed budget remains available for experiments
  (`REDLINES_THINKING_BUDGET`), and would be a downgrade as a default.
  OpenAI models keep `xhigh`, their top rung.
- **Source quality.** Tavily `search_depth: "advanced"` (re-ranked,
  passage-level results); the prompt asks for key sources "only pages you
  read"; each row carries `unread_sources`, the cited URLs no `read_page`
  call fetched, so the paper can report how often a citation was read.

## Low-probability forecasting corpus

The Red Lines Graph 4 needs a corpus of genuinely **low-probability** questions
(~1-9% true base rate) with **ground-truth resolutions**, so we can measure model
calibration and skill *in the tail* — where the "ForecastBench low-probability bias"
(models over-forecasting rare events) shows up. Simulation worlds give this cleanly:
contamination-free, arbitrarily many resolutions, and a known generative process.

## FreeCiv world — cross-game base-rate mining (implemented)

**Substrate.** `forecastbench-sim` ships **1,019 recorded FreeCiv games**
(`data/games/seed*_data.json`). The generator emits ~25 question templates
(comparative / rank / milestone / event / state_check / continuous) with
deterministic resolutions per game.

**Where "low probability" comes from.** A single recorded game gives a deterministic
0/1 — no probability. The *true low probability* of a question **class** is its
**cross-game base rate**. We group binary forecasting questions by
`(template_id, target-item, horizon)` — e.g.

- "Will *Feudalism* be discovered by turn 70?"  (target = tech)
- "Will government = *Monarchy* at turn T?"      (target = government)
- "Will *Marco Polo's Embassy* be completed by turn 70?"  (target = wonder)

compute the yes-rate across all games, and select classes whose base rate falls in
the tail band. Each game is then a Bernoulli draw against its class base rate — which
is exactly Graph 4's decile-mean-vs-observed-frequency structure, with real ground
truth. Each corpus instance is tagged with `class_base_rate` (the climatology
reference for a Brier skill score, matching the demo's Graph-4 design).

**Reference run** (`code/mine_lowprob_corpus.py`, all 1,019 games, snapshot turn 40,
band 1-9%, min_n=40):

| metric | value |
|---|---|
| binary forecasting questions | 425,270 |
| question classes total | 564 |
| **tail classes selected (1-9%)** | **35** |
| **resolved low-prob instances** | **25,919** |
| distinct games | 1,018 |
| corpus overall observed yes-rate | 4.58% |
| class base-rate span | 1.0% – 8.2% |
| families | government_at 14,865 · tech_discovered 6,778 · wonder_completed 4,276 |

Thematically legible tail items include tech=Nuclear Fission (2.9%), tech=Atomic
Theory (1.5%), wonder=Cure For Cancer (3.3%), tech=Communism (1.2%).

**Knobs.** `--snapshot-turn` (lead time), `--rate-lo/--rate-hi` (tail band),
`--min-n` (support per class). Longer horizons (H1->H7) shift base rates lower.

**Why this beats blinded past-event protocols** (an earlier design the team considered): no web/news
leakage, contamination-free, arbitrarily many resolutions, and ground truth is known,
so we compute true calibration/BSS rather than only relative skill.

## Pandemic (Starsim) world — Monte-Carlo threshold events (scoped, fast follow)

**Thematically better** for a catastrophic-risk dashboard (deaths / epidemic severity
read as risk; FreeCiv wonders/techs do not), but **less turnkey**.

- **What it is.** Starsim SIR, 2 regions (Riverton / Southbay), 5,000 agents, 90 days,
  3 metrics (cumulative_cases, active_infections, cumulative_deaths). Snapshot day 20,
  horizons 40/60. Built primarily for **conditional/causal** forecasting (a vaccine
  intervention run as control-vs-intervention worlds).
- **Gaps for a low-prob corpus.** (1) Only 3 templates (comparative + continuous); no
  threshold/milestone template — needs a ~20-line "continuous metric >= X by day T"
  template. (2) Probability comes from **Monte Carlo over sim seeds** (fraction of
  stochastic runs where a threshold event occurs) — the *true* generative probability
  given world state, cleaner than FreeCiv's base-rate proxy, but requires running the
  sim many times rather than reading recorded games.
- **Validated (40-seed MC).** The sim is genuinely stochastic and the tail is tunable
  via threshold. Day 60: beta 0.03 -> deaths mean 53 (sd 8), P(deaths>65) ~ 5%;
  beta 0.065 -> mean 97 (sd 9), P(deaths>116) ~ 2.5%. Thresholds ~1.5-2σ above the
  mean land in the 1-9% band; 200-500 seeds pin base rates precisely.
- **Caveat.** At these betas the epidemic almost always takes off (~100%), so rareness
  must come from **severity thresholds** (rare = "unusually severe"), or from pushing
  beta near the epidemic threshold where some runs fizzle (bimodal take-off).
- **Unique upside.** The vaccine machinery yields **conditional** low-prob questions
  for free ("P(severe | vaccination campaign)" vs unconditional) — the bridge to the
  decision-uplift / conditional-forecasting line.

**Recommendation.** FreeCiv corpus first for the July-13 MVP (turnkey, huge N, no new
code). Add pandemic threshold + seed-sweep Monte-Carlo as a fast follow — more legible
substrate for the dashboard itself. Small build: one template + an MC harness.

---

## Graph 4 subsetting

**The ask.** DeepSeek-V3 is Graph 4's visible low outlier: near the middle of the ECI
ladder by capability, but the worst tail skill in the set by a wide margin. At the
2026-08-10 project call, the team flagged distillation/MoE architecture as
a live hypothesis for that gap, and the plan asked for two things: subset to
dense, non-distilled models declared **in data**, not hand-picked, and show both the
full set and the clean subset — silently dropping the one point that hurts the trend
is the first thing an adversarial reader would find.

**Architecture is declared in data, public facts only.** `redlines/registry.py`'s
model table carries an `architecture` field for every model, one of `dense`, `moe`,
`distilled`, or `undisclosed`. Nothing here is guessed:

- **DeepSeek-V3** → `moe` — its technical report documents the mixture-of-experts
  architecture.
- **Llama-3.3-70B** → `dense` — Meta's model card.
- **Every closed-vendor model** (OpenAI, Anthropic, Google, xAI) in the ladder →
  `undisclosed`. None of these labs publish architecture details; "undisclosed" is
  the honest label for that gap, not a stand-in for "probably dense."

**The exclusion rule.** `redlines/registry.py::CONFOUNDED_ARCHITECTURES = {"moe",
"distilled"}`. A model drops out of the clean-subset trend iff its declared
architecture is in that set. MoE and distillation are the two architectures with a
documented capability-to-behavior relationship that differs from a plain dense
transformer — exactly the shape of confound that can distort a capability-vs-skill
trend line. `undisclosed` models stay **in** the clean subset: the absence of a public
architecture claim is not evidence of a confounded one, and excluding on suspicion
rather than fact would just be guessing with extra steps. Today the rule excludes
exactly one model — DeepSeek-V3 — which is also the visible outlier.

**Both numbers, always.** `redlines.views.graph4.build()` computes the trend statistic
(Spearman ρ between ECI and Brier skill) twice: once over the full set, once over the
clean subset. Current values, from the two-sim (CivBench + Starsim) blob:

| set | n | ρ (ECI ↔ Brier skill) |
|---|---|---|
| full ladder | 14 | +0.85 |
| clean subset (dense + undisclosed) | 13 | +0.86 |

(2026-08-27: GPT-5.5, Gemini 3.1 Pro and Grok 4.20 joined the ladder — every model the
dashboard forecasts with is now on Graph 4. Before that the numbers were 11 / +0.88 and
10 / +0.93; the three newcomers sit in the crowded 154-159 band where rank order is
noisy, so the trend softened a little. See docs/model-set.md.)

Excluding DeepSeek-V3 strengthens the correlation, which is what you would expect if
MoE is a real confound rather than noise on one point. That is consistent with the
distillation/MoE hypothesis; it is not proof of it — one excluded model is not enough
to attribute the gap to architecture specifically rather than something else about
that model or its deployment.

**Nothing is silently dropped.** The dashboard always draws the full set. Excluded
points are marked — a hollow, dashed-ring marker instead of a filled one, plus a
legend entry ("◌ excluded from trend (MoE)") — rather than removed, and both ρ values
are shown side by side with a one-line note explaining the gap between them. The
exclusion is a stated finding on the chart itself, not an edit made before the reader
sees it. See `redlines/views/graph4.py::build()` (computes both series, tags every
model/scatter entry with `architecture`/`excluded`) and
`web/demo/40-graph3-graph4-charts.jsx::ECIScatter` (renders both).
