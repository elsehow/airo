#!/usr/bin/env python3
"""The news-story pipeline (redlines/news.py, redlines/news_screen.py), step by step.

    python3 code/news.py poll              # fetch every feed once; free, no keys
    python3 code/news.py reduce            # fold new items into stories (Jev)
    python3 code/news.py reduce --replay   # rebuild stories from the logs, no calls
    python3 code/news.py screen            # would each story move the forecast? (Jev)
    python3 code/news.py explain --notes 1 --audit-below 0 --dry-run
    python3 code/news.py explain --notes 1 # the top-ECI model's note (paid; see --dry-run)
    python3 code/news.py fulltext --story s-...   # Tavily extract of a story's reports (paid, ~1c each)
    python3 code/news.py calibrate         # Jev's p against the notes' verdicts
    python3 code/news.py page --out ~/news.html
    python3 code/news.py report --out ~/news-report.md

State goes to .local/news/ (gitignored), or $AIRO_NEWS_DIR, or --state.
`reduce` and `screen` need TYPESAFE_API_KEY; `explain` needs the writer's
provider key. The forecast is the newest run in results/runs/, or --runs-dir
(e.g. raw/runs/ of the public redlines-data.zip when this checkout lags).
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from redlines import news, news_screen as ns  # noqa: E402

NOTE_COST_USD = 0.70   # one max-effort note, observed $0.55-0.81 (2026-10-13)


def forecast(a):
    dirs = [d for d in (a.snapshot_dir or [])] + [str(ns.DATA)]
    return ns.load_forecast(a.runs_dir, a.questions_dir or ns.DATA, dirs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["poll", "reduce", "fulltext", "screen", "explain", "calibrate", "page", "report"])
    ap.add_argument("--state", default=news.STATE_DIR, help="state directory (default %(default)s)")
    ap.add_argument("--replay", action="store_true", help="reduce: use logged decisions only, call nothing")
    ap.add_argument("--out", help="page/report: where to write it")
    ap.add_argument("--runs-dir", help="forecast runs directory (default results/runs/)")
    ap.add_argument("--snapshot-dir", action="append", help="where to look for the run's ECI snapshot")
    ap.add_argument("--questions-dir", help="autoarc_ladder.json and autoarc_crosscutting.json (default data/)")
    ap.add_argument("--notes", type=int, default=1, help="explain: newest flagged stories to write notes for")
    ap.add_argument("--audit-below", type=int, default=0,
                    help="explain: also the N highest-p stories just below the threshold")
    ap.add_argument("--story", action="append", help="fulltext, explain: a story id to act on (repeatable)")
    ap.add_argument("--frame", choices=ns.FRAMES, default="airo",
                    help="screen, explain, calibrate: show Jev and the writer the AIRO forecast (airo) "
                         "or ask about AI catastrophic-risk forecasts in general (generic)")
    ap.add_argument("--dry-run", action="store_true", help="explain: say what would be called, call nothing")
    a = ap.parse_args()
    state = a.state
    path = lambda name: os.path.join(state, name)
    if a.step == "poll":
        for row in news.poll(state_dir=state):
            print(json.dumps(row))
    elif a.step == "reduce":
        print(json.dumps(news.run_reduce(state_dir=state, replay=a.replay)))
    elif a.step == "fulltext":
        built, items = json.load(open(path("stories.json"))), news.load_items(state)
        by_id = {s["id"]: s for s in built["stories"]}
        ids = [m["item"] for sid in (a.story or []) for m in by_id[sid]["members"]]
        print(f"{len(ids)} articles, ~${0.016 * len(ids):.2f} at most", file=sys.stderr)
        if a.dry_run:
            return
        for r in news.fetch_fulltext(ids, items, state_dir=state):
            print(json.dumps({"item": r["item"], "url": r["url"], "chars": r.get("chars"), "error": r.get("error")}))
    elif a.step == "report":
        text = news.report(state_dir=state)
        if a.out:
            open(os.path.expanduser(a.out), "w").write(text)
            print(f"wrote {a.out}")
        else:
            print(text)
    else:
        fc = forecast(a)
        built = json.load(open(path("stories.json")))
        items = news.load_items(state)
        print(f"forecast {fc['run']} ({fc['day']}), panel {', '.join(fc['models'])}", file=sys.stderr)
        screen_log, notes_log = (path(f) for f in ns.LOGS[a.frame])
        log_rows = news.read_jsonl(screen_log)
        if a.step == "screen":
            if not os.environ.get("TYPESAFE_API_KEY"):
                sys.exit("no TYPESAFE_API_KEY set")
            calls = []
            ask = lambda st, qs: calls.append(1) or news.jev_ask(st, qs)
            out = ns.screen(built["stories"], items, fc, log_rows, ask=ask,
                            log=lambda r: news.append_jsonl(screen_log, [r]), frame=a.frame)
            print(json.dumps({"frame": a.frame, "stories": len(out), "calls": len(calls),
                              "flagged": sum(ns.flagged(r) for r in out.values()), "screen_at": ns.SCREEN_AT}))
            return
        screened = ns.screen(built["stories"], items, fc, log_rows, frame=a.frame)
        against = ns.frame_id(fc, a.frame)
        notes = [n for n in news.read_jsonl(notes_log) if n["forecast"] == against]
        if a.step == "explain":
            label, model_id, eci = ns.writer(fc)
            pick = ([s for s in built["stories"] if s["id"] in a.story] if a.story else
                    ns.pick_for_notes(built["stories"], screened, notes, a.notes, a.audit_below))
            print(f"writer {label} ({model_id}, ECI {eci}); {len(pick)} notes, "
                  f"~${NOTE_COST_USD * len(pick):.2f}", file=sys.stderr)
            for s in pick:
                tag = "flagged" if ns.flagged(screened[s["id"]]) else "audit"
                print(f"  [{tag} p {ns.p_max(screened[s['id']]):.2f}] {s['title']}", file=sys.stderr)
            if a.dry_run:
                return
            by_id = {s["id"]: s for s in built["stories"]}
            for s in pick:
                try:
                    n = ns.explain(by_id[s["id"]], items, fc, screened.get(s["id"]), frame=a.frame)
                except RuntimeError as e:
                    print(f"  skipped: {e}", file=sys.stderr)
                    news.append_jsonl(path("rationale_gaps.jsonl"), [{
                        "at": news._now(), "frame": a.frame, "story": s["id"], "forecast": against,
                        "error": str(e)}])
                    continue
                news.append_jsonl(notes_log, [n])
                print(json.dumps({"story": n["title"], "verdict": n["verdict"],
                                  "cost_usd": (n["usage"] or {}).get("cost_usd")}))
        elif a.step == "calibrate":
            print(json.dumps(ns.calibrate(screened, notes), indent=1))
        elif a.step == "page":
            out = os.path.expanduser(a.out or path("stories.html"))
            ns.render_page(state, out, {"day": fc["day"], "models": fc["models"]})
            print(f"wrote {out}")


if __name__ == "__main__":
    main()
