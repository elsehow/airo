# LEAP Wave 13: the ensemble's forecasts for a data-warehouse survey

`fri_forecaster/leap.py` runs a LEAP survey through the same harness and the same
ensemble rule as the ForecastBench round: each member of the panel (the top 4 by ECI)
forecasts every cell, and `build` takes the per-cell mean. It was written for Wave 13
(46 forecast cells in 8 question groups; two open-ended groups are not forecast) and
brought into this repository from agent-box's `w13-leap` branch on 2026-10-19.

## What it does

- **Snapshot.** `scripts/leap_questions.py <survey_id> > questions.json` dumps the
  survey's rows from the warehouse mart `mart_survey_question` (BigQuery, ADC
  credentials) into one JSON file, pinned into the run root like a ForecastBench question
  set. Groups carry their text, background, resolution criteria, unit, scenario and
  `survey_end_date`; questions their dimension, percentile and resolution date.
- **Run.** `leap.py run --root R --model <pi id>` forecasts the survey with one member, in
  one of two shard modes. `group` (the submission format): one pi call per question
  group, in dependency order; the revenue group gets the independence group's frozen
  cells in its prompt. `session` (a cross-check): the whole survey in one call. There is
  no system prompt: the instrument is the prompt, plus `MECHANICS` (the cell format,
  percentile ordering, 0-100 for probabilities). Resumable per member, like the
  ForecastBench driver; a member's manifest pins its settings.
- **Build.** `leap.py build --root R --member <pi id> ...` writes
  `<survey_source_id>.<shard>.mean.json` (per-cell mean, with each cell's members) and a
  `.provenance.json` with every member's value.
- **Findings.** `scripts/leap_panel.py <root> <out.html>` renders a static page: the
  ensemble against the single best model, bloc structure, shard agreement.

## Wave 13: done, not submitted

The runs are complete: four members (Opus 5.5, GPT-6 Astra, GPT-6.1 Sol, Fable 5.1) in
both shard modes, 46 of 46 cells each, about $96 of API spend. Findings: the ensemble
sits above Opus 5.5 alone on 43 of 46 cells (both GPT-6 models bullish, both Claude
models conservative); session mode adds nothing measurable and costs about four times
as much; percentile-order violations occur in both modes (no validator, by design; a
point for the survey's owners).

The group-shard mean is the submission candidate. **The submission path is not
started.** The warehouse ingests LLM forecasts as NDJSON from the forecaster bucket in
the `dwh-llm-forecaster` project (see that repository's README: one row per question
per model run, `run_id`, `run_timestamp`, `sample_index`, `prompt_template_name`), and
it keys every row on a `model_run_key` from the shared fri-utils registry, ignoring the
model columns. That registry holds single models only, so an anonymous ensemble needs
an entry of its own before it can be ingested. Also open: write access to the bucket,
and the agreement that "top 4 by ECI" is the ensemble to submit. The human deadline was
2026-10-20, with extensions to 2026-10-26.

The run data (member results, aggregates, the findings page, and the full pi traces)
stays off this repository: unpublished forecasts of a live survey. It lives on the
machine that ran it (`~/Projects/leap-w13-runs/main`, 140 MB) with a smaller copy of the
results and aggregates beside the agent-box worktree's `handoff/` folder.

## From the agent-box branch

Taken: `leap.py`, `scripts/leap_questions.py`, `scripts/leap_panel.py`. Not taken: its
`eci.py` port (superseded by `fri_forecaster.eci`, PR #13), its `harness_retry` and the
clean-`HOME` billing guard (both ported to the harness itself in PR #16: `harness.run`
retries a call that ended in a provider error, and pi is billed to API keys only).
