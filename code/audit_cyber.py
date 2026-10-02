#!/usr/bin/env python3
"""Read-only audit of the Sept 8 cyber forecasts; emit evidence JSON to stdout.

Run from any directory: python3 code/audit_cyber.py > docs/cyber-validation-2026-09-10.json
No API calls, forecast changes, or dashboard writes. Checks are independently
computed from the raw run, then compared with the dashboard mirrors.
"""
import hashlib
import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redlines.conditional import expected_loss, ladder_rungs
from redlines.logs import iter_rows  # noqa: E402

RUN = "2026-09-08T1717Z"


def read_jsonl(path):
    return list(iter_rows(ROOT / path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=RUN, help="Run ID to compare against the current dashboard mirrors")
    args = parser.parse_args()
    run = args.run
    paths = [f"results/runs/{run}.jsonl", "data/autoarc_ladder.json",
             "results/graph1_data.json", "results/graph2_data.json",
             "results/conditional_runs_combined.jsonl"]
    rows = read_jsonl(paths[0])
    spec = json.loads((ROOT / paths[1]).read_text())
    g1 = json.loads((ROOT / paths[2]).read_text())
    g2 = json.loads((ROOT / paths[3]).read_text())
    # One reviewed batch file may collect technical retries begun at a later
    # minute on the same elicitation date. Keep each actual call ID intact.
    run_ids = {r['run_id'] for r in rows}
    combined = [r for r in read_jsonl(paths[4]) if r["run_id"] in run_ids]
    labels = list(dict.fromkeys(r["label"] for r in rows))
    horizons = spec["horizons"]
    rungs = ladder_rungs(spec)
    raw = {(r["question_id"], r["label"]): r for r in rows}
    assert len(raw) == len(rows), "duplicate question/model rows"
    assert len(labels) == 4
    counts, failures = defaultdict(int), []

    def check(name, ok, detail):
        counts[name] += 1
        if not ok:
            failures.append({"check": name, "detail": detail})

    def grid(rs):
        return {(r["question_id"], r["label"], f["horizon"]): f["probability"]
                for r in rs for f in r["forecasts"]}

    def coherence(rs, prefix):
        p = grid(rs)
        for label in labels:
            for rung, _ in rungs:
                qid = f"ladder:cyber:{rung}"
                for h in horizons:
                    v = p.get((qid, label, h))
                    check(prefix + ":complete_bounded", v is not None and math.isfinite(v) and 0 <= v <= 1, [label, rung, h, v])
                    ceiling = p.get((f"ladder:ai:{rung}", label, h))
                    check(prefix + ":cyber_within_ai", v is not None and ceiling is not None and v <= ceiling + 1e-9, [label, rung, h, v, ceiling])
                for a, b in zip(horizons, horizons[1:]):
                    x, y = p.get((qid, label, a)), p.get((qid, label, b))
                    check(prefix + ":horizon", x is not None and y is not None and x <= y + 1e-9, [label, rung, a, b, x, y])
            for h in horizons:
                for (a, _), (b, _) in zip(rungs, rungs[1:]):
                    x, y = p.get((f"ladder:cyber:{a}", label, h)), p.get((f"ladder:cyber:{b}", label, h))
                    check(prefix + ":ladder", x is not None and y is not None and y <= x + 1e-9, [label, h, a, b, x, y])
        return p

    p = coherence(rows, "unconditional")
    arms = defaultdict(list)
    for r in combined:
        arms[(r.get("condition") or {}).get("id", "unconditional")].append(r)
    for name, rs in arms.items():
        if name != "unconditional":
            coherence(rs, name)
    check("combined_baseline_matches", grid(arms["unconditional"]) == grid(rows), run)
    for rung in spec["rungs"]:
        check("threshold_conversion", math.isclose(rung["damages_usd"], rung["deaths"] * 2.2e6), rung["short"])

    table, losses, rationales = [], [], []
    loss_q = next(q for q in g1["questions"] if q["id"] == "loss:cyber")
    for h in horizons:
        curve = next(c for c in g2["byHorizon"][h]["causes"] if c["key"] == "cyber")
        model_losses = []
        for rung, x in rungs:
            per_model = {label: p[(f"ladder:cyber:{rung}", label, h)] for label in labels}
            median = statistics.median(per_model.values())
            point = next(r for r in curve["rungs"] if r["rung"] == rung)
            # Graph 2 retains four decimal places in percentage points, first
            # per model and again for the median. Compare within that known
            # presentation precision; raw coherence checks remain exact.
            check("graph2_median", abs(median * 100 - point["median"]) <= .0001 + 1e-12, [h, rung])
            for label, v in per_model.items():
                check("graph2_model", abs(v * 100 - point["per_model"][label]) <= .00005 + 1e-12, [h, rung, label])
            table.append({"horizon": h, "rung": rung, "deaths_or_morbidity": x,
                          "damages_usd": x * 2.2e6, "median_probability": median,
                          "per_model": per_model})
        for label in labels:
            ps = [p[(f"ladder:cyber:{r}", label, h)] for r, _ in rungs]
            # Independent point-mass calculation: each interval's probability
            # receives its lower threshold, tail receives only the top threshold.
            direct = sum(x * (v - next_v) for (_, x), v, next_v in
                         zip(rungs, ps, ps[1:] + [0.0]))
            actual = expected_loss(dict(zip([r for r, _ in rungs], ps)), rungs)
            check("loss_independent_formula", math.isclose(direct, actual["value"], rel_tol=1e-12), [label, h])
            model_losses.append(direct)
            series = next(s for s in loss_q["series"] if s["label"] == label)
            check("graph1_model_loss", abs(direct - series["ps"][h]) <= .051, [label, h])
            losses.append({"model": label, "horizon": h, "loss_death_equivalents": direct,
                           "loss_usd_equivalents": direct * 2.2e6,
                           "top_two_rung_share": actual["top_share"], "repaired": actual["repaired"]})
        check("graph1_median_loss", abs(statistics.median(model_losses) - loss_q["median"][h]) <= .051, h)
    for label in labels:
        rs = [r for r in rows if r["label"] == label]
        r = raw[("ladder:cyber:100k", label)]
        rationales.append({"model": label, "elicited_at": r["elicited_at"],
                           "distinct_rationales_in_run": len({x["rationale"] for x in rs}),
                           "rationale": r["rationale"], "key_sources": r["key_sources"],
                           "grounded": r["grounded"], "search_hits": r["search_hits"],
                           "retained_evidence_entries": sum(len(x.get("evidence") or []) for x in rs),
                           "retained_evidence_scope": "whole model call; evidence is stored once, not on every question row",
                           "resolves_on": r["resolves_on"]})
    print(json.dumps({"run_id": run, "call_run_ids": sorted(run_ids),
                      "instrument_versions": sorted({r.get('instrument_version') or 'unversioned' for r in rows}),
                      "scope": "Pinned local batch file and local dashboard mirrors; not deployed-site verification",
                      "graph2_display_precision_pp": {"decimal_places": 4,
                          "per_model_tolerance": .00005, "median_tolerance": .0001},
                      "input_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in paths},
                      "models": labels, "condition_arms": list(arms), "check_counts": dict(counts),
                      "failures": failures, "probabilities": table, "expected_losses": losses,
                      "rationales": rationales}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
