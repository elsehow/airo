"""Conditional forecasts: what a LEAP policy does to each question, per model.

Reads results/conditional_runs.jsonl -- the output of
`code/run_unified.py --condition ... --unconditional N` -- and turns it into
the one number the conditional panel plots: how far each model's forecast
moves under a policy, measured against ITS OWN same-session unconditional
forecast.

WHY THE BASELINE IS THE SAME-SESSION ARM, NOT THE WEEKLY SERIES
A conditional run made ten days after the weekly point mixes the policy's
effect with ten days of news. The experiment therefore carries its own
unconditional arms, elicited in the same session as the conditionals, and
those are the zero line. Several of them (--unconditional 3) give the
re-elicitation noise floor: a policy whose delta sits inside the spread of
three identical unconditional calls has not been shown to do anything.

WHY PER-MODEL, THEN ENSEMBLE
Baselines differ tenfold across models (Grok 12% vs Fable 1% on general
catastrophe at 2030). A delta of the ensemble medians would be dominated by
whichever model moved most in absolute terms. Each model's delta is taken
against its own baseline first; the ensemble figure is the median of those.

THREE MEASURES, ONE STORY
  delta_pp     p_cond - p_uncond, in percentage points. What a reader asks.
  ratio        p_cond / p_uncond. Readable on a ~1% baseline where pp is not,
               and the only one that also applies to an expected loss. The
               page plots this one, on a log axis so 1/2x and 2x are the same
               distance from the baseline.
  dlogit       logit(p_cond) - logit(p_uncond). Symmetric in raise/lower;
               kept in the summary for the record.

EXPECTED LOSS: THE LADDER COMPRESSED TO ONE NUMBER
Each cause's eight rungs are P(loss >= x_k) at log-spaced thresholds x_k
(100 deaths or $220M ... 1B deaths or $2.2Q). Those are points on a survival
function, and E[loss] = integral of S(x) dx. With S known only at the rungs,
the sum  sum_k S(x_k) (x_k - x_{k-1})  with x_0 = 0 is a FLOOR on E[loss]:
it values every band at its lower threshold and counts nothing above 1B
beyond 1B itself. The unit is death-equivalents at the ladder's own
exchange rate, 1 death = $2.2M since 2026-08-31 (the "or" in "100 deaths or
$220M"; $10M, "100 deaths or $1B", before). Because
the thresholds rise tenfold per rung, the top rungs dominate the sum; the
summary carries each cell's top-two-rung share so a reader can see how much
of "expected lives" is the 100M and 1B rungs. A non-monotone ladder (a
higher rung more likely than a lower one -- the batch prompt states no
relation between questions, so it can happen) is repaired by the running
minimum from the bottom, which keeps the floor a floor; the count of
repaired rungs is carried too.

Horizons default to 2030 and 2050. LEAP's conditioning clause keeps the
policy in force through 2050 and elicits its own outcome at 2050 only; a
2100 cell under that clause is a forecast under a policy the prompt does not
extend past 2050, so it is computed but flagged (`horizon_note`).
"""
import json
import math
import random
import statistics as st
from collections import defaultdict

from .config import REPO_ROOT
from .superseded import is_superseded

CONDITIONAL_LOG = REPO_ROOT / "results" / "conditional_runs.jsonl"
POLICIES = REPO_ROOT / "data" / "leap_policies.json"
DEFAULT_HORIZONS = ("2030", "2050")
EPS = 1e-5
LOSS_PREFIX = "loss:"
# The ladder's rate: the value of a statistical life its criteria state --
# "100 deaths or $220M" since the ladder's 2026-08-31 revision ($2.2M; it was
# $10M, "100 deaths or $1B"). data/autoarc_ladder.json notes.vsl_usd carries
# the same number and tests/test_autoarc_generator.py pins the two together.
USD_PER_DEATH = 2.2e6


def _logit(p):
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


