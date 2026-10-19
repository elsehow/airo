"""Every coherence constraint the question set implies. No resolution needed.

The dashboard's questions form a lattice: some events strictly contain others, so
their probabilities are ordered whatever the world turns out to be. Each ordering
is checkable the day the forecast is made, which is what lets a protocol change
be judged rather than assumed (docs/coherence-experiment.md).

Lives in the package, not in code/, so tests/test_coherence.py can import it —
`code` is not a package and never will be. code/audit_coherence.py is the CLI
shim over this module.

Constraints:

  HORIZON    P must not fall as the horizon extends (cumulative questions).
  LADDER     Within a cause and a leg, P must not rise as the threshold rises.
  CROSS      No specific cause may exceed "any AI-related incident" at the
             same rung of the same leg.
  LEG        At every rung the damages question contains the deaths question
             (relations.legs): the Severity definitions count monetized
             mortality at the stated VSL toward economic damages, so reaching
             the death threshold reaches the dollar threshold.
  BRACKET    A cross-cutting question sits at a threshold on a ladder; its
             probability must sit on the correct side of that rung. The wording
             is not identical to the ladder's, so only the side the wording
             licenses is checked. The catastrophe questions resolve on 10% of
             population, so only the <=100M side of the bracket is licensed.
  SUBSET     One question's event is contained in another's: an AI-related
             epidemic is one kind of AI-related incident, 100k deaths is a
             subset of 1k deaths.

NONE of these hold by construction any more. Under unified-batch-v1 the prompt
stated the first three, so a clean HORIZON row measured compliance with an
instruction rather than the model's own coherence. The constraint block left the
prompt on 2026-08-18 (unified-batch-v2), which is what makes every row here a
measurement. Rows carrying the v1 tag are a different arm and must not be pooled
with v2 rows — tests/test_coherence.py warns when both are present.
"""
import json
from collections import defaultdict

from .config import REPO_ROOT
from .questions import horizon_sort_key, ladder_id
from .runlog import latest_per, load_runlog

LADDER_SPEC = REPO_ROOT / "data" / "autoarc_ladder.json"

# The relations live in data/autoarc_ladder.json, under "relations", NOT here.
#
# They used to be two hardcoded dicts, XPT_RELATIONS and SUBSET_PAIRS, keyed on
# XPT question ids and carrying -- by their own comment -- "judgments about
# English, not measurements". Most of those judgments have no successor: the
# Auto-ARC definitions state their containments outright, so a relation is now
# read off the question set rather than argued for. Moving them also makes a
# question-set swap a data change (edit the ladder JSON) rather than a code
# change.
#
# The set is deliberately small (project lead, 2026-08-18: minimal coherence
# checks, applied AFTER the fact, warning when there are obvious violations).
# Nothing here is inferred, and nothing is enforced -- code/run_unified.py's
# prompt states no relation at all, so every rate below measures the models
# rather than repeating our own instruction back to us.

CONSTRAINTS = ("HORIZON", "LADDER", "CROSS", "LEG", "BRACKET", "SUBSET")

EPS = 1e-9

# A path that cannot exist, so read() with no runs_dir audits exactly one file.
# load_runlog otherwise folds in every results/runs/*.jsonl scheduled run, which
# is right for the dashboard and wrong for auditing one protocol's output.
_NO_DIR = REPO_ROOT / "_no_such_dir"


def load_spec(path=LADDER_SPEC):
    return json.load(open(path))


def read(runlog=None, runs_dir=None, rows=None):
    """-> {(question_id, label): {horizon: percent}} from the latest row per key.

    Pass `rows` to audit an in-memory run log; otherwise the file(s) are read.
    """
    if rows is None:
        rows = (load_runlog(runlog, runs_dir or _NO_DIR) if runlog
                else load_runlog(runs_dir=runs_dir) if runs_dir
                else load_runlog())
    out = defaultdict(dict)
    for (qid, label), r in latest_per(rows).items():
        for f in (r["forecasts"] or []):
            out[(qid, label)][f["horizon"]] = 100 * f["probability"]
    return dict(out)


def _tally(cases):
    bad, n, ex = 0, 0, []
    for ok, detail in cases:
        n += 1
        if not ok:
            bad += 1
            ex.append(detail)
    return {"bad": bad, "n": n, "examples": ex,
            "rate": 100 * bad / n if n else 0.0}


