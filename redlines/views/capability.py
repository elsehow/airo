"""Capability tab: the frontier ECI -- history, the models' own forecast of it,
metr_graph's trend -- and every question conditional on the models' own
capability worlds.

Project lead, 2026-08-28: a tab called "Capability" with two graphs. (1) The
historical ECI trend plus the forecasted p50 / p25 / p75. (2) The questions
conditional on progress -- IDENTICAL to the Policy-levers graph except that
the rows are the model's own 25th / 50th / 75th percentile worlds instead of
policies, with the same unconditional line ("we expect p50 in the
unconditional").

Two self-elicited instruments exist (docs/conditional-forecasts.md):
data/eci_self6mo_conditions.json (frontier ECI six months from the run date)
and data/eci_self_conditions.json (end of 2030); the tab shows the six-month
one only for now (project lead, 2026-08-28) -- VARIANTS is the switch. Each is one
variant here:
its ECI forecast per model and call, the trend at its target date, and its
conditional cells shaped exactly as the policy tab's by
redlines.views.conditional._variant -- same arithmetic, same JSON shape, so
the page renders both with one component. The rows a variant shows are the
latest elicitation day's, pooled, as the policy tab does.

The trend is metr_graph's ECI-tab projection at its defaults, read from
data/eci_trend_2026-08-21.json (code/make_eci_trend.py: the seeded replica
run once, daily, on the laptop -- the box that publishes has no numpy): a
monthly p25 / p50 / p75 curve for the chart, from the anchor day (the last
frontier point, where the projection starts) on, and the three values at
each variant's target date. Context for the chart, never something the model saw.
"""
import json
import statistics as st
from datetime import datetime

from ..logs import log_exists
from ..conditional import (USD_PER_DEATH, group_rows, group_view, load_conditional, method_notes, newest_protocol, protocol_line)
from ..config import REPO_ROOT
from ..instrument import instrument_rows
from ..runlog import elicitation_date
from ..runlog import instrument_info
from ..questions import all_questions, load_ladder
from ..registry import model_colors
from .conditional import DEFAULT_HORIZONS, _variant, current_forecast_rows

# The variants, in the order the toggle offers them (the toggle appears only
# with more than one). Each is (short label, candidate sources): the sources
# are (set file, group) pairs that elicit the same quantity, and the one with
# the newest elicitation day is shown (ties: first listed) -- since 2026-08-28
# the combined instrument's capability group, which asks the six-month
# question in the same call as the policies, beside the standalone six-month
# set. The end-of-2030 set (("end of 2030", [("data/eci_self_conditions.json",
# None)])) is off the tab for now -- project lead, 2026-08-28: focus on the
# six-month one; add the line back to restore it.
VARIANTS = [
    ("six months out", [("data/combined_conditions.json", "capability"),
                        ("data/eci_self6mo_conditions.json", None)]),
]
# The live METR chart is refreshed independently of the historical prompt
# given to models.  Its observed ECI history and trend therefore update the
# display without rewriting what a past elicitation was shown.
TREND_JSON = REPO_ROOT / "data" / "eci_trend_2026-09-10.json"
# The one human forecast of the ECI: LEAP Wave 5's "U.S. versus China
# Polarity" question (code/pull_leap_axes.py, key eci_us). The FRI economist,
# 2026-09-02, after the axes work had used the wrong question: the U.S. vs.
# China one is where LEAP forecast the ECI of the top US model and the top
# China model separately.
LEAP_JSON = REPO_ROOT / "data" / "leap_reference.json"   # the tracked extract (code/make_leap_reference.py)
WAVE5_URL = "https://leap.forecastingresearch.org/reports/wave5"


def leap_eci(leap=None):
    """LEAP's forecast of the top-performing American system's ECI at end-2026,
    end-2030 and end-2040 (Wave 5, fielded 2026-01-12..02-03; each panelist
    gave p25/p50/p75). Per date and panel: n and the median across panelists
    of each percentile. `shown` is the superforecasters, as everywhere else on
    the page. None when the vendored file has no such question."""
    leap = leap or json.load(open(LEAP_JSON))
    a = leap["axes"].get("eci_us")
    if not a:
        return None
    dates = {}
    for hz, pcts in a["answers"].items():
        for p, panels in pcts.items():
            for panel, v in panels.items():
                if panel == "fri":
                    continue
                dates.setdefault(hz, {}).setdefault(panel, {"n": v["n"]})[p] = _r(v["median"], 1)
    return {
        "kind": "leap", "wave": a["survey"], "question": a["question_group"],
        "dimension": a["dimension"], "what": a["what"], "text": a["text"],
        "fielded": a["fielded"], "url": WAVE5_URL,
        "percentiles": [25, 50, 75], "shown": "superforecaster",
        # {date: {panel: {n, p25, p50, p75}}}
        "dates": dates,
        "scale": "the index as it stood when the wave was fielded (anchors: Claude 3.5 Sonnet "
                 "130, GPT-5 150), the same anchors as the CSV of 2026-08-21; Epoch notes scores "
                 "can shift retroactively as models and benchmarks are added.",
    }


