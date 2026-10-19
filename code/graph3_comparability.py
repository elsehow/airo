#!/usr/bin/env python3
"""Why Graph 3 stays on one ForecastBench round.

THE QUESTION
    Graph 3 draws superforecasters against 2024-era LLMs on the 2024-07-21
    round. The obvious ask (2026-08-10 call) is to add 2025 and 2026 model
    lines so the curve visibly walks toward the diagonal. This script measures
    whether that comparison would mean anything.

THE PROBLEM
    Three things differ between the 2024 line and any later line, and the chart
    would attribute all of it to model capability:

      1. PROMPT CONFIG. `scratchpad_with_news` exists ONLY in 2024-07-21.
         Rounds through 2025-08-31 carry `scratchpad`; from 2025-10-26 on the
         benchmark runs `zero_shot` only.
      2. ROUND. Each round is a fresh question set. Recent rounds have also had
         less time to resolve, so their resolved rows collapse onto the short
         horizons — 2026-02-15 resolves 192 of 205 rows at 7 days, against a
         balanced 7/30/90/180/365 in 2024. Short horizons are easier.
      3. MODEL VINTAGE. The effect we actually want to show.

    ForecastBench re-runs some models every round, which hands us the control
    for free: a FIXED model's score change across rounds is pure round effect.

WHAT IT FINDS (see docs/methodology.md for the write-up)
    Config effect      ~0.002 Brier   negligible — all three configs agree
    Round effect       ~0.035 Brier   a fixed model, swinging on question luck
    Vintage effect     ~0.013 Brier   replicated in three independent rounds

    The confound is about 3x the signal, so a cross-round Graph 3 would show
    benchmark difficulty and label it progress.

    THE NUMBERS MOVE AS THE BENCHMARK RESOLVES. Re-run this before citing it.
    On the 2026-03-05 data snapshot the vintage effect measured 0.003; the
    2026-08-11 refresh — which resolved the long horizons on eleven more rounds
    — put it at 0.013. The conclusion held, but the margin narrowed from 10x to
    3x. The tightest check is section 5: consecutive versions of the same model
    from the same lab, and two of the four went backwards.

    Refresh the data first (it is NOT in the git repo — the repo tracks only
    question and resolution sets):

        curl -L -o pfs.tar.gz \\
          https://www.forecastbench.org/assets/data/processed-forecast-sets/processed_forecast_sets.tar.gz

    then extract over ~/Projects/forecastbench-datasets/processed_forecast_sets/
    and run:

        python3 code/graph3_comparability.py

    then regenerate the tables in docs/methodology.md from the new JSON (the
    test suite fails until you do), and re-read the prose around them:

        python3 -m redlines.graph3_report
"""
import datetime as dt
import glob
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redlines.config import FB_DATASETS_ROOT as FB, GRAPH3_ROUND as ROUND
from redlines.views.graph3 import usable

PROC = FB / "processed_forecast_sets"
OUT = Path(__file__).resolve().parent.parent / "results" / "graph3_comparability.json"

# Rounds sampled across the benchmark's history. Not all 33 — these span the
# config change, the range of horizon maturity, and the model generations.
# 2025-08-03 is the newest round whose long horizons have fully resolved;
# 2026-06-21 is the newest round the baseline models were run on at all.
ROUNDS = ["2024-07-21", "2025-08-03", "2025-11-23", "2026-02-15", "2026-06-21"]

# Models ForecastBench kept running across rounds. Each is its own control:
# the model does not change, so any score change is the round. GPT-4.1 alone
# spans 20 rounds. Claude-3-5-Sonnet reaches back to the human round.
ANCHORS = [
    "GPT-4.1-2025-04-14 (zero shot)",
    "GPT-5-Mini-2025-08-07 (zero shot)",
    "GPT-5-Nano-2025-08-07 (zero shot)",
    "Claude-Haiku-4-5-20251001 (zero shot)",
    "Claude-Sonnet-4-5-20250929 (zero shot)",
    "Claude-3-5-Sonnet-20240620 (zero shot)",
]

