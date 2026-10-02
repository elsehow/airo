"""Axes: the forecast against an x-axis quantity -- the frontier ECI, the
combined OpenAI + Anthropic revenue run-rate (LEAP Wave 11) and the year of
Expert AGI (LEAP Wave 8) -- from the axes instrument
(data/axes_conditions.json, code/make_axis_conditions.py; rows in
results/conditional_runs_axes.jsonl).

The FRI economist's spec (2026-09-02) and the worklist's C11/C12: one scatter per
axis with the panel's own forecast of the quantity and the LEAP superforecasters'
answer overlaid. Per question and horizon, each model's forecast under each
fixed level (a dot per model per level, a line through each model's dots),
the panel median (median across models at each level), and each model's
UNCONDITIONAL forecast placed at its own median forecast of the quantity --
the level it expects, so the dot sits where that model thinks the world is.
Along the x-axis: the panel's own forecast of the quantity (median across
models of each percentile, in LEAP's percentiles) and the LEAP
superforecasters' aggregate (median across panelists of each percentile,
data/leap_reference.json, the tracked extract); for the ECI axis, the trend at the run's
target date, and -- since 2026-09-03 -- LEAP Wave 5's forecast of the top US
system's ECI at end-2026, the one human forecast of the ECI there is
(redlines.views.capability.leap_eci).

The cells come from the same summary the Policy and Capability tabs use
(redlines.views.conditional._variant on the group's view of the set), so a
level's per-model value here is the value those tabs would show for the
same condition. The blob keeps the day's newest instrument under the set's
protocol line, as the other conditional views do.
"""
import json
import statistics as st

from ..logs import log_exists
from ..conditional import (USD_PER_DEATH, group_rows, group_view, load_conditional,
                           newest_protocol, protocol_line)
from ..config import REPO_ROOT
from ..instrument import instrument_rows
from ..runlog import elicitation_date
from ..runlog import instrument_info
from ..questions import all_questions, human_baselines, load_human_baselines, load_ladder
from ..registry import model_colors
from .capability import _r, _trend, leap_eci
from .conditional import _variant, current_forecast_rows

SET = REPO_ROOT / "data" / "axes_conditions.json"
LOG = REPO_ROOT / "results" / "conditional_runs_axes.jsonl"
# The tracked extract of the LEAP panel aggregates the page shows
# (code/make_leap_reference.py); the internal pull under data/leap/ is not
# published and is not needed to build.
LEAP = REPO_ROOT / "data" / "leap_reference.json"
HORIZONS = ("2030", "2050", "2100")
DEFAULT_HORIZON = "2050"
DEFAULT_QUESTION = "catastrophe:ai"

# Per axis: how the page draws it. `scale` is the x-axis scale; `fmt` names
# the number format the page applies; `xTitle` is the axis caption, with
# {date} filled from the run's target date where the quantity is rolling.
AXES = {
    "eci": {"label": "Frontier ECI", "short": "ECI", "scale": "linear", "fmt": "int",
            "phrase": "the frontier ECI six months out",
            "xTitle": "frontier ECI on {date}", "reference": "trend"},
    "revenue": {"label": "OpenAI + Anthropic revenue", "short": "Revenue", "scale": "log", "fmt": "money",
                "phrase": "the combined OpenAI + Anthropic revenue run-rate at end of 2030",
                "xTitle": "combined annualized revenue run-rate at end of 2030, $B (2026 USD)",
                "reference": "leap"},
    "agi": {"label": "Year of Expert AGI", "short": "AGI year", "scale": "linear", "fmt": "year",
            "phrase": "the year Expert AGI first occurs",
            "xTitle": "first year the LEAP panel agrees Expert AGI exists", "reference": "leap"},
}


def _rows(log_path, spec, experiment):
    if not log_exists(log_path):
        return [], spec["protocol"], None
    rows = instrument_rows(load_conditional(str(log_path)))
    rows = [r for r in rows if (r.get("experiment") or None) == experiment]
    rows, proto = newest_protocol(rows, protocol_line(spec["protocol"]))
    if not rows:
        return [], spec["protocol"], None
    day = max(elicitation_date(r) for r in rows)
    return [r for r in rows if elicitation_date(r) == day], proto, day


