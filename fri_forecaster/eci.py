#!/usr/bin/env python3
"""Epoch Capabilities Index: fetch, rank, top-k. Ported from airo/redlines/eci.py.

    python3 -m fri_forecaster.eci [K]     # the current top K (default 4)

The published index (https://epoch.ai/data/eci_scores.csv) is the source of
truth, FETCHED never hand-copied. best_model(): one row per model (the top
variant when the CSV carries per-variant rows). A snapshot older than
STALE_AFTER_DAYS days prints a warning; --fetch refreshes.
"""
import csv
import io
import json
import sys
import urllib.request
from datetime import date, datetime

SCORES_URL = "https://epoch.ai/data/eci_scores.csv"
CACHE = "~/.cache/fri-forecaster/eci_scores.csv"
STALE_AFTER_DAYS = 31
TOP_VARIANTS = False   # True: per-variant rows are separate members


def _path():
    import os
    return os.path.expanduser(CACHE)


def fetch():
    """Download the published index to the cache; returns rows (dicts)."""
    with urllib.request.urlopen(SCORES_URL, timeout=60) as r:
        text = r.read().decode()
    import os
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    open(_path(), "w").write(text)
    return parse(text)


def parse(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        try:
            out.append({"model": r.get("Model") or r.get("model"),
                        "display": r.get("Display name") or r.get("display_name") or r.get("Model"),
                        "eci": float(r["eci"]), "date": r.get("date"), "org": r.get("Organization")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def rows(refetch=False):
    import os
    if refetch or not os.path.exists(_path()):
        return fetch()
    return parse(open(_path()).read())


def best_model(rows_):
    """One entry per model: its best variant (per-variant rows collapse)."""
    best = {}
    for r in rows_:
        k = r["model"] or r["display"]
        if k not in best or r["eci"] > best[k]["eci"]:
            best[k] = r
    return sorted(best.values(), key=lambda r: -r["eci"])


def stale_after_rows(rows_):
    dates = [r["date"] for r in rows_ if r.get("date")]
    if not dates:
        return None
    newest = max(datetime.strptime(str(d)[:10], "%Y-%m-%d").date() for d in dates)
    return newest, (date.today() - newest).days


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    k = int(args[0]) if args and args[0].isdigit() else 4
    refetch = "--fetch" in args
    rows_ = rows(refetch=refetch)
    if not TOP_VARIANTS:
        rows_ = best_model(rows_)
    age = stale_after_rows(rows_)
    if age and age[1] > STALE_AFTER_DAYS:
        print(f"WARNING: ECI snapshot is {age[1]} days old ({age[0]})", file=sys.stderr)
    out = [{"rank": i + 1, "eci": r["eci"], "model": r["model"], "display": r["display"], "org": r["org"]}
           for i, r in enumerate(rows_[:k])]
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
