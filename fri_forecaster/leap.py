#!/usr/bin/env python3
"""Forecast a LEAP survey from the data warehouse with the pi harness.

Question snapshot: a JSON file (dumped from mart.mart_survey_question, e.g.
via scripts/leap_questions.py) pinned into the run root, like the FB driver
pins a question set.

Two shard modes, both per member:

  group    one pi call per question group, run in order. Dependent groups
           (e.g. revenue conditional on the independence question) get the
           earlier group's frozen cells injected into their prompt. Cheap
           retries, full research budget per group. This is shard "b".

  session  ONE pi call for the whole survey: the prompt orders the groups
           and asks for a research turn + submit_cells per group; the model
           sees its own earlier cells in the conversation and can condition
           later answers on them. shard "a".

build    combine members: per-cell mean across members.

Cells are the survey rows: key question_id (a row already is one
dimension/date/percentile cell). Values carry the group's unit; probability
rows are 0-100.
"""
No system prompt: the instrument carries everything. The model gets the
survey (group texts, backgrounds, resolution criteria) and the tools; no
persona, no forecasting advice. The only added text is MECHANICS: the
format contract the tools depend on (cell fields, units, percentile
ordering) and the workflow in session mode.
"""
import argparse
import hashlib
import json
import os
import sys

from fri_forecaster import harness
from fri_forecaster.keys import load_keys

TOOL_DESCRIPTIONS = {
    "web_search": "Search the web. Returns titles, URLs, snippets and dates. Use `recent_days` to restrict to recent news.",
    "read_page": "Read the text of one web page (in windows: pass `offset` to continue a long page).",
    "submit_cells": "Submit forecast cells: a list of {question_id, value}. Call whenever one group's cells are ready.",
    "submit_forecast": "Submit the final summary: a short rationale. Call once, at the end.",
}

CELL_SCHEMA = {"type": "object",
               "required": ["question_id", "value"],
               "properties": {"question_id": {"type": "string"},
                              "value": {"type": "number"}}}

KEY_FIELDS = ["question_id"]
MECHANICS = """MECHANICS: submit every cell listed above, each as {question_id, value} via submit_cells. `value` is one number in the unit stated for the group. For percentile cells give your estimate at that percentile of the asked quantity, in that unit (they must respect their order: p10 <= p50 <= p90). Probability units are percentages: 0-100."""
# The revenue group conditions on the independence group.
DEPENDS_ON = {"43f1bf32b9e4058a7c6fb9c3f633a650078566aaedfdc671e37d7bfb9e418f88":
              "d10e8fa0acd7479ca220e4a4ccebb1911bcbd600651944d96541d1f03b5e3a76"}

PROMPT_VERSION = "leap-v1"


def load_questions(root):
    qpath = os.path.join(root, "questions.json")
    if not os.path.exists(qpath):
        sys.exit(f"{qpath}: missing question snapshot (dump it from the DWH first)")
    return json.load(open(qpath))


def group_cells(g):
    return [q["question_id"] for q in g["questions"]]


def order_groups(groups):
    """Dependencies first: a group's dependency (if any) precedes it."""
    by_id = {g["question_group_id"]: g for g in groups}
    ordered, seen = [], set()
    for g in groups:
        gid = g["question_group_id"]
        dep = DEPENDS_ON.get(gid)
        if dep and dep not in seen and dep in by_id:
            ordered.append(by_id[dep]); seen.add(dep)
        if gid not in seen:
            ordered.append(g); seen.add(gid)
    return ordered


def cell_lines(g):
    lines = ["question_id | dimension | resolution date | cell"]
    for q in g["questions"]:
        pct = q["question_percentile"]
        what = (f"p{int(pct)} percentile" if pct is not None else "value")
        dim = (q["question_dimension"] or "").strip() or "(none)"
        lines.append(f"{q['question_id']} | {dim} | {q['question_resolution_date']} | {what}")
    return lines