def _forecast(rows, elicit, colors):
    """The models' own forecast of one axis quantity: per model the median
    over its calls of each field, and the ensemble (median across models)."""
    calls = {}
    for r in rows:
        e = (r.get("elicited") or {}).get(elicit["key"])
        if e:
            calls.setdefault(r["label"], {})[r["call_id"]] = e
    fields = [f for f in elicit["fields"] if all(f in a for c in calls.values() for a in c.values())]
    models = []
    for label in sorted(calls):
        arms = calls[label]
        models.append({"label": label, "color": colors.get(label),
                       **{f: _r(st.median(a[f] for a in arms.values()), 2) for f in fields},
                       "n": len(arms)})
    ens = {f: _r(st.median(m[f] for m in models), 2) for f in fields} if models else None
    return {"key": elicit["key"], "fields": fields,
            "percentiles": elicit.get("percentiles") or {}, "models": models, "ensemble": ens}


def _leap_eci_reference(leap):
    """LEAP's forecast of the ECI, shaped like a LEAP axis reference so the
    page draws it the same way: the end-2026 date (two months before the
    axis's own six-months-out date; the page names the date), per panel the
    median across panelists of each percentile."""
    le = leap_eci(leap)
    if not le:
        return None
    at = "2026-12-31"
    return {"kind": "leap", "wave": le["wave"], "question": le["question"], "dimension": le["dimension"],
            "fielded": le["fielded"], "url": le["url"], "at": at, "percentiles": le["percentiles"],
            "panels": le["dates"].get(at, {}), "shown": le["shown"], "scale": le["scale"]}


def _leap_reference(spec, axis, leap):
    """The LEAP panels' aggregate for the axis quantity: per panel, the median
    across panelists of each asked percentile, and n."""
    ref = spec["reference"].get(axis) or {}
    at, pcts = ref.get("at"), ref.get("percentiles") or []
    src = next(g for g in spec["groups"] if g["key"] == axis)["source"]
    key = {"revenue": "revenue", "agi": "agi_year"}[axis]
    answers = leap["axes"][key]["answers"].get(at or "none", {})
    panels = {}
    for p in pcts:
        for panel, a in answers.get(f"p{p}", {}).items():
            if panel == "fri":
                continue
            panels.setdefault(panel, {"n": a["n"]})[f"p{p}"] = _r(a["median"], 2)
    out = {"kind": "leap", "wave": src.get("wave"), "question": src.get("question_group"),
           "fielded": leap["axes"][key]["fielded"], "percentiles": pcts, "panels": panels,
           "shown": "superforecaster"}
    if axis == "agi":
        pb = leap["axes"]["agi_p"]["answers"]["2099-12-31"]["p50"]
        out["pBefore2100"] = {panel: _r(a["median"] / 100, 3) for panel, a in pb.items() if panel != "fri"}
    return out


# Which human groups ride along: the superforecasters only, as on Graph 1
# (project lead, 2026-08-18: only supers everywhere), and only the LEAP panel:
# it is the one panel that has also forecast every axis quantity (revenue, the
# AGI year, and -- Wave 5 -- the top US system's ECI), so its unconditional
# has an x to sit at: its own median. XPT never forecast any of them. The ECI
# axis carried no humans between 2026-09-02 (project lead: a diamond placed at
# the trend's median was invented) and 2026-09-03 (the FRI economist pointed at
# Wave 5).
HUMAN_GROUPS = ("superforecaster",)
HUMAN_PANELS = ("LEAP",)


def _humans(qid, horizon, doc):
    """The LEAP superforecasters' UNCONDITIONAL median for one cell, same units
    as the models' (percent). No human panel has answered our questions
    conditional on anything; the page draws this at the panel's own median of
    the axis quantity -- the same placement the models' hollow dots get."""
    out = []
    for b in human_baselines(qid, horizon, doc):
        if b["project"] not in HUMAN_PANELS:
            continue
        for group, stats in b["groups"].items():
            if group in HUMAN_GROUPS:
                out.append({"panel": b["project"], "group": group,
                            "date": (b.get("elicited") or {}).get("date"), "p": stats["median"]})
    return sorted(out, key=lambda x: (x["panel"], x["group"]))


def _cells(variant, humans_doc=None):
    """The scatter's cells from the shared variant: per question and horizon
    the unconditional per model and, per level, the per-model values."""
    out = []
    for q in variant["questions"]:
        by = {}
        for h, cell in q["byHorizon"].items():
            by[h] = {
                "valueKind": cell["valueKind"],
                "baselineMedian": cell.get("baselineMedian"),
                "humans": _humans(q["id"], h, humans_doc) if humans_doc is not None else [],
                "baselines": [{"label": b["label"], "color": b["color"], "p": b["p"], "n": b.get("n")}
                              for b in cell.get("baselines", [])],
                "levels": [{"id": b["id"], "median": b.get("pMedian"), "nModels": b.get("nModels"),
                            "models": [{"label": m["label"], "color": m["color"], "p": m["p"],
                                        "baseline": m.get("baseline"), "grounded": m.get("grounded")}
                                       for m in b.get("models", [])]}
                           for b in cell.get("bars", [])],
            }
        out.append({k: q.get(k) for k in ("id", "name", "short", "heading", "group", "groupKey",
                                           "severity", "railLabel", "color", "valueKind", "horizons")}
                   | {"byHorizon": by})
    return out