# A set's protocol tag moves when the elicitation under it changes (the
# questions may be byte-identical; what was asked, and how, was not). Newest
# first: a view that reads a set shows the newest tag present in its log and
# falls back down the line, so the tab keeps its rows on the day of a bump and
# switches the day the first run under the new tag lands.
PROTOCOL_LINEAGE = {
    # 2026-10-01, v8: the extinction pair's criteria stop naming their source.
    # The AI question had said its criteria were XPT's, "kept verbatim so the
    # forecasts compare with that panel's", and the total-extinction question
    # that it was XPT's own; both notes opened "Added ... for AIRO". The rules
    # are unchanged, the attribution is gone from the rendered text
    # (docs/extinction-questions-2026-09-15.md). Not additive: the same two
    # questions, asked without being told whose number to match.
    "unified-joint-combined-v8": ("unified-joint-combined-v7", "unified-joint-combined-v6",
                                  "unified-joint-combined-v5", "unified-joint-combined-v4",
                                  "unified-joint-combined-v3", "unified-joint-combined-v2",
                                  "unified-joint-combined-v1"),
    # 2026-09-16, v7: the extinction RUNG joins every incident ladder
    # (data/auto-arc/addendum-extinction-rung-2026-09-16.json): 37 -> 41
    # questions, 222 -> 246 cells. Additive, like v6, and tagged for the
    # same reason: a grid answered beside four more questions is a different
    # elicitation. The same day, the debrief turn went per question
    # (a harness change, which does not bump the tag).
    "unified-joint-combined-v7": ("unified-joint-combined-v6", "unified-joint-combined-v5",
                                  "unified-joint-combined-v4", "unified-joint-combined-v3",
                                  "unified-joint-combined-v2", "unified-joint-combined-v1"),
    # 2026-09-15, v6: the extinction pair joins the cross-cutting group
    # (data/auto-arc/addendum-extinction-2026-09-15.json): 35 -> 37 questions,
    # 210 -> 222 cells. Additive -- every earlier block renders unchanged --
    # but a grid answered beside two more questions is a different elicitation
    # (docs/coherence-experiment.md), and the tag is how a reader tells.
    "unified-joint-combined-v6": ("unified-joint-combined-v5", "unified-joint-combined-v4",
                                  "unified-joint-combined-v3", "unified-joint-combined-v2",
                                  "unified-joint-combined-v1"),
    # 2026-09-10, v5: the prospective incident-counting definitions
    # (redlines.instrument.CURRENT_INSTRUMENT); the questions were re-versioned
    # under the same call shape.
    "unified-joint-combined-v5": ("unified-joint-combined-v4", "unified-joint-combined-v3",
                                  "unified-joint-combined-v2", "unified-joint-combined-v1"),
    # 2026-09-02, the agentic harness (code/make_combined_conditions.py);
    # v3 the same evening: the grid delivered in pieces (submit_cells),
    # Anthropic's own thinking budget, Tavily advanced search, and the
    # cited-but-unread flag. The axes sets (code/make_axis_conditions.py)
    # were built the same day and bumped with it.
    # 2026-09-03, v4: the model's own p10 and p90 join the capability
    # conditions (five rows, not three); the self-elicited sets bumped with it.
    "unified-joint-combined-v4": ("unified-joint-combined-v3", "unified-joint-combined-v2",
                                  "unified-joint-combined-v1"),
    "unified-joint-combined-v3": ("unified-joint-combined-v2", "unified-joint-combined-v1"),
    "unified-joint-eciself6mo-v2": ("unified-joint-eciself6mo-v1",),
    "unified-joint-eciself-v2": ("unified-joint-eciself-v1",),
    "unified-joint-combined-v2": ("unified-joint-combined-v1",),
    # 2026-09-10: v3 ran with the vendored Epoch CSV's ECI text; v4 is the
    # live METR snapshot's (code/make_axis_conditions.py).
    "unified-joint-axes-v4": ("unified-joint-axes-v3", "unified-joint-axes-v2", "unified-joint-axes-v1"),
    "unified-joint-paperaxes-v4": ("unified-joint-paperaxes-v3", "unified-joint-paperaxes-v2",
                                   "unified-joint-paperaxes-v1"),
    "unified-joint-axes-v3": ("unified-joint-axes-v2", "unified-joint-axes-v1"),
    "unified-joint-paperaxes-v3": ("unified-joint-paperaxes-v2", "unified-joint-paperaxes-v1"),
    "unified-joint-axes-v2": ("unified-joint-axes-v1",),
    "unified-joint-paperaxes-v2": ("unified-joint-paperaxes-v1",),
}


# THE published instrument's tag today. data/combined_conditions.json carries
# the same string (tests pin the two together); the views, the run log's
# grounding line and the coherence test all read it from here, so a bump is
# one edit plus the lineage entry above.
COMBINED_PROTOCOL = "unified-joint-combined-v8"
# The first combined tag elicited by the agentic harness (iterative search +
# page reads, 2026-09-02); v1 (2026-08-28) still ran the legacy grounding.
AGENTIC_SINCE = "unified-joint-combined-v2"


def protocol_line(tag):
    """(tag, *its predecessors), newest first."""
    return (tag,) + tuple(PROTOCOL_LINEAGE.get(tag, ()))


def newest_protocol(rows, line):
    """The rows of the newest tag in `line` that any row carries, and that tag.
    ([], None) when none of them does."""
    present = {r.get("protocol") for r in rows} & set(line)
    if not present:
        return [], None
    proto = min(present, key=line.index)
    return [r for r in rows if r.get("protocol") == proto], proto


def load_conditional(path=CONDITIONAL_LOG, experiment=None, protocol=None):
    """Rows of one experiment and/or one protocol. Two protocols write here --
    separate calls (unified-batch-v2, one condition per call) and the joint
    instrument (unified-joint-v1, every condition in one call) -- and their
    unconditional arms are different elicitations, so a summary is always of
    one protocol; pass protocol=None only to list what the log holds."""
    rows = []
    for one in _paths(path):
        with open(one) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if experiment and r.get("experiment") != experiment:
                    continue
                if protocol and r.get("protocol") != protocol:
                    continue
                if not isinstance(r.get("forecasts"), list):
                    continue
                if is_superseded(r):       # redlines.superseded: replaced the same day
                    continue
                rows.append(r)
    return rows


