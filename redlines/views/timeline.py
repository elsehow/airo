"""Timeline: how the bottom-line forecasts MOVE between elicitation dates.

Byte-exact port (2026-08-13) of the inline timeline script's build. Where Graph 1
(redlines/views/graph1.py) collapses the run log to each model's LATEST
forecast, this keeps the time axis: one snapshot per calendar date on which
forecasts were elicited, so the panel shows drift rather than a single
instant.

Grouping is by DATE, not run_id — a day's forecasts were appended in several
batches (the starter set, then the ladder), but they are one "as of" reading.

Feeds the Timeline panel, the lead of index.html's Forecasts tab
(web/demo/19-live-timeline.jsx; a standalone timeline.html until
2026-09-08): risk-category rail, horizon toggle, a dot per model per date
and the ensemble median over time.

THE SERIES STARTS AT redlines.runlog.SERIES_START (2026-09-02, the agentic
harness). Earlier elicitations -- the frontier five's batch, the joint
pilots, the 2026-08-28 three-draw pilot whose re-run bands the page used to
draw -- are a different method and are not spliced onto this line; they stay
in the run log and the CSV export. Everything below that pools a day's
draws still runs, and on a one-call-per-run series it is the identity:
`rerun`, `ci` and `noise` come out None and the page shows no bars.

The local forecasts_of() read guard from the inline timeline script is gone: every
row returned by redlines.runlog.load_runlog() already has "forecasts"
normalized to a (possibly empty) list of dicts (see that module's
docstring), so this module no longer needs to guard against a string or None
payload itself.

SHORT and per-question category now live in data/starter_questions.json
(migrated in 2026-08-13, see redlines/questions.py) instead of a local SHORT
dict.

REPLICATES (2026-08-28). A date's calls for one (question, model) are POOLED
by redlines.runlog.pool(): the plotted point is the mean of that day's draws,
`lo`/`hi` its min-max, and `draws` every raw value. The ensemble median is the
median of those per-model means, as before; `rerun` is its re-run interval --
the panel median recomputed once per draw index (all models' first draw, all
their second, ...) and spanned min-max -- and is None on any date with a
single draw per model, where there is no width to show. The old cross-model
min-max `spread` is gone: the model lines already show disagreement, and the
band's job is now to show how far the SAME models move when merely asked
again. The reason is in pool()'s docstring; the short form is that week-to-
week movement (median 0.8pp, p90 10pp) was no larger than same-day re-run
movement (median 0.6pp, p90 10pp), so a lone weekly draw was being read as
news it did not contain.

`noise` is that floor, measured from the log itself: on the latest date with
replicates, every pairwise |draw_i - draw_j| across (question, model,
horizon) cells, summarised as median / p90 / max. It is None until such a
date exists, and the page says nothing numeric about noise until then.
"""
import statistics
from collections import defaultdict
from datetime import date

from ..questions import (horizon_sort_key, is_future, load_ladder,
                         severity_label)
from ..rail import grouping as rail_grouping, panel_questions as rail_questions
from ..registry import model_colors, published_panel
from ..runlog import (answered_horizons, grounding, load_runlog, pool,
                      rows_by_day, series_rows)
from ..runlog import instrument_info, complete_panel_rows, current_panel, elicitation_date, SERIES_START
from ..conditional import USD_PER_DEATH, apply_or, ladder_rungs, level_or
from ..config import REPO_ROOT
from ..questions import SEVERITY_AXIS
from ..instrument import CURRENT_INSTRUMENT
from .graph1 import _loss_question, _loss_series
import json

MONTH = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# The inline timeline script's MODEL_COLORS (borrowed from code/make_demo_graph1.py),
# now sourced from the registry (same frontier-five order, same colors).
MODEL_COLORS = model_colors()

