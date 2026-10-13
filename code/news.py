#!/usr/bin/env python3
"""The news-story pipeline (redlines/news.py), step by step.

    python3 code/news.py poll              # fetch every feed once; free, no keys
    python3 code/news.py reduce            # fold new items into stories (Jev)
    python3 code/news.py reduce --replay   # rebuild stories from the logs, no calls
    python3 code/news.py report --out ~/news-report.md

State goes to .local/news/ (gitignored), or $AIRO_NEWS_DIR, or --state.
`reduce` needs TYPESAFE_API_KEY; `poll`, `reduce --replay` and `report` need
nothing.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from redlines import news  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["poll", "reduce", "report"])
    ap.add_argument("--state", default=news.STATE_DIR, help="state directory (default %(default)s)")
    ap.add_argument("--replay", action="store_true", help="reduce: use logged decisions only, call nothing")
    ap.add_argument("--out", help="report: where to write the markdown report")
    a = ap.parse_args()
    if a.step == "poll":
        for row in news.poll(state_dir=a.state):
            print(json.dumps(row))
    elif a.step == "reduce":
        stats = news.run_reduce(state_dir=a.state, replay=a.replay)
        print(json.dumps(stats))
    else:
        text = news.report(state_dir=a.state)
        if a.out:
            with open(os.path.expanduser(a.out), "w") as f:
                f.write(text)
            print(f"wrote {a.out}")
        else:
            print(text)


if __name__ == "__main__":
    main()