def group_view(policies, group):
    """A grouped set (data/combined_conditions.json) seen as ONE of its groups.

    A plain set dict carrying that group's conditions, instruction,
    definitions, horizon and source, so summarize() and the two tabs read it
    exactly as they read the single-purpose set it was composed from -- the
    policy group IS the LEAP set's text, byte for byte. `conditioning` keeps
    the set's unconditional line and gains the group's `assumption`, the one
    sentence of ours the model saw beside the group's own text. A set with no
    groups is returned as is.
    """
    groups = policies.get("groups") or []
    if not groups:
        return policies
    g = next(x for x in groups if x["key"] == group)
    conditioning = dict(policies["conditioning"])
    conditioning.update({"instruction": g["instruction"], "horizon": g["horizon"],
                         "assumption": g["assumption"]})
    if g.get("definitions"):
        conditioning["definitions"] = g["definitions"]
    return {**policies, "kind": g["kind"], "group": group, "heading": g["heading"],
            "source": {**g["source"], "instrument": policies["source"]["wave"]},
            "conditioning": conditioning,
            "conditions": [c for c in policies["conditions"] if c.get("group") == group]}


def group_rows(rows, group):
    """The rows one group's view reads: every unconditional row (the same
    call's baseline) and the rows of that group's conditions."""
    return [r for r in rows if r.get("condition") is None
            or (r["condition"] or {}).get("group") == group]


def _paths(path):
    """One path, or several (a list, or a ':'-joined string), existing only."""
    if isinstance(path, (list, tuple)):
        ps = list(path)
    elif isinstance(path, str) and ":" in path:
        ps = path.split(":")
    else:
        ps = [path]
    from pathlib import Path
    return [Path(p) for p in ps if Path(p).exists()]


def protocols_in(path=CONDITIONAL_LOG):
    """-> {protocol: {"experiments": [...], "runs": [...], "rows": n}}"""
    out = {}
    for one in _paths(path):
        with open(one) as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                e = out.setdefault(r.get("protocol"), {"experiments": set(), "runs": set(), "rows": 0})
                e["experiments"].add(r.get("experiment")); e["runs"].add(r.get("run_id")); e["rows"] += 1
    return {k: {"experiments": sorted(x for x in v["experiments"] if x),
                "runs": sorted(v["runs"]), "rows": v["rows"]} for k, v in out.items()}


def _call(r):
    return r.get("call_id") or r.get("arm") or r.get("run_id")


def _slot(d, call):
    """A key for this call in d that does not overwrite an earlier row from a
    log without call ids (the same run_id twice is two draws, not one)."""
    k, i = call, 0
    while k in d:
        i += 1
        k = f"{call}#{i}"
    return k


def _cells(rows):
    """-> {(qid, horizon, label): {"uncond": {call: p}, "cond": {cid: {call: p}},
                                   "grounded": {cid: bool}}}

    Values are kept PER CALL on both sides. Under the single instrument the
    same call answers the unconditional and every condition, so a condition's
    ratio is paired within the call (the between-call wander cancels); the
    separate-call pilot has no shared calls and falls back to an unpaired
    comparison. `grounded` is carried per condition because a call that ran
    with no search evidence answers from memory; the page marks them.
    """
    cells = defaultdict(lambda: {"uncond": {}, "cond": defaultdict(dict), "grounded": {}})
    for r in rows:
        call = _call(r)
        for f in r["forecasts"]:
            key = (r["question_id"], f["horizon"], r["label"])
            if r.get("condition"):
                cid = r["condition"]["id"]
                d = cells[key]["cond"][cid]
                d[_slot(d, call)] = f["probability"]
                cells[key]["grounded"][cid] = (cells[key]["grounded"].get(cid, True)
                                               and bool(r.get("grounded")))
            else:
                d = cells[key]["uncond"]
                d[_slot(d, call)] = f["probability"]
    return cells


# ---- confidence intervals ---------------------------------------------------
# Two-sided 97.5% Student-t quantiles by degrees of freedom; 1.96 beyond.
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042}
BOOT_B = 600
BOOT_SEED = 0


def _t975(df):
    if df <= 0:
        return None
    for k in sorted(_T975):
        if df <= k:
            return _T975[k]
    return 1.96


def _lg(p):
    return math.log(max(p, EPS))


def effect_paired(pairs):
    """[(uncond, cond)] from the same calls -> {est, ci, n, paired: True}.

    est is the mean log-ratio (exp of it is the geometric-mean ratio); ci the
    95% t-interval on it, None with one pair. A zero spread gives a
    zero-width interval: three identical answers are three identical answers.
    """
    rs = [_lg(c) - _lg(u) for u, c in pairs if u is not None and c is not None]
    if not rs:
        return None
    m = st.fmean(rs)
    if len(rs) < 2:
        return {"est": m, "ci": None, "n": len(rs), "paired": True, "logs": rs}
    half = _t975(len(rs) - 1) * st.stdev(rs) / math.sqrt(len(rs))
    return {"est": m, "ci": [m - half, m + half], "n": len(rs), "paired": True, "logs": rs}


