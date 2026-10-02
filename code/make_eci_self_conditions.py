#!/usr/bin/env python3
"""Generate data/eci_self_conditions.json: the SELF-ELICITED capability
instrument -- the model forecasts the frontier ECI at end of 2030 itself
(10th / 25th / 50th / 75th / 90th percentiles), then answers every cell
conditional on each of its own five values.

Designed 2026-08-28 (project lead). The fixed set (data/eci_conditions.json) hands
the model three levels from metr_graph's projection; this one asks the model
for its own distribution first, from the vendored Epoch history, and
conditions on that. Two things come out that the fixed set cannot give:
the model's ECI forecast against the trend projection's, and whether asking
for it moves the unconditional.

    python3 code/make_eci_self_conditions.py           # writes data/eci_self_conditions.json (end of 2030)
    python3 code/make_eci_self_conditions.py --check    # verify the file is current
    python3 code/make_eci_self_conditions.py --months 6 --out data/eci_self6mo_conditions.json [--check]
                                                       # the ROLLING variant: six months from the run date

THE ROLLING VARIANT (--months N; project lead, 2026-08-28: six months from the
run date, generated into the prompt at run time). The target is not a
fixed date but run date + N months, so the file carries the texts with a
`{target_date}` placeholder and `elicit.target_months`; the runner resolves
the date when it builds the prompt (run_unified.resolve_set, the same
month arithmetic as the rolling horizons' resolves_on) and stamps it on
every row (`elicited.target_date`). The trend to compare against is then
computed at analysis time for that date (code/analyze_eci_self.py via
code/eci_projection_metrgraph.project), so the file has no `trend` block.

WHAT IS DERIVED AND WHAT IS AUTHORED

  derived    the frontier history the model is shown -- every new high among
             US developers' models since GPT-4, one score per model as Epoch
             publishes it, from the newest Epoch snapshot in data/ -- and, for the record, the
             metr_graph 2030-EOY percentiles the answers are compared to
             (never shown to the model).
  authored   the definitions, the two steps, the conditioning instruction,
             the unconditional line, ids and labels. Same discipline as the
             other sets: nothing about how capability relates to any
             question, nothing about direction, no pace verdict.

The conditions are keyed by percentile, not by level: `eci_p25` is "the
frontier ECI on 2030-12-31 is approximately the 25th-percentile value YOU
gave". The level therefore differs per call, and the runner stamps each
condition row with the value the model gave (condition.value).
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from redlines import eci  # noqa: E402

# The frontier history the prompt quotes comes from the newest Epoch snapshot
# in data/ (redlines.eci.latest_published), which code/cron_run.sh fetches
# before every elicitation and regenerates this file from. Project lead,
# 2026-10-01: Epoch's ECI is the source of truth. From 2026-09-10 to then it
# was a Playwright scrape of METR's Streamlit app (data/live_metr_eci_frontier.json,
# kept as the record of what those runs were shown); the cron box could not
# run the scrape, so the runs stopped when the copy aged out (2026-09-23).
# Before 2026-09-10 a vendored August CSV, which told models Fable 5 was
# still frontier after Astra had passed it -- the reason the history must
# follow the index rather than a file someone remembers to refresh.
OUT = os.path.join(ROOT, "data", "eci_self_conditions.json")

TARGET = "2030EOY"
TARGET_DATE_TEXT = "December 31, 2030"
PLACEHOLDER = "{target_date}"
HISTORY_FROM = "2023-03-01"   # GPT-4 is the first point; the Feb-2023 LLaMAs are not a frontier anyone dates from
US = "United States of America"
# The forecast asks five percentiles since 2026-09-02 (A4 on the worklist:
# p10/p90 give the Capability box plot its whiskers). The CONDITIONS were the
# middle three until 2026-09-03; project lead: condition on the 10th and 90th
# percentiles too, now that they are elicited -- so a
# condition per elicited percentile, five rows, tails included. Protocol v2 of
# both self-elicited sets and v4 of the combined instrument.
FIELDS = [("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90)]
CONDITION_FIELDS = list(FIELDS)
ORDINAL = {"p10": "10th", "p25": "25th", "p50": "50th", "p75": "75th", "p90": "90th"}

DEFINITIONS = (
    "Definitions. ECI: the Epoch Capabilities Index, published by Epoch AI -- a "
    "single score summarising a model's results across dozens of benchmarks, "
    "fit with an item-response model so that scores stay comparable as "
    "benchmarks saturate and new ones are added. Higher is more capable; the "
    "scale has no ceiling. All scores here are on the scale as published by "
    "Epoch on {csv_date}.\n"
    "Frontier ECI: the highest ECI score of any publicly released model from a "
    "US developer, as scored by Epoch.\n\n"
    "Frontier ECI history -- every release by a US developer that set a new "
    "high, from GPT-4 on (Epoch's index of "
    "{csv_date}, {n_models} models scored):\n"
    "{history}\n"
    "As of {csv_date} no released model has scored above {top_name}, "
    "{top_score} ({top_date})."
)

ELICIT = (
    "Forecast the frontier ECI on {date}, on the scale above. Give your 10th, "
    "25th, 50th, 75th and 90th percentiles as eci_forecast (p10, p25, p50, p75, "
    "p90; numbers, with p10 <= p25 <= p50 <= p75 <= p90): your 50th percentile "
    "is the value you think the frontier is equally likely to end up above or "
    "below, your 25th and 75th bracket the middle half of your distribution, "
    "and your 10th and 90th bracket the middle four-fifths."
)

INSTRUCTION = (
    "For each condition below, assume that the frontier ECI on {date} is "
    "approximately the value you gave for that percentile in eci_forecast "
    "(within about two points of it). Treat it as a fact you have learned "
    "about the world, not as an intervention: update your expectations about "
    "everything that would ordinarily accompany that level of capability -- "
    "investment, compute, algorithmic progress, deployment, and how "
    "governments and developers respond -- as you would upon learning it, "
    "and then forecast each question in that world. Do not hold other "
    "factors fixed where the stated level would change them."
)

UNCONDITIONAL = ("forecast the world as you expect it to unfold, including "
                 "whatever level of AI capability you expect to be reached by {date}.")

ASSUME = ("Assume that on {date} the frontier ECI is approximately your {ord}-percentile "
          "value from eci_forecast (within about two points of it).")

# The rolling variant's label and ids say "in six months", not a year.
LABEL_FIXED = "Frontier ECI at end of 2030 = your {ord} percentile"
LABEL_ROLLING = "Frontier ECI {months} months from the run date = your {ord} percentile"


def frontier_history(path):
    """Every US release that set a new high since GPT-4, from one Epoch
    snapshot (redlines.eci.frontier_history), and how many models it scores."""
    hist = eci.frontier_history(path, since=HISTORY_FROM, country=US)
    if not hist:
        raise ValueError(f"{path}: no US frontier history")
    return hist, len(eci.load(path))


def build(months=None):
    """months=None: the fixed end-of-2030 set. months=N: the rolling set,
    target = run date + N months, texts carry PLACEHOLDER."""
    day, snapshot = eci.latest_published()
    csv_date = day.isoformat()
    hist, n_models = frontier_history(snapshot)
    top_date, top_score, top_name = hist[-1]
    history = "\n".join(f"  {d}  {s:6.1f}  {dn}" for d, s, dn in hist)
    date_text = PLACEHOLDER if months else TARGET_DATE_TEXT
    conds = []
    for key, pct in CONDITION_FIELDS:
        conds.append({
            "id": f"eci_{key}",
            "leap_id": None,
            "label": (LABEL_ROLLING.format(months=months, ord=ORDINAL[key]) if months
                      else LABEL_FIXED.format(ord=ORDINAL[key])),
            "policy": None,
            "part": None,
            "field": key,
            "assume": ASSUME.format(date=date_text, ord=ORDINAL[key]),
            "description": "",
        })
    slug = f"eciself{months}mo" if months else "eciself"
    when = f"{months} months from the run date" if months else "at end of 2030"
    return {
        "title": f"Self-elicited frontier-ECI conditions ({when.removeprefix('at ')}), as the runner prepends them",
        "slug": slug,
        "kind": "capability",
        "protocol": f"unified-joint-{slug}-v2",
        "source": {
            "panel": None,
            "wave": f"Frontier ECI {when}, the model's own p10/p25/p50/p75/p90 (Epoch ECI snapshot of {csv_date})",
            "status": "no human panel; the model's percentiles are compared to the metr_graph "
                      "projection at the run's own target date (code/analyze_eci_self.py)",
            "documents": [os.path.relpath(snapshot, ROOT)],
            "outcome_horizons": [],
            "policy_probability_horizons": [],
        },
        "generated_by": os.path.relpath(__file__, ROOT),
        "elicit": {
            "key": "eci_forecast",
            "fields": [k for k, _ in FIELDS],
            "percentiles": {k: p for k, p in FIELDS},
            # Fixed: the ISO date. Rolling: None here, resolved per run from
            # target_months by run_unified.resolve_set and stamped on the rows.
            "target_date": None if months else "2030-12-31",
            "target_months": months,
            "text": ELICIT.format(date=date_text),
            "minimum": 0,
            "maximum": 1000,
        },
        "conditioning": {
            "instruction": INSTRUCTION.format(date=date_text),
            "unconditional_forecast": UNCONDITIONAL.format(date=date_text),
            "definitions": DEFINITIONS.format(csv_date=csv_date,
                                              n_models=n_models, history=history,
                                              top_name=top_name, top_score=top_score,
                                              top_date=top_date),
            "horizon": f"every condition is a level of the frontier ECI on {date_text}.",
        },
        "history": [{"date": d, "score": s, "model": dn} for d, s, dn in hist],
        "trend": None,
        "conditions": conds,
        "notes": {
            "levels": "per call: the model's own eci_forecast values; the runner stamps "
                      "condition.value with the number the condition refers to.",
            "conditioning": "a fact learned about the world, not an exogenous intervention "
                            "(same clause as data/eci_conditions.json, dated 2030).",
            "comparison": "the model's five percentiles against `trend`" + (
                          " (computed at the resolved date by code/analyze_eci_self.py)" if months else "")
                          + "; this instrument's unconditional against the policy instrument's "
                          "and the fixed ECI set's from the same day.",
            **({"target": f"run date + {months} months; the prompt's {PLACEHOLDER} is filled by "
                          "run_unified.resolve_set with the same month arithmetic as the rolling "
                          "horizons (day clamped to the month's length)."} if months else {}),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--months", type=int, default=None,
                    help="the rolling variant: target = run date + N months (needs --out)")
    args = ap.parse_args()
    if args.months and os.path.abspath(args.out) == os.path.abspath(OUT):
        sys.exit("--months needs its own --out (the default file is the end-of-2030 set)")
    doc = build(args.months)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.check:
        cur = open(args.out, encoding="utf-8").read() if os.path.exists(args.out) else ""
        if cur != text:
            sys.exit(f"{args.out} is stale — rerun {os.path.relpath(__file__, ROOT)}")
        print("ok")
        return
    open(args.out, "w", encoding="utf-8").write(text)
    print(f"  history: {len(doc['history'])} frontier points, "
          f"{doc['history'][0]['date']} -> {doc['history'][-1]['date']}")
    for c in doc["conditions"]:
        h = hashlib.sha256(c["assume"].encode()).hexdigest()[:8]
        print(f"  {c['id']:8} {h}  {c['label']}")
    if doc["trend"]:
        print(f"  trend 2030EOY: " + ", ".join(f"{k} {doc['trend'][k]}" for k, _ in CONDITION_FIELDS))
    else:
        print(f"  rolling: run date + {doc['elicit']['target_months']} months; trend computed at analysis time")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
