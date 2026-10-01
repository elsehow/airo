"""Conditional panel: what each LEAP policy does to a question, against baseline.

Feeds the Conditional-on tab of index.html: one question
at a time, one bar per policy condition, a zero line at the same-session
unconditional forecast, per-model dots over each bar, and the re-elicitation
noise floor drawn as a band so a bar inside it reads as "no evidence of an
effect" rather than as an effect.

The arithmetic lives in redlines/conditional.py; this module shapes it for
the page and joins it to the question set (names, severities, groups) and
the model registry (colours). It never states a direction: whether a policy
raises or lowers a forecast is what the run measured.

Lived on its own page (conditional.html) for one day, 2026-08-27, while the
protocol was being chosen; folded into index.html as a tab once the single
instrument became the published protocol and the unconditional series and
the conditionals came from the same calls.
"""
import json

from ..conditional import (COMBINED_PROTOCOL, CONDITIONAL_LOG, LOSS_PREFIX, POLICIES, USD_PER_DEATH, group_rows, group_view, load_conditional, method_notes, protocol_line, protocols_in, summarize)
from ..config import REPO_ROOT
from pathlib import Path
from ..questions import all_questions, cause_category, load_ladder, severity_label
from ..rail import CROSS_COLOR, GROUP_CROSS, GROUP_DOMAIN
from ..registry import model_colors
from ..runlog import current_panel, load_runlog
from ..runlog import instrument_info, complete_panel_rows, latest_instrument_rows
from ..instrument import instrument_rows
from ..runlog import elicitation_date


def current_forecast_rows(rows):
    """Use the headline's panel for current dashboard conditionals too.

    Select before computing summaries so removed models cannot influence
    medians or ECI percentiles. Current views require the complete configured
    four-model grid on one batch date. Explicit historical/experiment builds
    bypass this presentation gate.
    """
    rows = [r for r in instrument_rows(rows) if r.get("run_date")]
    return complete_panel_rows(latest_instrument_rows(rows))

# 2030 and 2050 only. LEAP's clause keeps the policy in force through 2050,
# so a 2100 conditional is a forecast under a policy the prompt has already
# let lapse: incoherent as a "policy effect". The instrument still elicits
# 2100 (the unconditional 2100 feeds the main page) and the summary keeps it,
# flagged; this tab just does not show it.
DEFAULT_HORIZONS = ("2030", "2050")
PILOT_ORDER = ["catastrophe:ai", "catastrophe:general", "disempowerment",
               "extinction:general", "extinction:ai"]   # the addendum pair last (2026-09-15)

# The page shows the ladder compressed: one expected-loss row per cause, not
# eight rung rows. The rungs stay in the summary (analyze_conditional.py
# --question ladder:ai:1B); they are just not a chart each here. The rail's
# section names are the shared ones (redlines.rail), so this tab and Graph 1
# read alike.
LOSS_GROUP = GROUP_DOMAIN

# The policy instrument's protocols, newest first. The log also holds the
# 2026-08-27 separate-call pilot (unified-batch-v2, one condition per call);
# it is history, not a view. Two joint tags because the v1 -> v2 bump
# (2026-08-28, the cross-cutting questions onto the six-horizon grid) was
# additive; selection only -- build() narrows a day to ONE protocol.
PROTOCOLS = ("unified-joint-v6", "unified-joint-v5", "unified-joint-v4", "unified-joint-v3", "unified-joint-v2", "unified-joint-v1")
PROTOCOL = PROTOCOLS[0]

# Where the tab's rows come from: (log, condition set, group, protocols
# newest-first), in order of preference when two share the newest day. Since
# 2026-08-28 the combined instrument -- the policies AND the capability
# conditions in one call (data/combined_conditions.json) -- is a source; its
# policy group renders here exactly as the LEAP set does, since the LEAP items
# are byte-identical inside it (redlines.conditional.group_view). NEWEST DAY
# WINS across sources: the tab always shows the freshest instrument, so the
# cron switching sets needs no edit here, and the blob says which it showed.
SOURCES = (
    (REPO_ROOT / "results" / "conditional_runs_combined.jsonl",
     REPO_ROOT / "data" / "combined_conditions.json", "policy",
     protocol_line(COMBINED_PROTOCOL)),
    (CONDITIONAL_LOG, POLICIES, None, PROTOCOLS),
)