def effect_unpaired(uncond, cond):
    """Separate calls: Welch interval on mean log(cond) - mean log(uncond).

    A side with one value contributes no variance (its spread is unknown, not
    zero); with fewer than two values on both sides there is no interval.
    """
    us, cs = [_lg(x) for x in uncond], [_lg(x) for x in cond]
    if not us or not cs:
        return None
    m = st.fmean(cs) - st.fmean(us)
    vu = st.variance(us) / len(us) if len(us) > 1 else 0.0
    vc = st.variance(cs) / len(cs) if len(cs) > 1 else 0.0
    if len(us) < 2 and len(cs) < 2:
        return {"est": m, "ci": None, "n": len(cs), "paired": False, "logs": [m]}
    se = math.sqrt(vu + vc)
    if se == 0:
        return {"est": m, "ci": [m, m], "n": len(cs), "paired": False, "logs": [m]}
    num = (vu + vc) ** 2
    den = (vu ** 2 / (len(us) - 1) if len(us) > 1 else 0) + (vc ** 2 / (len(cs) - 1) if len(cs) > 1 else 0)
    df = max(1, int(num / den)) if den > 0 else 1
    half = _t975(df) * se
    return {"est": m, "ci": [m - half, m + half], "n": len(cs), "paired": False, "logs": [m]}


def ensemble_ci(per_model_logs, B=BOOT_B, seed=BOOT_SEED):
    """Bootstrap percentile 95% interval for the MEDIAN across models of each
    model's mean log-ratio, resampling models with replacement and, within
    each, its repeats. Seeded, so a build is a pure function of its inputs.
    -> [lo, hi] or None (needs two models, or one model with two repeats)."""
    logs = [l for l in per_model_logs if l]
    if not logs or (len(logs) < 2 and len(logs[0]) < 2):
        return None
    rng = random.Random(seed)
    meds = []
    for _ in range(B):
        picks = [logs[rng.randrange(len(logs))] for _ in logs]
        means = [st.fmean(rng.choice(l) for _ in l) for l in picks]
        meds.append(st.median(means))
    meds.sort()
    lo = meds[int(0.025 * (B - 1))]
    hi = meds[int(0.975 * (B - 1))]
    return [lo, hi]


def _lgt(p):
    """logit, clamped away from 0 and 1."""
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def _expit(x):
    return 1 / (1 + math.exp(-x))


def level_or(ps):
    """95% t-interval on a PROBABILITY level from its repeats, on the logit
    scale, as an odds-ratio pair [exp(-h), exp(h)] about the centre. None
    with one draw.

    Logit, not log (switched 2026-08-27): a probability is bounded on both
    sides, and a log-scale interval on a 60% level ran past 100%. On the
    logit scale the interval is bounded, skewed the right way near either
    edge, and the same interval whichever way the question is worded
    (logit(1-p) = -logit(p)). Below ~10% the two scales agree to two
    decimals, so the policy tab's numbers did not move. Losses stay on log
    (bounded below only): see _level_ci.
    """
    if len(ps) < 2:
        return None
    lg = [_lgt(p) for p in ps]
    h = _t975(len(lg) - 1) * st.stdev(lg) / math.sqrt(len(lg))
    return [math.exp(-h), math.exp(h)]


def apply_or(p, orr):
    """Place an odds-ratio interval on a level: [lo, hi] as probabilities."""
    return [_expit(_lgt(p) + math.log(orr[0])), _expit(_lgt(p) + math.log(orr[1]))]


def or_to_ratios(p, orr):
    """The same interval as RATIOS to p, which is how the views apply a band
    to a centre (x = centre x ratio). None if there is no interval."""
    if not orr or not p:
        return None
    lo, hi = apply_or(p, orr)
    return [lo / p, hi / p]


def _level_ci(logs):
    """95% t-interval on a level from its repeats, as RATIOS to the geometric
    mean (so [0.8, 1.25] reads "±20-25% around the centre"). None with one."""
    if len(logs) < 2:
        return None
    m = st.fmean(logs)
    half = _t975(len(logs) - 1) * st.stdev(logs) / math.sqrt(len(logs))
    return [math.exp(-half), math.exp(half)]


def _excludes_zero(ci):
    return None if ci is None else (ci[0] > 0 or ci[1] < 0)


def _spread(values):
    """Noise floor for one model's repeated unconditional calls."""
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    base = st.fmean(values)
    return {"n": len(values), "pp": 100 * (hi - lo),
            "dlogit": max(_logit(v) for v in values) - min(_logit(v) for v in values),
            "ratio": (hi / lo) if lo > 0 else None,
            "lo": (lo / base) if base > 0 else None,      # range as ratios to the
            "hi": (hi / base) if base > 0 else None,      # baseline, for the band
            "sd_pp": 100 * st.pstdev(values)}