def build_group_prompt(g, due, base=None):
    lines = [f"Today is {due}.", "", "GROUP TEXT:", g["question_group_text"], ""]
    if g.get("scenario_description"):
        lines += ["SCENARIO:", g["scenario_description"], ""]
    if g.get("background"):
        lines += ["BACKGROUND:", g["background"], ""]
    if g.get("resolution_criteria"):
        lines += ["RESOLUTION CRITERIA:", g["resolution_criteria"], ""]
    unit = g.get("unit") or "probability (0-100)"
    lines += [f"UNIT: {unit}.", MECHANICS, "", "CELLS:"]
    lines += cell_lines(g)
    if base:
        lines += ["", "YOUR EARLIER, FROZEN FORECASTS - treat these as given and make this answer consistent with them:"]
        for gid, cells in base.items():
            for k, v in cells.items():
                lines.append(f"  {k} = {v}")
    return "\n".join(lines)


def build_session_prompt(groups, due):
    lines = [f"Today is {due}. You are taking part in a survey. There are {len(groups)} question groups; "
             "work through them ONE AT A TIME: research a group (web_search / read_page), then submit that "
             "group's cells with submit_cells, then move to the next group. You will see your own earlier "
             "cells in this conversation: keep your answers consistent with them.", ""]
    for i, g in enumerate(groups, 1):
        lines += [f"=== GROUP {i}/{len(groups)} (question_group_id {g['question_group_id']}) ==="]
        lines += ["UNIT: " + (g.get("unit") or "probability (0-100)") + ".", MECHANICS, "",
                  g["question_group_text"], ""]
        if g.get("background"):
            lines += ["BACKGROUND:", g["background"], ""]
        if g.get("resolution_criteria"):
            lines += ["RESOLUTION CRITERIA:", g["resolution_criteria"], ""]
        lines += ["CELLS:"] + cell_lines(g) + [""]
    return "\n".join(lines)


def slug(s):
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in s)


def member_dir(root, model, thinking, research, shard):
    return os.path.join(root, "members", slug(f"{model}--{thinking}--{'research' if research else 'noresearch'}--{shard}"))


def manifest_of(snapshot, model, thinking, research, shard, min_research, pi):
    return {"model": model, "thinking": thinking, "research": research, "shard": shard,
            "min_research": min_research if research else 0,
            "survey_id": snapshot["survey_id"], "survey_source_id": snapshot["survey_source_id"],
            "prompt_version": PROMPT_VERSION, "pi": pi, "pi_version": harness.pi_version(pi)}


def check_manifest(path, want):
    if os.path.exists(path):
        have = json.load(open(path))
        diff = {k: (have.get(k), want[k]) for k in want if have.get(k) != want[k]}
        if diff:
            sys.exit(f"{path}: this member was run with different settings, refusing to resume: {diff}")
    else:
        json.dump(want, open(path, "w"), indent=1)


def read_results(log):
    results = {}
    if not os.path.exists(log):
        return results
    for line in open(log):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        k = r["group_id"]
        if k not in results or r["complete"]:
            results[k] = r
    return results


def cells_of(r):
    return r.get("cells") or {}


def complete(r):
    return bool(r) and r.get("complete")


def forecast_group_session(gid, g, mdir, args, research, groups):
    """Run the whole survey in one session (already ran? -- only unfinished reruns)."""
    res = harness.run(model=args.model, system="",
                      prompt=build_session_prompt(groups, args.due),
                      workdir=os.path.join(mdir, "calls", "session"),
                      cell_schema=CELL_SCHEMA, key_fields=KEY_FIELDS,
                      allowed_keys=args.all_cells, cells_tool=True,
                      tool_descriptions=TOOL_DESCRIPTIONS,
                      research_tools=harness.RESEARCH_TOOLS if research else (),
                      min_research=args.min_research * len(groups) if research else 0,
                      max_turns=args.max_turns or None,
                      thinking=args.thinking, pi=args.pi, timeout=args.timeout)
    got = {}
    for qid, cell in (res["cells"] or {}).items():
        v = cell.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            got[qid] = float(v)
    return got, res