def pick_source(sources=SOURCES, experiment=None):
    """-> {day, rows, spec, protocol, source} for the source with the newest
    elicitation day (ties: the first listed), its rows narrowed to that day and
    to one protocol (the newest present) and, for a grouped set, to the group;
    None when no source has rows."""
    best = None
    for log, set_path, group, protocols in sources:
        if not Path(log).exists():
            continue
        rows = [r for r in instrument_rows(load_conditional(str(log), experiment)) if r.get("protocol") in protocols]
        if not rows:
            continue
        day = max(elicitation_date(r) for r in rows)
        if best is not None and day <= best["day"]:
            continue
        rows = [r for r in rows if elicitation_date(r) == day]
        proto = min({r.get("protocol") for r in rows}, key=protocols.index)
        rows = [r for r in rows if r.get("protocol") == proto]
        spec = json.load(open(set_path))
        if group:
            rows, spec = group_rows(rows, group), group_view(spec, group)
        best = {"day": day, "rows": rows, "spec": spec, "protocol": proto,
                "source": {"log": _rel(log), "set": _rel(set_path), "group": group,
                           "slug": spec.get("slug", "leap")}}
    return best


def _rel(p):
    p = Path(p)
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _pct(x):
    return None if x is None else round(100 * x, 4)


def _loss(x):
    return None if x is None else round(x, 1)


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def _question_meta(q, spec):
    """Rail label, heading and group for one question.

    Cross-cutting questions keep their own short names. A loss row is one
    cause's ladder folded to its expected loss; its heading says so.
    """
    if q.get("category") == "crosscutting":
        return {"group": GROUP_CROSS, "groupKey": "crosscutting",
                "short": q.get("short") or q.get("name") or q["id"],
                "heading": q.get("short") or q.get("name") or q["id"],
                "severity": severity_label(q) if q.get("severity") else None,
                "valueKind": "probability",
                # Rail row: same label and dot as Graph 1's rail.
                "railLabel": q.get("name") or q.get("short") or q["id"],
                "color": CROSS_COLOR}
    cause = q.get("cause_label") or q.get("cause")
    return {"group": cause, "groupKey": q.get("cause"),
            "short": severity_label(q),
            "heading": f"{cause}, {severity_label(q)}",
            "severity": severity_label(q), "valueKind": "probability",
            "railLabel": severity_label(q), "color": None}


def _loss_question(cause, spec):
    """A synthetic question record for one cause's expected loss."""
    c = next((c for c in spec["causes"] if c["key"] == cause), {"label": cause})
    rungs = spec["rungs"]
    return {"id": LOSS_PREFIX + cause, "name": f"{c['label']}: expected loss",
            "text": (f"{c['label']}: expected combined loss in death-equivalents (not expected deaths) "
                     f"(one death-equivalent = ${USD_PER_DEATH / 1e6:g}M in dollar-equivalents), a floor "
                     f"computed from the eight rung forecasts {rungs[0]['label']} … {rungs[-1]['label']}: "
                     "each band valued at its lower threshold, with severity capped at the top rung. Small probabilities at extreme thresholds can dominate this estimate; the floor is under the forecast distribution, not a guarantee about actual harm."),
            "group": LOSS_GROUP, "groupKey": "loss", "short": c["label"],
            "heading": f"{c['label']} — expected loss", "severity": None,
            "valueKind": "loss",
            # Rail row: the workbook category and the cause's colour, as on
            # Graph 1's rail and Graph 2's curves.
            "railLabel": cause_category(c) if "key" in c else c["label"],
            "color": c.get("color")}


