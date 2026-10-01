#!/usr/bin/env bash
# Scheduled forecast run. Lives on the box that serves airo.forecastingresearch.org, fired
# by cron — WEDNESDAYS AND FRIDAYS 12:00 UTC = 05:00 PT (twice weekly from
# 2026-09-16; Fridays only from 2026-08-14, Mondays before that) — and
# safe to run by hand for a one-off. The crontab is the authority on timing;
# this line is a comment and will drift if you let it.
#
# WHY THIS EXISTS
#   Graph 1 becomes the dashboard's headline only once several months of
#   forecasts have accrued (2026-08-10 call). That is the one deliverable whose
#   cost is elapsed time rather than effort, so the job starts now — months
#   before the over-time view it feeds is due. The unified-batch cutover
#   (2026-08-14) retired the earlier series, so the Timeline panel is rebuilding
#   from one snapshot and every run from here is load-bearing.
#
# WHAT IT RUNS
#   The WHOLE question set, in one call per model (code/run_unified.py
#   --joint), with NO relation between the questions stated in the prompt --
#   coherence is measured afterwards, never bought. The set is 37 questions in
#   5 groups (four AI incident types x 8 severity rungs, plus five
#   cross-cutting questions -- the extinction pair since 2026-09-15) over six horizons -- two of them ROLLING, so each
#   run stamps an absolute resolves_on per row. ONE call per model since
#   2026-09-02 (--repeats 1): the same-day repeats that preceded it measured a
#   re-asking spread nobody read as accuracy, and their budget went to the
#   agentic harness instead. The views draw no interval on a single-draw day.
#
# WHICH MODELS
#   THE PANEL (2026-08-28): run_unified.py --model-set defaults to eci_topk,
#   the four highest-ECI models the registry can run, re-ranked each run from
#   the newest data/epoch_capabilities_index_*.csv (redlines/eci.py). The run
#   prints the snapshot's date and age. Rows stamp panel={set,k,snapshot}. The
#   frontier five the series ran on until then are `--model-set frontier5`.
#   SINCE 2026-10-01 THE SNAPSHOT IS FETCHED HERE, before every run, from
#   Epoch's published scores (python3 -m redlines.eci --fetch), and the
#   capability conditions are regenerated from it -- no hand step between a
#   model shipping and the panel and prompt knowing it. A new model the index
#   ranks into the panel that the registry has no row for is skipped (the next
#   runnable one takes the seat) and paged: add its row to redlines/registry.py.
#
# ALERTS (2026-10-01): with NTFY_TOPIC set in the env file, a failed run, a
#   failed fetch, a failed publish, a panel change and an unrunnable model at
#   the top of the index each push one line to https://ntfy.sh/$NTFY_TOPIC
#   (the ntfy app, subscribed to that topic). A finished run pushes a quiet
#   one too, so silence on a Wednesday or Friday afternoon means the box or
#   cron itself is down. The topic lives only in the env file: anyone who
#   knows it can read the channel, so messages say what failed, never data.
#
# OUTPUT
#   One dated file per run under results/runs/. Never appends to the shared
#   results/forecast_runs.jsonl: this box's checkout is rsynced from a laptop,
#   and two writers on one tracked file means a merge conflict every week.
#   redlines/runlog.py::load_runlog() reads the log and this directory.
#
#   Pull them down with:
#     rsync -avz <box>:Projects/redlines/results/runs/ results/runs/
#   and the inputs the run quoted (the fetched index and the sets built from it):
#     rsync -avz '<box>:Projects/redlines/data/epoch_capabilities_index_*.csv' data/
#     rsync -avz <box>:Projects/redlines/data/{eci_self_conditions,eci_self6mo_conditions,combined_conditions}.json data/
#
# SETUP
#   Keys live in ~/.config/redlines/env (mode 600), one KEY=value per line:
#   ANTHROPIC / OPENAI / GEMINI / GOOGLE / XAI / TAVILY (METACULUS is no
#   longer read; the lookup left the toolset on 2026-09-02). They are
#   sourced into the environment here; redlines.llm.load_keys() reads the SAME
#   file (and never overrides a variable already set), so the run works whether
#   or not this script sourced it first.
#
#   PY just has to be an interpreter with litellm — `pip install -e '.[acquire]'`
#   in any venv. It points at the xrisk-canaries venv on this box only because
#   that is where litellm was already installed; override with REDLINES_PY.
set -euo pipefail

