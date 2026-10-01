#!/usr/bin/env python3
"""THE forecast runner: one call per model, every question, every horizon.

This replaces the per-question elicitation in code/run_forecasts.py. The
evidence is in docs/coherence-experiment.md; the short version:

  - asked one question per call, 46% of severity ladders come back incoherent
    (P rising as the death threshold rises), and 4.5% of cause/total pairs put a
    specific cause above "all causes"
  - asked all rungs of one cause per call, within-ladder violations go to ZERO
    but 0.6% of cross-cause pairs still break
  - asked ALL causes in one call, both go to zero, and the ">=99% pinned rung"
    count drops from 20 to 13
  - on FreeCiv chains, which resolve, batching also improves Brier
    (median -0.0073 per chain, p = 0.010) — so it is not buying tidiness with
    accuracy

So the unit of elicitation is THE WHOLE QUESTION SET. Every question the
dashboard plots is answered in one context, which is what makes the panels
mutually consistent instead of separately plausible.

THE PROMPT STATES NO RELATION BETWEEN THE QUESTIONS, AND MUST NOT (2026-08-18).
Shared context is the whole treatment; coherence is a MEASUREMENT taken after
the fact by redlines/coherence.py, never something the prompt buys. Nick told
the 2026-08-17 project call, verbatim: "nothing is being forced ... we do not
suggest in prompts that it should be, and we do not throw out results that do
not cohere." Until this change that was false — PROMPT carried a four-line
"your numbers must respect the logical relations" block, so every coherence
number the dashboard reported was contaminated by it.

What the evidence licenses, and where this goes past it: the ladder experiment's
arm C (joint + the monotonicity rule) beat arm B (joint, no rule) by nothing at
all, 0.0% violations either way, which is why docs/coherence-experiment.md's own
conclusion reads "Do not state the constraint." That covers the ladder, cross-
cause and subset lines. It does NOT cover the horizon line: arm B carried
"probabilities must be non-decreasing across horizons" too, so that constraint
was never run un-instructed and its 0.0% rate was manufactured — as
tests/test_coherence.py admitted in a comment, "(prompt-enforced both ways)".
Removing it as well is a deliberate step past the experiment, taken because a
rate the prompt dictated is not a rate worth publishing. Expect HORIZON to stop
reading zero. That is the measurement working, not a regression.

tests/test_coherence.py::test_prompt_states_no_constraint guards this file
against a quiet re-instruction.

Composition (Auto-ARC set, 2026-08-18):
  - the four incident causes, each spanning all eight severity rungs
  - the cross-cutting questions (five since 2026-09-15) as their own group; they belong to no
    cause, because a catastrophe at 10% of population is not a rung of any
    incident type
  - EXCLUDED: config.UNBATCHED (the P6-bio comparison rows, which sit at 2045 on
    a deaths-only severity and share neither grid)

Each question carries its own RESOLUTION CRITERIA into the prompt. Bridget's
definitions hold the measurement window, the but-for standard, what counts as
excess mortality, the QALY conversion and the value of a statistical life
— none of it stated in the question text, all of it changing the answer. The
retired set had no criteria to send, so this is new.

Horizons come from the SPEC, not from whichever question sorts first, because
the set has questions on different grids. Two of them are ROLLING (6mo, 12mo):
they move with the run date, so every row stamps `resolves_on` and `run_date`.
Without that a rolling forecast cannot be found or scored later, and two runs a
month apart would both say "6mo" and mean different weeks.

Output rows use the SAME schema as results/forecast_runs.jsonl — one row per
(question_id, model) — so every view, both pages and both golden tests read it
unchanged. Batch provenance rides along in extra fields.

Run with any interpreter that has the acquisition extra installed
(`pip install -e '.[acquire]'` — it pulls in litellm, the only third-party
dependency the runners need; `python3 -m redlines build` still needs none):

    python code/run_unified.py --smoke
    python code/run_unified.py
"""
import argparse
import concurrent.futures as cf
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import traceback
from datetime import date, datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from redlines.llm import call_tools, load_keys, reasoning_for, research_coverage  # noqa: E402
from redlines.tools import FORECAST_TOOLS                # noqa: E402
from redlines.registry import DEFAULT_MODEL_SET, MODEL_SETS, panel_provenance  # noqa: E402
from redlines.instrument import counting_windows  # noqa: E402
from redlines.config import UNBATCHED                      # noqa: E402
from redlines.questions import (horizon_label, horizon_sort_key,  # noqa: E402
                                resolves_on, severity_label)

LADDER = os.path.join(ROOT, "data", "autoarc_ladder.json")
CROSS = os.path.join(ROOT, "data", "autoarc_crosscutting.json")
RUNLOG = os.path.join(ROOT, "results", "forecast_runs_unified.jsonl")
# LEAP Wave 12 policy conditions (code/make_leap_policies.py), and where a
# conditional run writes. Conditional rows never enter RUNLOG: the panels, the
# timeline and tests/test_coherence.py all read it as THE unconditional series.
POLICIES = os.path.join(ROOT, "data", "leap_policies.json")
CONDITIONAL_LOG = os.path.join(ROOT, "results", "conditional_runs.jsonl")
# The combined instrument -- the policies AND the capability conditions in one
# call (code/make_combined_conditions.py). THE PUBLISHED SET since 2026-08-28
# evening (Nick: the dashboard shows the panel on the single instrument): its
# unconditional slice is the series every panel reads, results/runs/, and the
# whole instrument goes to its own log, which both tabs read.
COMBINED = os.path.join(ROOT, "data", "combined_conditions.json")
# Sets whose unconditional slice IS the published series. Anything else is an
# experiment and is kept out of results/runs/ by main_joint.
PUBLISHED_SETS = (COMBINED, POLICIES)

# Bumped v1 -> v2 on 2026-08-18, when the constraint block left PROMPT. The tag
# is the only thing that separates a forecast the prompt told how to cohere from
# one it did not, so the two must never share a name: every coherence rate we
# publish depends on knowing which arm a row came from.
PROTOCOL = "unified-batch-v2"

# How many model turns a call may take before the loop forces submit_forecast
# (redlines.llm.call_tools max_iters). A turn is one model reply; it may carry
# several tool calls. This is a TERMINATION GUARD, not a budget -- the prompt
# does not mention it (Nick, 2026-09-02: the floor is fine, a stated maximum is
# not; the model stops when more searching would not move a number). 8 -> 20
# with the iterative-search prompt, then 40: the smokes stopped on their own at
# 4 and 16 calls, and the cap only has to sit below what the context holds --
# the ~30k-token instrument plus up to 8,000 characters per tool result plus
# the carried thinking blocks -- for every panel model.
MAX_ROUNDS = 40
# The RESEARCH FLOOR (redlines.llm.call_tools min_evidence): submit_forecast is
# not offered until this many tool calls have returned. Asked nicely, with the
# prompt below and no floor, Fable 5 searched four times, read nothing and
# submitted (2026-09-02 smoke) -- the same behaviour as under the old one-pass
# prompt. Ten is a floor, not a target: 37 questions over six causes of
# catastrophe, so it is roughly one search and one read per cause before the
# model may answer. A turn may carry several calls, so the floor costs a
# handful of turns out of RESEARCH_ROUNDS.
MIN_RESEARCH = 10
# THE COVERAGE RULE (2026-09-11; redlines.llm.call_tools coverage): beside the
# floor, submission is withheld until EVERY question group has had a
# web_search with recent_days tagged with the group's key (`cause`). The
# floor counts calls; this says what they must span. Why: of three GPT-6
# Astra draws of the combined instrument (2026-09-08, 09-10, a 09-11 smoke),
# the 09-10 draw ran eight searches and none on misalignment, and put its
# loss-of-control forecasts at half the other two's, which had each read a
# loss-of-control incident report -- run-to-run spread that was a gap in the
# reading, not a change of mind. The prompt had asked for a recent check on
# each cause all along; the loop now holds the model to it. The groups come
# from the batch (research_tools), so the rule follows the question set.

SYSTEM = f"""You are a careful probabilistic forecaster producing calibrated
probabilities for catastrophic-risk questions. Ground your forecast in evidence,
and gather it in steps: web_search for current events, expert reports, base
rates and published estimates; read_page to read the results that matter in
full; then search again on what you learned. Let each round shape the next
query. Before you estimate, check what has happened recently on EVERY question
group: for each group, at least one web_search with recent_days (counted back
from today's date in your prompt) tagged with that group's key as `cause`.
The submission tools (submit_cells, submit_forecast) are offered only after at
least {MIN_RESEARCH} tool calls have returned (searches or page reads) and every
group has had its recent search; stop once more searching would not move a
number. Reason from base rates first, then adjust. These are low-probability
questions — beware both dismissing tail risk as zero and inflating it for
vividness. When done, call submit_forecast."""

PROMPT = """Today is {today}.
{condition}
Below are {n} forecasting questions, grouped by cause of catastrophe. Forecast
all of them together, in one pass.
{constraints}
{blocks}
Horizons: {horizons}. Each question names the ones it is asked over — answer
those and no others.

Research before answering, in rounds: search for the recent developments, base
rates and expert estimates that bear on each cause of catastrophe, read the
pages that matter most, and search again on what you learn. Then call
submit_forecast ONCE, with a probability in [0,1] for every question x horizon
cell ({cells} in total), a 3-6 sentence rationale covering the whole set, and the
key sources you relied on. After it is accepted you will be asked one more thing, per question: a short
rationale for its numbers naming the mechanism at that severity and the anchor
you used, the sources that mattered most to it, and the assumption you are least
sure of -- research with those questions in mind."""

# The CONDITIONAL ARM (--condition). Everything else in the call is identical
# to the unconditional run -- same models, tools, questions, criteria, horizons,
# token budget -- and the {condition} slot above renders empty when no condition
# is given, so the unconditional prompt is byte-for-byte what it was (checked
# by tests/test_conditional.py). The instruction sentence is LEAP Wave 12's own
# conditioning text, verbatim from data/leap_policies.json; the policy
# description is what a LEAP panelist sees on the survey's Policies tab. We add
# only the framing lines, and they say nothing about how the questions relate
# to each other or to the policy -- the direction of the effect is the
# measurement.
CONDITION_BLOCK = """
===== CONDITION: {label} =====

Forecast every question below CONDITIONAL on the policy scenario in this block.

{instruction}

Condition: {assume}

{description}

{definitions}
Horizon: {horizon}

Every probability you submit is a forecast under this condition, not an
unconditional one.
=====
"""

