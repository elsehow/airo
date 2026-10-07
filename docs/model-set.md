# Model set, ECI spread, access & budget

The Red Lines ECI plot correlates each model's accuracy on the simulated
low-probability corpus against its **ECI** (Epoch AI Capabilities Index). So every
model on the plot must have a known ECI, and a good demo needs a *spread* of ECIs.

 ## ECI source

ECI = **Epoch AI Capabilities Index**. The single source of truth is
`redlines/eci.py`, which reads the dated snapshots under `data/`:

    data/epoch_capabilities_index_2026-07-07.csv   # 188 models, ECI 64 -> 161 -- PINNED (Graph 4's vintage)
    data/epoch_capabilities_index_2026-08-21.csv   # Epoch's raw export, 200 models (the trend / projection input)
    data/epoch_capabilities_index_2026-08-28.csv   # top 17, retrieved by hand
    data/epoch_capabilities_index_2026-09-08.csv   # top 6, transcribed by hand from the Epoch leaderboard -- the NEWEST

Two vintages, two jobs. `eci.PINNED` (2026-07-07) is what every registry row's
`eci` field reads, so Graph 4's ladder and every tracked artifact stay
byte-identical until someone refreshes the pin on purpose and re-baselines
`tests/`. `eci.latest()` — the newest file by the date in its name — is what
**the model panel is selected from** (below). Both formats are read (the
leaderboard's `rank,model,eci,ci_low,ci_high,retrieved`, and Epoch's raw
per-variant export, best variant per model name). Nothing is hand-copied.

**Staleness WARN.** A panel chosen from an old index is a stale panel. Anything
that selects the panel (`run_unified.py`, `python3 -m redlines.registry`,
`python3 -m redlines.eci`) prints `WARN: ECI snapshot … is N days old (> 31)`
once the newest snapshot is more than `eci.STALE_AFTER_DAYS` = 31 days old, with
the URL to retrieve a new one and the filename to save it as. Retrieving is
still by hand: save the leaderboard (or Epoch's export) as
`data/epoch_capabilities_index_<today>.csv` and the WARN goes away; the next
run re-ranks on it.

(Earlier CivBench "estimates" are superseded; a few differed materially, e.g.
Opus 4.6 156 official vs 152 est.)

## The model panel: top-k by ECI (since 2026-08-28)

The forecast panel is **not a hand-typed list**. `redlines.registry.panel()`
is the `PANEL_K` = 4 highest-ECI models in the newest snapshot that the
registry can run (has a row for), re-ranked every time it is asked for — the
rule measured in an internal FRI analysis (`forecastbench-ensembling`, not published; see
`docs/eci-top4-arm.md`): average the top 3–4 by ECI; the specific list goes
stale fast, so never inherit one. On the 2026-08-28 snapshot that was
Fable 5 (162), GPT-5.5 Pro (162), Opus 5 (162), GPT-5.6 Sol (161); on the
2026-09-08 snapshot it is GPT-6 Astra (167), Fable 5.1 (164), Opus 5 (163),
GPT-5.5 Pro (162).

**One seat per family (since 2026-09-08).** Two versions of one model are one
opinion twice, so a model whose `family` (a hand-assigned column on
`registry._ROWS`) already holds a seat is passed over with a WARN naming it
and the next runnable model takes the seat: Fable 5 (163) sits behind
Fable 5.1 on the 2026-09-08 index. Families are the lines whose versions
supersede one another -- Claude's tiers each their own (Fable, Opus, Sonnet,
Haiku); OpenAI's plain GPT-n one line, the Pro tier another, and the
code-named GPT-5.6 Sol / GPT-6 Astra each their own, which is why Astra sits
beside GPT-5.5 Pro. That assignment is a judgement, made in the registry and
nowhere else. GPT-5.5 Pro and GPT-5.6 Sol tie at 162 on that index; Epoch's
rank order (Pro first) breaks it, and the WARN says so.

**GPT-6 Astra runs through litellm's Responses bridge** (`openai/responses/gpt-6-astra`):
on `/v1/chat/completions` OpenAI refuses function tools for it under any
`reasoning_effort`, and the grounding tools are the point.

- `run_unified.py --model-set` defaults to `eci_topk`; the cron therefore runs
  the panel. Rows stamp `panel: {set, k, snapshot}` so a panel change is
  legible in the series. `frontier5` (Fable 5 / GPT-5.5 / Opus 4.8 /
  Gemini 3.1 Pro / Grok 4.20) survives as a named set: the panel the series
  ran on until then.