def outside_noise(cond_values, uncond_values):
    """Does a condition's answer clear the model's own re-elicitation noise?

    The test is range separation: every conditional value lies beyond every
    unconditional one, on one side. With one conditional call against three
    unconditional ones, a fresh unconditional call would itself land outside
    their range half the time (2/(n+1)), so a single-pass "outside" is a
    floor on evidence, not significance; with three against three the chance
    that two draws from the same distribution separate is 2/C(6,3) = 10%.
    -> True / False, or None when there is no unconditional RANGE to be
    outside of (fewer than two repeats) or nothing under the condition.
    """
    if not cond_values or len(uncond_values) < 2:
        return None
    return min(cond_values) > max(uncond_values) or max(cond_values) < min(uncond_values)


# ── expected loss from a ladder ─────────────────────────────────────────────

def ladder_rungs(spec=None):
    """[(rung short, deaths)] ascending, from the ladder spec: the LOSS rungs,
    i.e. those with a dollar leg. The extinction rung (2026-09-16, an
    addendum) is a population floor with no damages leg -- no sum of direct
    losses is an extinction -- so it is not a point on the loss ladder the
    fold integrates, and every run before it stays foldable."""
    if spec is None:
        from .questions import load_ladder
        spec = load_ladder()
    return [(r["short"], float(r["deaths"])) for r in spec["rungs"]
            if r.get("kind", "deaths_or_damages") == "deaths_or_damages"]


def expected_loss(survival, rungs):
    """Floor on E[loss] in death-equivalents from P(loss >= x_k) at the rungs.

    survival: {rung short: p}. Every rung must be present, else None.
    Returns {"value", "top_share" (share of the sum from the top two rungs),
    "repaired" (rungs lowered to restore monotonicity), "terms"}.
    """
    if any(r not in survival for r, _ in rungs):
        return None
    s, repaired = [], 0
    for r, _ in rungs:
        p = float(survival[r])
        if s and p > s[-1]:            # a higher rung more likely than a lower one
            p = s[-1]
            repaired += 1
        s.append(p)
    terms, prev = [], 0.0
    for (_, x), p in zip(rungs, s):
        terms.append(p * (x - prev))
        prev = x
    total = sum(terms)
    top = sum(terms[-2:]) / total if total > 0 else None
    return {"value": total, "top_share": top, "repaired": repaired, "terms": terms}


def _ladder_cells(rows, rungs):
    """-> {(cause, horizon, label): {"uncond": {call: {rung: p}},
                                     "cond": {cid: {call: {rung: p}}},
                                     "grounded": {cid: bool}}}

    Arms are kept apart (keyed by call) on both sides so each call yields its
    own expected loss and the calls' spread is the noise, exactly as for a
    probability cell.
    """
    want = {r for r, _ in rungs}
    cells = defaultdict(lambda: {"uncond": defaultdict(dict),
                                 "cond": defaultdict(lambda: defaultdict(dict)),
                                 "grounded": {}})
    for r in rows:
        qid = r["question_id"]
        parts = qid.split(":")
        if len(parts) != 3 or parts[0] != "ladder" or parts[2] not in want:
            continue
        cause, rung = parts[1], parts[2]
        call = r.get("call_id") or r.get("arm") or r.get("run_id")
        for f in r["forecasts"]:
            key = (cause, f["horizon"], r["label"])
            if r.get("condition"):
                cid = r["condition"]["id"]
                cells[key]["cond"][cid][call][rung] = f["probability"]
                cells[key]["grounded"][cid] = (cells[key]["grounded"].get(cid, True)
                                               and bool(r.get("grounded")))
            else:
                cells[key]["uncond"][call][rung] = f["probability"]
    return cells


def _loss_models(cells, rungs):
    """Per (loss:cause, horizon): {label: model entry} in the summarize() shape."""
    out = defaultdict(dict)
    for (cause, h, label), c in sorted(cells.items()):
        arms = [expected_loss(v, rungs) for v in c["uncond"].values()]
        arms = [a for a in arms if a]
        if not arms:
            continue
        values = [a["value"] for a in arms]
        base = st.fmean(values)
        noise = _spread(values)
        if noise:                       # pp and logit mean nothing for a loss
            noise = {"n": noise["n"], "ratio": noise["ratio"], "lo": noise["lo"],
                     "hi": noise["hi"], "pp": None, "dlogit": None}
        m = {"baseline": base, "baseline_n": len(values), "baseline_values": values,
             "noise": noise,
             "baseline_logs": [_lg(v) for v in values],
             "baseline_ci": _level_ci([_lg(v) for v in values]),
             "top_share": st.fmean(a["top_share"] for a in arms if a["top_share"] is not None)
             if any(a["top_share"] is not None for a in arms) else None,
             "repaired": sum(a["repaired"] for a in arms),
             "conditions": {}}
        ubc = {k: a["value"] for k, a in ((k, expected_loss(v, rungs)) for k, v in c["uncond"].items()) if a}
        for cid, by_call in c["cond"].items():
            es = {k: expected_loss(v, rungs) for k, v in by_call.items()}
            es = {k: e for k, e in es.items() if e}
            if not es:
                continue
            cbc = {k: e["value"] for k, e in es.items()}
            p = st.fmean(cbc.values())
            m["conditions"][cid] = _effect_entry(ubc, cbc, base, p, c["grounded"].get(cid, True))
            m["conditions"][cid].update({
                "top_share": st.fmean(e["top_share"] for e in es.values() if e["top_share"] is not None)
                if any(e["top_share"] is not None for e in es.values()) else None,
                "repaired": sum(e["repaired"] for e in es.values()),
            })
        out[(LOSS_PREFIX + cause, h)][label] = m
    return out