# THE SINGLE INSTRUMENT (--joint) -- the published protocol from 2026-08-27.
# One call per model that IS the survey: every question x horizon cell,
# answered unconditionally and under each policy condition, in a single
# submission -- the way a LEAP panelist sees one table with Unconditional and
# every condition side by side. Repeats of the whole instrument (--repeats,
# default 3) give the noise, on the conditionals as well as the unconditional.
#
# Two outputs per run. The UNCONDITIONAL slice goes to --out (the dated file
# under results/runs/ that every panel reads through redlines.runlog) and is
# the published series; the WHOLE instrument -- unconditional and every
# condition, same call ids -- goes to results/conditional_runs.jsonl, which
# the Conditional-on panel reads. The unconditional rows are written twice on
# purpose: the series file must stand alone, and the conditional panel pairs
# each condition with its own call's unconditional by call id.
#
# Rows carry their own protocol tag. An unconditional answered beside eight
# policy conditions is a different elicitation from the plain batch that ran
# weekly until 2026-08-27 (same day, an hour apart, it came out ~2x lower on
# the headline cell), so the series marks the switch rather than hiding it.
# The plain batch (no --joint) is kept for ablations and prints a deprecation
# note; it is no longer what the cron runs.
# v1 -> v2 on 2026-08-28, when the three cross-cutting questions moved onto the
# ladder's six-horizon grid (201 -> 210 cells). ADDITIVE, and checked: the 32
# ladder question blocks and the whole LEAP conditions block are byte-identical
# across the bump. What is not additive is the two catastrophe questions'
# criteria, which gained a sentence scoping "the resolution year" to a rolling
# horizon -- so their 2030/2050/2100 numbers are the same question asked under
# slightly different rules, and a reader comparing those three cells across the
# bump should know it. The tag is how anyone can tell.
# This tag is the LEAP-only set's; the published set (COMBINED) carries its own
# in the file (unified-joint-combined-v2 since 2026-09-02, the agentic harness:
# code/make_combined_conditions.py).
# v3 -> v4 on 2026-09-15: the extinction pair (35 -> 37 questions, 210 -> 222
# cells; data/auto-arc/addendum-extinction-2026-09-15.json). Additive, like
# the v1 -> v2 bump: every existing block renders byte-identically.
# v5 -> v6 on 2026-10-01: the extinction pair's criteria stop naming their
# source (XPT, AIRO); docs/extinction-questions-2026-09-15.md.
PROTOCOL_JOINT = "unified-joint-v6"
RUNS_DIR = os.path.join(ROOT, "results", "runs")
UNCONDITIONAL_KEY = "unconditional"

PROMPT_JOINT = """Today is {today}.

Below are {n} forecasting questions, grouped by cause of catastrophe. Forecast
all of them together, in one pass -- and forecast every question x horizon cell
under each of the {k} conditions listed in the CONDITIONS section that follows
the questions: once unconditionally, and once under each {kind} condition.

{blocks}
{conditions}
Horizons: {horizons}. Each question names the ones it is asked over -- answer
those and no others.

Research before answering, in rounds: search for the recent developments, base
rates and expert estimates that bear on each cause of catastrophe, read the
pages that matter most, and search again on what you learn. The conditions need
no searching of their own -- they are assumptions, applied to the same evidence.
Deliver the probabilities with submit_cells, in as many calls as you like: any
subset of the {cells} question x horizon cells per call, each cell with a
probability in [0,1] under each of the {k} conditions
({total} probabilities, keyed by condition id); a later call for a cell
replaces the earlier one. Then call submit_forecast ONCE,
with{extra} a 3-6 sentence rationale covering the whole set, the key sources
you relied on (only pages you read), and any cells not yet delivered. After it is accepted you will be asked one more thing, per question: a short
rationale for its numbers naming the mechanism at that severity and the anchor
you used, the sources that mattered most to it, and the assumption you are least
sure of -- research with those questions in mind."""

# The framing lines are ours; the instruction, the unconditional wording, the
# definitions and every policy description are LEAP's, verbatim. Nothing here
# says how the conditions relate to each other or to any question.
CONDITIONS_BLOCK = """
===== CONDITIONS =====

Each question x horizon cell takes {k} probabilities, keyed by the condition ids
below.

{instruction}

{definitions}
Horizon: {horizon}

--- {uncond_key} ---
Unconditional: {unconditional}
{policy_blocks}
=====
"""

CONDITION_ITEM = """
--- {id} ---
{label}{tag}.
Condition: {assume}

{description}
"""

# A condition with nothing to say beyond its clause (the self-elicited set)
# renders without the empty description's blank lines. Every LEAP condition
# has a description, so the LEAP text is untouched.
CONDITION_ITEM_BARE = """
--- {id} ---
{label}{tag}.
Condition: {assume}
"""

# A SELF-ELICITED set (data/eci_self_conditions.json): the model first
# forecasts a quantity -- the frontier ECI at a date, five percentiles --
# and the conditions refer to its own answers. Same section name, so the
# head of PROMPT_JOINT still points at it; the definitions carry the history
# the model forecasts from; the two steps are numbered so the tool's
# eci_forecast field is not a surprise.
CONDITIONS_BLOCK_ELICIT = """
===== CONDITIONS =====

{definitions}

Step 1 -- {elicit}

Step 2 -- each question x horizon cell takes {k} probabilities, keyed by the
condition ids below.

{instruction}
Horizon: {horizon}

--- {uncond_key} ---
Unconditional: {unconditional}
{policy_blocks}
=====
"""

# A GROUPED set (data/combined_conditions.json, code/make_combined_conditions.py;
# Nick, 2026-08-28: one instrument carrying the policy levers AND the
# capability conditionals, never their product). The set has `groups`, each
# with its own instruction, definitions and horizon -- LEAP's text for the
# policies, the self-elicited set's for capability, both verbatim -- plus one
# `assumption` sentence of ours saying what that group holds the OTHER
# group's quantity at: policy conditions sit on the model's own median
# capability trajectory (its eci_p50), capability conditions under whatever
# policy it expects unconditionally. The `conditions` list stays flat and
# tags each item with its group, so the tool, the cleaner, the stamps and
# summarize() see one list of ids exactly as they do for any other set.
# Each item renders through CONDITION_ITEM / CONDITION_ITEM_BARE, so a LEAP
# policy's text inside this block is byte-identical to its text in the
# policy instrument (tests/test_conditional.py::TestCombinedSet).
PROMPT_JOINT_GROUPED = """Today is {today}.

Below are {n} forecasting questions, grouped by cause of catastrophe. Forecast
all of them together, in one pass -- and forecast every question x horizon cell
under each of the {k} conditions listed in the CONDITIONS section that follows
the questions: once unconditionally, and once under each condition in each of
its {ngroups} groups ({kinds}). Every condition is taken on its own; no
condition from one group is combined with a condition from another.

{blocks}
{conditions}
Horizons: {horizons}. Each question names the ones it is asked over -- answer
those and no others.

Research before answering, in rounds: search for the recent developments, base
rates and expert estimates that bear on each cause of catastrophe, read the
pages that matter most, and search again on what you learn. The conditions need
no searching of their own -- they are assumptions, applied to the same evidence.
Deliver the probabilities with submit_cells, in as many calls as you like: any
subset of the {cells} question x horizon cells per call, each cell with a
probability in [0,1] under each of the {k} conditions
({total} probabilities, keyed by condition id); a later call for a cell
replaces the earlier one. Then call submit_forecast ONCE,
with{extra} a 3-6 sentence rationale covering the whole set, the key sources
you relied on (only pages you read), and any cells not yet delivered. After it is accepted you will be asked one more thing, per question: a short
rationale for its numbers naming the mechanism at that severity and the anchor
you used, the sources that mattered most to it, and the assumption you are least
sure of -- research with those questions in mind."""

GROUP_BLOCK = """
===== {heading} =====

{instruction}

{assumption}

{definitions}{elicit}Horizon: {horizon}
{items}"""


def load_policies(path=POLICIES):
    return json.load(open(path))


# A CONDITION SET is a JSON file in data/leap_policies.json's shape: a
# `conditioning` block (instruction, unconditional_forecast, horizon, and
# either LEAP's frontier_model or a ready `definitions` paragraph), the
# `conditions` (id, label, assume, description, optional leap_id), a `source`,
# and optionally `kind` (the noun the prompt uses: "policy"), `slug` and
# `protocol`. The LEAP set is the published one; data/eci_conditions.json
# (code/make_eci_conditions.py) is the capability set. Rendering is shared and
# the LEAP text is pinned byte-for-byte by tests/test_conditional.py.
def set_kind(policies):
    return policies.get("kind", "policy")


def set_slug(policies):
    return policies.get("slug", "leap")


def set_protocol(policies):
    return policies.get("protocol", PROTOCOL_JOINT)


def _definitions(policies):
    c = policies["conditioning"]
    return c.get("definitions") or f"Definitions. Frontier model: {c['frontier_model']}"


def set_elicits(policies):
    """Every quantity a set asks the model to forecast before the grid, in
    prompt order: [{key, fields, text, minimum, maximum, ...}] -- the tool
    gets one object per entry with one number per field, and the cleaner
    requires all of them. A set carries one as `elicit` (the ECI sets) or
    several as `elicits` (the axes sets, code/make_axis_conditions.py, one
    per group: `group` names the section its text renders in). Optional per
    entry: `monotone` (the fields that must be non-decreasing; default all
    of them), `bounds` ({field: [min, max]}, over the entry's minimum and
    maximum), `target_months` (a rolling date, see resolve_set)."""
    if policies.get("elicits"):
        return list(policies["elicits"])
    e = policies.get("elicit")
    return [e] if e else []


def set_elicit(policies):
    """The set's one elicited quantity, or None -- the first when it has
    several. The ECI sets have exactly one; the axes sets' readers use
    set_elicits."""
    es = set_elicits(policies)
    return es[0] if es else None


def _monotone(elicit):
    return list(elicit.get("monotone") or elicit["fields"])