# The tightest vintage test available: same lab, same tier, consecutive
# versions, inside one round. Nothing varies except the model generation —
# not the questions, not the config, not even the model size.
FAMILY_PAIRS = {
    "2026-06-21": [("Claude-Sonnet-4-5-20250929 (zero shot)", "Claude-Sonnet-4-6 (zero shot)"),
                   ("Claude-Opus-4-7 (zero shot)", "Claude-Opus-4-8 (zero shot)"),
                   ("Grok-4.20-0309-Reasoning (zero shot)", "Grok-4.3 (zero shot)"),
                   ("GPT-5.4-2026-03-05 (zero shot)", "GPT-5.5-2026-04-23 (zero shot)")],
}

# Within a round the questions, config and horizon mix are identical for every
# model, so an older-vs-frontier split isolates vintage with nothing else moving.
VINTAGE = {
    "2025-11-23": {
        "older": ["Claude-3-7-Sonnet-20250219 (zero shot)", "GPT-4.1-2025-04-14 (zero shot)",
                  "Gemini-2.5-Flash (zero shot)", "Qwen3-235B-A22B-Fp8-Tput (zero shot)"],
        "frontier": ["Claude-Sonnet-4-5-20250929 (zero shot)", "GPT-5.1-2025-11-13 (zero shot)",
                     "Gemini-3-Pro-Preview (zero shot)", "Grok-4-1-Fast-Reasoning (zero shot)",
                     "Kimi-K2-Thinking (zero shot)"],
    },
    "2026-02-15": {
        "older": ["GPT-4.1-2025-04-14 (zero shot)", "Claude-Sonnet-4-20250514 (zero shot)",
                  "Gemini-2.5-Pro (zero shot)", "GPT-5-Nano-2025-08-07 (zero shot)"],
        "frontier": ["Claude-Opus-4-6 (zero shot)", "GPT-5.2-2025-12-11 (zero shot)",
                     "Gemini-3-Pro-Preview (zero shot)", "Grok-4-1-Fast-Reasoning (zero shot)",
                     "Kimi-K2-Thinking (zero shot)"],
    },
    "2026-06-21": {
        "older": ["Claude-Sonnet-4-5-20250929 (zero shot)", "Claude-Haiku-4-5-20251001 (zero shot)",
                  "GPT-5-Mini-2025-08-07 (zero shot)", "GPT-5-Nano-2025-08-07 (zero shot)"],
        "frontier": ["Claude-Opus-4-8 (zero shot)", "GPT-5.5-2026-04-23 (zero shot)",
                     "Gemini-3.1-Pro-Preview (zero shot)", "Grok-4.3 (zero shot)",
                     "Kimi-K2.6 (zero shot)"],
    },
}


def horizon(row):
    return (dt.datetime.fromisoformat(row["resolution_date"])
            - dt.datetime.fromisoformat(row["forecast_due_date"])).days


def load_round(round_, pattern):
    """Every model in one round matching a config glob -> {model: usable rows}."""
    out = {}
    for p in sorted(glob.glob(str(PROC / round_ / pattern))):
        d = json.load(open(p))
        if "SECOND" in d["model"]:   # duplicate reruns — don't double-weight
            continue
        out[d["model"]] = usable(d["forecasts"])
    return out


def score(pairs):
    """Brier plus the low-probability bin, which is the tail claim in one number."""
    n = len(pairs)
    if n < 20:
        return None
    lo = [(f, o) for f, o in pairs if f < 0.10]
    return {
        "n": n,
        "base": round(sum(o for _, o in pairs) / n, 4),
        "brier": round(sum((f - o) ** 2 for f, o in pairs) / n, 4),
        "lo_n": len(lo),
        "lo_pred": round(sum(f for f, _ in lo) / len(lo), 4) if lo else None,
        "lo_obs": round(sum(o for _, o in lo) / len(lo), 4) if lo else None,
    }


def crowd(per_model, keys, min_models):
    """Per-question median across models — the same aggregation Graph 3 draws."""
    ks = [k for k in keys if sum(k in m for m in per_model.values()) >= min_models]
    return [(statistics.median(m[k]["forecast"] for m in per_model.values() if k in m),
             next(m[k]["resolved_to"] for m in per_model.values() if k in m)) for k in ks]


