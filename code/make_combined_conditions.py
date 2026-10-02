#!/usr/bin/env python3
"""Generate data/combined_conditions.json: ONE survey instrument that carries
both the LEAP Wave 12 policy conditions and the self-elicited six-month
capability conditions -- side by side, never crossed.

Project lead, 2026-08-28: one survey instrument should cover both the
capability and the policy conditions -- not policy x capability, but the two
kept separate: policy questions assuming the median ECI trajectory,
capability questions assuming "whatever the unconditional policy is". This
file is that instrument. One call per model answers every
question x horizon cell fourteen times: unconditionally, under each of the
eight LEAP policies, and under each of the model's own five capability
percentiles -- 210 x 14 = 2,940 probabilities, against 1,890 on the policy
instrument and 1,260 on the capability one.

    python3 code/make_combined_conditions.py           # writes data/combined_conditions.json
    python3 code/make_combined_conditions.py --check    # verify the file is current

WHAT IS COMPOSED AND WHAT IS AUTHORED

  composed   everything the two component sets say, verbatim: LEAP's
             conditioning instruction, frontier-model definition, horizon
             line and all eight policy items (data/leap_policies.json), and
             the capability set's ECI definitions and frontier history, its
             Step-1 elicitation, its fact-learned instruction, horizon line
             and five own-percentile items (data/eci_self6mo_conditions.json).
             The runner renders each item through the same template as the
             component instrument, so a policy's text inside this block is
             byte-identical to its text in the policy instrument
             (tests/test_conditional.py::TestCombinedSet).
  authored   four sentences, and only these: the one-line rule that every
             condition stands alone (conditioning.instruction), the merged
             unconditional line (conditioning.unconditional_forecast), and
             each group's `assumption` -- what that group holds the OTHER
             group's quantity at. Same discipline as every other set:
             nothing about how a policy or a capability level relates to any
             question, no direction, no pace verdict.

THE TWO ASSUMPTIONS, which are the whole design:

  policy       every policy condition sits on the model's own MEDIAN
               capability trajectory -- the frontier ECI on the target date
               is its 50th percentile from eci_forecast, the same level as
               condition eci_p50. LEAP's clause already says "hold other
               factors constant"; this says what constant means for
               capability. The like-for-like baseline for a policy delta is
               therefore eci_p50 rather than the unconditional; on 2026-08-28
               every model's own-median world reproduced its unconditional to
               0.98-1.00x, so the two baselines agree to within noise, and
               the tabs keep reading deltas against the unconditional.
  capability   no policy condition applies: the model assumes whatever AI
               policies it expects to be implemented, as in its unconditional
               forecast. The capability instruction is still the fact-learned
               one (update everything that would accompany that level,
               "how governments and developers respond" included) -- so the
               expected policy response to a capability level is part of the
               world, not held fixed. That is the reading of "whatever the
               unconditional policy is" that keeps the capability set as
               its designer intended; the alternative (freeze policy at the
               unconditional expectation) would contradict that instruction
               and is not what this file says.

The target date is rolling, as in the six-month set: `{target_date}` is
filled by run_unified.resolve_set at run time (run date + 6 months) in every
text here, the group assumptions included.

Protocol tag `unified-joint-combined-v1`: a different instrument from the
policy one (`unified-joint-v*`) and the capability one
(`unified-joint-eciself6mo-v1`), so its unconditional slice is its own
series -- an unconditional answered beside thirteen conditions and an ECI
forecast is not the one answered beside eight policies. Piloted 2026-08-28
into results/combined_runs/; THE PUBLISHED SET since that evening (project
lead: the dashboard shows the panel on the single instrument): the runner
writes its unconditional slice to results/runs/ and the instrument to
results/conditional_runs_combined.jsonl, and the cron runs it.

v1 -> v2 on 2026-09-02: THE AGENTIC HARNESS. The questions and conditions in
this file did not change; what changed is how the models are asked -- the
Metaculus lookup left the toolset, a page reader joined it, the prompt asks
for iterative multi-step search instead of one pass and the loop enforces a
research floor before submit_forecast is offered (code/run_unified.py
SYSTEM / PROMPT_JOINT / MIN_RESEARCH, redlines/tools.py, redlines/llm.py),
reasoning runs at each provider's top rung (redlines.llm.REASONING), and the
cron elicits once instead of five times. A forecast gathered that way is a different elicitation from
one gathered the old way, and the tag is how a reader tells them apart; the
tabs show the newest tag present and fall back to v1 until a v2 run lands
(redlines.conditional.PROTOCOL_LINEAGE).

v3 -> v4 on 2026-09-03: FIVE CAPABILITY CONDITIONS. The model's own 10th and
90th percentiles join the 25th/50th/75th as conditions (project lead: condition
on the 10th and 90th percentiles too, now that they are elicited).
The elicitation was already five percentiles; the instrument now asks a
question in each of those five worlds -- 210 x 14 = 2,940 probabilities a
call. First cron run under v4: Friday 2026-09-04.

v4 -> v5 on 2026-09-10: the prospective incident-counting definitions
(redlines.instrument.CURRENT_INSTRUMENT), same call shape.

v5 -> v6 on 2026-09-15: THE EXTINCTION PAIR. Two cross-cutting questions in
XPT's wording (human extinction, AI extinction: data/auto-arc/
addendum-extinction-2026-09-15.json, docs/extinction-questions-2026-09-15.md)
join the grid, 35 -> 37 questions and 210 -> 222 cells, 3,108 probabilities
a call. Nothing in this file changed; the tag moves because the grid a
model answers beside these conditions did. First scheduled run under v6:
the first cron run after the box carries this code.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LEAP = os.path.join(ROOT, "data", "leap_policies.json")
CAP = os.path.join(ROOT, "data", "eci_self6mo_conditions.json")
OUT = os.path.join(ROOT, "data", "combined_conditions.json")

SLUG = "combined"
PROTOCOL = "unified-joint-combined-v8"
PLACEHOLDER = "{target_date}"

# ── The authored sentences ──────────────────────────────────────────────────
STANDALONE = (
    "Every condition stands alone: a policy condition is not combined with any "
    "capability condition, and a capability condition is not combined with any "
    "policy condition. Each section below states what its conditions assume "
    "about the other."
)

UNCONDITIONAL = (
    "forecast the world as you expect it to unfold, including AI policies you "
    "expect to be implemented and whatever level of AI capability you expect to "
    "be reached by {target_date}."
)

POLICY_ASSUMPTION = (
    "In every policy condition, assume that AI capability progresses along your "
    "median trajectory -- in particular, that the frontier ECI on {target_date} is "
    "approximately your 50th-percentile value from eci_forecast (within about two "
    "points of it), the same level as condition eci_p50 in the CAPABILITY "
    "CONDITIONS section."
)

CAPABILITY_ASSUMPTION = (
    "No policy condition applies here. As in the unconditional forecast, assume "
    "whatever AI policies you expect to be implemented -- not any of the "
    "conditions in the POLICY CONDITIONS section."
)

HORIZON = ("a policy condition is in force through December 31, 2050; a capability "
           "condition is a level of the frontier ECI on {target_date}.")


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def build():
    leap = json.load(open(LEAP, encoding="utf-8"))
    cap = json.load(open(CAP, encoding="utf-8"))
    if not cap.get("elicit") or not cap["elicit"].get("target_months"):
        raise SystemExit(f"{CAP} is not the rolling self-elicited set; this instrument is built on it")
    conds = ([{**c, "group": "policy"} for c in leap["conditions"]]
             + [{**c, "group": "capability"} for c in cap["conditions"]])
    ids = [c["id"] for c in conds]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"condition ids collide across the component sets: {ids}")
    return {
        "title": "Policy and capability conditions in one instrument -- LEAP Wave 12 "
                 "policies beside the self-elicited frontier ECI six months from the run "
                 "date -- as the runner prepends them",
        "slug": SLUG,
        "kind": "policy or capability",
        "protocol": PROTOCOL,
        "source": {
            "panel": "LEAP, for the policy conditions only; no human panel answers the "
                     "capability conditions",
            "wave": "LEAP Wave 12 policies + frontier ECI 6 months from the run date "
                    "(the model's own p10/p25/p50/p75/p90)",
            "status": f"policy: {leap['source']['status']}; capability: {cap['source']['status']}",
            "documents": leap["source"]["documents"] + cap["source"]["documents"],
            "outcome_horizons": leap["source"]["outcome_horizons"],
            "policy_probability_horizons": leap["source"]["policy_probability_horizons"],
            # The component files this was composed from, pinned by content,
            # so --check fails the day either is regenerated.
            "components": [
                {"slug": leap.get("slug", "leap"), "file": os.path.relpath(LEAP, ROOT),
                 "sha256": _sha(LEAP), "generated_by": leap.get("generated_by")},
                {"slug": cap["slug"], "file": os.path.relpath(CAP, ROOT),
                 "sha256": _sha(CAP), "generated_by": cap.get("generated_by"),
                 "protocol": cap.get("protocol")},
            ],
        },
        "generated_by": "code/make_combined_conditions.py",
        "elicit": cap["elicit"],
        "conditioning": {
            "instruction": STANDALONE,
            "unconditional_forecast": UNCONDITIONAL,
            "definitions": cap["conditioning"]["definitions"],
            "horizon": HORIZON,
        },
        "groups": [
            {
                "key": "policy", "kind": "policy", "heading": "POLICY CONDITIONS",
                "instruction": leap["conditioning"]["instruction"],
                "assumption": POLICY_ASSUMPTION,
                "definitions": f"Definitions. Frontier model: {leap['conditioning']['frontier_model']}",
                "horizon": leap["conditioning"]["horizon"],
                "source": leap["source"],
                "authored": ["assumption"],
            },
            {
                "key": "capability", "kind": "capability", "heading": "CAPABILITY CONDITIONS",
                "instruction": cap["conditioning"]["instruction"],
                "assumption": CAPABILITY_ASSUMPTION,
                "definitions": None,
                "horizon": cap["conditioning"]["horizon"],
                "source": cap["source"],
                "authored": ["assumption"],
            },
        ],
        "history": cap["history"],
        "trend": None,
        "conditions": conds,
        "notes": {
            "design": "Nick, 2026-08-28: one instrument covering the policy levers and the "
                      "capability conditionals, never their product. Policy conditions are "
                      "evaluated on the model's own median capability trajectory (its "
                      "eci_p50); capability conditions under whatever policy the model "
                      "expects unconditionally.",
            "baseline": "Each condition's delta is read against the same call's "
                        "unconditional, as on both tabs. For a policy condition the "
                        "like-for-like baseline is eci_p50 (same capability assumption); on "
                        "2026-08-28 every model's own-median world reproduced its "
                        "unconditional (0.98-1.00x), so the two agree to within noise.",
            "authored": "conditioning.instruction, conditioning.unconditional_forecast and "
                        "each group's assumption are ours; every other sentence is the "
                        "component set's, verbatim. A policy item renders byte-identically "
                        "to data/leap_policies.json's (tests/test_conditional.py).",
            "levels": cap["notes"]["levels"],
            "conditioning": "policy: LEAP's exogenous-intervention clause; capability: a "
                            "fact learned about the world (the component sets' own clauses, "
                            "each in its own section).",
            "target": cap["notes"]["target"],
            "cost": "222 cells x 14 keys = 3,108 probabilities per call (210 x 14 = 2,940 "
                    "before the extinction pair, 2026-09-15), against 1,998 on the policy "
                    "instrument and 1,332 on the capability one.",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    doc = build()
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.check:
        cur = open(args.out, encoding="utf-8").read() if os.path.exists(args.out) else ""
        if cur != text:
            sys.exit(f"{args.out} is stale — rerun {os.path.relpath(__file__, ROOT)}")
        print("ok")
        return
    open(args.out, "w", encoding="utf-8").write(text)
    for g in doc["groups"]:
        n = sum(c["group"] == g["key"] for c in doc["conditions"])
        print(f"  {g['key']:11} {n} conditions  {g['heading']}")
    for c in doc["conditions"]:
        h = hashlib.sha256(c["assume"].encode()).hexdigest()[:8]
        print(f"  {c['group']:11} {c['id']:8} {h}  {c['label']}")
    print(f"  rolling: run date + {doc['elicit']['target_months']} months")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