def set_horizons(policies, horizons):
    """The horizons a set is asked over: the batch's, narrowed to the set's
    own `horizons` list when it carries one (the axes sets: 2030, 2050 and
    2100 only -- a level fixed at end of 2030 says nothing a six-month cell
    should be read under, and the probabilities have to fit one submission)."""
    want = policies.get("horizons")
    if not want:
        return list(horizons)
    missing = [h for h in want if h not in horizons]
    if missing:
        sys.exit(f"condition set {set_slug(policies)!r} asks horizons {missing} "
                 f"the batch does not have ({list(horizons)})")
    return [h for h in horizons if h in want]


def set_groups(policies):
    """A grouped set's groups (key, kind, heading, instruction, assumption,
    definitions, horizon, source), in prompt order; [] for a plain set."""
    return list(policies.get("groups") or [])


def submit_extra(policies):
    es = set_elicits(policies)
    if not es:
        return ""
    parts = [f"{e['key']} ({len(e['fields'])} numbers)" for e in es]
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f" your {listed} and"


def add_months(d, n):
    """d + n calendar months, day clamped to the month's length -- the
    arithmetic redlines.questions.resolves_on uses for the rolling horizons,
    so a set targeting "six months from today" lands on the 6mo horizon's
    own resolution date."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or not y % 400) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


TARGET_PLACEHOLDER = "{target_date}"


def resolve_set(policies, today):
    """A set whose elicited quantity is dated relative to the run
    (elicit.target_months) -> a copy with the date filled into every text
    (TARGET_PLACEHOLDER -> "February 28, 2027") and elicit.target_date set
    (ISO). Any other set is returned as is, untouched."""
    rolling = [e for e in set_elicits(policies) if e.get("target_months")]
    if not rolling:
        return policies
    months = {e["target_months"] for e in rolling}
    if len(months) != 1:
        sys.exit(f"condition set {set_slug(policies)!r}: one rolling date per set, "
                 f"got {sorted(months)} months")
    import copy
    target = add_months(today, months.pop())
    text = f"{target.strftime('%B')} {target.day}, {target.year}"
    out = copy.deepcopy(policies)
    for e in (out.get("elicits") or ([out["elicit"]] if out.get("elicit") else [])):
        if e.get("target_months"):
            e["target_date"] = target.isoformat()
        e["text"] = e["text"].replace(TARGET_PLACEHOLDER, text)
    for k, v in out["conditioning"].items():
        if isinstance(v, str):
            out["conditioning"][k] = v.replace(TARGET_PLACEHOLDER, text)
    for c in out["conditions"]:
        for k in ("label", "assume", "description"):
            if isinstance(c.get(k), str):
                c[k] = c[k].replace(TARGET_PLACEHOLDER, text)
    for g in out.get("groups") or []:
        for k, v in list(g.items()):
            if isinstance(v, str):
                g[k] = v.replace(TARGET_PLACEHOLDER, text)
    return out


def expand_conditions(wanted, policies):
    """--condition ids (or 'all') -> condition dicts, in the file's order."""
    by_id = {c["id"]: c for c in policies["conditions"]}
    if "all" in wanted:
        return list(policies["conditions"])
    unknown = [w for w in wanted if w not in by_id]
    if unknown:
        sys.exit(f"unknown --condition {unknown}; choose from "
                 f"{', '.join(by_id)} or 'all'")
    return [by_id[w] for w in wanted]


def condition_block(cond, policies):
    c = policies["conditioning"]
    return CONDITION_BLOCK.format(label=cond["label"], instruction=c["instruction"],
                                  assume=cond["assume"], description=cond["description"],
                                  definitions=_definitions(policies), horizon=c["horizon"])

def _condition_items(conds):
    """The per-condition items, one rendering for every set."""
    return "".join((CONDITION_ITEM if x.get("description") else CONDITION_ITEM_BARE)
                   .format(id=x["id"], label=x["label"],
                           tag=f" ({x['leap_id']})" if x.get("leap_id") else "",
                           assume=x["assume"], description=x.get("description", ""))
                   for x in conds)


def conditions_block_grouped(conds, policies):
    """The CONDITIONS section of a grouped set: the shared definitions and
    Step 1 (if the set elicits), the key list, the unconditional line, then
    one block per group in the set's order -- each group's own instruction,
    our assumption sentence, its definitions and horizon, and its items."""
    c = policies["conditioning"]
    es = set_elicits(policies)
    # A set-level elicit (the combined set's ECI forecast) is Step 1 in the
    # head; a per-group elicit (the axes sets) renders inside its section,
    # after that section's definitions, which is what the forecast is of.
    shared = [e for e in es if not e.get("group")]
    per_group = {e["group"]: e for e in es if e.get("group")}
    by_group = {}
    for x in conds:
        by_group.setdefault(x["group"], []).append(x)
    groups = [g for g in set_groups(policies) if g["key"] in by_group]
    k = len(conds) + 1
    counts = ", then ".join(f"the {len(by_group[g['key']])} {g['kind']} conditions "
                            f"({g['heading']})" for g in groups)
    keyed = (f"each question x horizon cell takes {k} probabilities, keyed by the "
             f"condition ids below: {UNCONDITIONAL_KEY}, then {counts}. {c['instruction']}")
    head = f"\n===== CONDITIONS =====\n\n{_definitions(policies)}\n\n"
    if shared:
        head += "Step 1 -- " + "\n\n".join(e["text"] for e in shared) + f"\n\nStep 2 -- {keyed}\n\n"
    elif per_group:
        keys = ", ".join(e["key"] for e in es)
        head += (f"Step 1 -- each section below first asks for your own forecast of the "
                 f"quantity its conditions are levels of; give them as {keys}.\n\n"
                 f"Step 2 -- {keyed}\n\n")
    else:
        head += f"{keyed[0].upper()}{keyed[1:]}\n\n"
    head += f"--- {UNCONDITIONAL_KEY} ---\nUnconditional: {c['unconditional_forecast']}\n"
    body = "".join(GROUP_BLOCK.format(heading=g["heading"], instruction=g["instruction"],
                                      assumption=g["assumption"],
                                      definitions=f"{g['definitions']}\n" if g.get("definitions") else "",
                                      elicit=(f"Your forecast -- {per_group[g['key']]['text']}\n\n"
                                              if g["key"] in per_group else ""),
                                      horizon=g["horizon"], items=_condition_items(by_group[g["key"]]))
                   for g in groups)
    return f"{head}{body}\n=====\n"


def conditions_block(conds, policies):
    if set_groups(policies):
        return conditions_block_grouped(conds, policies)
    c = policies["conditioning"]
    items = _condition_items(conds)
    e = set_elicit(policies)
    if e:
        return CONDITIONS_BLOCK_ELICIT.format(k=len(conds) + 1, instruction=c["instruction"],
                                              definitions=_definitions(policies), horizon=c["horizon"],
                                              elicit=e["text"], uncond_key=UNCONDITIONAL_KEY,
                                              unconditional=c["unconditional_forecast"],
                                              policy_blocks=items)
    return CONDITIONS_BLOCK.format(k=len(conds) + 1, instruction=c["instruction"],
                                   definitions=_definitions(policies), horizon=c["horizon"],
                                   uncond_key=UNCONDITIONAL_KEY,
                                   unconditional=c["unconditional_forecast"],
                                   policy_blocks=items)


def constraint_block(spec, groups, by_group):
    """The unified-batch-v1 constraint text, DERIVED from the spec.

    This is the ablation arm only (--state-constraints). v2, the default, says
    nothing about how the questions relate, which is what makes the coherence
    rate a measurement instead of a compliance check.

    It is derived rather than restored. The literal v1 block named "All causes"
    and questions about "one type of actor, one delivery route" -- none of which
    exist in the Auto-ARC set. Pasting it back would test a prompt that
    describes a different question set, and the comparison would measure that
    confusion instead of the constraint. Every relation below is read from
    spec["relations"], the same structure redlines.coherence audits, so the two
    arms and the scorer can never drift apart.
    """
    rel = spec["relations"]
    labels = {c["key"]: c["label"] for c in spec["causes"]}
    container = labels[rel["cross"]["container"]]
    contained = ", ".join(labels[k] for k in rel["cross"]["contained"])
    lines = [
        "Your numbers must respect the logical relations between these "
        "questions:",
        "  - Probabilities are non-decreasing across horizons.",
        "  - Within a cause, a higher severity threshold is a strictly harder "
        "event, so probability must not increase as the threshold rises.",
        f'  - "{container}" contains {contained}, so at any threshold and '
        "horizon none of those may exceed it.",
    ]
    for b in rel["subset"]:
        lines.append(f"  - {b['why'].capitalize()}, so {b['narrower']} may not "
                     f"exceed {b['broader']}.")
    return "\n".join(lines) + "\n"


def load_batch(ladder_path, cross_path, exclude):
    """-> (groups, {group_key: [question, ...]}, horizons, skipped)

    Every question in one call. The ladder's four causes, in severity order,
    plus the cross-cutting questions as their own group — they belong to no
    cause by design, since a catastrophe at 10% of population is not a rung of
    any incident type.

    No category-to-cause map any more: each ladder question names its own cause
    and each cross-cutting one names none, so the old config.BATCH_CAUSE (and
    the silent-drop bug it caused, which once lost three questions) has nothing
    left to do.
    """
    spec = json.load(open(ladder_path))
    cross = json.load(open(cross_path))["questions"]
    rung_order = [r["short"] for r in spec["rungs"]]
    horizons = sorted([h for h in spec["horizons"] if h],
                      key=lambda h: horizon_sort_key(h, spec))

    groups = [{"key": c["key"], "label": c["label"]} for c in spec["causes"]]
    by_group = {}
    for c in spec["causes"]:
        rungs = [q for q in spec["questions"] if q["cause"] == c["key"]]
        by_group[c["key"]] = sorted(rungs, key=lambda q: rung_order.index(q["rung"]))

    skipped = []
    groups.append({"key": "crosscutting", "label": "Cross-cutting"})
    by_group["crosscutting"] = []
    for q in cross:
        if q["id"] in exclude:
            skipped.append((q["id"], "excluded by config.UNBATCHED"))
            continue
        by_group["crosscutting"].append(q)
    return groups, by_group, horizons, skipped, spec


def submit_tool(qids, horizons):
    return {
        "name": "submit_forecast",
        "description": "Submit your final calibrated forecast for every question.",
        "parameters": {
            "type": "object",
            "properties": {
                "forecasts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_id": {"type": "string", "enum": qids},
                            "horizon": {"type": "string", "enum": horizons},
                            "probability": {"type": "number", "minimum": 0,
                                            "maximum": 1},
                        },
                        "required": ["question_id", "horizon", "probability"],
                    },
                },
                "rationale": {"type": "string"},
                "key_sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["forecasts", "rationale"],
        },
    }


