# fri_forecaster: a ForecastBench round, end to end

`scripts/fb_round.sh <due date>` runs one ForecastBench round unattended: it waits for the
question set, has every model forecast every question through pi, combines the models'
forecasts into the sets you submit, and reports what it cost. What it submits comes from
a **name registry**; how the machine is set up comes from **`round.env`**. Both are
private and live outside the repo (`~/.config/fri-forecaster/`); `examples/` shows their
shape.

```
 Epoch's ECI ──> pick models ──> registry: conditions, their members, a fingerprint
                 (once, when a                     │
                  configuration is registered)     │
                                                   ▼
 round day:  1 check   each condition's name still matches the code, or stop
             2 wait    for <due>-llm.json in forecastbench-datasets
             3 ECI     re-read the ranking; warn if a condition's models moved
             4 run     each member forecasts every question: one pi call each
             5 build   each condition = the mean of its members' forecasts
                       ──> <due>.<team>.<N>.json, ready to upload
             6 report  summary.txt: coverage, files, API cost per member
```

## 1. Picking models by ECI

A **condition** is a rule for what to submit, defined by rank on Epoch's ECI (Epoch
Capabilities Index). The example registry has three:

| condition  | members                          | research |
|------------|----------------------------------|----------|
| `ensemble` | the top 4 models by ECI          | yes      |
| `unaided`  | the same 4 models                | no       |
| `solo`     | the top model by ECI             | yes      |

The pick happens **once, when a configuration is registered**, not every round. The
registry entry records why in its `reason` (e.g. which Epoch snapshot the pick came
from), each member in fri-utils'
`ModelRun` shape (model, provider, thinking level, tools, the one-shot baseline's
`model_run_key`), and a fingerprint of the code that shapes forecasts: the system prompt,
the question prompt and the tool descriptions.

A configuration gets a leaderboard name, `<condition>-<place>` (e.g. `ensemble-oak`), and
a registered entry is never edited. When anything that changes forecasts changes
(members, thinking, prompts, tools, the pi version), the condition moves to the next
place in the registry's list. So a leaderboard name always means exactly one
configuration, and places carry no rank: a later configuration never reads as an
upgrade.

```sh
python -m fri_forecaster.names show                  # each condition's current name
python -m fri_forecaster.names current ensemble      # its name, or exit 1 if the code drifted
python -m fri_forecaster.names fingerprint ensemble  # for registering a new name
```

## 2. The round

**Check.** Before anything runs, every condition's registered fingerprint is compared
with the code. A mismatch stops the round (exit 3) and names the place to register next.

**Wait.** The question set `<due>-llm.json` appears in
[forecastbench-datasets](https://github.com/forecastingresearch/forecastbench-datasets)
at 00:00 UTC on the due date. The script polls every two minutes and gives up at
`WAIT_UNTIL` (08:00 UTC by default).

**ECI.** `fri_forecaster.eci` fetches Epoch's published index and ranks it (the same
module AIRO's panel is chosen from; `python -m fri_forecaster.eci --fetch --names`), or
`eci_ranked`, a function `round.env` may define, prints the ranking instead. If a
condition's members are no longer the top N, the round says so in its log and summary.
It does not swap models: a new top N is a new configuration, registered under the next
place.

**Run.** A **member** is one model at one thinking level, with research on or off. The
three conditions above need 8: four models with research, the same four without (solo's
model is one of the four). Each member forecasts every question in the set (about 500)
with `forecastbench run`, one pi call per question
([the call itself](../README.md#how-it-works)):

- a market question gets one forecast; a dataset question one per resolution date;
- research members get `web_search` and `read_page` and must make 2 successful research
  calls before `submit_forecast` unlocks; others get only `submit_forecast`;
- every member writes `manifest.json` with its settings, and resuming under different
  settings is refused;
- research members run in parallel, then the others; a second pass retries whatever the
  first left unanswered.

**Build.** Each condition becomes one forecast set: per question and resolution date, the
mean of its members' forecasts. A set covering less than 95% of the market questions or
of the dataset questions is written but marked not ready (`build` exits 1). The upload
looks like this:

```json
{
 "organization": "<team>",
 "model": "ensemble-oak",
 "model_organization": "<team>",
 "question_set": "2026-10-11-llm.json",
 "forecasts": [
  {"id": "SPY", "source": "yfinance", "forecast": 0.58, "resolution_date": "2026-11-10", "reasoning": null},
  {"id": "42666", "source": "metaculus", "forecast": 0.31, "resolution_date": null, "reasoning": null}
 ]
}
```

**Report.** `summary.txt`: the ECI check, coverage for each set, the files to upload, and
API cost per member.

## On disk

```
<ROUNDS_DIR>/<due>/
  question_set.json                       the round's questions, fetched once
  members/<model>--<thinking>--<research|noresearch>/
    manifest.json                         the member's settings, pinned
    results.jsonl                         one line per question answered
    calls/<source>__<id>/attempt-N/       one pi call's inbox and outbox
  <due>.<team>.<N>.json                   forecast set N, ready to upload
  <due>.<team>.<N>.json.provenance.json   its members and how they were combined
  logs/  summary.txt
```

## Setup

Copy `examples/round.env.example` to `~/.config/fri-forecaster/round.env` and set
`FB_ORG` (the team name ForecastBench assigned) and `FORECASTER_NAMES` (the registry). API
keys go in `~/.config/fri-forecaster/env`. Every call is billed to API keys: the harness
refuses an agent folder that holds a `pi /login`, drops bearer and OAuth tokens from pi's
environment, and requires the model's provider key.

```sh
SAMPLE=8 scripts/fb_round.sh 2026-10-11 rehearsal   # a cheap end-to-end check on a past set
scripts/fb_round.sh 2026-10-25                       # the real round
```

## Modules

| file               | what it does                                                      |
|--------------------|-------------------------------------------------------------------|
| `harness.py`       | one pi call: inbox, run, outbox, evidence and usage, merged answer |
| `pi_tools.ts`      | the pi extension: research tools, submit tools, research floor    |
| `tools.py`         | `web_search` / `read_page` (Tavily), stdlib only                  |
| `tool_cli.py`      | the research tools as a CLI for `pi_tools.ts`; backs off on 429s  |
| `keys.py`          | API keys from the environment or an env file                      |
| `forecastbench.py` | the ForecastBench driver: members (`run`) and sets (`build`)      |
| `names.py`         | the name registry: conditions, members, fingerprints              |
| `leap.py`          | a LEAP survey from the data warehouse, per member, and its mean ensemble (docs/leap-w13.md) |