def _variant(rows, policies, horizons, spec, qs, colors):
    """One protocol's rows -> {questions, runs, rows, experiments, ...}."""
    summary = summarize(rows, policies, horizons=horizons) if rows else None

    # Cross-cutting first (the pilot's cells), then each cause in the ladder
    # spec's order with its rungs in severity order -- never sorted as text,
    # which puts 1B between 10M and 1k.
    cause_order = [c["key"] for c in spec["causes"]]
    rung_order = [r["short"] for r in spec["rungs"]]

    def order_key(qid):
        if qid in PILOT_ORDER:
            return (0, 0, PILOT_ORDER.index(qid))
        if qid.startswith(LOSS_PREFIX):
            cause = qid[len(LOSS_PREFIX):]
            return (1, cause_order.index(cause) if cause in cause_order else 99, "")
        q = qs.get(qid, {})
        if q.get("cause") in cause_order and q.get("rung") in rung_order:
            return (2, cause_order.index(q["cause"]), rung_order.index(q["rung"]))
        return (3, 0, qid)

    questions = []
    if summary:
        for qid in sorted(summary["questions"], key=order_key):
            if qid.startswith(LOSS_PREFIX):
                q = _loss_question(qid[len(LOSS_PREFIX):], spec)
            else:
                q = qs.get(qid)
            if not q or qid.startswith("ladder:"):
                continue
            by_h = {}
            for h, cell in summary["questions"][qid].items():
                if h not in horizons:      # summarize() keeps 2100 flagged; the tab drops it
                    continue
                kind = cell.get("value_kind", "probability")
                val = _pct if kind == "probability" else _loss
                bars = []
                for c in summary["conditions"]:
                    e = cell["ensemble"].get(c["id"])
                    if not e:
                        continue
                    models = []
                    for label, m in cell["models"].items():
                        v = m["conditions"].get(c["id"])
                        if not v:
                            continue
                        models.append({
                            "label": label, "color": colors.get(label),
                            "baseline": val(m["baseline"]), "p": val(v["p"]),
                            "values": [val(x) for x in v.get("values", [])],
                            "deltaPp": _r(v["delta_pp"]), "dlogit": _r(v["dlogit"]),
                            "ratio": _r(v["ratio"]),
                            "n": v["n"], "grounded": v.get("grounded", True),
                            "outside": v.get("outside"),
                            "ci": [_r(v["ci"][0]), _r(v["ci"][1])] if v.get("ci") else None,
                            "paired": v.get("paired", False),
                            "topShare": _r(v.get("top_share")), "repaired": v.get("repaired", 0),
                        })
                    bars.append({
                        "id": c["id"], "label": c["label"], "leapId": c["leap_id"],
                        "deltaPp": _r(e["delta_pp"]), "dlogit": _r(e["dlogit"]),
                        "ratio": _r(e["ratio"]),
                        "pMedian": val(e["p_median"]),
                        "raised": e["raised"], "lowered": e["lowered"], "nModels": e["n_models"],
                        "outside": e.get("outside"),
                        "ci": [_r(e["ci"][0]), _r(e["ci"][1])] if e.get("ci") else None,
                        "nOutside": e.get("n_outside", 0), "nOutsideDir": e.get("n_outside_dir", 0),
                        "nTested": e.get("n_tested", 0),
                        "models": models,
                    })
                by_h[h] = {
                    "valueKind": kind,
                    "baselineMedian": val(cell["baseline_median"]),
                    "baselines": [{"label": l, "color": colors.get(l),
                                   "p": val(m["baseline"]), "n": m["baseline_n"],
                                   "values": [val(v) for v in m["baseline_values"]],
                                   "ci": [_r(m["baseline_ci"][0]), _r(m["baseline_ci"][1])] if m.get("baseline_ci") else None,
                                   "topShare": _r(m.get("top_share"))}
                                  for l, m in cell["models"].items()],
                    # 95% interval of the unconditional itself, as ratios to it.
                    "baselineCi": ([_r(cell["baseline_ci"][0]), _r(cell["baseline_ci"][1])]
                                   if cell.get("baseline_ci") else None),
                    "noise": ({"pp": _r(cell["noise"]["pp"]),
                               "dlogit": _r(cell["noise"]["dlogit"]),
                               "ratio": _r(cell["noise"].get("ratio")),
                               "lo": _r(cell["noise"].get("lo")), "hi": _r(cell["noise"].get("hi")),
                               "models": cell["noise"]["models"]} if cell["noise"] else None),
                    "nModels": cell["n_models"],
                    "note": cell.get("horizon_note"),
                    "topShare": _r(cell.get("top_share_median")),
                    "repaired": cell.get("repaired", 0),
                    "bars": bars,
                }
            meta = q if qid.startswith(LOSS_PREFIX) else _question_meta(q, spec)
            meta = {k: meta.get(k) for k in ("group", "groupKey", "short", "heading", "severity", "valueKind", "railLabel", "color")}
            questions.append({"id": qid, "name": q.get("name") or q.get("text", "")[:80],
                              "text": q.get("text"), **meta,
                              "horizons": [h for h in horizons if h in by_h],
                              "byHorizon": by_h})

    return {
        "questions": questions,
        "instrumentInfo": instrument_info(rows),
        "runs": summary["meta"]["runs"] if summary else [],
        "experiments": summary["meta"]["experiments"] if summary else [],
        "rows": len(rows),
        "repeats": _repeats(rows),
    }