def _trend(target_dates):
    """metr_graph's p25/p50/p75 from the precomputed daily file: a monthly
    curve (the anchor day, month starts, plus the last day) for the chart,
    and the values at each target date -- the day itself, or the nearest day
    in the file."""
    t = json.load(open(TREND_JSON))
    daily = t["daily"]
    by = {r["date"]: r for r in daily}
    curve = [{"date": r["date"], "p25": r["p25"], "p50": r["p50"], "p75": r["p75"]}
             for r in daily if r["date"].endswith("-01") or r is daily[0]]
    last = daily[-1]
    if curve[-1]["date"] != last["date"]:
        curve.append({"date": last["date"], "p25": last["p25"], "p50": last["p50"], "p75": last["p75"]})

    def at(date):
        r = by.get(date)
        if r is None:
            want = datetime.fromisoformat(date)
            r = min(daily, key=lambda x: abs((datetime.fromisoformat(x["date"]) - want).days))
        return {k: r[k] for k in ("p25", "p50", "p75")}

    return {
        "source": t["source"]["label"],
        "url": t["source"]["app"],
        "dataDate": t["source"]["retrieved"],
        "fit": t["fit"],
        "curve": curve,
        "at": {d: at(d) for d in target_dates},
    }


def _r(x, nd=1):
    return None if x is None else round(x, nd)


def _forecasts(rows, spec, colors):
    """Each model's ECI forecast: per call, its median, and the ensemble."""
    el = spec["elicit"]
    calls = {}
    for r in rows:
        e = (r.get("elicited") or {}).get(el["key"])
        if e:
            calls.setdefault(r["label"], {})[r["arm"]] = e
    # The fields every call answered: the forecast asks five percentiles
    # since 2026-09-02 (p10/p90 for the whiskers); rows before that carry
    # three, and a day's blob shows what its rows have.
    fields = [f for f in el["fields"] if all(f in a for c in calls.values() for a in c.values())]
    models = []
    for label in sorted(calls):
        arms = calls[label]
        med = {f: st.median(a[f] for a in arms.values()) for f in fields}
        models.append({
            "label": label, "color": colors.get(label),
            **{f: _r(med[f]) for f in fields},
            "n": len(arms),
            "calls": [{"arm": arm, **{f: _r(arms[arm][f]) for f in fields}} for arm in sorted(arms)],
        })
    ens = ({f: _r(st.median(m[f] for m in models)) for f in fields} if models else None)
    return models, ens


def _condition_values(rows):
    """{condition id: median over calls of the level the condition named}."""
    by = {}
    for r in rows:
        c = r.get("condition")
        if c and c.get("value") is not None:
            by.setdefault(c["id"], {})[r["call_id"]] = c["value"]
    return {cid: st.median(v.values()) for cid, v in by.items()}


def _method(spec):
    return method_notes("conditional", "mean over the day's repeats",
                        conditioning=spec.get("notes", {}).get("conditioning"))


def _pick(sources):
    """The candidate (set, group) with the newest elicitation day, its rows
    narrowed to that day (and to the group), the set seen as that group:
    -> (spec, rows, slug, group, set path). With no rows anywhere, the first
    candidate and no rows."""
    best = None
    for path, group in sources:
        spec = json.load(open(REPO_ROOT / path))
        slug = spec["slug"]
        log = REPO_ROOT / "results" / f"conditional_runs_{slug}.jsonl"
        # The set's protocol and its predecessors (redlines.conditional
        # PROTOCOL_LINEAGE): the newest tag present wins, so a bump keeps the
        # tab on the old rows until the first run under the new tag lands.
        rows = instrument_rows(load_conditional(str(log))) if log_exists(log) else []
        rows, proto = newest_protocol(rows, protocol_line(spec["protocol"]))
        if not rows:
            if best is None:
                best = (None, path, group_view(spec, group) if group else spec, [], slug, group,
                        spec["protocol"])
            continue
        day = max(elicitation_date(r) for r in rows)
        if best is not None and best[0] is not None and day <= best[0]:
            continue
        rows = [r for r in rows if elicitation_date(r) == day]
        if group:
            rows, spec = group_rows(rows, group), group_view(spec, group)
        best = (day, path, spec, rows, slug, group, proto)
    _, path, spec, rows, slug, group, proto = best
    return spec, rows, slug, group, path, proto