# The repo is wherever this script lives; PY is any interpreter with litellm
# (`pip install -e '.[acquire]'`): the repo's own venv when there is one, else
# whatever REDLINES_PY names.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${REDLINES_PY:-}" ] && [ -x "$REPO/.venv/bin/python" ]; then
    REDLINES_PY="$REPO/.venv/bin/python"
fi
PY="${REDLINES_PY:-$HOME/Projects/xrisk-canaries/.venv/bin/python}"
ENVFILE="$HOME/.config/redlines/env"

STAMP="$(date -u +%Y-%m-%dT%H%MZ)"
OUT="$REPO/results/runs/$STAMP.jsonl"
LOG="$HOME/logs/forecast-$STAMP.log"
mkdir -p "$REPO/results/runs" "$HOME/logs"

exec >>"$LOG" 2>&1
echo "=== $STAMP  scheduled run ==="

# notify TITLE MESSAGE [PRIORITY] [TAGS] -- one line to the operator's phone.
# A no-op without NTFY_TOPIC; a failed push is logged, never fatal.
notify() {
    [ -n "${NTFY_TOPIC:-}" ] || return 0
    curl -fsS -m 20 -H "Title: $1" -H "Priority: ${3:-default}" -H "Tags: ${4:-}" \
        --data-binary "$2" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null \
        || echo "WARN: ntfy push failed: $1"
}
# Any exit before the end is a failed run: page with the log's last lines.
FINISHED=0
on_exit() {
    local rc=$?
    if [ "$FINISHED" != 1 ]; then
        notify "AIRO run $STAMP FAILED" "exit $rc on $(hostname). $(grep -E 'FATAL|Error|failed|stale' "$LOG" | tail -3 | cut -c1-200)
log: $LOG" high rotating_light
    fi
}
trap on_exit EXIT

if [ ! -r "$ENVFILE" ]; then
    echo "FATAL: $ENVFILE missing or unreadable — no API keys, nothing to do."
    exit 1
fi
set -a; . "$ENVFILE"; set +a

cd "$REPO"

# THE ECI SNAPSHOT (2026-10-01): fetch Epoch's index, then rebuild the
# capability conditions from it -- the frontier history the prompt quotes.
# A failed fetch keeps the previous snapshot and pages; the runner's
# preflight (code/check_eci_snapshot.py) still refuses one older than 21 days.
panel_labels() {
    "$PY" -c 'from redlines import registry; print(", ".join(m["label"] for m, _ in registry.panel()))'
}
PREV_PANEL="$(panel_labels 2>/dev/null || true)"
if ! "$PY" -m redlines.eci --fetch; then
    notify "AIRO: Epoch ECI fetch failed" "Run $STAMP goes ahead on the previous snapshot. Check https://epoch.ai/data/eci_scores.csv" high warning
fi
"$PY" code/check_eci_snapshot.py --rebuild
PANEL="$(panel_labels)"
UNRUNNABLE="$("$PY" -c 'from redlines import registry; print("\n".join(w for w in registry.panel_warnings() if "cannot run" in w or "panel is short" in w))')"
echo "panel: $PANEL"
if [ -n "$PREV_PANEL" ] && [ "$PANEL" != "$PREV_PANEL" ]; then
    notify "AIRO panel changed" "Was: $PREV_PANEL
Now: $PANEL" default busts_in_silhouette
fi
if [ -n "$UNRUNNABLE" ]; then
    notify "AIRO: index model with no registry row" "$UNRUNNABLE" high warning