def build(horizons=HORIZONS, log_path=None, experiment=None, set_path=None):
    spec = json.load(open(set_path or SET))
    leap = json.load(open(LEAP))
    ladder = load_ladder()
    qs = all_questions()
    humans_doc = load_human_baselines()
    colors = dict(model_colors())
    rows, proto, day = _rows(log_path or LOG, spec, experiment)
    if log_path is None and set_path is None and experiment is None:
        rows = current_forecast_rows(rows)
    elicits = {e["group"]: e for e in spec["elicits"]}
    targets = sorted({((r.get("elicited") or {}).get("targets") or {}).get("eci_forecast")
                      for r in rows} - {None})
    eci_target = targets[-1] if targets else None
    axes, questions = [], None
    for g in spec["groups"]:
        axis = g["key"]
        meta = AXES[axis]
        gspec = group_view(spec, axis)
        grows = group_rows(rows, axis)
        v = _variant(grows, gspec, list(horizons), ladder, qs, colors)
        levels = [{"id": c["id"], "value": c["value"], "unit": c["unit"], "label": c["label"],
                   "from": (c.get("chart") or {}).get("from")} for c in gspec["conditions"]]
        if meta["reference"] == "leap":
            reference = _leap_reference(spec, axis, leap)
        else:
            ref = spec["reference"]["eci"]
            tr = _trend([eci_target]) if eci_target else None
            at = tr["at"][eci_target] if tr else ref.get("trend_at_reference_target")
            # Provenance is the trend file's own (redlines.views.capability._trend
            # reads it), never a sentence typed here: the file is refreshed and
            # a typed sentence would name the wrong vintage.
            reference = {"kind": "trend",
                         "source": tr["source"] if tr else f"ECI trend projection ({ref.get('trend')})",
                         "dataDate": tr["dataDate"] if tr else None,
                         "url": tr["url"] if tr else None,
                         "percentiles": [25, 50, 75], "at": eci_target or ref.get("reference_target_date"),
                         "p25": at and at["p25"], "p50": at and at["p50"], "p75": at and at["p75"],
                         "pace": ref.get("pts_per_year"), "shown": "trend"}
        axes.append({
            "key": axis, "label": meta["label"], "short": meta["short"], "phrase": meta["phrase"],
            "heading": g["heading"],
            "kind": g["kind"], "scale": meta["scale"], "fmt": meta["fmt"],
            "xTitle": meta["xTitle"].format(date=eci_target or "the run date + 6 months"),
            "unit": levels[0]["unit"] if levels else None,
            "targetDate": (elicits[axis].get("target_date") if axis != "eci" else eci_target),
            "levels": levels,
            "reference": reference,
            # The ECI axis's human forecast of the quantity, beside the trend.
            "leap": _leap_eci_reference(leap) if axis == "eci" else None,
            "forecast": _forecast(grows, elicits[axis], colors),
            "elicit": {"key": elicits[axis]["key"], "text": elicits[axis]["text"]},
            "instruction": g["instruction"], "assumption": g["assumption"],
            "source": g["source"],
            # The page draws the questions once; every axis has the same set.
            # The LEAP superforecasters ride along on every axis, at their own
            # median forecast of the quantity.
            "questions": _cells(v, humans_doc),
        })
        questions = questions or [{k: q[k] for k in q if k != "byHorizon"} for q in axes[-1]["questions"]]
    present = sorted({r["label"] for r in rows})
    return {
        "title": "Forecasts against an x-axis quantity",
        "instrumentInfo": instrument_info(rows),
        "generatedAt": max((r.get("elicited_at") or "" for r in rows), default=None),
        "day": day, "protocol": proto,
        "instrument": {"set": "data/axes_conditions.json", "log": "results/conditional_runs_axes.jsonl",
                       "slug": spec["slug"], "title": spec["title"]},
        "conditioning": spec["conditioning"],
        "leap": {"file": "data/leap/axes-2026-09-02.json", "pulled": leap["pulled"]},
        "horizons": list(horizons), "defaultHorizon": DEFAULT_HORIZON,
        "defaultQuestion": DEFAULT_QUESTION, "defaultAxis": "eci",
        "questions": questions or [],
        "models": [{"label": l, "color": c} for l, c in model_colors() if l in present],
        "axes": axes,
        "usdPerDeath": USD_PER_DEATH,
        "notes": spec.get("notes", {}),
    }