def build_prompt(groups, by_group, horizons, spec, today=None,
                 state_constraints=False, condition=None, policies=None):
    """The whole set in one prompt, with each question's own resolution criteria.

    The criteria are new here. Bridget's definitions carry the measurement
    window, the but-for standard, what counts as excess mortality, the QALY
    conversion and the value of a statistical life — none of which the
    question text states, and all of which change the answer. Before the swap
    the runner sent bare question text because the retired set had no criteria
    to send.

    Shared blocks (severity, dates, the perfect-knowledge clause) are printed
    ONCE at the end rather than repeated under all 32 rungs, which would be
    about 100k characters of duplication and would bury the questions.
    """
    today = today or date.today()
    blocks, n, cells, shared = "", 0, 0, None
    for g in groups:
        qs = by_group[g["key"]]
        if not qs:
            continue
        blocks += f"===== {g['label'].upper()} =====\n\n"
        for q in qs:
            # Per-question horizons, because they genuinely differ. The
            # cross-cutting questions are not asked over a rolling window:
            # P(10% of humanity dies within six months) is noise, and Jason's
            # near-term signal lives on the incident ladder. Stating the whole
            # union grid here and filtering afterwards would still spend the
            # model's effort on the cells we then throw away.
            mine = [h for h in horizons if h in q["horizons"]]
            # The ladder's own label, verbatim: this line is part of the pinned
            # prompt text (severity_label() is the PAGE's wording).
            blocks += f"--- {q['id']} (severity: {q['severity']['label']}) ---\n"
            blocks += f"{q['text']}\n"
            blocks += f"Horizons for this question: {', '.join(mine)}\n"
            if q.get("criteria"):
                blocks += f"\nResolution criteria:\n{q['criteria']}\n"
            blocks += "\n"
            shared = shared or q.get("details")
            n += 1
            cells += len(mine)
    if isinstance(shared, dict):
        blocks += "===== APPLIES TO EVERY INCIDENT QUESTION ABOVE =====\n\n"
        for k, v in shared.items():
            if v:
                blocks += f"{k.replace('_', ' ').title()}:\n{v}\n\n"
        if spec.get("instrument_version"):
            incident = next(q for qs in by_group.values() for q in qs
                            if q.get("category") == "incident")
            windows = counting_windows(incident, horizons, today, spec)
            blocks += "Incident onset intervals (inclusive UTC calendar dates):\n"
            for h, window in windows.items():
                blocks += f"  {h}: {window['start']} through {window['end']}\n"
            blocks += ("These are onset intervals only. Count each eligible incident's "
                       "first three years of harm, including harm after its onset deadline. "
                       "The separate catastrophe and disempowerment questions retain "
                       "their own criteria.\n\n")

    # Rolling horizons must be dated in the prompt. "6mo" alone leaves the model
    # to guess the window, and two runs a month apart would be answering
    # different questions under the same label without either saying so.
    hz = ", ".join(f"{h} ({horizon_label(h, spec, today)})" for h in horizons)
    constraints = (constraint_block(spec, groups, by_group)
                   if state_constraints else "")
    cond = condition_block(condition, policies) if condition else ""
    return PROMPT.format(today=today.isoformat(), n=n, blocks=blocks,
                         horizons=hz, cells=cells, condition=cond,
                         constraints=constraints), n, cells


def clean_forecasts(raw, allowed, horizons):
    """-> {question_id: [{horizon, probability}, ...]}, or None.

    `allowed` is {question_id: {horizon, ...}} — PER QUESTION, not one global
    set. A model that answers the cross-cutting questions over a rolling window
    anyway has answered something we did not ask, and keeping it would put a
    six-month catastrophe forecast on a panel that never requested one.

    Same JSON-string defence as run_forecasts.py (Fable 5 has handed the array
    back as a string). A partial grid is kept: every downstream audit tolerates
    gaps, and a partial answer beats none.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, list):
        return None
    out = {}
    for f in raw:
        if not isinstance(f, dict):
            continue
        q, h, p = f.get("question_id"), f.get("horizon"), f.get("probability")
        if q in allowed and h in allowed[q] and isinstance(p, (int, float)):
            out.setdefault(q, {})[h] = p
    return {q: [{"horizon": h, "probability": p} for h, p in sorted(v.items())]
            for q, v in out.items()} or None


def _num_schema(lo, hi):
    out = {"type": "number"}
    if lo is not None:
        out["minimum"] = lo
    if hi is not None:
        out["maximum"] = hi
    return out


def _cells_schema(qids, horizons, cond_ids):
    keys = [UNCONDITIONAL_KEY] + list(cond_ids)
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "question_id": {"type": "string", "enum": qids},
                "horizon": {"type": "string", "enum": horizons},
                "probabilities": {
                    "type": "object",
                    "description": "one probability in [0,1] per condition id: " + ", ".join(keys),
                    "properties": {k: {"type": "number", "minimum": 0, "maximum": 1} for k in keys},
                    "required": keys,
                },
            },
            "required": ["question_id", "horizon", "probabilities"],
        },
    }


def submit_cells_tool(qids, horizons, cond_ids):
    """The PARTIAL tool (redlines.llm.call_tools partial_tool, 2026-09-02
    evening): the model delivers the grid in as many calls as it likes, any
    subset of cells per call; the runner keeps them (run_one_joint) and
    answers with the running count and what is still missing. Same cell
    schema as submit_forecast's `forecasts`."""
    return {
        "name": "submit_cells",
        "description": "Deliver forecasts in pieces: any subset of question x horizon cells, each "
                       "with a probability under every condition id. Call it as often as you "
                       "like; a later call for a cell replaces the earlier one. Returns how many "
                       "cells have been received and which are still missing.",
        "parameters": {
            "type": "object",
            "properties": {"forecasts": _cells_schema(qids, horizons, cond_ids)},
            "required": ["forecasts"],
        },
    }


def submit_tool_joint(qids, horizons, cond_ids, elicit=None):
    """The FINAL tool: rationale, sources, the elicited quantities, and any
    cells not delivered with submit_cells (`forecasts` is optional here since
    2026-09-02 evening; a call may still carry the whole grid). With `elicit`
    (one entry, or the set_elicits list), one required object of numbers per
    entry, listed first."""
    tool = {
        "name": "submit_forecast",
        "description": "Submit your final answer: the rationale, the key sources you read, "
                       "and any question x horizon cells not yet delivered with submit_cells.",
        "parameters": {
            "type": "object",
            "properties": {
                "forecasts": _cells_schema(qids, horizons, cond_ids),
                "rationale": {"type": "string"},
                "key_sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["rationale"],
        },
    }
    elicits = [elicit] if isinstance(elicit, dict) else list(elicit or [])
    for e in elicits:
        mono, bounds = _monotone(e), e.get("bounds") or {}
        order = ("" if len(mono) < 2 else ", in non-decreasing order" if mono == list(e["fields"])
                 else f"; {', '.join(mono)} in non-decreasing order")
        tool["parameters"]["properties"][e["key"]] = {
            "type": "object",
            "description": f"your forecast: one number per field, {', '.join(e['fields'])}{order}",
            "properties": {f: _num_schema(*bounds.get(f, (e.get("minimum", 0), e.get("maximum", 1e9))))
                           for f in e["fields"]},
            "required": list(e["fields"]),
        }
    tool["parameters"]["required"] = [e["key"] for e in elicits] + tool["parameters"]["required"]
    return tool


# THE DEBRIEF (2026-09-15, project lead; PER QUESTION since 2026-09-16):
# after the forecasts are accepted, one more turn asks, for EACH question,
# what drove its numbers -- a short rationale naming the mechanism at that
# severity and the anchor used, the sources that mattered most, and the
# assumption the model is least sure of. The first version (2026-09-15)
# asked per question GROUP (five entries); the cyber tail diagnostic of
# 2026-09-16 showed that a
# group-level pathway says nothing about the individual rungs that carry
# the expected loss, and the project lead's design was always the standard
# elicitation plus a rationale per rung per outcome: the run is the run,
# and the rationale data comes with it. Asked AFTER submission so it cannot
# move the numbers (redlines.llm.call_tools `debrief`); stored on the
# call's first row as `debrief` (the answer, keyed by question id) and
# `debrief_status`; exported as results/debriefs.csv (redlines.export).
# The harness merges deliveries across attempts and accepts a stringified
# entry, because Fable 5.1 truncated and stringified the five-entry version.
DEBRIEF_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {
            "type": "string",
            "description": "2-4 plain sentences: what drives your numbers for this question "
                           "across its horizons -- for a severity rung, the mechanism by which "
                           "that severity is reached and the historical anchor or base rate you "
                           "used, with its number; for a cross-cutting question, the pathway and "
                           "anchor likewise"},
        "key_sources": {
            "type": "array",
            "description": "the 1-3 sources that mattered most to this question's numbers, by "
                           "URL, each with one clause on what it contributed; only sources you "
                           "read or saw in this conversation",
            "items": {"type": "object",
                      "properties": {"url": {"type": "string"},
                                     "contribution": {"type": "string"}},
                      "required": ["url", "contribution"]}},
        "weakest_link": {
            "type": "string",
            "description": "one sentence: the assumption behind these numbers that the evidence "
                           "supports least"},
    },
    "required": ["rationale", "key_sources", "weakest_link"],
}


def debrief_questions(groups, by_group):
    """The questions a debrief covers, in prompt order."""
    return [q for g in groups for q in by_group[g["key"]]]


# Anthropic's tool schemas allow property keys matching ^[a-zA-Z0-9_.-]{1,64}$
# only: a question id's colons are refused ("ladder:ai:100"), which is how
# the first per-question debrief (2026-09-16 16:45 UTC) failed for Fable 5.1
# and Opus 5 while the OpenAI models answered it. The tool is keyed by the
# id with ':' written as '__', and the answer is keyed back by id before it
# is stored, so the row and the CSV never see the tool's spelling.
def debrief_key(qid):
    return qid.replace(":", "__")


def debrief_qid(key):
    return key.replace("__", ":")


