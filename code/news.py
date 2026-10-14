#!/usr/bin/env python3
"""The news-story pipeline (redlines/news.py, redlines/news_update.py), step by step.

    python3 code/news.py poll              # fetch every feed once; free, no keys
    python3 code/news.py reduce            # fold new items into stories (Jev)
    python3 code/news.py reduce --replay   # rebuild stories from the logs, no calls
    python3 code/news.py fulltext --dry-run   # each story's first readable article (Tavily, paid)
    python3 code/news.py update --frame airo --dry-run
    python3 code/news.py update --frame airo   # the top-ECI model reads the week (paid)
    python3 code/news.py page --out ~/news.html
    python3 code/news.py report --out ~/news-report.md

State goes to .local/news/ (gitignored), or $AIRO_NEWS_DIR, or --state.
`reduce` needs TYPESAFE_API_KEY, `fulltext` TAVILY_API_KEY, `update` the
writer's provider key. The forecast is the newest run in results/runs/, or
--runs-dir (e.g. raw/runs/ of the public redlines-data.zip when this checkout lags).
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from redlines import news, news_update as nu  # noqa: E402

UPDATE_COST_USD = 1.50     # one max-effort read of ~100 briefs (~45k tokens in); digests ran $0.51-1.28 (2026-10-13)
TAVILY_USD_PER_URL = 0.008 # a basic extract is 1 credit per 5 URLs, billed per call: at most a credit each


def forecast(a):
    dirs = [d for d in (a.snapshot_dir or [])] + [str(nu.DATA)]
    return nu.load_forecast(a.runs_dir, a.questions_dir or nu.DATA, dirs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["poll", "reduce", "fulltext", "update", "page", "report"])
    ap.add_argument("--state", default=news.STATE_DIR, help="state directory (default %(default)s)")
    ap.add_argument("--replay", action="store_true", help="reduce: use logged decisions only, call nothing")
    ap.add_argument("--out", help="page/report: where to write it")
    ap.add_argument("--runs-dir", help="forecast runs directory (default results/runs/)")
    ap.add_argument("--snapshot-dir", action="append", help="where to look for the run's ECI snapshot")
    ap.add_argument("--questions-dir", help="autoarc_ladder.json (default data/)")
    ap.add_argument("--frame", choices=nu.FRAMES, default="airo",
                    help="update: show the writer the AIRO forecast (airo), or the questions without numbers (generic)")
    ap.add_argument("--order", choices=nu.ORDERS, default="forward",
                    help="update: list the stories in the fixed shuffle, or reversed")
    ap.add_argument("--depth", choices=["basic", "advanced"], default="basic", help="fulltext: Tavily extract depth")
    ap.add_argument("--dry-run", action="store_true", help="fulltext, update: say what would be called, call nothing")
    a = ap.parse_args()
    state = a.state
    path = lambda name: os.path.join(state, name)
    if a.step == "poll":
        for row in news.poll(state_dir=state):
            print(json.dumps(row))
        return
    if a.step == "reduce":
        print(json.dumps(news.run_reduce(state_dir=state, replay=a.replay)))
        return
    if a.step == "report":
        text = news.report(state_dir=state)
        if a.out:
            open(os.path.expanduser(a.out), "w").write(text)
            print(f"wrote {a.out}")
        else:
            print(text)
        return
    fc = forecast(a)
    built, items = json.load(open(path("stories.json"))), news.load_items(state)
    post = nu.after_forecast(built["stories"], items, fc)
    print(f"forecast {fc['run']}, {len(post)} stories after {nu.forecast_time(fc)}", file=sys.stderr)
    if a.step == "fulltext":
        tried = {r["item"] for r in news.read_jsonl(path(news.FULLTEXT_LOG))}
        todo = [s for s in post if not news.first_readable(s, items)]
        urls = sum(1 for s in todo for m in s["members"] if m["item"] not in tried)
        print(f"{len(post) - len(todo)} readable; {len(todo)} not, with {urls} reports not yet tried "
              f"(at most ${urls * TAVILY_USD_PER_URL * (2 if a.depth == 'advanced' else 1):.2f})", file=sys.stderr)
        if a.dry_run:
            return
        extract = lambda url: news.extract_text(url, depth=a.depth)
        for r in news.fetch_first_readable(todo, items, state_dir=state, extract=extract):
            print(json.dumps({"item": r["item"], "url": r["url"], "chars": r.get("chars"), "error": r.get("error")}))
        print(f"{sum(1 for s in post if news.first_readable(s, items))} of {len(post)} readable", file=sys.stderr)
    elif a.step == "update":
        label, model_id, eci = nu.writer(fc)
        user = nu.prompt(nu.listing(post, order=a.order), items, fc, a.frame)
        print(f"writer {label} ({model_id}), {a.frame}/{a.order}, prompt {len(user):,} chars "
              f"(~{len(user) // 4:,} tokens), ~${UPDATE_COST_USD:.2f}", file=sys.stderr)
        if a.dry_run:
            return
        try:
            row = nu.update(built["stories"], items, fc, a.frame, a.order)
        except RuntimeError as e:
            sys.exit(f"skipped: {e}")
        news.append_jsonl(path(nu.LOG), [row])
        print(json.dumps({"frame": a.frame, "order": a.order, "error": row["error"], "cites": len(row["cites"]),
                          "cost_usd": (row["usage"] or {}).get("cost_usd")}))
    elif a.step == "page":
        out = os.path.expanduser(a.out or path("stories.html"))
        nu.render_page(state, out, fc)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