def cmd_run(args):
    harness.pi_argv(args.pi)             # no pi: fail here, not mid-run
    load_keys()
    root = os.path.abspath(args.root)
    os.makedirs(root, exist_ok=True)
    snapshot = load_questions(root)
    args.snapshot, args.due = snapshot, str(snapshot.get("survey_end_date")
                                                    or snapshot["groups"][0].get("survey_end_date") or "")
    research = not args.no_research
    mdir = member_dir(root, args.model, args.thinking, research, args.shard)
    os.makedirs(mdir, exist_ok=True)
    n_forecast = len([g for g in snapshot["groups"] if g["question_type"] == "forecast"])
    min_res = args.min_research if args.shard == "group" else args.min_research * n_forecast
    check_manifest(os.path.join(mdir, "manifest.json"),
                   manifest_of(snapshot, args.model, args.thinking, research, args.shard, min_res, args.pi))

    groups = [g for g in snapshot["groups"] if g["question_type"] == "forecast"]
    if args.only:
        groups = order_groups([g for g in groups if g["question_group_id"].startswith(args.only)])
    else:
        groups = order_groups(groups)
    args.all_cells = [qid for g in groups for qid in group_cells(g)]
    log = os.path.join(mdir, "results.jsonl")
    results = read_results(log)
    if args.shard == "session":
        # One full-coverage session call serves every group: don't re-run per group.
        full = [r for r in (results.get(g["question_group_id"]) for g in groups) if complete(r)]
        n_all = len(args.all_cells)
        if not full:
            pass
        elif any(len(cells_of(r)) == n_all for r in full):
            print("session already covers every cell; nothing to do")
            return 0
    print(f"survey {snapshot['survey_id'][:8]} member {os.path.basename(mdir)}: {len(groups)} groups, "
          f"{len(args.all_cells)} cells; {sum(complete(results.get(g['question_group_id'])) for g in groups)} groups done")

    frozen = {}      # group_id -> cells, for DEPENDS_ON injection
    spent = [0.0]
    for g in groups:
        gid = g["question_group_id"]
        todo = complete(results.get(gid)) is not True
        if not todo:
            frozen[gid] = cells_of(results[gid])
            continue

        if args.shard == "session":
            got, res = forecast_group_session(gid, g, mdir, args, research, groups)
            if set(args.all_cells) <= set(got):
                # mark the remaining groups complete from this same call
                for h in groups:
                    if h is g or complete(results.get(h["question_group_id"])):
                        continue
                    rr = {"group_id": h["question_group_id"], "cells": got, "wanted": group_cells(h),
                          "complete": True, "rationale": (res.get("answer") or {}).get("rationale"),
                          "rc": res["rc"], "usage": res["usage"], "delivery": res.get("delivery"),
                          "n_evidence": len(res["evidence"]), "attempt": os.path.relpath(res["workdir"], mdir),
                          "same_session_as": gid}
                    with open(log, "a") as f:
                        f.write(json.dumps(rr) + "\n")
                frozen.update({h["question_group_id"]: got for h in groups})
                continue
        else:
            base = {DEPENDS_ON[gid]: frozen[DEPENDS_ON[gid]]} if gid in DEPENDS_ON and DEPENDS_ON[gid] in frozen else None
            res = harness.run(model=args.model, system="",
                              prompt=build_group_prompt(g, args.due, base),
                              workdir=os.path.join(mdir, "calls", gid[:12]),
                              cell_schema=CELL_SCHEMA, key_fields=KEY_FIELDS,
                              allowed_keys=group_cells(g), cells_tool=True,
                              tool_descriptions=TOOL_DESCRIPTIONS,
                              research_tools=harness.RESEARCH_TOOLS if research else (),
                              min_research=args.min_research if research else 0,
                              thinking=args.thinking, pi=args.pi, timeout=args.timeout)
            got = {qid: float(c["value"]) for qid, c in (res["cells"] or {}).items()
                   if isinstance(c.get("value"), (int, float)) and not isinstance(c.get("value"), bool)}
        want = group_cells(g)
        r = {"group_id": gid, "cells": got, "wanted": want, "complete": set(want) <= set(got),
             "rationale": (res.get("answer") or {}).get("rationale"), "rc": res["rc"], "usage": res["usage"],
             "delivery": res.get("delivery"), "n_evidence": len(res["evidence"]),
             "attempt": os.path.relpath(res["workdir"], mdir)}
        with open(log, "a") as f:
            f.write(json.dumps(r) + "\n")
        frozen[gid] = got
        spent[0] += res["usage"].get("cost_usd") or 0
        u = res["usage"]
        print(f"  {gid[:12]}: {len(got)}/{len(want)} cells, research {u.get('research_ok')} ok / "
              f"{u.get('research_failed')} failed, {u.get('seconds')}s, ${u.get('cost_usd')} (total ${spent[0]:.2f})")
        if not r["complete"]:
            missing = sorted(set(want) - set(got))[:5]
            print(f"    INCOMPLETE, rc={res['rc']}, missing e.g. {missing}; rerun to retry")
    n_complete = sum(1 for g in groups if complete(read_results(log).get(g["question_group_id"])))
    print(f"coverage: {n_complete}/{len(groups)} groups complete")