def build(horizons=DEFAULT_HORIZONS, variants=VARIANTS):
    ladder = load_ladder()
    qs = all_questions()
    colors = dict(model_colors())
    out_variants, stamps = [], []
    history = None
    for label, sources in variants:
        spec, rows, slug, group, path_, proto = _pick(sources)
        if variants is VARIANTS:
            rows = current_forecast_rows(rows)
        if rows:
            stamps += [r.get("elicited_at") or "" for r in rows]
        history = history or spec.get("history")
        target = sorted({(r.get("elicited") or {}).get("target_date") for r in rows} - {None})
        target_date = target[-1] if target else spec["elicit"].get("target_date")
        v = _variant(rows, spec, horizons, ladder, qs, colors)
        levels = _condition_values(rows)
        # The row's sub-line: the level the condition named (median over
        # calls), where the policy tab shows LEAP's id.
        for q in v["questions"]:
            for cell in q["byHorizon"].values():
                for b in cell["bars"]:
                    b["leapId"] = f"ECI ≈ {levels[b['id']]:.0f}" if b["id"] in levels else None
        models, ens = _forecasts(rows, spec, colors)
        present = {m["label"] for m in models} | {r["label"] for r in rows}
        # Row labels short enough for the chart's left column; the set's own
        # label ("Frontier ECI 6 months from the run date = your 25th
        # percentile") is the prompt's, not the page's.
        short = {"p10": "Own 10th percentile", "p25": "Own 25th percentile", "p50": "Own median (50th)",
                 "p75": "Own 75th percentile", "p90": "Own 90th percentile"}
        for q in v["questions"]:
            for cell in q["byHorizon"].values():
                for b in cell["bars"]:
                    f = next((c["field"] for c in spec["conditions"] if c["id"] == b["id"]), None)
                    b["label"] = short.get(f, b["label"])
        conds = [{"id": c["id"], "label": short.get(c["field"], c["label"]), "promptLabel": c["label"],
                  "leapId": (f"ECI ≈ {levels[c['id']]:.0f}" if c["id"] in levels else None),
                  "field": c["field"], "assume": c["assume"], "policy": None, "part": None,
                  "level": _r(levels.get(c["id"])),
                  # What the model was shown before the conditions: Step 1.
                  "description": spec["elicit"]["text"]}
                 # The rows the day answered, in the set's order: a set that
                 # grew (v4 added the model's own p10 and p90, 2026-09-03)
                 # lists five conditions, but a day run under the old tag
                 # answered three, and the page must not name rows it does
                 # not draw. Every condition when no run has landed yet.
                 for c in spec["conditions"] if not rows or c["id"] in levels]
        out_variants.append({
            "key": slug, "label": label,
            "instrumentInfo": instrument_info(rows),
            # Which instrument fed this variant: the set, its group (the
            # combined instrument's capability group, or None for a
            # standalone set) and the log.
            "instrument": {"set": path_, "group": group, "slug": slug,
                           "log": f"results/conditional_runs_{slug}.jsonl"},
            "targetDate": target_date,
            "targetMonths": spec["elicit"].get("target_months"),
            "title": spec["title"],
            "source": spec["source"],
            "conditioning": spec["conditioning"],
            "elicit": {k: spec["elicit"][k] for k in ("key", "fields", "percentiles", "text")},
            "conditions": conds,
            "horizons": list(horizons),
            "defaultHorizon": "2030",
            # The tag the rows shown carry (the set's own, when it has none).
            "protocol": proto,
            "questions": v["questions"],
            "models": [{"label": l, "color": c} for l, c in model_colors() if l in present],
            "runs": v["runs"], "experiments": v["experiments"], "rows": v["rows"],
            "repeats": v["repeats"],
            "forecast": {"models": models, "ensemble": ens},
            "notes": spec.get("notes", {}),
            "usdPerDeath": USD_PER_DEATH,
            "rungs": [{"short": r["short"], "label": r["label"], "deaths": r["deaths"]}
                      for r in ladder["rungs"]],
            "method": _method(spec),
        })
    targets = sorted({v["targetDate"] for v in out_variants if v["targetDate"]})
    trend = _trend(targets)
    for v in out_variants:
        v["forecast"]["trend"] = trend["at"].get(v["targetDate"])
    # `history` in the elicitation set remains the prompt record.  The chart
    # instead uses the current upstream ECI history packaged with its trend.
    current_history = json.load(open(TREND_JSON)).get("frontier") or history or []
    latest = current_history[-1] if current_history else None
    return {
        "title": "Forecasts conditional on AI capability",
        "instrumentInfo": out_variants[0]["instrumentInfo"] if out_variants else instrument_info([]),
        "generatedAt": max(stamps, default=None),
        "eci": {
            "csvDate": trend["dataDate"],
            "definition": "Epoch AI's Capabilities Index: one score per model across dozens "
                          "of benchmarks, fit with an item-response model. Frontier ECI = the "
                          "highest score of any released model from a US developer.",
            "history": current_history,
            "latest": latest,
            "trend": trend,
        },
        # The LEAP superforecasters' forecast of the same quantity, drawn beside
        # the models' box on the frontier chart (2026-09-03).
        "leap": leap_eci(),
        "variants": out_variants,
        "defaultVariant": out_variants[0]["key"] if out_variants else None,
    }
