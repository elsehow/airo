#!/usr/bin/env python3
"""Compare the dashboard's published arm (frontier five) with the ECI top-4 arm.

Both arms answered the same instrument (unified-joint-v1, LEAP condition set) on
the same day, so this is a like-for-like swap of the panel, not a protocol change.

  frontier5 : Fable 5, GPT-5.5, Opus 4.8, Gemini 3.1 Pro, Grok 4.20
  eci_top4  : Fable 5, GPT-5.5 Pro, Opus 5, GPT-5.6 Sol   (Fable 5 shared)

Since 2026-08-28 (pm) the arm's rule is the default panel (`--model-set
eci_topk`, redlines.registry.panel(), re-ranked from the newest ECI snapshot);
this script still compares the one-day arm in results/experiments/eci_top4/
against the frontier five's same-day instrument.

Usage: python3 code/compare_eci_top4.py [--date 2026-08-28]
"""
import argparse, glob, json, os, statistics as st
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys  # noqa: E402
sys.path.insert(0, REPO)
from redlines.logs import log_exists, log_files  # noqa: E402
PUBLISHED = os.path.join(REPO, "results", "conditional_runs.jsonl")
NEW_GLOB = os.path.join(REPO, "results", "experiments", "eci_top4", "instrument_*.jsonl")
FRONTIER5 = ["Fable 5", "GPT-5.5", "Opus 4.8", "Gemini 3.1 Pro", "Grok 4.20"]
ECI_TOP4 = ["Fable 5", "GPT-5.5 Pro", "Opus 5", "GPT-5.6 Sol"]


def load(paths, date, protocol="unified-joint-v1"):
    """(condition, question_id, horizon) -> {label: [p per repeat]}"""
    out = defaultdict(lambda: defaultdict(list))
    for p in paths:
        if not log_exists(p):
            continue
        for f in (open(fp) for fp in log_files(p)):
            for line in f:
                d = json.loads(line)
                if d.get("protocol") != protocol or (date and d.get("run_date") != date):
                    continue
                c = d.get("condition")
                cond = (c.get("id") if isinstance(c, dict) else c) or "unconditional"
                for fc in d.get("forecasts") or []:
                    out[(cond, d["question_id"], fc["horizon"])][d["label"]].append(
                        fc["probability"])
    return out


def arm_mean(cell, labels):
    """Ensemble point: per-model mean over repeats, then mean across models."""
    per = [st.mean(cell[l]) for l in labels if cell.get(l)]
    return (st.mean(per), len(per)) if per else (None, 0)


def spread(cell, labels):
    per = [st.mean(cell[l]) for l in labels if cell.get(l)]
    return max(per) - min(per) if len(per) > 1 else None


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-28")
    a = ap.parse_args()

    old = load([PUBLISHED], a.date)
    new = load(sorted(glob.glob(NEW_GLOB)) + [PUBLISHED], a.date)

    cov = defaultdict(int)
    for cell in new.values():
        for l in ECI_TOP4:
            if cell.get(l):
                cov[l] += 1
    print("ECI top-4 coverage (cells with >=1 draw), and repeats per cell:")
    for l in ECI_TOP4:
        reps = [len(c[l]) for c in new.values() if c.get(l)]
        print(f"  {l:14s} cells={cov[l]:5d}  repeats/cell={st.mode(reps) if reps else 0}")

    rows = []
    for key in sorted(set(old) & set(new)):
        o, no = arm_mean(old[key], FRONTIER5)
        n, nn = arm_mean(new[key], ECI_TOP4)
        if o is None or n is None or nn < 4:
            continue
        rows.append((key, o, n, n - o, spread(old[key], FRONTIER5),
                     spread(new[key], ECI_TOP4)))
    if not rows:
        print("\nno comparable cells yet — the fill run is still in flight")
        return

    unc = [r for r in rows if r[0][0] == "unconditional"]
    print(f"\n{len(rows)} question x horizon x condition cells compared "
          f"({len(unc)} unconditional)")

    for name, sel in (("UNCONDITIONAL (Graph 1 / Timeline bottom lines)", unc),
                      ("ALL CONDITIONS (Conditional-on panel)", rows)):
        d = [r[3] for r in sel]
        ad = [abs(x) for x in d]
        print(f"\n--- {name} ---")
        print(f"  ECI top-4 minus frontier five, in pp:")
        print(f"    mean {100*st.mean(d):+.2f}   median {100*st.median(d):+.2f}   "
              f"|median| {100*st.median(ad):.2f}   p90 {100*pct(ad,0.9):.2f}   "
              f"max {100*max(ad):.2f}")
        print(f"    higher in {sum(1 for x in d if x>0)}/{len(d)} cells "
              f"({100*sum(1 for x in d if x>0)/len(d):.0f}%)")
        os_ = [r[4] for r in sel if r[4] is not None]
        ns_ = [r[5] for r in sel if r[5] is not None]
        print(f"  between-model spread (max-min across the arm), median pp: "
              f"frontier5 {100*st.median(os_):.1f}  eci_top4 {100*st.median(ns_):.1f}")

    print("\n--- largest unconditional moves ---")
    for key, o, n, dd, _, _ in sorted(unc, key=lambda r: -abs(r[3]))[:12]:
        print(f"  {key[1]:22s} {key[2]:>5s}  {100*o:5.1f} -> {100*n:5.1f} pp  ({100*dd:+5.1f})")

    print("\n--- by horizon (unconditional) ---")
    byh = defaultdict(list)
    for key, o, n, dd, _, _ in unc:
        byh[key[2]].append((o, n, dd))
    for h in sorted(byh, key=lambda x: ("6mo", "12mo", "2028", "2030", "2050", "2100").index(x)
                    if x in ("6mo", "12mo", "2028", "2030", "2050", "2100") else 9):
        v = byh[h]
        print(f"  {h:>5s}  n={len(v):3d}  frontier5 {100*st.mean(x[0] for x in v):5.1f}pp  "
              f"eci_top4 {100*st.mean(x[1] for x in v):5.1f}pp  "
              f"delta {100*st.mean(x[2] for x in v):+5.1f}pp")


if __name__ == "__main__":
    main()