def audit(P, spec=None, labels=None, horizons=None):
    """-> {constraint: {bad, n, rate, examples}} for every constraint above."""
    spec = spec or load_spec()
    if labels is None:
        from .registry import model_colors
        labels = [l for l, _ in model_colors()]
    # Horizons come from the SPEC, not from whichever question happens to be
    # first: the set has questions on different grids, and reading question[0]
    # silently truncated every constraint to that one question's horizons.
    # Sorted by the date they resolve, because "6mo" and "12mo" order before
    # "2028" by meaning and after it by ASCII.
    horizons = horizons or sorted(
        [h for h in spec["horizons"] if h],
        key=lambda h: horizon_sort_key(h, spec))

    rungs = [r["short"] for r in spec["rungs"]]
    causes = [c["key"] for c in spec["causes"]]
    legs = [l["key"] for l in spec["legs"]]
    rel = spec["relations"]

    def g(qid, lab, h):
        return P.get((qid, lab), {}).get(h)

    def lad(cause, rung, leg, lab, h):
        return g(ladder_id(cause, rung, leg), lab, h)

    def horizon_cases():
        for (qid, lab), byh in P.items():
            seq = [byh[h] for h in horizons if h in byh]
            for a, b in zip(seq, seq[1:]):
                yield b >= a - EPS, f"{lab} {qid}: {a:g} -> {b:g}"

    def ladder_cases():
        for c in causes:
            for leg in legs:
                for lab in labels:
                    for h in horizons:
                        seq = [(r, lad(c, r, leg, lab, h)) for r in rungs
                               if lad(c, r, leg, lab, h) is not None]
                        for (ra, a), (rb, b) in zip(seq, seq[1:]):
                            yield b <= a + EPS, f"{lab} {c} {leg} {h}: {ra}={a:g} -> {rb}={b:g}"

    def cross_cases():
        """Every specific incident type sits inside "any AI-related incident".

        The container is named in the data. There is NO all-cause ceiling in
        this question set -- nuclear and natural pandemics are outside it -- so
        this check is AI-internal only, which is a real narrowing from the
        retired set and is recorded in the ladder spec's notes.
        """
        top = rel["cross"]["container"]
        for c in rel["cross"]["contained"]:
            for leg in legs:
                for lab in labels:
                    for r in rungs:
                        for h in horizons:
                            v, t = lad(c, r, leg, lab, h), lad(top, r, leg, lab, h)
                            if v is None or t is None:
                                continue
                            yield v <= t + EPS, f"{lab} {c} {r} {leg} {h}: {v:g} > {top} {t:g}"

    def leg_cases():
        """At every rung the damages question contains the deaths question
        (relations.legs; the reason is in the spec, not here)."""
        pair = rel.get("legs")
        if not pair:
            return
        for c in causes:
            for r in rungs:
                for lab in labels:
                    for h in horizons:
                        a = lad(c, r, pair["contained"], lab, h)
                        b = lad(c, r, pair["container"], lab, h)
                        if a is None or b is None:
                            continue
                        yield a <= b + EPS, (f"{lab} {c} {r} {h}: {pair['contained']}={a:g} > "
                                             f"{pair['container']}={b:g}")

    def bracket_cases():
        """A cross-cutting question against the ladder rung that contains it.

        One side only, and the data says which -- the rung AND the leg. The AI
        catastrophe question is 10% of population, about 820M deaths, which
        sits BETWEEN the 100M and 1B rungs. The >=100M rung is a strictly
        easier event on both legs (on damages because monetized mortality
        counts toward them), so it bounds the question; the >=1B rung does not
        on either leg. Checking the side the wording does not license would
        manufacture violations out of our own carelessness.
        """
        for b in rel["bracket"]:
            for lab in labels:
                for h in horizons:
                    x = g(b["narrower"], lab, h)
                    y = lad(b["cause"], b["rung"], b["leg"], lab, h)
                    if x is None or y is None:
                        continue
                    yield x <= y + EPS, (
                        f"{lab} {b['narrower']} {h}: {x:g} > "
                        f"{b['cause']}:{b['rung']}:{b['leg']}={y:g}")

    def subset_cases():
        for pair in rel["subset"]:
            narrow, broad = pair["narrower"], pair["broader"]
            for lab in labels:
                for h in horizons:
                    a, b = g(narrow, lab, h), g(broad, lab, h)
                    if a is None or b is None:
                        continue
                    yield a <= b + EPS, f"{lab} {h}: {narrow}={a:g} > {broad}={b:g}"

    return {
        "HORIZON": _tally(horizon_cases()),
        "LADDER": _tally(ladder_cases()),
        "CROSS": _tally(cross_cases()),
        "LEG": _tally(leg_cases()),
        "BRACKET": _tally(bracket_cases()),
        "SUBSET": _tally(subset_cases()),
    }


def totals(results):
    bad = sum(r["bad"] for r in results.values())
    n = sum(r["n"] for r in results.values())
    return {"bad": bad, "n": n, "rate": 100 * bad / n if n else 0.0}