def debrief_tool(questions):
    """The debrief tool: one object per question, all required."""
    return {
        "name": "submit_debrief",
        "description": "After your forecasts are accepted: for each question, what drove "
                       "its numbers. Plain language a reader outside this conversation can "
                       "follow; no shorthand. May be called more than once, each call "
                       "carrying some questions; entries merge. Keys are the question ids "
                       "with ':' written as '__'.",
        "parameters": {
            "type": "object",
            "properties": {debrief_key(q["id"]): {**DEBRIEF_QUESTION_SCHEMA,
                                                  "description": f"{q['id']}: " + (q.get("text") or "")[:180]}
                           for q in questions},
            "required": [debrief_key(q["id"]) for q in questions],
        },
    }


def debrief_prompt(questions):
    ids = ", ".join(debrief_key(q["id"]) for q in questions)
    return (
        "Your forecasts are accepted and will not change. Now call submit_debrief with one "
        f"entry for EACH question, keyed by its id with ':' written as '__': {ids}. If one "
        "call cannot carry them all, call it again with the rest; entries merge. For each "
        "question, in plain language "
        "that a reader who has not seen this conversation can follow (spell out every idea; "
        "no abbreviations or shorthand): rationale -- 2-4 sentences on what drives your "
        "numbers for it across its horizons: for a severity rung, the mechanism by which that "
        "severity is reached and the historical anchor or base rate you used, with its "
        "number; key_sources -- the 1-3 sources that mattered most, by URL, each with one "
        "clause on what it contributed, only sources you read or saw here; weakest_link -- "
        "one sentence naming the assumption the evidence supports least. Be specific and "
        "concrete; do not restate your probabilities.")


def validate_debrief(args, questions):
    """Problems with a debrief, in the model's terms; [] when it is complete."""
    problems = []
    if not isinstance(args, dict):
        return ["the debrief must be an object keyed by question id"]
    for q in questions:
        d = args.get(debrief_key(q["id"]), args.get(q["id"]))
        if not isinstance(d, dict):
            problems.append(f"{q['id']}: missing")
            continue
        r = d.get("rationale")
        if not (isinstance(r, str) and len(r.strip()) >= 60):
            problems.append(f"{q['id']}: rationale needs 2-4 sentences")
        ks = d.get("key_sources")
        if not (isinstance(ks, list) and ks and all(
                isinstance(x, dict) and isinstance(x.get("url"), str) and x["url"].strip()
                and isinstance(x.get("contribution"), str) and x["contribution"].strip() for x in ks)):
            problems.append(f"{q['id']}: key_sources needs 1-3 items, each with url and contribution")
        wl = d.get("weakest_link")
        if not (isinstance(wl, str) and wl.strip()):
            problems.append(f"{q['id']}: weakest_link missing")
    return problems


def debrief_state(groups, by_group):
    """A fresh `debrief` dict for redlines.llm.call_tools, per attempt. Three
    retries and a 48k turn: 37 entries is a long tool call, and deliveries
    merge across attempts."""
    qs = debrief_questions(groups, by_group)
    return {"tool": debrief_tool(qs), "prompt": debrief_prompt(qs),
            "validate": lambda args: validate_debrief(args, qs), "retries": 3,
            "max_tokens": 48000}


def debrief_fields(state, first):
    """The two row fields, on the call's first row only."""
    if not first:
        return {"debrief": None, "debrief_status": None}
    result = state.get("result")
    if isinstance(result, dict):     # the tool's key spelling -> the question id
        result = {debrief_qid(k): v for k, v in result.items()}
    return {"debrief": result,
            "debrief_status": {k: state.get(k) for k in ("complete", "attempts", "problems", "error")}}


def debrief_note(rows):
    """For the log: how the debrief went, from the first row."""
    st = (rows[0].get("debrief_status") if rows else None) or {}
    if not st or st.get("attempts") is None:
        return "no debrief"
    if st.get("complete"):
        return f"debrief ok ({st['attempts']} attempt(s))"
    if st.get("error"):
        return f"debrief FAILED ({st['error'][:80]})"
    return f"debrief INCOMPLETE ({len(st.get('problems') or [])} problem(s) after {st['attempts']} attempt(s))"


def clean_elicit(raw, elicit):
    """-> {field: float} with every field present and non-decreasing, else None."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for f in elicit["fields"]:
        v = raw.get(f)
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return None
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        out[f] = float(v)
    vals = [out[f] for f in _monotone(elicit)]
    if any(b < a for a, b in zip(vals, vals[1:])):
        return None
    bounds = elicit.get("bounds") or {}
    for f in elicit["fields"]:
        lo, hi = bounds.get(f, (elicit.get("minimum"), elicit.get("maximum")))
        if (lo is not None and out[f] < lo) or (hi is not None and out[f] > hi):
            return None
    return out


def build_prompt_joint(groups, by_group, horizons, spec, conds, policies, today=None):
    """The whole set, and the whole condition set, in one prompt.

    The question blocks are exactly build_prompt's (same criteria, same shared
    blocks, same horizon line); the CONDITIONS section follows them.
    -> (prompt, n_questions, n_cells) where n_cells counts question x horizon,
    not x condition.
    """
    today = today or date.today()
    policies = resolve_set(policies, today)
    # The conditions come from the resolved set too (a rolling set's texts
    # carry the date); the caller's list only says which ones, in what order.
    by_id = {c["id"]: c for c in policies["conditions"]}
    conds = [by_id[c["id"]] for c in conds]
    base, n, cells = build_prompt(groups, by_group, horizons, spec, today)
    head = f"Today is {today.isoformat()}.\n\nBelow are {n} forecasting questions, grouped by cause of catastrophe. Forecast\nall of them together, in one pass.\n\n"
    tail_at = base.index("\nHorizons: ")
    assert base.startswith(head), "build_prompt's head changed; update build_prompt_joint"
    blocks = base[len(head):tail_at]
    hz = ", ".join(f"{h} ({horizon_label(h, spec, today)})" for h in horizons)
    k = len(conds) + 1
    groups = set_groups(policies)
    if groups:
        present = [g for g in groups if any(c.get("group") == g["key"] for c in conds)]
        kinds = " and ".join(f"{g['kind']} conditions" for g in present)
        return PROMPT_JOINT_GROUPED.format(
            today=today.isoformat(), n=n, k=k, blocks=blocks, ngroups=len(present),
            kinds=kinds, extra=submit_extra(policies),
            conditions=conditions_block(conds, policies),
            horizons=hz, cells=cells, total=cells * k), n, cells
    return PROMPT_JOINT.format(today=today.isoformat(), n=n, k=k, blocks=blocks,
                               kind=set_kind(policies), extra=submit_extra(policies),
                               conditions=conditions_block(conds, policies),
                               horizons=hz, cells=cells, total=cells * k), n, cells


def _as_list(raw):
    """A grid delivered as a JSON string (some models stringify the array)
    parsed to a list; anything that is not a list becomes []."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return raw if isinstance(raw, list) else []


def clean_forecasts_joint(raw, allowed, horizons, cond_ids):
    """-> {condition_key: {question_id: [{horizon, probability}, ...]}}, or None.

    Same defences as clean_forecasts; a cell whose probabilities object lacks
    a condition keeps the conditions it has. Keys are UNCONDITIONAL_KEY and
    the condition ids.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, list):
        return None
    keys = [UNCONDITIONAL_KEY] + list(cond_ids)
    out = {k: {} for k in keys}
    for f in raw:
        if not isinstance(f, dict):
            continue
        q, h, ps = f.get("question_id"), f.get("horizon"), f.get("probabilities")
        if isinstance(ps, str):
            try:
                ps = json.loads(ps)
            except json.JSONDecodeError:
                continue
        if q not in allowed or h not in allowed[q] or not isinstance(ps, dict):
            continue
        for k in keys:
            p = ps.get(k)
            if isinstance(p, (int, float)) and not isinstance(p, bool):
                out[k].setdefault(q, {})[h] = p
    out = {k: {q: [{"horizon": h, "probability": p} for h, p in sorted(v.items())]
               for q, v in grid.items()}
           for k, grid in out.items() if grid}
    return out or None


def research_tools(groups):
    """FORECAST_TOOLS with web_search's `cause` narrowed to this batch's
    question groups (an enum, required), and the coverage keys the loop
    holds the model to. -> (tools, keys). The shared tool is left untouched."""
    keys = [g["key"] for g in groups]
    search = copy.deepcopy(FORECAST_TOOLS[0])
    search["parameters"]["properties"]["cause"] = {
        "type": "string", "enum": keys,
        "description": "the question group this search is for: "
                       + "; ".join(f"{g['key']} = {g['label']}" for g in groups)
                       + ". Every group needs at least one search with recent_days "
                         "tagged with its key before submission is offered."}
    search["parameters"]["required"] = ["query", "cause"]
    return [search] + list(FORECAST_TOOLS[1:]), keys


def coverage_line(rows):
    """'coverage ai:1 bio:1 ...' from a call's recorded evidence, for the log."""
    cov = research_coverage([e for r in rows for e in (r.get("evidence") or [])])
    return "coverage " + " ".join(f"{k}:{n}" for k, n in cov.items()) if cov else "coverage none"


