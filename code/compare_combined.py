#!/usr/bin/env python3
"""Compare the combined instrument's pilot with the same-day single-purpose ones.

The combined instrument (data/combined_conditions.json; docs/conditional-forecasts.md,
last section) asks every cell unconditionally, under the eight LEAP policies and
under the model's own three capability percentiles, in ONE call. The question a
pilot has to answer is whether asking everything at once changes any of the three
readings the two tabs publish -- the unconditional level, the policy deltas, the
capability factors -- against the instruments that ask for one at a time. All of
them ran on 2026-08-28, so the comparison is same-day:

  combined   results/conditional_runs_combined.jsonl   unified-joint-combined-v1   the ECI panel (4)
  eci_top4   results/experiments/eci_top4/             unified-joint-v1            the SAME four models, policies only
  frontier   results/conditional_runs.jsonl            unified-joint-v1 / -v2      the frontier five, policies only
  eciself    results/conditional_runs_eciself6mo.jsonl unified-joint-eciself6mo-v1 the frontier five, capability only

Fable 5 is on every panel, so it is the one like-for-like row across all four.

Usage: python3 code/compare_combined.py [--date 2026-08-28] [--horizon 2030 --horizon 2050]
"""
import argparse
import glob
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from redlines.conditional import summarize          # noqa: E402
from redlines.views.capability import _trend        # noqa: E402
from redlines.logs import log_exists, log_files  # noqa: E402

R = os.path.join(ROOT, "results")
SETS = {
    "combined": (os.path.join(ROOT, "data", "combined_conditions.json"), "unified-joint-combined-v1",
                 [os.path.join(R, "conditional_runs_combined.jsonl")]),
    # The arm's own files hold the three new models; Fable 5's five same-day
    # repeats are the published run's (docs/eci-top4-arm.md), so the main log
    # is read too and filtered to the arm's panel below.
    "eci_top4": (os.path.join(ROOT, "data", "leap_policies.json"), "unified-joint-v1",
                 sorted(glob.glob(os.path.join(R, "experiments", "eci_top4", "instrument_*.jsonl")))
                 + [os.path.join(R, "conditional_runs.jsonl")]),
    "frontier_v1": (os.path.join(ROOT, "data", "leap_policies.json"), "unified-joint-v1",
                    [os.path.join(R, "conditional_runs.jsonl")]),
    "frontier_v2": (os.path.join(ROOT, "data", "leap_policies.json"), "unified-joint-v2",
                    [os.path.join(R, "conditional_runs.jsonl")]),
    "eciself": (os.path.join(ROOT, "data", "eci_self6mo_conditions.json"), "unified-joint-eciself6mo-v1",
                [os.path.join(R, "conditional_runs_eciself6mo.jsonl")]),
}
QUESTIONS = ["catastrophe:ai", "catastrophe:general", "disempowerment", "loss:ai", "loss:misalign"]
ECI_TOP4 = ["Fable 5", "GPT-5.5 Pro", "Opus 5", "GPT-5.6 Sol"]
POLICY = ["sq", "p1", "p2a", "p2b", "p3a", "p3b", "p4", "p5"]
CAP = ["eci_p25", "eci_p50", "eci_p75"]


def load(name, day):
    set_path, proto, paths = SETS[name]
    rows = []
    for p in paths:
        if not log_exists(p):
            continue
        for f in (open(fp) for fp in log_files(p)):
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("protocol") == proto and r["elicited_at"][:10] == day \
                        and isinstance(r.get("forecasts"), list):
                    rows.append(r)
    if name == "eci_top4":
        rows = [r for r in rows if r["label"] in ECI_TOP4]
    return rows, json.load(open(set_path))


def fmt(x, kind="probability"):
    if x is None:
        return "   -  "
    return f"{100 * x:6.2f}" if kind == "probability" else f"{x:6.0f}"