def _effect_entry(uncond_by_call, cond_by_call, base, p, grounded):
    """One model under one condition: level, ratio, CI, verdict."""
    shared = [k for k in cond_by_call if k in uncond_by_call]
    if shared:
        eff = effect_paired([(uncond_by_call[k], cond_by_call[k]) for k in shared])
    else:
        eff = effect_unpaired(list(uncond_by_call.values()), list(cond_by_call.values()))
    ci = eff["ci"] if eff else None
    return {
        "p": p, "n": len(cond_by_call), "values": list(cond_by_call.values()),
        "grounded": grounded,
        "delta": p - base,
        # The ratio is the paired (geometric-mean) estimate when the calls
        # pair, else the ratio of means.
        "ratio": math.exp(eff["est"]) if eff else ((p / base) if base > 0 else None),
        "ci": [math.exp(ci[0]), math.exp(ci[1])] if ci else None,
        "paired": bool(eff and eff["paired"]), "n_pairs": len(shared),
        "logs": eff["logs"] if eff else [],
        "outside": _excludes_zero(ci),
        "delta_pp": None, "dlogit": None,
    }


def summarize(rows, policies=None, horizons=DEFAULT_HORIZONS, questions=None,
              rungs=None):
    """-> {"questions": {qid: {horizon: {...}}}, "conditions": [...], "meta": {...}}

    Per (question, horizon): each model's baseline (mean of its unconditional
    arms), its per-condition forecast and deltas, and the ensemble medians of
    the per-model deltas. Models with no baseline in the session are skipped
    for that cell, not silently given someone else's.

    Ladder questions also fold into one `loss:<cause>` entry per cause and
    horizon -- the expected loss in death-equivalents (see module docstring),
    with the same per-model-then-ensemble arithmetic. Pass rungs=[] to skip.
    """
    policies = policies or json.load(open(POLICIES))
    cond_order = [c["id"] for c in policies["conditions"]]
    labels = {c["id"]: c["label"] for c in policies["conditions"]}
    leap_ids = {c["id"]: c.get("leap_id") for c in policies["conditions"]}
    # The 2100 note is about LEAP's clause; a capability set has no such clause.
    clause_note = policies.get("kind", "policy") == "policy"
    cells = _cells(rows)
    all_h = sorted({h for _, h, _ in cells})
    want_h = [h for h in all_h if h in horizons] if horizons else all_h

    def keep(qid, h):
        if questions and qid not in questions:
            return False
        return h in want_h or h == "2100"

    out = defaultdict(dict)
    for (qid, h, label) in sorted(cells):
        if not keep(qid, h):
            continue
        c = cells[(qid, h, label)]
        if not c["uncond"]:
            continue
        uvals = list(c["uncond"].values())
        base = st.fmean(uvals)
        entry = out[qid].setdefault(h, {"models": {}, "ensemble": {}, "n_models": 0,
                                        "value_kind": "probability"})
        m = {"baseline": base, "baseline_n": len(uvals),
             "baseline_values": uvals, "noise": _spread(uvals),
             "baseline_logs": [_lg(u) for u in uvals],
             # Level interval on the logit scale (level_or), carried both as
             # odds ratios (to combine across models) and as ratios to this
             # model's centre (what the page multiplies by).
             "baseline_or": level_or(uvals),
             "baseline_ci": or_to_ratios(base, level_or(uvals)),
             "conditions": {}}
        for cid, by_call in c["cond"].items():
            ps = list(by_call.values())
            p = st.fmean(ps)
            m["conditions"][cid] = _effect_entry(c["uncond"], by_call, base, p,
                                                 c["grounded"].get(cid, True))
            m["conditions"][cid].update({
                "delta_pp": 100 * (p - base),
                "dlogit": _logit(p) - _logit(base),
            })
        entry["models"][label] = m

    if rungs is None:
        rungs = ladder_rungs()
    if rungs:
        for (qid, h), models in _loss_models(_ladder_cells(rows, rungs), rungs).items():
            if not keep(qid, h):
                continue
            out[qid][h] = {"models": models, "ensemble": {}, "n_models": 0,
                           "value_kind": "loss"}

    for qid, byh in out.items():
        for h, entry in byh.items():
            models = entry["models"]
            entry["n_models"] = len(models)
            entry["baseline_median"] = st.median(m["baseline"] for m in models.values())
            noises = [m["noise"] for m in models.values() if m["noise"]]
            entry["noise"] = ({"pp": st.median(n["pp"] for n in noises)
                               if all(n["pp"] is not None for n in noises) else None,
                               "dlogit": st.median(n["dlogit"] for n in noises)
                               if all(n["dlogit"] is not None for n in noises) else None,
                               "lo": st.median(n["lo"] for n in noises if n.get("lo") is not None)
                               if any(n.get("lo") is not None for n in noises) else None,
                               "hi": st.median(n["hi"] for n in noises if n.get("hi") is not None)
                               if any(n.get("hi") is not None for n in noises) else None,
                               "ratio": st.median(n["ratio"] for n in noises if n["ratio"] is not None)
                               if any(n["ratio"] is not None for n in noises) else None,
                               "models": len(noises)} if noises else None)
            # The unconditional's own 95% interval -- the band around the 1x
            # line: each model's t-interval on its level over its repeats, as
            # ratios to its centre, then the median across models. This is
            # re-elicitation uncertainty (ask again, where does it land), not
            # how far the models disagree with each other; a bootstrap over
            # models would measure the latter and span the 10x level spread.
            if entry["value_kind"] == "probability":
                # Median across models of the per-model ODDS-RATIO interval,
                # placed on the ensemble median's odds -- so the band can
                # never run past 0 or 100% however the models' centres differ.
                ors = [m["baseline_or"] for m in models.values() if m.get("baseline_or")]
                entry["baseline_or"] = ([st.median(c[0] for c in ors), st.median(c[1] for c in ors)]
                                        if ors else None)
                entry["baseline_ci"] = or_to_ratios(entry["baseline_median"], entry["baseline_or"])
            else:
                bcis = [m["baseline_ci"] for m in models.values() if m.get("baseline_ci")]
                entry["baseline_ci"] = ([st.median(c[0] for c in bcis), st.median(c[1] for c in bcis)]
                                        if bcis else None)
            if entry["value_kind"] == "loss":
                shares = [m["top_share"] for m in models.values() if m.get("top_share") is not None]
                entry["top_share_median"] = st.median(shares) if shares else None
                entry["repaired"] = sum(m.get("repaired", 0) for m in models.values())
            for cid in cond_order:
                per = {lbl: m["conditions"][cid] for lbl, m in models.items()
                       if cid in m["conditions"]}
                if not per:
                    continue
                e = {
                    "label": labels[cid], "leap_id": leap_ids[cid],
                    "n_models": len(per),
                    "delta": st.median(v["delta"] for v in per.values()),
                    "delta_pp": st.median(v["delta_pp"] for v in per.values())
                                if all(v["delta_pp"] is not None for v in per.values()) else None,
                    "dlogit": st.median(v["dlogit"] for v in per.values())
                              if all(v["dlogit"] is not None for v in per.values()) else None,
                    "ratio": st.median(v["ratio"] for v in per.values() if v["ratio"] is not None)
                             if any(v["ratio"] is not None for v in per.values()) else None,
                    "p_median": st.median(v["p"] for v in per.values()),
                    "raised": sum(1 for v in per.values() if v["delta"] > 0),
                    "lowered": sum(1 for v in per.values() if v["delta"] < 0),
                }
                # The ensemble's verdict: a 95% bootstrap interval for the
                # median across models of each model's mean log-ratio
                # (models and repeats resampled). Outside when it excludes 1x.
                # Per-model counts are carried for the label; they do not decide.
                med = e["delta"]
                same = [v for v in per.values() if v.get("outside")
                        and (v["delta"] > 0) == (med > 0) and med != 0]
                e["n_outside"] = sum(1 for v in per.values() if v.get("outside"))
                e["n_outside_dir"] = len(same)
                e["n_tested"] = sum(1 for v in per.values() if v.get("outside") is not None)
                ci = ensemble_ci([v.get("logs") or [] for v in per.values()])
                e["ci"] = [math.exp(ci[0]), math.exp(ci[1])] if ci else None
                e["outside"] = _excludes_zero(ci)
                e["ratio"] = (math.exp(st.median(math.log(v["ratio"]) for v in per.values() if v["ratio"]))
                              if any(v["ratio"] for v in per.values()) else e["ratio"])
                if entry["value_kind"] == "loss":
                    e["repaired"] = sum(v.get("repaired", 0) for v in per.values())
                entry["ensemble"][cid] = e
            entry["horizon_note"] = (
                "elicited under LEAP's clause, which keeps the policy in force "
                "through 2050 only" if h == "2100" and clause_note else None)

    runs = sorted({r["run_id"] for r in rows})
    protos = sorted({r.get("protocol") for r in rows} - {None})
    return {
        "questions": {q: dict(v) for q, v in out.items()},
        "conditions": [{"id": c, "label": labels[c], "leap_id": leap_ids[c]}
                       for c in cond_order],
        "meta": {"runs": runs, "rows": len(rows), "protocols": protos,
                 "condition_set": policies.get("slug", "leap"),
                 "experiments": sorted({r.get("experiment") for r in rows} - {None}),
                 "horizons": want_h, "source": policies["source"],
                 "usd_per_death": USD_PER_DEATH,
                 "rungs": [{"short": r, "deaths": x} for r, x in rungs] if rungs else []},
    }