def cmd_build(args):
    root = os.path.abspath(args.root)
    snapshot = load_questions(root)
    members = {}
    for model in args.member:
        mdir = member_dir(root, model, args.thinking, not args.no_research, args.shard)
        if not os.path.exists(os.path.join(mdir, "manifest.json")):
            sys.exit(f"no member run at {mdir}")
        members[os.path.basename(mdir)] = read_results(os.path.join(mdir, "results.jsonl"))
    out_cells, prov = {}, {}
    for g in snapshot["groups"]:
        if g["question_type"] != "forecast":
            continue
        for qid in group_cells(g):
            vals = [(name, cells_of(m[g["question_group_id"]])[qid])
                    for name, m in members.items()
                    if g["question_group_id"] in m and qid in cells_of(m[g["question_group_id"]])]
            if not vals:
                continue
            out_cells[qid] = {"group_id": g["question_group_id"], "value": sum(v for _, v in vals) / len(vals),
                              "n_members": len(vals), "n_success": len(vals),
                              "members": [name for name, _ in vals]}
            for name, v in vals:
                prov.setdefault(name, {})[qid] = v
    path = os.path.join(root, f"{snapshot['survey_source_id']}.{args.shard}.mean.json")
    json.dump({"survey_id": snapshot["survey_id"], "survey_source_id": snapshot["survey_source_id"],
               "aggregate": "mean", "shard": args.shard, "cells": out_cells}, open(path, "w"), indent=1)
    json.dump(prov, open(path + ".provenance.json", "w"), indent=1)
    print(f"{len(out_cells)}/{sum(len(group_cells(g)) for g in snapshot['groups'] if g['question_type'] == 'forecast')} cells "
          f"from {len(members)} member(s) -> {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="forecast the survey with one member")
    r.add_argument("--root", required=True, help="the run folder, shared by every member")
    r.add_argument("--model", required=True, help="pi model id, e.g. anthropic/claude-opus-5.5")
    r.add_argument("--shard", default="group", choices=("group", "session"),
                   help="group: one pi call per question group (b); session: whole survey in one call (a)")
    r.add_argument("--thinking", default="high")
    r.add_argument("--no-research", action="store_true")
    r.add_argument("--min-research", type=int, default=2,
                   help="successful research calls per group (session: multiplied by groups)")
    r.add_argument("--max-turns", type=int, default=None, help="session mode turn limit")
    r.add_argument("--only", default=None, help="run only groups whose id starts with this prefix")
    r.add_argument("--timeout", type=int, default=1800, help="seconds per pi call")
    r.add_argument("--pi", default=harness.DEFAULT_PI)
    b = sub.add_parser("build", help="combine members (mean per cell)")
    b.add_argument("--root", required=True)
    b.add_argument("--member", action="append", required=True, help="pi model id; repeat for an ensemble")
    b.add_argument("--thinking", default="high")
    b.add_argument("--no-research", action="store_true")
    b.add_argument("--shard", default="group", choices=("group", "session"))
    args = ap.parse_args(argv)
    return cmd_run(args) if args.cmd == "run" else cmd_build(args)


if __name__ == "__main__":
    sys.exit(main())
