#!/usr/bin/env python3
"""Preflight for the combined instrument: the capability conditions must quote
a recent Epoch ECI snapshot, and the condition sets must be generated from it.

code/cron_run.sh fetches Epoch's published scores (python3 -m redlines.eci
--fetch) and regenerates the sets before every run, so on a normal day the
snapshot is hours old. A failed fetch (Epoch down, the CSV reshaped) leaves
the previous snapshot in charge and pages the operator; the run goes ahead on
it while it is younger than --max-age-days (21: three weeks of failed fetches
is a problem a person must look at, not something to forecast through).
Until 2026-10-01 this gate checked a METR Streamlit scrape that the box could
not refresh, and it stopped the runs of 2026-09-23, -25 and -30.

    python3 code/check_eci_snapshot.py                    # 21-day gate
    python3 code/check_eci_snapshot.py --max-age-days 0   # today only
    python3 code/check_eci_snapshot.py --rebuild          # regenerate the sets first (the cron)
"""
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from redlines import eci  # noqa: E402

# The generators whose output quotes the snapshot, in dependency order.
GENERATORS = [
    ["code/make_eci_self_conditions.py"],
    ["code/make_eci_self_conditions.py", "--months", "6", "--out", "data/eci_self6mo_conditions.json"],
    ["code/make_combined_conditions.py"],
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=21,
                    help="fail when the newest Epoch snapshot is older than this (default 21)")
    ap.add_argument("--rebuild", action="store_true",
                    help="regenerate the condition sets from the newest snapshot before checking")
    args = ap.parse_args(argv)
    if args.rebuild:
        for cmd in GENERATORS:
            subprocess.run([sys.executable, *cmd], cwd=ROOT, check=True)
    try:
        day, path = eci.latest_published()
    except FileNotFoundError as e:
        raise SystemExit(f"ECI preflight failed: {e}")
    age = (date.today() - day).days
    if age > args.max_age_days:
        raise SystemExit(f"Epoch ECI snapshot is stale ({path.name}, {age} days old; max "
                         f"{args.max_age_days}). Fetch one: python3 -m redlines.eci --fetch")
    if age > 0:
        print(f"WARN: Epoch ECI snapshot is {age} day(s) old ({path.name}); "
              f"today's fetch did not land", file=sys.stderr)
    for cmd in GENERATORS:
        r = subprocess.run([sys.executable, *cmd, "--check"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"ECI preflight failed: {' '.join(cmd)} --check: "
                             f"{(r.stdout + r.stderr).strip()} (regenerate from {path.name})")
    top_day, top_score, top_model = eci.frontier_history(path)[-1]
    print(f"Epoch ECI snapshot: {day}; frontier {top_model} {top_score} ({top_day})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