def run_one_joint(label, model_id, groups, by_group, horizons, run_id, retries, spec,
                  conds, policies, experiment=None, arm=None, panel=None, today=None):
    """One call: the full instrument. -> rows, one per (question, condition)."""
    today = today or datetime.now(timezone.utc).date()
    policies = resolve_set(policies, today)
    conds = [c for c in policies["conditions"] if c["id"] in {x["id"] for x in conds}]
    prompt, n, want_cells = build_prompt_joint(groups, by_group, horizons, spec,
                                               conds, policies, today)
    block = conditions_block(conds, policies)
    sha = hashlib.sha256(block.encode()).hexdigest()
    cond_ids = [c["id"] for c in conds]
    stamps = {UNCONDITIONAL_KEY: None}
    # A grouped set stamps each condition with its group and the group's own
    # source (LEAP's wave for a policy, the ECI set's for a capability level).
    cgroups = {g["key"]: g for g in set_groups(policies)}
    for c in conds:
        g = cgroups.get(c.get("group")) if cgroups else None
        stamps[c["id"]] = {"id": c["id"], "leap_id": c.get("leap_id"), "label": c["label"],
                           "source": ((g or {}).get("source") or {}).get("wave") or policies["source"]["wave"],
                           "sha256": sha, "set": set_slug(policies),
                           **({"group": c["group"]} if cgroups else {})}
    qids = [q["id"] for g in groups for q in by_group[g["key"]]]
    allowed = {q["id"]: {h for h in horizons if h in q["horizons"]}
               for g in groups for q in by_group[g["key"]]}
    want = want_cells * (len(conds) + 1)
    elicits = set_elicits(policies)
    grids, answer, evidence, attempts, elicited = None, {}, [], 0, None
    usage = {}   # the whole call's tokens and price, retries included
    # The grid arrives in pieces (submit_cells; redlines.llm.call_tools
    # partial_tool): keyed by cell, a later piece replacing an earlier one,
    # the final call's `forecasts` last. `delivery` records how it came.
    received, delivery = {}, {"cells_calls": 0, "cells_in_pieces": 0, "cells_in_final": 0}

    def take_cells(forecasts=None, **_):
        delivery["cells_calls"] += 1
        n = 0
        forecasts = _as_list(forecasts)
        for f in forecasts:
            if (isinstance(f, dict) and f.get("question_id") in allowed
                    and f.get("horizon") in allowed[f["question_id"]]
                    and isinstance(f.get("probabilities"), dict)):
                received[(f["question_id"], f["horizon"])] = f
                n += 1
        missing = [f"{q} @ {h}" for q in qids for h in horizons
                   if h in allowed[q] and (q, h) not in received]
        return {"accepted": n, "received": len(received), "of": want_cells,
                "missing": len(missing), "missing_first": missing[:20]}

    partial = {**submit_cells_tool(qids, horizons, cond_ids), "fn": take_cells}
    while attempts <= retries:
        attempts += 1
        received.clear()
        delivery.update(cells_calls=0, cells_in_pieces=0, cells_in_final=0)
        try:
            research, coverage = research_tools(groups)
            debrief = debrief_state(groups, by_group)
            answer, evidence = call_tools(
                model_id, prompt, research, submit_tool_joint(qids, horizons, cond_ids, elicits),
                system=SYSTEM, max_iters=MAX_ROUNDS, max_tokens=64000,
                min_evidence=MIN_RESEARCH, usage=usage, partial_tool=partial,
                coverage=coverage, debrief=debrief)
        except Exception as exc:
            # A provider error or a call that never submitted: worth the same
            # retry budget as a short grid, and just as visible in the log.
            if attempts > retries:
                raise
            print(f"  retry {label:16} attempt {attempts}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        delivery["cells_in_pieces"] = len(received)
        merged = dict(received)
        for f in _as_list(answer.get("forecasts")):
            if isinstance(f, dict) and "question_id" in f and "horizon" in f:
                merged[(f["question_id"], f["horizon"])] = f
                delivery["cells_in_final"] += 1
        answer["forecasts"] = list(merged.values())
        grids = clean_forecasts_joint(answer.get("forecasts"), allowed, horizons, cond_ids)
        got = sum(len(v) for g in (grids or {}).values() for v in g.values())
        elicited = ({e["key"]: clean_elicit(answer.get(e["key"]), e) for e in elicits}
                    if elicits else None)
        if grids and got >= 0.9 * want and (not elicits or all(elicited.values())):
            break
        print(f"  retry {label:16} attempt {attempts}: {got}/{want} cells x conditions"
              + "".join(f", {k} {'ok' if v else 'missing/unordered'}"
                        for k, v in (elicited or {}).items()))
    # Stamp each condition with the level it names in this call: a fixed
    # level carries its own `value` (the axes sets); a condition on the
    # model's own number (`field`) takes what it gave for that field of its
    # elicit -- the set's one, or the one the condition's `elicit` names.
    for c in conds:
        if c.get("value") is not None:
            stamps[c["id"]]["value"] = c["value"]
        elif c.get("field"):
            key = c.get("elicit") or (elicits[0]["key"] if elicits else None)
            stamps[c["id"]]["value"] = ((elicited or {}).get(key) or {}).get(c["field"])
    hits = sum(len((e.get("result") or {}).get("results") or [])
               for e in evidence if e.get("tool") == "web_search")
    debrief = debrief if attempts else debrief_state(groups, by_group)
    # Cited but not read (the source-quality pass, 2026-09-02 evening): the
    # key sources the model lists that no read_page call in this call fetched.
    read = {(e.get("args") or {}).get("url") for e in evidence if e.get("tool") == "read_page"}
    unread = [u for u in (answer.get("key_sources") or []) if isinstance(u, str) and u not in read]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    call_id = f"{run_id}:{set_slug(policies)}:{arm}:{label}"
    rows, first = [], True
    for key in [UNCONDITIONAL_KEY] + cond_ids:
        grid = (grids or {}).get(key) or {}
        for g in groups:
            for q in by_group[g["key"]]:
                rows.append({
                    "run_id": run_id, "elicited_at": stamp,
                    "question_id": q["id"], "model": model_id, "label": label,
                    "forecasts": grid.get(q["id"]),
                    "rationale": answer.get("rationale"),
                    "key_sources": answer.get("key_sources"),
                    "grounded": hits > 0, "search_hits": hits,
                    "evidence": evidence if first else [],
                    # What the call cost, on the same row as its evidence
                    # (redlines.llm.tally_usage): turns, tokens, cost_usd.
                    "usage": usage if first else None,
                    # How the grid arrived (submit_cells pieces vs the final
                    # call) and which cited sources were never read.
                    "delivery": dict(delivery) if first else None,
                    "unread_sources": unread if first else None,
                    # The debrief turn's answer and how it went (call_tools
                    # `debrief`), on the call's first row like the evidence.
                    **debrief_fields(debrief, first),
                    "resolves_on": {h: resolves_on(h, today, spec) for h in horizons},
                    "run_date": today.isoformat(),
                    "instrument_version": spec.get("instrument_version"),
                    "counting_window": counting_windows(q, horizons, today, spec),
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "prompt": prompt if first else None,
                    "system_prompt": SYSTEM if first else None,
                    "protocol": set_protocol(policies),
                    "condition_set": set_slug(policies),
                    "call_id": call_id, "attempts": attempts,
                    "batch_size": len(qids),
                    "cause": q.get("cause"), "group": g["key"],
                    "asked_horizons": q.get("horizons"),
                    "raw_forecasts": (None if grids else answer.get("forecasts")) if first else None,
                    "condition": stamps[key],
                    # The elicited quantity (a self-conditioned set), on every
                    # row of the call; None for other sets.
                    "elicited": ({**elicited,
                                  # The rolling date when the set has one, else
                                  # the first quantity's; every quantity's under
                                  # `targets`.
                                  "target_date": next((e.get("target_date") for e in elicits
                                                       if e.get("target_months")),
                                                      elicits[0].get("target_date")),
                                  "targets": {e["key"]: e.get("target_date") for e in elicits}}
                                 if elicits else None),
                    "experiment": experiment, "arm": arm,
                    # Which conditions this call was asked, so a partial
                    # submission is visibly partial.
                    "joint_conditions": [UNCONDITIONAL_KEY] + cond_ids,
                    # Which model set this call belongs to -- for the ECI
                    # panel, which snapshot chose it (redlines.registry).
                    "panel": panel,
                })
                first = False
    return rows


def run_one(label, model_id, groups, by_group, horizons, run_id, retries, spec,
            state_constraints=False, condition=None, policies=None,
            experiment=None, arm=None, panel=None, today=None):
    today = today or datetime.now(timezone.utc).date()
    prompt, n, want_cells = build_prompt(groups, by_group, horizons, spec, today,
                                         state_constraints, condition, policies)
    # Provenance for a conditional row: which condition, and a hash of the exact
    # block the model saw, so a later edit to the policy text cannot be pooled
    # with this run unnoticed.
    cond_stamp = None
    if condition:
        block = condition_block(condition, policies)
        cond_stamp = {"id": condition["id"], "leap_id": condition["leap_id"],
                      "label": condition["label"],
                      "source": policies["source"]["wave"],
                      "sha256": hashlib.sha256(block.encode()).hexdigest()}
    qids = [q["id"] for g in groups for q in by_group[g["key"]]]
    allowed = {q["id"]: {h for h in horizons if h in q["horizons"]}
               for g in groups for q in by_group[g["key"]]}
    grid, answer, evidence, attempts = None, {}, [], 0
    # Batching concentrates failure: one empty submission costs every question,
    # not one. Gemini 3.1 Pro did exactly that in the ladder experiment (searched
    # seven times, submitted nothing). Retry on an empty or badly partial grid.
    usage = {}   # the whole call's tokens and price, retries included
    debrief = debrief_state(groups, by_group)
    while attempts <= retries:
        attempts += 1
        research, coverage = research_tools(groups)
        debrief = debrief_state(groups, by_group)
        answer, evidence = call_tools(
            model_id, prompt, research, submit_tool(qids, horizons),
            system=SYSTEM, max_iters=MAX_ROUNDS, max_tokens=32000,
            min_evidence=MIN_RESEARCH, usage=usage, coverage=coverage, debrief=debrief)
        grid = clean_forecasts(answer.get("forecasts"), allowed, horizons)
        # CELLS, not questions. The guard used to read len(grid) >= 0.9 *
        # len(qids), which counts a question as complete the moment ONE of its
        # horizons comes back. A model that answered all 35 questions at a
        # single horizon -- 35 of 201 cells -- scored 100% and was never
        # re-asked. Six horizons per incident question make that a 6x gap.
        got = sum(len(v) for v in (grid or {}).values())
        if grid and got >= 0.9 * want_cells:
            break
        print(f"  retry {label:16} attempt {attempts}: {got}/{want_cells} cells "
              f"({len(grid or {})}/{len(qids)} questions)")
    # A search that RAN is not a search that WORKED. bool(evidence) was true
    # whenever the model called web_search at all, including when every call
    # came back {"results": [], "error": "web search unavailable (no
    # TAVILY_API_KEY set)"} -- which is exactly what an expired ADC token
    # produces. The 2026-08-18 smoke wrote grounded=true on 35 rows whose four
    # searches all failed, and the dashboard publishes that field as "shared
    # web search (Tavily)". Count hits, not attempts.
    hits = sum(len((e.get("result") or {}).get("results") or [])
               for e in evidence if e.get("tool") == "web_search")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    call_id = f"{run_id}:{arm}:{label}" if arm else f"{run_id}:{label}"
    rows = []
    first = next(q for g in groups for q in by_group[g["key"]])
    for g in groups:
        for q in by_group[g["key"]]:
            # A rolling horizon is only findable later if the run stamps the
            # date it resolves on (Nick, 2026-08-18). Two runs a month apart
            # both say "6mo" and mean different weeks; without this the series
            # cannot be scored, which is the only reason these questions are
            # worth asking.
            rows.append({
                "run_id": run_id,
                "elicited_at": stamp,
                "question_id": q["id"],
                "model": model_id,
                "label": label,
                "forecasts": (grid or {}).get(q["id"]),
                "rationale": answer.get("rationale"),
                "key_sources": answer.get("key_sources"),
                "grounded": hits > 0,
                "search_hits": hits,
                # Evidence and the raw payload belong to the CALL. Repeating them
                # on all 40 rows would multiply the file by 40 and make any
                # per-call count wrong.
                "evidence": evidence if q is first else [],
                "usage": usage if q is first else None,
                **debrief_fields(debrief, q is first),
                "resolves_on": {h: resolves_on(h, today, spec) for h in horizons},
                "run_date": today.isoformat(),
                "instrument_version": spec.get("instrument_version"),
                "counting_window": counting_windows(q, horizons, today, spec),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "prompt": prompt if q is first else None,
                "system_prompt": SYSTEM if q is first else None,
                "protocol": "unified-batch-v1" if state_constraints else PROTOCOL,
                "call_id": call_id,
                "attempts": attempts,
                "batch_size": len(qids),
                "cause": q.get("cause"),
                "group": g["key"],
                "asked_horizons": q.get("horizons"),
                "raw_forecasts": None if grid else answer.get("forecasts"),
                # Conditional-arm provenance. All None on the published series.
                "condition": cond_stamp,
                "experiment": experiment,
                "arm": arm,
                "panel": panel,
            })
    return rows


def usage_line(rows):
    """A call's cost for the log, from the usage on its first row."""
    u = (rows[0].get("usage") if rows else None) or {}
    if not u:
        return "usage unknown"
    s = (f"{u.get('turns', 0)} turns, {u.get('input_tokens', 0) / 1000:.0f}k in / "
         f"{u.get('output_tokens', 0) / 1000:.1f}k out")
    if u.get("reasoning_tokens"):
        s += f" ({u['reasoning_tokens'] / 1000:.1f}k reasoning)"
    cost, unpriced = u.get("cost_usd"), u.get("unpriced_turns")
    s += f", ${cost:.2f}" if cost is not None else ", unpriced"
    if unpriced and cost is not None:
        s += f" (+{unpriced} unpriced turn(s))"
    return s


def tally_spend(spent, rows):
    return spent + (((rows[0].get("usage") if rows else None) or {}).get("cost_usd") or 0.0)


def select_models(args):
    """The models to call, and the provenance stamp their rows carry.

    The default set is THE PANEL (redlines.registry.panel): the k highest-ECI
    models the registry can run, re-ranked from the newest ECI snapshot every
    run. Selecting it prints the snapshot's date and age, and the registry
    WARNs on a stale snapshot, a tie at the cut, or a model the index ranks
    above the cut that the registry cannot run. Rows stamp {set, k, snapshot}
    so a panel change is legible in the series.
    """
    models = MODEL_SETS[args.model_set]()
    prov = panel_provenance(args.model_set)
    if prov.get("members"):
        print(f"    panel {prov['set']}: top {prov['k']} by ECI, snapshot {prov['snapshot']} "
              f"({prov['age_days']} days old): "
              + ", ".join(f"{m['label']} {m['eci']:g}" for m in prov["members"]))
    else:
        print(f"    model set {prov['set']}: " + ", ".join(l for l, _ in models))
    if args.models:
        want = {m.strip().lower() for m in args.models.split(",")}
        have = [l for l, _ in models]
        models = [(l, m) for l, m in models if l.lower() in want]
        if not models:
            sys.exit(f"--models {args.models!r} matched none of {have}")
    if args.smoke:
        models = models[:1]
    stamp = {k: v for k, v in prov.items() if k in ("set", "k", "snapshot")}
    return models, stamp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="one model only")
    ap.add_argument("--models", help="comma-separated label filter")
    ap.add_argument("--model-set", default=DEFAULT_MODEL_SET, choices=sorted(MODEL_SETS),
                    help="which registry model set to run (default: eci_topk, THE PANEL "
                         "since 2026-08-28 -- the four highest-ECI models the registry "
                         "can run, re-ranked from the newest ECI snapshot under data/, "
                         "which WARNs when older than a month; frontier5 = the "
                         "hand-picked five the series ran on until then)")
    ap.add_argument("--retries", type=int, default=2,
                    help="re-ask when the grid comes back empty or <90%% complete")
    ap.add_argument("--out", default=None,
                    help="plain batch: the log to append to (default the shared "
                         "tracked log); --joint: the dated series file (default "
                         "results/runs/<stamp>.jsonl)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--allow-ungrounded", action="store_true",
                    help="run without Tavily (rows are marked grounded=false)")
    ap.add_argument("--state-constraints", action="store_true",
                    help="ABLATION ARM: put the coherence relations in the "
                         "prompt and tag the rows unified-batch-v1. Never for "
                         "the published series -- it contaminates the "
                         "measurement. Write these to results/experiments/.")
    ap.add_argument("--conditions", default=COMBINED,
                    help="the CONDITION SET: a JSON file in data/leap_policies.json's "
                         "shape. Default: data/combined_conditions.json, THE PUBLISHED "
                         "SET since 2026-08-28 -- the LEAP policies AND the six-month "
                         "capability conditions in one instrument. "
                         "data/leap_policies.json (policies only) is published too; "
                         "data/eci_conditions.json is the fixed capability set; a set "
                         "not in PUBLISHED_SETS never writes into results/runs/.")
    ap.add_argument("--condition", action="append", default=[],
                    help="CONDITIONAL ARM: prepend one LEAP Wave 12 policy "
                         "condition from data/leap_policies.json (an id, or "
                         "'all'; repeatable). One call per model per condition. "
                         "Never for the published series: needs --out.")
    ap.add_argument("--unconditional", type=int, default=None,
                    help="how many unconditional arms to run in the same "
                         "session (default 1 without --condition, 0 with it). "
                         "Repeats give the re-elicitation noise floor that the "
                         "conditional deltas are read against.")
    ap.add_argument("--joint", action="store_true",
                    help="THE PUBLISHED PROTOCOL (since 2026-08-27): one call per "
                         "model answering every cell unconditionally AND under "
                         "every condition (--condition, default all) in a single "
                         "submission. Unconditional slice -> --out (default "
                         "results/runs/<stamp>.jsonl); whole instrument -> "
                         "--conditional-out.")
    ap.add_argument("--repeats", type=int, default=1,
                    help="with --joint: run the whole instrument this many "
                         "times per model (default 1, the published protocol since "
                         "2026-09-02; the cron passes 1; more than one repeat on a "
                         "published set fails code/validate_launch_run.py's "
                         "one-call-per-cell check)")
    ap.add_argument("--conditional-out", default=None,
                    help="with --joint: where the whole instrument (every "
                         "condition) is appended (default results/conditional_runs.jsonl "
                         "for the published set, results/conditional_runs_<slug>.jsonl "
                         "for another)")
    ap.add_argument("--experiment",
                    help="tag every row with this experiment name (needs --out)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print each arm's prompt and exit; no model is called")
    args = ap.parse_args()

    # The combined instrument asks models to forecast and condition on frontier
    # ECI. Refuse to run it against a stale frontier history or a condition
    # set not generated from the newest Epoch snapshot
    # (code/check_eci_snapshot.py; code/cron_run.sh fetches and regenerates
    # before every run). A dry run calls no model and prints the prompt as it
    # stands, so it is not gated.
    if args.joint and not args.dry_run and \
            os.path.abspath(args.conditions) == os.path.abspath(COMBINED):
        subprocess.run([sys.executable, os.path.join(ROOT, "code", "check_eci_snapshot.py")],
                       check=True)

    if args.joint:
        return main_joint(args)
    if args.out is None:
        args.out = RUNLOG
    print("NOTE: the plain unconditional batch is DEPRECATED as the published "
          "protocol (2026-08-27); the cron runs --joint. This path is kept for "
          "ablations and experiments.", file=sys.stderr)
    policies = load_policies(args.conditions) if args.condition else None
    conds = expand_conditions(args.condition, policies) if args.condition else []
    n_uncond = args.unconditional if args.unconditional is not None else (0 if conds else 1)
    if n_uncond < 0 or (n_uncond == 0 and not conds):
        sys.exit("nothing to run: --unconditional 0 and no --condition")
    # Arms. The plain weekly run is one unnamed unconditional arm, so its rows
    # carry arm=None exactly as before; anything else is named.
    if conds or args.unconditional is not None:
        arms = [(f"unconditional#{i + 1}", None) for i in range(n_uncond)]
        arms += [(c["id"], c) for c in conds]
    else:
        arms = [(None, None)]
    if (conds or args.experiment) and os.path.abspath(args.out) == os.path.abspath(RUNLOG):
        sys.exit("refusing: a conditional or experiment run would write into the "
                 "published run log. Use --out results/conditional_runs.jsonl "
                 "(or results/experiments/<name>.jsonl)")

    if args.dry_run:
        groups, by_group, horizons, skipped, spec = load_batch(LADDER, CROSS, UNBATCHED)
        for arm, cond in arms:
            prompt, n, cells = build_prompt(groups, by_group, horizons, spec,
                                            date.today(), args.state_constraints,
                                            cond, policies)
            print(f"##### ARM {arm or 'unconditional'}: {n} questions, {cells} cells, "
                  f"{len(prompt)} chars #####")
            print(prompt)
        return

    load_keys()
    # Refuse rather than degrade. Without Tavily every model still answers --
    # from parametric memory, with no 2026 evidence -- and the run looks
    # identical from the outside: exit 0, "done" on every model, a full grid.
    # cron_run.sh would swallow it. These forecasts are published under a
    # provenance line that names web search, so an ungrounded run has to be an
    # explicit choice.
    if not os.environ.get("TAVILY_API_KEY") and not args.allow_ungrounded:
        sys.exit("refusing to run: TAVILY_API_KEY is unset, so every web_search "
                 "returns an error and the forecasts would be ungrounded while "
                 "the dashboard labels them grounded.\n"
                 "  fix:      gcloud auth application-default login\n"
                 "  override: --allow-ungrounded (marks the rows grounded=false)")
    models, panel = select_models(args)

    groups, by_group, horizons, skipped, spec = load_batch(LADDER, CROSS, UNBATCHED)
    n = sum(len(v) for v in by_group.values())
    # The true cell count, from the per-question horizon lists. The header used
    # to print n * len(horizons), which assumes every question is asked over
    # every horizon -- it is not. The three cross-cutting questions skip the
    # rolling windows, so the naive product said 210 where the prompt asked 201.
    _, _, cells = build_prompt(groups, by_group, horizons, spec, date.today(),
                               args.state_constraints)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    proto = "unified-batch-v1" if args.state_constraints else PROTOCOL
    if args.state_constraints:
        print("ABLATION ARM: the prompt STATES the coherence relations. These "
              "rows are tagged unified-batch-v1 and must not be pooled with the "
              "published v2 series.")
        if os.path.abspath(args.out) == os.path.abspath(RUNLOG):
            sys.exit("refusing: --state-constraints would write contaminated "
                     "rows into the published run log. Use --out "
                     "results/experiments/<name>.jsonl")
    print(f"run {run_id} protocol {proto}: {len(models) * len(arms)} calls "
          f"({len(models)} models x {len(arms)} arm(s)), {n} questions over "
          f"{len(horizons)} horizons = {cells} cells each")
    if len(arms) > 1 or arms[0][0]:
        print(f"    arms: {', '.join(a for a, _ in arms)}"
              + (f"  [experiment: {args.experiment}]" if args.experiment else ""))
    for g in groups:
        print(f"    {g['key']:14} {len(by_group[g['key']]):2d} questions")
    print(f"    horizons: {', '.join(horizon_label(h, spec, date.today()) for h in horizons)}")
    for qid, why in skipped:
        print(f"    SKIP {qid}: {why}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    lock = threading.Lock()
    done = failed = 0
    spent = 0.0
    with open(args.out, "a") as f, cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        # Arm-major submission order: with five workers and five models, the
        # pool holds one call per vendor at a time, the same load as the weekly run.
        futs = {ex.submit(run_one, l, m, groups, by_group, horizons, run_id,
                          args.retries, spec, args.state_constraints,
                          cond, policies, args.experiment, arm, panel): (arm, l)
                for arm, cond in arms for l, m in models}
        for fut in cf.as_completed(futs):
            arm, label = futs[fut]
            tag = f"{label:16}" if not arm else f"{arm + ':' + label:32}"
            try:
                rows = fut.result()
            except Exception as e:
                failed += 1
                print(f"  FAIL  {tag}: {type(e).__name__}: {str(e)[:200]}")
                traceback.print_exc()
                continue
            with lock:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
                f.flush()
            done += 1
            got = sum(1 for r in rows if r["forecasts"])
            ev = sum(len(r["evidence"]) for r in rows)
            spent = tally_spend(spent, rows)
            print(f"  done  {tag} {got}/{len(rows)} questions answered, {usage_line(rows)}, "
                  f"{ev} evidence, {coverage_line(rows)}, {rows[0]['attempts']} attempt(s), "
                  f"{debrief_note(rows)}")
    print(f"{done} ok, {failed} failed, ${spent:.2f} priced spend -> {args.out}")


def main_joint(args):
    """--joint: the whole instrument per call, --repeats calls per model.

    Unconditional slice -> args.out; every row -> args.conditional_out.
    """
    today = datetime.now(timezone.utc).date()
    policies = load_policies(args.conditions)
    conds = expand_conditions(args.condition or ["all"], policies)
    published_set = os.path.abspath(args.conditions) in {os.path.abspath(p) for p in PUBLISHED_SETS}
    slug, proto = set_slug(policies), set_protocol(policies)
    if args.out and os.path.abspath(args.out) == os.path.abspath(RUNLOG):
        sys.exit("refusing: never append to the shared tracked log; the series "
                 "is one dated file per run under results/runs/ (see cron_run.sh)")
    if args.repeats < 1:
        sys.exit("--repeats must be >= 1")
    # A smoke or an experiment is not the published series. The plain path
    # refuses to write those into the run log; this path routes them by
    # default, so a hand smoke never appends to results/runs/ or the
    # instrument logs the dashboard reads (and never trips the launch
    # validator's one-call-per-cell check on the next real run's date).
    if args.smoke or args.experiment:
        tag = args.experiment or "smoke"
        exp_dir = os.path.join(ROOT, "results", "experiments")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        args.out = args.out or os.path.join(exp_dir, f"{tag}-{stamp}.jsonl")
        args.conditional_out = args.conditional_out or os.path.join(
            exp_dir, f"{tag}-{stamp}-instrument.jsonl")
        for path in (args.out, args.conditional_out):
            ap_ = os.path.abspath(path)
            if ap_.startswith(os.path.abspath(RUNS_DIR) + os.sep) or \
                    os.path.basename(ap_).startswith("conditional_runs"):
                sys.exit(f"refusing: a smoke/experiment run must not write to {path}; "
                         "that is a published log (default: results/experiments/)")
    arms = [f"joint#{i + 1}" for i in range(args.repeats)]
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    if published_set:
        out = args.out or os.path.join(RUNS_DIR, f"{run_id}.jsonl")
        # The LEAP set's instrument log is the original one; every other
        # published set keeps a log named by its slug (the tabs know both).
        cond_out = args.conditional_out or (
            CONDITIONAL_LOG if os.path.abspath(args.conditions) == os.path.abspath(POLICIES)
            else os.path.join(ROOT, "results", f"conditional_runs_{slug}.jsonl"))
    else:
        # Another condition set is another instrument: its unconditional slice
        # is not the published series and its rows are not the policy panel's.
        # Both land beside the policy files, named by the set, unless told
        # otherwise -- and never in the series' places.
        out = args.out or os.path.join(ROOT, "results", f"{slug}_runs", f"{run_id}.jsonl")
        cond_out = args.conditional_out or os.path.join(ROOT, "results",
                                                        f"conditional_runs_{slug}.jsonl")
        for path in (out, cond_out):
            ap_ = os.path.abspath(path)
            if ap_ == os.path.abspath(CONDITIONAL_LOG) or ap_.startswith(os.path.abspath(RUNS_DIR) + os.sep):
                sys.exit(f"refusing: condition set {slug!r} ({proto}) must not write to "
                         f"{path}; that is the published series/panel log")
    if os.path.abspath(cond_out) == os.path.abspath(out):
        sys.exit("--conditional-out must differ from --out")
    groups, by_group, horizons, skipped, spec = load_batch(LADDER, CROSS, UNBATCHED)
    horizons = set_horizons(policies, horizons)
    prompt, n, cells = build_prompt_joint(groups, by_group, horizons, spec, conds,
                                          policies, today)
    for el in set_elicits(resolve_set(policies, today)):
        print(f"    elicits {el['key']} {el['fields']} for {el.get('target_date')}"
              + (f" (run date + {el['target_months']} months)" if el.get("target_months") else ""))
    if args.dry_run:
        print(f"##### JOINT [{slug}: {proto}]: {n} questions, {cells} cells x {len(conds) + 1} "
              f"conditions = {cells * (len(conds) + 1)} probabilities, {len(prompt)} chars #####")
        print(prompt)
        return
    load_keys()
    if not os.environ.get("TAVILY_API_KEY") and not args.allow_ungrounded:
        sys.exit("refusing to run: TAVILY_API_KEY is unset (see the unconditional path)")
    models, panel = select_models(args)
    print(f"run {run_id} protocol {proto} [set {slug}]: {len(models) * len(arms)} calls "
          f"({len(models)} models x {len(arms)} repeat(s)), {n} questions x "
          f"{len(horizons)} horizons = {cells} cells x {len(conds) + 1} conditions "
          f"= {cells * (len(conds) + 1)} probabilities each")
    print(f"    harness: research floor {MIN_RESEARCH} calls, coverage "
          f"{', '.join(g['key'] for g in groups)}, guard {MAX_ROUNDS} rounds; reasoning "
          + ", ".join(f"{l}={reasoning_for(m) or 'default'}" for l, m in models))
    print(f"    conditions: {UNCONDITIONAL_KEY}, {', '.join(c['id'] for c in conds)}"
          + (f"  [experiment: {args.experiment}]" if args.experiment else ""))
    for g in set_groups(policies):
        print(f"      {g['key']:11} {sum(c.get('group') == g['key'] for c in conds)} conditions -- {g['heading']}")
    print(f"    unconditional slice -> {out}\n    whole instrument     -> {cond_out}")
    for qid, why in skipped:
        print(f"    SKIP {qid}: {why}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(cond_out)), exist_ok=True)
    lock = threading.Lock()
    done = failed = 0
    spent = 0.0
    with open(out, "a") as f, open(cond_out, "a") as fc, \
            cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one_joint, l, m, groups, by_group, horizons, run_id,
                          args.retries, spec, conds, policies, args.experiment, arm, panel,
                          today): (arm, l)
                for arm in arms for l, m in models}
        for fut in cf.as_completed(futs):
            arm, label = futs[fut]
            tag = f"{arm + ':' + label:32}"
            try:
                rows = fut.result()
            except Exception as e:
                failed += 1
                print(f"  FAIL  {tag}: {type(e).__name__}: {str(e)[:120]}")
                continue
            with lock:
                for r in rows:
                    fc.write(json.dumps(r) + "\n")
                    if r["condition"] is None:
                        f.write(json.dumps(r) + "\n")
                f.flush(); fc.flush()
            done += 1
            got = sum(1 for r in rows if r["forecasts"])
            ev = sum(len(r["evidence"]) for r in rows)
            spent = tally_spend(spent, rows)
            print(f"  done  {tag} {got}/{len(rows)} question x condition rows answered, {usage_line(rows)}, "
                  f"{ev} evidence, {coverage_line(rows)}, {rows[0]['attempts']} attempt(s), "
                  f"{debrief_note(rows)}")
    print(f"{done} ok, {failed} failed, ${spent:.2f} priced spend -> {out} (unconditional) + {cond_out} (instrument)")
    if failed:
        # An incomplete panel cannot be published (code/validate_launch_run.py
        # needs every model on the date), so the run is a failure, not a
        # partial success; cron_run.sh stops here rather than spending on the
        # axes instruments for a date that will not publish.
        sys.exit(1)


if __name__ == "__main__":
    main()