def _repeats(rows):
    """How many times each model answered unconditionally -- the noise's n."""
    calls = {}
    for r in rows:
        if not r.get("condition"):
            calls.setdefault(r["label"], set()).add(r.get("call_id") or r.get("arm"))
    return {l: len(c) for l, c in calls.items()}


def build(log_path=None, experiment=None, horizons=DEFAULT_HORIZONS,
          policies_path=None):
    """The tab's blob. With no arguments, the newest instrument among SOURCES;
    a log and/or set names one source explicitly (the LEAP protocols)."""
    spec = load_ladder()
    qs = all_questions()
    colors = dict(model_colors())
    if log_path or policies_path:
        sources = ((log_path or CONDITIONAL_LOG, policies_path or POLICIES, None, PROTOCOLS),)
    else:
        sources = SOURCES
    # The latest elicitation DATE only, every call that day pooled -- the
    # run log's doctrine (redlines.runlog.latest_pooled). Without this the
    # tab would pool every week's instrument into one ever-growing sample.
    # Two runs on one day (2026-08-27: 3 repeats at 1828Z, 2 more at 2137Z)
    # are one day's five draws.
    picked = pick_source(sources, experiment)
    if picked:
        rows, policies, protocol, source = picked["rows"], picked["spec"], picked["protocol"], picked["source"]
    else:
        rows, policies, protocol = [], json.load(open(sources[0][1])), sources[0][3][0]
        source = {"log": _rel(sources[0][0]), "set": _rel(sources[0][1]), "group": sources[0][2],
                  "slug": policies.get("slug", "leap")}
        policies = group_view(policies, source["group"]) if source["group"] else policies
    if not log_path and not policies_path and experiment is None:
        rows = current_forecast_rows(rows)
    v = _variant(rows, policies, horizons, spec, qs, colors)
    conds = [{"id": c["id"], "label": c["label"], "leapId": c["leap_id"],
              "assume": c["assume"], "policy": c["policy"], "part": c["part"],
              # The policy text as the model saw it (LEAP's, verbatim).
              "description": c.get("description")}
             for c in policies["conditions"]]
    return {
        "title": "Forecasts conditional on LEAP Wave 12 policies",
        "instrumentInfo": instrument_info(rows),
        # Derived from the log, not the clock: the assembled page must be a
        # pure function of its inputs (tests/test_assemble_golden.py).
        "generatedAt": max((r.get("elicited_at") or "" for r in rows), default=None),
        "source": policies["source"],
        "conditioning": policies["conditioning"],
        "conditions": conds,
        "horizons": list(horizons),
        "defaultHorizon": "2030",
        # The instrument actually summarised -- which log, set and group, and
        # its protocol -- not the newest one defined.
        "protocol": protocol,
        "instrument": source,
        "questions": v["questions"],
        # The models on this day's instrument, in the registry's order.
        "models": [{"label": l, "color": c} for l, c in model_colors()
                   if l in {r["label"] for r in rows}],
        "runs": v["runs"],
        "experiments": v["experiments"],
        "rows": v["rows"],
        "repeats": v["repeats"],
        "notes": policies.get("notes", {}),
        "usdPerDeath": USD_PER_DEATH,
        "rungs": [{"short": r["short"], "label": r["label"], "deaths": r["deaths"]}
                  for r in spec["rungs"]],
        "method": method_notes("policy", "mean of the unconditional arms"),
    }