- **A model the index ranks above the cut with no row gets one on its own
  (since 2026-10-07).** After the fetch, `python3 -m redlines.autoreg` finds
  its provider from Epoch's `Organization`, matches the display name to
  exactly one API id from that provider's model list ("GPT-6.1 Sol" =
  `gpt-6.1-sol`; a trailing date, "preview" or "latest" allowed), probes it
  with one tool-call request through the harness's own request path, and
  records the row in `data/auto_models.json`, which the registry reads after
  `_ROWS`. Label, family and color follow the hand rows: the name without
  "Claude ", the name without version numbers (so GPT-6.1 Sol shares
  GPT-5.6 Sol's `gpt-sol` seat rule), and the spare color farthest from the
  panel it joins, chosen once and kept. GPT-6.1 Sol, third on the 2026-10-07
  index, sat out that day's run for want of a row; this is why. Only a model
  that cannot be matched or fails the probe is skipped with a WARN — a
  `_ROWS` entry for it then takes its seat next run, and a hand row always
  wins over an automatic one. A tie at the cut is broken by Epoch's rank
  order and WARNed.
- Every registry row carries a color, so any row the index promotes can be
  drawn. `model_colors()` lists the panel first, in its own colors, then every
  other model by ECI in the one retired gray (`RETIRED_COLOR`; decided
  2026-09-08: the same colors on every chart, deprecated models gray). A
  model that leaves the panel keeps its rows: the Timeline draws its points
  in gray and names it on hover; the latest-reading views (Graph 1, the data
  bank) take the newest run's panel through `runlog.current_rows()`.
- The Graph-4 ladder is untouched: its ECI is the pinned vintage, and the
  2026-08-28 panel members are deliberately not on it (a later vintage on the
  same trend line would compare two indices).

## Reachability (verified 2026-07-07 via live inference)

Keys loaded, at the time, from a GCP Secret Manager project via `load_api_keys_from_gcp()`
for OpenAI/Anthropic/Google/Together/xAI, with DeepInfra/Fireworks direct in `.env`
(today every key comes from `~/.config/redlines/env`; see the README).
**Confirmed running:** claude-fable-5 (161), gpt-5.5-pro (161), gpt-5.5 (159),
claude-opus-4-8 (158), gpt-3.5-turbo (114), DeepSeek-V3 (133, deepinfra),
Llama-3.3-70B (127, deepinfra). Harness note: fable-5 / gpt-5.5.x reject `temperature`
-> `litellm.drop_params=True`; gpt-5.5-pro is slow (~16s/call) so **claude-fable-5 is
the 161 anchor**.

## Chosen demo set — official ECI, verified reachable (114 -> 161)

Base set (9 models): GPT-3.5 (114) · Llama-3.3-70B (127) · GPT-4o (129) ·
DeepSeek-V3 (133) · Sonnet 4.5 (147) · GPT-5 (150) · Opus 4.6 (156) · Opus 4.8 (158) ·
Fable 5 (161, high anchor). Official spread has a **133 -> 147 gap**.

Recommended +2 gap-fillers (`GAP_FILLERS` in `code/eci_scores.py`) for an even ladder:
GPT-4.1 (137) · Haiku 4.5 (143) -> **11 models, evenly spaced 114 -> 161**. Both cheap.

**2026-08-27 — the whole frontier five is on the ladder.** GPT-5.5 (159), Gemini 3.1
Pro (155) and Grok 4.20 (154) were run through both simulators (same 150 CivBench
games / 1,739 questions, seed 42; same 250 Starsim runs) and merged into
`results/eval_full.json` and `results/pandemic/smoke_preds.json`, so every model the
dashboard forecasts with also appears on Graph 4 -> **14 models, 114 -> 161**. They
carry the `g4_ladder` + `pandemic_smoke` roles in `redlines/registry.py`. Both runners
take `--models` to add a model without re-running the rest (`run_eval.py --out` and
`pandemic_smoke.py --out` to a side directory, then merge by `(game_id, question_id)`).

## Access

`forecastbench-sim/.env` active keys = GCP creds + DeepInfra + Fireworks. The
OpenAI / Anthropic / Google / Together keys load from **GCP Secret Manager** via
`fbsim_core.evaluation.models.load_api_keys_from_gcp()` (GOOGLE_CLOUD_PROJECT set).
All chosen models are reachable this way (the frontier ones were already run by the
team). Open-weight swaps go direct via DeepInfra / Fireworks / Together.

## Budget (ceiling $150)

The eval **batches all of a game's low-prob questions under one ~6k-token world
report** (`build_batch_prompt`), so cost scales with **# games sampled**, not #
questions (25.9k).

- Full corpus (1,018 games) × frontier 5 ≈ $200-250+ (GPT-5/Opus reasoning tokens
  dominate) — over budget.
- **Plan: stratified-sample ~150 games** (preserving the 35 tail classes) -> ~4k
  low-prob instances/model, ~150 report-prompts/model. Est. **~$25-60 total** for the
  widened set (weak models are cheap; only the frontier models cost). Cap output ~2k,
  meter spend. Headroom to scale to ~300 games if the scatter needs more density.

## A third ECI vintage: the conditional benches' roster

Graphs 5 and 6 (`docs/conditional-benches.md`) put 24 models on an ECI axis
read from `data/causal/models.csv` — the Epoch index as published on
2026-08-27, resolved to OpenRouter ids for the causal bench and locked with
its dataset. `redlines/roster.py` is the one reader. It is neither the
2026-07-07 vintage Graph 4 is pinned to nor the newest snapshot the panel is
chosen from, and it is deliberately not re-derived from either: the newest
snapshot is a leaderboard top-17 that does not reach the roster's weaker
models, and recomputing the roster's values would move a published headline.
The gaps are fractions of a point (Fable 5: 162.49 vs 162 vs the pinned 162)
and each chart names its vintage.

## Graph 4 and the panel (2026-08-28 evening)

Decision: Graph 4 gets Opus 5 and GPT-5.6 Sol. Both now carry
`g4_ladder` + `pandemic_smoke` in `redlines/registry.py` and were run through
both simulators exactly as the rest of the ladder (the same 150 CivBench
games / 1,739 questions, seed 42; the same 250 Starsim runs), then merged with
`code/merge_graph4_run.py --tag panel2`. Their ECI on Graph 4's axis is the
newest snapshot's (Opus 5 162, Sol 161), not the pinned 2026-07-07 vintage
(neither model existed then) — a mixed-vintage point or so, stated here rather
than hidden. GPT-5.5 Pro, the panel's fourth member, stays off Graph 4: at
$30/$180 per million tokens the two simulators would cost ~$100–250.

The Secret Manager copy of the Anthropic key that `fbsim_core`'s
`load_api_keys_from_gcp` loads was stale on 2026-08-28 (401); the harness
skips a key already in the environment, so export a working
`ANTHROPIC_API_KEY` (from `~/.config/redlines/env`) before running
`code/run_eval.py` or `code/pandemic_smoke.py`.