fi
# ONE call per model, every question. The second command that used to run here
# forecast XPT question #2 (a natural pandemic), which was held out of the batch
# because it nested under no rung of the bio ladder. The Auto-ARC set retired
# that question and holds nothing out — config.UNBATCHED is empty — so the
# command is gone, along with code/run_forecasts.py, which imported a
# STABLE_SUBSET that no longer exists and would now fail on import.
# THE SINGLE INSTRUMENT (2026-08-27, --joint): each call answers every cell
# unconditionally AND under each condition of the set. The unconditional
# slice lands in $OUT (this series); the whole instrument is appended to
# results/conditional_runs_<slug>.jsonl for the conditional panels. The plain
# batch (--unconditional N) is deprecated.
# THE COMBINED INSTRUMENT (2026-08-28 evening): the LEAP policies AND the
# six-month capability conditions in one call, on THE PANEL (the four highest-
# ECI models; --model-set defaults to it). 2,520 probabilities a call, so two
# workers (three rate-limit the Anthropic endpoints when anything else runs on
# this box) and a 30-minute request timeout (GPT-5.5 Pro overran litellm's
# ten in the pilot).
# ONE ELICITATION PER MODEL since 2026-09-02 (a project decision): the repeats
# bought a re-asking spread nobody reads as accuracy, and the budget goes to
# the agentic harness instead -- every model now searches iteratively and
# reads pages (redlines/tools.py, MAX_ROUNDS in run_unified.py), so a
# call is longer and dearer than it was. 4 models x 1 = 4 calls. The views
# draw no interval on a single-draw day; the dots and the median are the
# reading.
export REDLINES_LLM_TIMEOUT="${REDLINES_LLM_TIMEOUT:-1800}"
# The runner exits non-zero when any panel model fails (the date cannot
# publish without all of them), which under `set -e` stops this script before
# the axes instruments spend on a date that will not publish. Its preflight
# also refuses an Epoch snapshot older than 21 days or condition sets not
# built from the newest one (code/check_eci_snapshot.py).
if ! "$PY" code/run_unified.py --joint --repeats 1 --workers 2 \
        --conditions data/combined_conditions.json --out "$OUT"; then
    echo "FATAL: the combined instrument did not complete for every panel model; see above. Skipping the axes instruments and publication."
    exit 1
fi

# A run that produced nothing is a failure worth seeing in the log, not an
# empty file that quietly widens a gap in the time series.
if [ ! -s "$OUT" ]; then
    echo "FATAL: no rows written — removing empty $OUT"
    rm -f "$OUT"
    exit 1
fi
echo "=== done: $(wc -l < "$OUT") rows -> $OUT ==="

# THE AXES INSTRUMENTS (2026-09-03, the FRI economist's spec of 2026-09-02) --
# the same questions at 2030/2050/2100 only, conditional on FIXED levels of an
# x-axis quantity (data/axes_conditions.json for the dashboard's scatter
# panels, data/paper_axes_conditions.json for the paper's figure) -- ran here
# after the combined instrument from 2026-09-03 to 2026-09-14, about $60 and
# $100 a run. LEFT THE SCHEDULE on 2026-09-14 (project decision): they are
# not re-elicited on every run, and the axes panel keeps drawing the newest
# complete axes date. To re-elicit one by hand on this box:
#     "$PY" code/run_unified.py --joint --repeats 1 --workers 2 \
#         --conditions data/axes_conditions.json
# (rows go to results/conditional_runs_<slug>.jsonl and results/<slug>_runs/,
# never into results/runs/), then audit that date with
# code/validate_launch_run.py --sets axes and run code/publish_dashboard.sh.

# Republish the dashboard with the new data point. A publish failure must not
# mask the successful run above — log it and carry on.
if ! "$REPO/code/publish_dashboard.sh"; then
    echo "WARN: publish_dashboard.sh failed — the last successful dashboard publication remains served"
    notify "AIRO run $STAMP: publish FAILED" "The forecasts ran ($(wc -l < "$OUT") rows) but the dashboard was not republished. log: $LOG" high warning
    FINISHED=1
    exit 0
fi
FINISHED=1
notify "AIRO run $STAMP published" "$(grep -E 'ok, [0-9]+ failed' "$LOG" | tail -1 | sed 's/ -> .*//'). Panel: $PANEL" low white_check_mark