def method_notes(compare, baseline, conditioning=None):
    """The `method` block both conditional tabs print, worded once.

    `compare` is the ratio's numerator as the tab names it ("policy",
    "conditional"); `baseline` says where the unconditional level comes from.
    The interval sentences describe what is drawn WHEN a day holds repeats;
    since 2026-09-02 each model answers once per run, so no band or interval
    is drawn until a day holds more than one call.
    """
    notes = {
        "baseline": "Each model's own unconditional forecast, elicited in the same "
                    f"call as the conditionals ({baseline}).",
        "ensemble": "Median across models of the per-model change, not the change "
                    "of the ensemble median.",
        "noise": "Band (drawn only when a day holds repeats of the same call): the "
                 "unconditional forecast's own 95% CI when re-asked. Per model, a "
                 "t-interval over its same-day repeats on the logit scale (log scale "
                 "for an expected loss); the band is the median across models of "
                 "those intervals, placed on the ensemble median. Since 2026-09-02 "
                 "each model answers once per run, so no band is drawn.",
        "outside": "95% CI of the change (when a day holds repeats). Per model: a "
                   f"paired t-interval on the log of ({compare} ÷ unconditional) over "
                   "repeats of the same call. Ensemble: a bootstrap percentile interval "
                   "for the median across models of those per-model means, resampling "
                   "models and repeats.",
        "loss": "Sum over rungs of P(loss ≥ rung) × (rung − previous rung): a "
                "floor under the forecast distribution for combined severity, in death-equivalents at the "
                f"ladder's own rate of one death-equivalent per ${USD_PER_DEATH / 1e6:g}M. This is not expected deaths; small probabilities at extreme thresholds can dominate the estimate.",
    }
    if conditioning is not None:
        notes["conditioning"] = conditioning
    return notes