def ratio(a, b):
    return None if not a or not b else a / b


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-28")
    ap.add_argument("--horizon", action="append")
    ap.add_argument("--question", action="append")
    args = ap.parse_args()
    hz = tuple(args.horizon or ("2030", "2050"))
    qs = args.question or QUESTIONS

    S, calls = {}, {}
    for name in SETS:
        rows, spec = load(name, args.date)
        if not rows:
            print(f"[{name}: no rows on {args.date}]")
            continue
        S[name] = summarize(rows, policies=spec, horizons=hz)
        calls[name] = {}
        for r in rows:
            if r.get("condition") is None:
                calls[name].setdefault(r["label"], set()).add(r["call_id"])
    for name, c in calls.items():
        print(f"{name:12} " + ", ".join(f"{l} x{len(v)}" for l, v in sorted(c.items())))

    # 1. The ECI forecasts: combined vs eciself, per model, against the trend.
    print("\n== ECI forecast for 2027-02-28 (p25 / p50 / p75; median over calls) ==")
    trend = _trend(["2027-02-28"])["at"]["2027-02-28"]
    print(f"{'trend (metr_graph)':22} {trend['p25']:6.1f} {trend['p50']:6.1f} {trend['p75']:6.1f}")

    def eci_forecasts(name):
        rows, _ = load(name, args.date)
        out = {}
        for r in rows:
            e = (r.get("elicited") or {}).get("eci_forecast")
            if e and r.get("condition") is None:
                out.setdefault(r["label"], {})[r["call_id"]] = e
        return {l: {k: st.median(v[k] for v in c.values()) for k in ("p25", "p50", "p75")} for l, c in out.items()}
    ef = {n: eci_forecasts(n) for n in ("combined", "eciself") if n in S}
    for label in sorted(set().union(*[set(v) for v in ef.values()])):
        line = f"{label:22}"
        for n in ("combined", "eciself"):
            v = ef.get(n, {}).get(label)
            line += (f" {n:9} {v['p25']:6.1f} {v['p50']:6.1f} {v['p75']:6.1f}" if v else f" {n:9} {'-':>20}")
        print(line)

    # 2. Per question x horizon: unconditional levels, policy ratios, capability ratios.
    for qid in qs:
        for h in hz:
            cells = {n: S[n]["questions"].get(qid, {}).get(h) for n in S}
            cells = {n: c for n, c in cells.items() if c}
            if not cells:
                continue
            kind = next(iter(cells.values())).get("value_kind", "probability")
            unit = "%" if kind == "probability" else "death-equivalents"
            print(f"\n== {qid} @ {h}  ({unit}) ==")
            # Unconditional per model, every instrument.
            names = [n for n in ("combined", "eci_top4", "frontier_v1", "frontier_v2", "eciself") if n in cells]
            labels = sorted(set().union(*[set(cells[n]["models"]) for n in names]))
            print(f"{'unconditional':22}" + "".join(f" {n:>12}" for n in names) + "   combined/eci_top4")
            for label in labels:
                vals = [cells[n]["models"].get(label, {}).get("baseline") for n in names]
                rr = ratio(cells["combined"]["models"].get(label, {}).get("baseline"),
                           cells.get("eci_top4", {}).get("models", {}).get(label, {}).get("baseline")) \
                    if "combined" in cells and "eci_top4" in cells else None
                print(f"  {label:20}" + "".join(f" {fmt(v, kind):>12}" for v in vals)
                      + (f"   {rr:5.2f}x" if rr else ""))
            ens = [cells[n]["baseline_median"] for n in names]
            print(f"  {'ensemble median':20}" + "".join(f" {fmt(v, kind):>12}" for v in ens))

            # Policy ratios: combined vs the same four models' policy-only arm, and
            # the combined read against its own eci_p50 (the like-for-like baseline).
            pol_names = [n for n in ("combined", "eci_top4", "frontier_v1", "frontier_v2") if n in cells]
            if "combined" in cells:
                print(f"{'policy ratio (ens.)':22}" + "".join(f" {n:>12}" for n in pol_names) + "   combined vs eci_p50")
                for cid in POLICY:
                    vals = [cells[n]["ensemble"].get(cid, {}).get("ratio") for n in pol_names]
                    per = []
                    for label, m in cells["combined"]["models"].items():
                        pc = m["conditions"].get(cid, {}).get("p")
                        p50 = m["conditions"].get("eci_p50", {}).get("p")
                        per.append(ratio(pc, p50))
                    vs50 = med(per)
                    flag = "*" if cells["combined"]["ensemble"].get(cid, {}).get("outside") else " "
                    print(f"  {cid:20}" + "".join(f" {v:11.2f}x" if v else f" {'-':>12}" for v in vals)
                          + (f"   {vs50:5.2f}x" if vs50 else "") + f"  {flag}")
            # Capability ratios: combined (panel) vs eciself (frontier five); Fable 5 alone too.
            cap_names = [n for n in ("combined", "eciself") if n in cells]
            if len(cap_names) == 2:
                print(f"{'capability ratio':22}" + "".join(f" {n + ' ens.':>14}" for n in cap_names)
                      + "".join(f" {n + ' Fable':>14}" for n in cap_names))
                for cid in CAP:
                    ens = [cells[n]["ensemble"].get(cid, {}).get("ratio") for n in cap_names]
                    fab = [cells[n]["models"].get("Fable 5", {}).get("conditions", {}).get(cid, {}).get("ratio")
                           for n in cap_names]
                    print(f"  {cid:20}" + "".join(f" {v:13.2f}x" if v else f" {'-':>14}" for v in ens + fab))
    print("\n* = the combined ensemble's policy effect is outside its re-run noise (redlines.conditional).")


if __name__ == "__main__":
    main()