# The first GPT-6 Astra run (September 8) is an exploratory historical point
# whose AI-catastrophe answer is not suitable for the public trend line. Keep
# the raw row in downloads/archive, but omit it from this graph and from that
# date's displayed ensemble median. This is a display decision, not deletion
# or a revised forecast.
DISPLAY_EXCLUSIONS = {("catastrophe:ai", "GPT-6 Astra", "2026-09-08")}


def day_label(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{MONTH[m]} {d}"


def rerun_band(per_model_draws):
    """[[draw, ...] per model] -> [lo, hi] over replicate-wise panel medians,
    or None when no model has more than one draw.

    Draw index k pairs each model's k-th call with every other model's k-th
    call; a model with fewer draws simply drops out of the later medians.
    """
    K = max((len(d) for d in per_model_draws), default=0)
    if K < 2:
        return None
    meds = []
    for k in range(K):
        vk = [d[k] for d in per_model_draws if len(d) > k]
        meds.append(statistics.median(vk))
    return [round(min(meds), 3), round(max(meds), 3)]


def noise_floor(by_day, days):
    """The re-run noise floor from the latest replicated date, or None.

    Every pairwise absolute difference between one cell's draws, pooled over
    all (question, model, horizon) cells of that date, in percentage points.
    """
    for d in reversed(days):
        diffs = []
        for (dd, _, _), r in by_day.items():
            if dd != d:
                continue
            for ps in r["draws"].values():
                v = [100 * p for p in ps]
                diffs += [abs(a - b) for i, a in enumerate(v) for b in v[i + 1:]]
        if diffs:
            diffs.sort()
            draws = max(r["replicates"] for (dd, _, _), r in by_day.items() if dd == d)
            cells = sum(1 for (dd, _, _), r in by_day.items() if dd == d
                        for ps in r["draws"].values() if len(ps) > 1)
            return {"date": d, "label": day_label(d), "draws": draws, "cells": cells,
                    "median": round(statistics.median(diffs), 2),
                    "p90": round(diffs[int(0.9 * (len(diffs) - 1))], 2),
                    "max": round(diffs[-1], 2)}
    return None


def _prob_row(q, rail, by_day, days, horizons):
    """One cross-cutting question: per model, lists aligned to `days` of the
    pooled point, its draws, their min-max, and the model's 95% CI (logit
    t-interval over that day's draws, redlines.conditional.level_or); the
    ensemble median and ITS 95% CI (median across models of the per-model
    odds-ratio intervals, on the ensemble median) -- the same interval
    Graph 1's grey bars and the Policy-levers band show, so a move between
    two dates can be read against it. `rerun` (the replicate-wise range of
    panel medians) is kept for the table and tests."""
    series, declined = [], defaultdict(list)
    for label, color in MODEL_COLORS:
        ps = {h: [] for h in horizons}
        lo = {h: [] for h in horizons}
        hi = {h: [] for h in horizons}
        draws = {h: [] for h in horizons}
        ci = {h: [] for h in horizons}
        ci_or = {h: [] for h in horizons}
        seen = False
        for d in days:
            r = by_day.get((d, q["id"], label))
            if (q["id"], label, d) in DISPLAY_EXCLUSIONS:
                for h in horizons:
                    ps[h].append(None); lo[h].append(None); hi[h].append(None)
                    draws[h].append(None); ci[h].append(None); ci_or[h].append(None)
                continue
            fcs = r["forecasts"] if r else []
            if r and not fcs:
                declined[d].append(label)
            got = {f["horizon"]: 100 * f["probability"] for f in fcs}
            raw = r["draws"] if r else {}
            for h in horizons:
                v = got.get(h)
                ps[h].append(round(v, 3) if v is not None else None)
                vals = [round(100 * p, 3) for p in raw.get(h, [])]
                draws[h].append(vals or None)
                lo[h].append(min(vals) if vals else None)
                hi[h].append(max(vals) if vals else None)
                orr = level_or(raw.get(h, [])) if len(raw.get(h, [])) > 1 else None
                ci_or[h].append(orr)
                ci[h].append([round(100 * x, 3) for x in apply_or(v / 100, orr)]
                             if orr and v else None)
                seen = seen or v is not None
        if seen:
            series.append({"label": label, "color": color, "ps": ps,
                           "lo": lo, "hi": hi, "draws": draws, "ci": ci, "ciOr": ci_or})
    median, rerun, ci = {}, {}, {}
    for h in horizons:
        med, band, cis = [], [], []
        for i in range(len(days)):
            vals = [s["ps"][h][i] for s in series if s["ps"][h][i] is not None]
            m = round(statistics.median(vals), 3) if vals else None
            med.append(m)
            band.append(rerun_band([s["draws"][h][i] for s in series
                                    if s["draws"][h][i]]))
            ors = [s["ciOr"][h][i] for s in series if s["ciOr"][h][i]]
            if ors and m:
                orr = [statistics.median(c[0] for c in ors), statistics.median(c[1] for c in ors)]
                cis.append([round(100 * x, 3) for x in apply_or(m / 100, orr)])
            else:
                cis.append(None)
        median[h], rerun[h], ci[h] = med, band, cis
    return {
        "id": q["id"], "short": q.get("short") or q.get("cause_label"),
        "category": rail["category"], "railLabel": rail["railLabel"],
        "text": q["text"], "severity": severity_label(q),
        # The resolution criteria travel with the question, as on Graph 1:
        # the panel shows them behind the same "Resolution criteria" toggle.
        "criteria": q.get("criteria") or "", "details": q.get("details") or None,
        "value_kind": "probability", "horizons": horizons,
        "series": series, "median": median, "rerun": rerun, "ci": ci,
        "declined": dict(declined),
        "display_note": ("GPT-6 Astra's first exploratory run (September 8) is omitted from this graph; its raw forecast remains in the archive and download."
                          if q["id"] == "catastrophe:ai" else None),
    }


def _loss_row(cause, rungs, by_day, days, horizons, spec):
    """One cause's eight rungs folded to expected loss, per day -- the same
    row Graph 1 shows (graph1._loss_series, run once per date), with the
    lists aligned to `days`. Loss intervals are on the log scale."""
    color = dict(MODEL_COLORS)
    per, declined = {}, defaultdict(list)
    for d in days:
        latest_d = {(qid, label): r for (dd, qid, label), r in by_day.items() if dd == d}
        series_d, declined_d = _loss_series(cause, rungs, latest_d, horizons)
        declined[d].extend(declined_d)
        by_label = {s["label"]: s for s in series_d}
        for label, _ in MODEL_COLORS:
            s = by_label.get(label)
            e = per.setdefault(label, {k: {h: [] for h in horizons}
                                       for k in ("ps", "lo", "hi", "draws", "ci", "ciRatio")})
            for h in horizons:
                v = s["ps"].get(h) if s else None
                dr = (s["draws"].get(h) if s else None) or None
                e["ps"][h].append(v)
                e["draws"][h].append(dr)
                e["lo"][h].append(min(dr) if dr else None)
                e["hi"][h].append(max(dr) if dr else None)
                e["ci"][h].append(s["ci"].get(h) if s else None)
                e["ciRatio"][h].append(s["ciRatio"].get(h) if s else None)
    series = [{"label": l, "color": color[l], **e} for l, e in per.items()
              if any(v is not None for h in horizons for v in e["ps"][h])]
    median, rerun, ci = {}, {}, {}
    for h in horizons:
        med, cis = [], []
        for i in range(len(days)):
            vals = [s["ps"][h][i] for s in series if s["ps"][h][i] is not None]
            m = round(statistics.median(vals), 1) if vals else None
            med.append(m)
            rs = [s["ciRatio"][h][i] for s in series if s["ciRatio"][h][i]]
            cis.append([round(m * statistics.median(c[0] for c in rs), 1),
                        round(m * statistics.median(c[1] for c in rs), 1)] if rs and m else None)
        median[h], ci[h] = med, cis
        rerun[h] = [None] * len(days)
    lq = _loss_question(cause, spec)
    return {**lq, "value_kind": "loss", "horizons": horizons,
            "series": series, "median": median, "rerun": rerun, "ci": ci,
            "declined": {d: ls for d, ls in declined.items() if ls}}


def _reference_marks():
    """Definitional marks for the loss axis (Extinction), from the same file
    Graph 2 draws its reference marks from."""
    path = REPO_ROOT / "data" / "historical_events.json"
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    return [{"label": e.get("short") or e["label"], "v": e["severity"]["central"]}
            for e in doc.get("events", [])
            if e.get("kind") == "reference" and "xtinction" in e.get("label", "")]


def build():
    # The WHOLE set, railed and grouped by the shared module — the same rail
    # Graph 1 draws, so the two panels cannot disagree about what the dashboard
    # tracks or what each category is called.
    spec = load_ladder()
    qs = rail_questions(spec)
    per_q, categories = rail_grouping(qs, spec)
    # Keep the top-line probability questions' historical readings visible.
    # The September 10 instrument revision changed incident counting, so loss
    # rows below still use only current-version rows; the unchanged headline
    # questions can show their prior assessments as explicitly legacy points.
    all_rows = load_runlog(panel_only=False)
    current_rows_all = [r for r in all_rows if r.get("instrument_version")]
    legacy_probability_ids = {q["id"] for q in qs if not q.get("cause")}
    legacy_rows = [r for r in all_rows
                   if not r.get("instrument_version")
                   and r.get("question_id") in legacy_probability_ids
                   and elicitation_date(r) >= SERIES_START]
    current_series_rows = [r for r in current_rows_all if elicitation_date(r) >= SERIES_START]
    rows = current_series_rows + legacy_rows
    batches = rows_by_day(rows)
    newest = max(batches, default=None)
    current_batches = rows_by_day(current_series_rows)
    complete_current = [r for day, day_rows in current_batches.items()
                        for r in complete_panel_rows(day_rows, None if day == newest else current_panel(day_rows))]
    rows = complete_current + legacy_rows
    # Same rule as Graph 1: the axis is the spec's grid intersected with
    # what has actually been answered, so a newly added horizon appears the
    # run it is filled and not before. See runlog.answered_horizons.
    answered = answered_horizons(rows)

    # One snapshot per elicitation date; within a date, every call for a
    # (question, model) is one reading: pool() takes their mean and keeps the
    # draws. Before replication a day held one call per pair, and pool() of
    # one row is that row -- the numbers this produced for 2026-08-18 and
    # 2026-08-21 are byte-identical to the latest-row-wins dedup it replaced.
    by_day_rows = rows_by_day(rows)
    days = sorted(by_day_rows)
    by_day = {}
    for d, day_rows in by_day_rows.items():
        groups = defaultdict(list)
        for r in day_rows:
            groups[(r["question_id"], r["label"])].append(r)
        for (qid, label), reps in groups.items():
            by_day[(d, qid, label)] = pool(reps)
    # Every model with a row on any day, since this panel is the history: a
    # model that left the panel keeps its points (project lead, 2026-09-08), drawn in
    # the retired gray MODEL_COLORS gives every non-member, and flagged
    # `legacy` so the legend and the tooltip can say so. "Current" is the
    # registry's panel (the ensemble of record, what the next run asks), the
    # same rule that colors it -- so the flag and the gray never disagree.
    present = {label for _, _, label in by_day}
    current = {m["label"] for m, _ in published_panel()}

    snapshots = []
    for d in days:
        drows = by_day_rows[d]
        pooled = [r for (dd, _, _), r in by_day.items() if dd == d]
        snapshots.append({
            "date": d,
            "instrumentVersion": (CURRENT_INSTRUMENT if any(r.get("instrument_version") for r in drows)
                                  else "legacy"),
            "instrumentInfo": instrument_info(drows),
            "label": day_label(d),
            "runs": sorted({r["run_id"] for r in drows}),
            "n": len(drows),
            "calls": len({r.get("call_id") or f"{r['run_id']}:{r['label']}" for r in drows}),
            # Calls per (question, model) that day -- 1 before 2026-08-28.
            "draws": max((r["replicates"] for r in pooled), default=0),
            # Which elicitation produced the day. The series switched from the
            # plain batch (unified-batch-v2) to the single instrument's
            # unconditional slice (unified-joint-v1) on 2026-08-27; a reader
            # comparing across that date is comparing two elicitations.
            "protocols": sorted({r.get("protocol") for r in drows} - {None}),
            # Which model set answered: the stamped panel (set, k, snapshot
            # date) from 2026-08-28 on, the hand-picked frontier five before.
            "panel": sorted({(r.get("panel") or {}).get("set") or "frontier5" for r in drows}),
        })

    # Cross-cutting questions as themselves; each incident cause as ONE
    # expected-loss row (since 2026-08-27, matching Graph 1 and the
    # Policy-levers tab), emitted at its first rung and never again.
    questions, done = [], set()
    rungs = ladder_rungs(spec)
    # Incident expected-loss rows are intentionally kept on the current
    # instrument; their old definitions must not be silently joined to this
    # series. Probability rows use the combined history above.
    current_by_day = {}
    for d, day_rows in rows_by_day([r for r in rows if r.get("instrument_version")]).items():
        groups = defaultdict(list)
        for r in day_rows:
            groups[(r["question_id"], r["label"])].append(r)
        for (qid, label), reps in groups.items():
            current_by_day[(d, qid, label)] = pool(reps)
    for q in qs:
        # As on Graph 1: a question added to the set after the last answered
        # run (an addendum's `since`) is not drawn until a run answers it.
        if not q.get("cause") and q["id"] not in answered:
            continue
        horizons = sorted([h for h in q["horizons"]
                           if h and is_future(h, spec)
                           and h in answered.get(q["id"], set())],
                          key=lambda h: horizon_sort_key(h, spec))
        if q.get("cause"):
            if q["cause"] in done:
                continue
            done.add(q["cause"])
            questions.append(_loss_row(q["cause"], rungs, current_by_day, days, horizons, spec))
            continue
        questions.append(_prob_row(q, per_q[q["id"]], by_day, days, horizons))
    for q in questions:
        for s in q["series"]:
            s["legacy"] = s["label"] not in current

    return {
        "snapshots": snapshots,
        "instrumentInfo": instrument_info(rows),
        # None, not a crash: an empty run log is a real state — a fresh
        # checkout, or the window between retiring one question set and
        # running the next. The panel should render empty and say so.
        "latest": max((r["elicited_at"] for r in rows), default=None),
        "grounding": grounding(rows),
        "models": [{"label": l, "color": c, "legacy": l not in current}
                   for l, c in MODEL_COLORS if l in present],
        "categories": categories,
        # Calls per model in the newest run, and the measured re-run floor.
        # Both are read off the log, so the page's sentences about noise
        # appear when the data can back them and not before.
        "replicates": snapshots[-1]["draws"] if snapshots else 0,
        "noise": noise_floor(by_day, days),
        # Who wrote these questions, from the spec. The page said "Questions
        # and resolution criteria are the Existential Risk Persuasion
        # Tournament's" — true of the set retired on 2026-08-18, false of this
        # one, and typed into the chunk so nothing caught it at the swap.
        "provenance": load_ladder().get("provenance", {}),
        "questions": questions,
        # The loss rows' axis: the ladder's rungs, the shared severity axis,
        # the ladder's rate, and the Extinction reference mark.
        "rungs": [{"short": r["short"], "label": r["label"], "deaths": r["deaths"]}
                  for r in spec["rungs"]],
        "severityAxis": SEVERITY_AXIS,
        "usdPerDeath": USD_PER_DEATH,
        "marks": _reference_marks(),
    }