def fmt_loss(v):
    """3.4M, 120k, 1.2B -- death-equivalents."""
    if v is None:
        return "-"
    for cut, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= cut:
            return f"{v / cut:.3g}{suf}"
    return f"{v:.3g}"


def table(summary, qid, horizon, measure="delta_pp"):
    """A text table: conditions down, models across, ensemble last."""
    entry = summary["questions"].get(qid, {}).get(horizon)
    if not entry:
        return f"(no rows for {qid} @ {horizon})"
    loss = entry.get("value_kind") == "loss"
    models = list(entry["models"])
    if loss and measure in ("delta_pp", "dlogit"):
        measure = "ratio"
    fmt = {"delta_pp": "{:+.2f}", "ratio": "{:.2f}x", "dlogit": "{:+.2f}", "p": "{:.2%}"}[measure]
    if loss and measure == "p":
        fmt = None
    val = (lambda v: fmt_loss(v)) if fmt is None else (lambda v: fmt.format(v))
    base_fmt = fmt_loss if loss else (lambda v: f"{100 * v:.2f}%")
    w = max(12, *(len(m) for m in models))
    head = (f"{qid} @ {horizon}  [{measure}]  baseline median {base_fmt(entry['baseline_median'])}"
            + ("  (expected loss, death-equivalents; floor)" if loss else ""))
    if entry["noise"]:
        n = entry["noise"]
        head += (f"  noise floor x{n['ratio']:.2f}" if n.get("ratio") else "") + \
                ("" if loss else f" / ±{n['pp'] / 2:.2f}pp / {n['dlogit'] / 2:.2f} logit") + \
                f" ({n['models']} models with repeats)"
    else:
        head += "  no repeats"
    lines = [head]
    lines.append("  ".join(["condition".ljust(34)] + [m.rjust(w) for m in models] + ["ensemble".rjust(w)]))
    base = ["baseline (unconditional)".ljust(34)]
    for m in models:
        base.append(base_fmt(entry["models"][m]["baseline"]).rjust(w))
    base.append(base_fmt(entry["baseline_median"]).rjust(w))
    lines.append("  ".join(base))
    for c in summary["conditions"]:
        cid = c["id"]
        row = [f"{cid:4} {c['label'][:28]}".ljust(34)]
        for m in models:
            v = entry["models"][m]["conditions"].get(cid)
            s = val(v[measure]) if v and v.get(measure) is not None else "-"
            if v and v.get("outside"):
                s += "*"      # clears the model's own re-elicitation range
            if v and not v.get("grounded", True):
                s += "†"      # answered with no search evidence
            row.append(s.rjust(w))
        e = entry["ensemble"].get(cid)
        ekey = "p_median" if measure == "p" else measure
        es = val(e[ekey]) if e and e.get(ekey) is not None else "-"
        if e and e.get("outside"):
            es += "*"
        row.append(es.rjust(w))
        lines.append("  ".join(row))
    lines.append("  * outside the 95% CI: per model, a paired t-interval on the log-ratio over "
                 "repeats of the same call; ensemble, a bootstrap interval for the median across models")
    return "\n".join(lines)