def fmt(label, s):
    if s is None:
        return f"  {label:46} — too few resolved rows"
    lo = (f"{s['lo_pred']:.3f}->{s['lo_obs']:.3f} (n={s['lo_n']})"
          if s["lo_pred"] is not None else "—")
    return (f"  {label:46} n={s['n']:5}  base={s['base']:.3f}  "
            f"brier={s['brier']:.4f}   <10%: {lo}")


def main():
    sup = usable(json.load(open(PROC / ROUND / f"{ROUND}.ForecastBench.human_super.json"))["forecasts"])
    zs = {r: load_round(r, "*_zero_shot.json") for r in ROUNDS}
    report = {}

    # --- 1. CONFIG ------------------------------------------------------
    # Same round, same 577 questions, prompt scaffold varied. If these agree,
    # the config break between rounds is not what would move a cross-round line.
    print("\n1. CONFIG EFFECT — 2024-07-21, the same 577 super questions\n")
    report["config"] = {}
    for name, pattern in [("scratchpad + news", "*scratchpad_with_news.json"),
                          ("scratchpad", "*[!s]_scratchpad.json"),
                          ("zero shot", "*_zero_shot.json")]:
        pm = load_round(ROUND, pattern)
        s = score(crowd(pm, sup, len(pm) // 2))
        report["config"][name] = dict(s, models=len(pm))
        print(fmt(f"LLM crowd, {name} ({len(pm)} models)", s))
    print(fmt("superforecasters", score([(v["forecast"], v["resolved_to"]) for v in sup.values()])))
    briers = [v["brier"] for v in report["config"].values()]
    report["config_spread"] = round(max(briers) - min(briers), 4)
    print(f"\n  -> configs span {report['config_spread']:.4f} Brier. Negligible.")

    # --- 2. HORIZONS ----------------------------------------------------
    # Recent rounds have not had time to resolve their long horizons.
    print("\n2. HORIZON COLLAPSE — resolved rows by horizon, one model per round\n")
    report["horizons"] = {}
    for r in ROUNDS:
        rows = next(iter(zs[r].values()))
        mix = {}
        for v in rows.values():
            mix[horizon(v)] = mix.get(horizon(v), 0) + 1
        long_ = sum(n for h, n in mix.items() if h >= 90)
        report["horizons"][r] = {"total": len(rows), "ge90d": long_,
                                 "main": {h: mix.get(h, 0) for h in (7, 30, 90, 180, 365)}}
        m = report["horizons"][r]["main"]
        print(f"  {r}  n={len(rows):5}  7d={m[7]:4} 30d={m[30]:4} 90d={m[90]:4} "
              f"180d={m[180]:4} 365d={m[365]:4}   >=90d: {100*long_/len(rows):.0f}%")

    # --- 3. ROUND -------------------------------------------------------
    # A model that does not change, scored on rounds that do.
    print("\n3. ROUND EFFECT — the SAME model across rounds. All movement is question luck.\n")
    report["anchors"] = {}
    swings = []
    for a in ANCHORS:
        per_round = {r: score([(v["forecast"], v["resolved_to"]) for v in zs[r][a].values()])
                     for r in ROUNDS if a in zs[r]}
        per_round = {r: s for r, s in per_round.items() if s}
        if len(per_round) < 2:
            continue
        bs = [s["brier"] for s in per_round.values()]
        swing = round(max(bs) - min(bs), 4)
        swings.append(swing)
        report["anchors"][a] = {"rounds": per_round, "swing": swing}
        print(f"  {a}")
        for r, s in per_round.items():
            print(fmt(f"  {r}", s))
        print(f"    -> swings {swing:.4f} Brier with no change to the model\n")
    report["round_effect"] = round(statistics.mean(swings), 4)
    print(f"  -> mean fixed-model swing across rounds: {report['round_effect']:.4f} Brier")

    # --- 4. VINTAGE -----------------------------------------------------
    # One round, one config, one question set. Only the model generation moves.
    print("\n4. VINTAGE EFFECT — one round, same questions, older models vs frontier\n")
    report["vintage"] = {}
    for r, groups in VINTAGE.items():
        keys = set().union(*[set(m) for m in zs[r].values()])
        report["vintage"][r] = {}
        print(f"  round {r}")
        for label, names in groups.items():
            pm = {n: zs[r][n] for n in names if n in zs[r]}
            missing = [n for n in names if n not in zs[r]]
            if missing:
                print(f"    NOTE: absent from this round: {missing}")
            s = score(crowd(pm, keys, len(pm)))
            report["vintage"][r][label] = dict(s, models=sorted(pm))
            print(fmt(f"  {label} — median of {len(pm)}", s))
        # Model-to-model spread inside the round bounds how much a group
        # difference can mean: pick different models, get a different answer.
        singles = {n: score([(v["forecast"], v["resolved_to"]) for v in m.values()])
                   for n, m in zs[r].items()}
        singles = {n: s for n, s in singles.items() if s}
        spread = round(max(s["brier"] for s in singles.values())
                       - min(s["brier"] for s in singles.values()), 4)
        gap = round(report["vintage"][r]["older"]["brier"]
                    - report["vintage"][r]["frontier"]["brier"], 4)
        report["vintage"][r]["gap"] = gap
        report["vintage"][r]["within_round_model_spread"] = spread
        print(f"    -> vintage gap {gap:+.4f} Brier, "
              f"against a {spread:.4f} spread between individual models in the same round\n")

    # --- 5. FAMILY PAIRS ------------------------------------------------
    # Tighter than the group split: one lab, one tier, consecutive versions.
    print("\n5. VERSION BUMPS — same lab, same tier, same round, one generation apart\n")
    report["family_pairs"] = {}
    for r, pairs in FAMILY_PAIRS.items():
        for old, new in pairs:
            if old not in zs[r] or new not in zs[r]:
                print(f"  {r}: absent — {old if old not in zs[r] else new}")
                continue
            keys = set(zs[r][old]) & set(zs[r][new])   # only what both answered
            a = score([(zs[r][old][k]["forecast"], zs[r][old][k]["resolved_to"]) for k in keys])
            b = score([(zs[r][new][k]["forecast"], zs[r][new][k]["resolved_to"]) for k in keys])
            gap = round(a["brier"] - b["brier"], 4)
            report["family_pairs"][f"{r} {old} -> {new}"] = {"old": a, "new": b, "gap": gap}
            print(f"  {old[:34]:36} -> {new[:30]:32} "
                  f"{a['brier']:.4f} -> {b['brier']:.4f}  = {gap:+.4f}   (n={len(keys)})")
    if report["family_pairs"]:
        fg = [v["gap"] for v in report["family_pairs"].values()]
        report["family_pair_effect"] = round(statistics.mean(fg), 4)
        print(f"\n  -> mean version bump: {report['family_pair_effect']:+.4f} Brier "
              f"(range {min(fg):+.4f} to {max(fg):+.4f})")

    # --- VERDICT --------------------------------------------------------
    gaps = [v["gap"] for v in report["vintage"].values()]
    report["vintage_effect"] = round(statistics.mean(gaps), 4)
    ratio = report["round_effect"] / report["vintage_effect"] if report["vintage_effect"] else float("inf")
    report["verdict"] = (
        f"Vintage is worth {report['vintage_effect']:+.4f} Brier; the round confound is "
        f"{report['round_effect']:.4f}, {ratio:.0f}x larger. Graph 3 stays on {ROUND}.")
    print("=" * 78)
    print(f"  config  {report['config_spread']:.4f}   |   round  {report['round_effect']:.4f}   "
          f"|   vintage  {report['vintage_effect']:+.4f}")
    print(f"  {report['verdict']}")
    print("=" * 78)

    OUT.parent.mkdir(exist_ok=True)
    json.dump(report, open(OUT, "w"), indent=1)
    print(f"\n-> {OUT.relative_to(OUT.parent.parent)}")
    print("   now: python3 -m redlines.graph3_report  (rewrites docs/methodology.md tables)")


if __name__ == "__main__":
    main()
