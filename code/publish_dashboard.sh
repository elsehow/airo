#!/usr/bin/env bash
# Rebuild the data-driven dashboard blobs from the accrued run log and publish
# the pages to nginx's docroot. Runs on the exe.dev box after each scheduled
# forecast run (see cron_run.sh); safe to run by hand.
#
# Only the run-log-driven views rebuild here (g1, g2, databank, timeline, axes,
# conditional, method -- the FAQ's live prompt and panel, rationales -- the
# "Why these forecasts?" explanations) plus the CSV export.
# Graph 3 and Graph 4 are frozen artifacts whose inputs (the ForecastBench
# tarball, the forecastbench-sim eval) live on the laptop; their blocks in the
# page pass through untouched, and refresh only when the laptop rsyncs new
# pages over.
#
# Serving: nginx serves DOCROOT for https://airo.forecastingresearch.org. REDLINES_REPO and
# REDLINES_DOCROOT override the defaults (tests point them at a temp dir).
set -euo pipefail

REPO="${REDLINES_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOCROOT="${REDLINES_DOCROOT:-/var/www/html}"

cd "$REPO"
# Validate the newest current-version date across the combined instrument and
# the headline log before rebuilding or touching nginx's last good files. The
# axes instruments left the schedule on 2026-09-14: their views draw the newest
# complete date they have, and a hand re-elicitation is audited separately
# (validate_launch_run.py --sets axes,paperaxes).
# The validator reports coherence warnings separately; only integrity errors
# block publication. Its diagnostic contains no provider traces or prompts.
LAUNCH_DATE="$(python3 - <<'PY_PREFLIGHT'
import json
from datetime import date
from pathlib import Path
from redlines.instrument import CURRENT_INSTRUMENT
from redlines.logs import iter_rows, log_exists
from redlines.runlog import load_runlog

paths = [Path('results') / 'conditional_runs_combined.jsonl']
rows = load_runlog(panel_only=False)
missing = []
for path in paths:
    if not log_exists(path):
        missing.append(str(path))
        continue
    rows.extend(iter_rows(path))
days = [date.fromisoformat(r['run_date']).isoformat() for r in rows
        if r.get('instrument_version') == CURRENT_INSTRUMENT and r.get('run_date')]
if missing or not days:
    diagnostic = Path('results/validation/latest-integrity.json')
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text(json.dumps({
        'instrument_version': CURRENT_INSTRUMENT,
        'passed_integrity_checks': False,
        'errors': [{'check': 'publication_preflight',
                    'detail': {'missing_files': missing, 'current_date_available': bool(days)}}],
    }, indent=2) + '\n')
    raise SystemExit('Publication withheld: missing current instrument data; see ' + str(diagnostic))
print(max(days))
PY_PREFLIGHT
)"
if ! python3 code/validate_launch_run.py --date "$LAUNCH_DATE" --out results/validation/latest-integrity.json; then
    echo "Publication withheld: integrity validation failed; currently served files are unchanged." >&2
    exit 1
fi
python3 -m redlines build --views g1,g2,databank,timeline,conditional,capability,axes,method,rationales,csv
# Atomic: copy beside the target, then rename, so a request that lands
# mid-publish never sees a truncated page or a half-written archive.
publish() { cp "$1" "$2.tmp" && mv -f "$2.tmp" "$2"; }
publish index.html "$DOCROOT/index.html"
# The page's static assets (FRI brand, 2026-09-08): the self-hosted Season
# Sans faces and the logo lockup, referenced from index.html as web/fonts/...
# and web/img/... .
mkdir -p "$DOCROOT/web"
cp -R web/img "$DOCROOT/web/"
# The fonts are not in the repository (see LICENSE-DATA); a checkout that
# has them (the serving box) publishes them, one without them falls back.
if [ -d web/fonts ]; then cp -R web/fonts "$DOCROOT/web/"; fi
# timeline.html was folded into index.html on 2026-09-08 (the Timeline is the
# Forecasts tab's lead panel). Links to the old URL land on the front page.
printf '%s\n' '<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=/"><title>Moved</title><a href="/">The timeline is now the front page.</a>' > "$DOCROOT/timeline.html"
# The dataset behind the pages (redlines/export.py), the "Download forecasts"
# button's target: every forecast from every model in every run.
publish results/forecasts.csv "$DOCROOT/forecasts.csv"
# ... and the rationales beside them (one line per call x question x
# condition; join on call_id + question_id + condition).
publish results/rationales.csv "$DOCROOT/rationales.csv"
# ... and the debriefs (2026-09-15; one line per call x question group).
if [ -f results/debriefs.csv ]; then publish results/debriefs.csv "$DOCROOT/debriefs.csv"; fi
# The Download button's target: everything, zipped (redlines/export.py::bundle_zip).
publish results/redlines-data.zip "$DOCROOT/redlines-data.zip"
echo "published -> $DOCROOT ($(date -u +%Y-%m-%dT%H%MZ))"
