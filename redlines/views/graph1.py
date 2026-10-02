"""Graph 1: the bottom-line forecasts from the frontier ensemble.

Nine questions in two rail groups:

  crosscutting  general catastrophe, AI catastrophe, human disempowerment,
                and since 2026-09-15 the extinction pair (human extinction,
                AI extinction; an addendum in XPT's wording). Severity is
                fixed -- 10% of population, none, a population floor of
                5,000 -- and only dates vary.
  incident      one EXPECTED-LOSS row per cause (since 2026-08-27): the
                eight rung forecasts folded to a floor on E[loss] in
                death-equivalents, the arithmetic the Conditional-on tab
                uses (redlines.conditional.expected_loss). The rungs
                themselves stay on Graph 2's severity ladder; here a cause
                is one row, not eight.

Featured questions are referenced, never copied. Duplicating one into the
cross-cutting file would get it elicited twice in the same call and put two
different numbers for one question into the coherence lattice. The 1M rung is
the one the workbook flags for human forecasting at every horizon, so it is the
only row where a model-versus-human read will exist across the whole time axis.

Every threshold this panel displays comes from questions.severity_label(), and
every horizon from questions.horizon_label(). None of it is typed into the page.

Human baselines carry their SOURCE. Before the swap all thirteen came from XPT
2022 and the panel printed that string as a constant; now only two questions
carry an anchor at all, and a third panel's number may arrive later, so the
label follows the data or it is wrong on five of the seven questions.

The two catastrophe questions now carry a `human` series each — a hollow
diamond per panel per horizon, superforecasters only (project lead, 2026-08-18:
report only supers everywhere), coloured from a muted reference palette and
labelled from the data (never a group name typed into the page). The other five
carry none. Turned on 2026-08-18 (project lead: they answer close but not
identical wordings, so they are drawn as a reference, with the mismatch stated
in humanCoverage.note, not reconciled here).
"""
import statistics

from ..conditional import (LOSS_PREFIX, USD_PER_DEATH, _level_ci, _lg, apply_or,
                           expected_loss, ladder_rungs, level_or, or_to_ratios)
from ..questions import (horizon_label, horizon_sort_key, human_baselines,
                         human_comparisons_wanted, is_future,
                         load_human_baselines, load_ladder, resolves_on,
                         severity_label)
from ..rail import grouping as rail_grouping, panel_questions as rail_questions
from ..registry import model_colors
from ..runlog import answered_horizons, current_rows, grounding, latest_pooled, load_runlog, instrument_info
from ..runlog import latest_instrument_rows, complete_panel_rows
from ..runlog import elicitation_date

MODEL_COLORS = model_colors()

# Human reference layer. Muted, low-chroma colours chosen to sit clearly apart
# from the vivid model palette (crimson/blue/orange/green/purple) and from the
# dark median ink — these read as reference points, not competing forecasts.
# One colour per (panel, group), assigned by a deterministic rank so the blob
# is byte-stable and a series keeps its colour across questions. Ordered so
# consecutive series get visibly different hues.
HUMAN_COLORS = [
    "#3f5566",  # deep slate
    "#7c6a54",  # warm taupe
    "#6c8296",  # light slate
    "#a08a63",  # tan
    "#8a8194",  # mauve-grey
    "#5f7a6b",  # sage
]
# Report superforecasters only (project lead, 2026-08-18: report only supers
# everywhere). The data file keeps every group; the panel plots the one the
# paper compares against, which also keeps it to one human mark per panel per
# horizon instead of three. Widen this tuple to bring experts/public back.
# Widened 2026-09-15 for the extinction pair: the AI-researcher median from the
# 2023 Expert Survey on Progress in AI is the comparison the project team asked for, and
# it is a group of its own panel (ESPAI), not an expert row of an FRI one.
PLOTTED_GROUPS = ("superforecaster", "ai_researcher")
# Display order only, so the palette assignment is stable. Unknown panels/groups
# sort last but still render — nothing here decides WHETHER a series is drawn,
# except the PLOTTED_GROUPS filter above.
_PANEL_RANK = {"XPT": 0, "LEAP": 1, "ESPAI": 2}
_GROUP_RANK = {"superforecaster": 0, "expert": 1, "public": 2, "ai_researcher": 3}


def _human_series(qid, horizons, doc):
    """Superforecaster panel medians for one question: one mark per panel.

    Data-driven within the PLOTTED_GROUPS filter — the panels are whatever the
    fetched baselines carry, never named here. Only horizons this panel actually
    plots are kept, so a human number at a horizon the chart does not show is
    dropped rather than floating off-axis. Ordered and coloured deterministically
    so the blob is byte-stable.
    """
    acc, date = {}, {}
    for h in horizons:
        for b in human_baselines(qid, h, doc):
            panel = b["project"]
            for group, stats in b["groups"].items():
                if group not in PLOTTED_GROUPS:
                    continue
                acc.setdefault((panel, group), {})[h] = stats["median"]
                date[(panel, group)] = b["elicited"].get("date")
    keys = sorted(acc, key=lambda k: (_PANEL_RANK.get(k[0], 9),
                                      _GROUP_RANK.get(k[1], 9), k))
    return [{"panel": p, "group": g, "date": date[(p, g)],
             "color": HUMAN_COLORS[i % len(HUMAN_COLORS)], "ps": acc[(p, g)]}
            for i, (p, g) in enumerate(keys)]


def _ensemble(series, horizons, kind="probability"):
    """(median, ci) across a question's model series, per horizon.

    The CI is the Conditional-on tab's band: the median across models of
    each model's own 95% interval, placed on the ensemble median.
    Re-elicitation uncertainty -- how far the same models move when merely
    asked again -- not model disagreement, which the dots show. Empty at a
    horizon with a single draw per model.

    A probability series carries the per-model interval as an odds ratio
    (`ciOr`, logit scale: bounded in 0-100%); a loss series as a ratio
    (`ciRatio`, log scale). Percent in, percent out.
    """
    median, ci = {}, {}
    for h in horizons:
        vals = [s["ps"][h] for s in series if h in s["ps"]]
        if vals:
            median[h] = round(statistics.median(vals), 3)
        if h not in median:
            continue
        if kind == "probability":
            ors = [s["ciOr"][h] for s in series if s.get("ciOr", {}).get(h)]
            if ors:
                orr = [statistics.median(c[0] for c in ors), statistics.median(c[1] for c in ors)]
                lo, hi = apply_or(median[h] / 100, orr)
                ci[h] = [round(100 * lo, 3), round(100 * hi, 3)]
        else:
            rs = [s["ciRatio"][h] for s in series if s.get("ciRatio", {}).get(h)]
            if rs:
                lo = statistics.median(c[0] for c in rs)
                hi = statistics.median(c[1] for c in rs)
                ci[h] = [round(median[h] * lo, 3), round(median[h] * hi, 3)]
    return median, ci


def _loss_series(cause, rungs, latest, horizons):
    """One cause's eight rungs folded to expected loss: (series, declined).

    Per draw k -- the k-th call of the day, aligned across rungs because all
    eight rungs are answered in the same call -- expected_loss() of that
    draw's rung grid. The point is the mean over draws and the interval a
    t-interval on their logs: exactly redlines.conditional._loss_models, so
    this row and the Conditional-on tab's unconditional column agree. A
    model missing any rung that day has no loss and is listed as declined.
    """
    series, declined = [], []
    for label, color in MODEL_COLORS:
        rows = {r: latest.get((f"ladder:{cause}:{r}", label)) for r, _ in rungs}
        if all(v is None for v in rows.values()):
            continue
        if any(v is None or not v["forecasts"] for v in rows.values()):
            declined.append(label)
            continue
        ps, draws, ci, ci_ratio, shares, repaired = {}, {}, {}, {}, [], 0
        for h in horizons:
            grids = {}
            for r, _ in rungs:
                d = (rows[r].get("draws") or {}).get(h)
                if not d:      # a pre-replication row: its one forecast is the draw
                    d = [f["probability"] for f in rows[r]["forecasts"] if f["horizon"] == h]
                grids[r] = d
            if any(not g for g in grids.values()):
                continue
            k = min(len(g) for g in grids.values())
            losses = [expected_loss({r: grids[r][i] for r, _ in rungs}, rungs) for i in range(k)]
            losses = [l for l in losses if l]
            if not losses:
                continue
            vals = [l["value"] for l in losses]
            ps[h] = round(statistics.fmean(vals), 1)
            draws[h] = [round(v, 1) for v in vals]
            c = _level_ci([_lg(v) for v in vals])
            if c:
                ci_ratio[h] = c
                ci[h] = [round(ps[h] * c[0], 1), round(ps[h] * c[1], 1)]
            shares += [l["top_share"] for l in losses if l["top_share"] is not None]
            repaired += sum(l["repaired"] for l in losses)
        if ps:
            series.append({"label": label, "color": color, "ps": ps, "draws": draws,
                           "ci": ci, "ciRatio": ci_ratio,
                           "topShare": round(statistics.fmean(shares), 4) if shares else None,
                           "repaired": repaired})
    return series, declined


def _loss_question(cause, spec):
    """The synthetic question record for one cause's expected-loss row."""
    c = next(c for c in spec["causes"] if c["key"] == cause)
    rungs = spec["rungs"]
    return {
        "id": LOSS_PREFIX + cause,
        "short": c["label"],
        "category": f"inc:{cause}",
        "railLabel": "Expected loss",
        "color": c.get("color"),
        "severity": None, "severityShort": None,
        "valueKind": "loss",
        "text": (f"{c['label']}: expected combined loss in death-equivalents (not expected deaths) "
                 f"(one death-equivalent = ${USD_PER_DEATH / 1e6:g}M in dollar-equivalents), a floor "
                 f"computed from the eight rung forecasts {rungs[0]['label']} … {rungs[-1]['label']}: "
                 "each band valued at its lower threshold, with severity capped at the top rung. Small probabilities at extreme thresholds can dominate this estimate; the floor is under the forecast distribution, not a guarantee about actual harm. "
                 "The rungs themselves are on the severity ladder (Graph 2)."),
        "criteria": "", "details": None,
    }


def build():
    # The whole set, railed and grouped by the shared module so this panel and
    # the Timeline draw the same rail (Graph 1 fixes severity and varies time;
    # each rung is its own selectable question).
    spec = load_ladder()
    qs = rail_questions(spec)
    per_q, categories = rail_grouping(qs, spec)
    rows = complete_panel_rows(latest_instrument_rows(load_runlog()))
    # The axis is the spec's grid INTERSECTED with what has been answered, so a
    # horizon added to the question set does not show up as an empty column
    # before the run that fills it. See runlog.answered_horizons.
    answered = answered_horizons(rows)

    # Each pair's newest DATE, every call that day pooled to its mean
    # (redlines.runlog.pool). One call per day, as before 2026-08-28, gives
    # exactly that call; three calls give their centre rather than whichever
    # finished last.
    # The current panel's rows only (redlines.runlog.current_rows): this is
    # the latest reading, and a model that left the panel would otherwise
    # sit here at its last run's number beside the panel's newer one. Its
    # history is on the Timeline, in gray.
    latest = latest_pooled(current_rows(rows))
    # The models this panel actually has rows for. MODEL_COLORS is every
    # model the registry can draw (the current ECI panel first, then the
    # rest); the legend lists only those present, so a panel change shows
    # up here the run it lands and never as an empty legend entry.
    present = {label for _, label in latest}

    # The run date every rolling horizon is measured from. A "within 6 months"
    # point means nothing on a time axis without it.
    as_of = max((elicitation_date(r) for r in rows), default=None)

    hdoc = load_human_baselines()
    rungs = ladder_rungs(spec)
    questions, done = [], set()
    for q in qs:
        # A question that entered the set after the latest complete run (an
        # addendum's `since`) has no reading yet: not drawn as an empty panel,
        # for the same reason an unanswered horizon is not drawn as an empty
        # column (runlog.answered_horizons). It appears the run that answers it.
        if not q.get("cause") and q["id"] not in answered:
            continue
        rail = per_q[q["id"]]
        horizons = sorted([h for h in q["horizons"]
                           if is_future(h, spec)
                           and h in answered.get(q["id"], set())],
                          key=lambda h: horizon_sort_key(h, spec))
        if q.get("cause"):
            # A rung: the whole cause is one expected-loss row, emitted at its
            # first rung and never again.
            if q["cause"] in done:
                continue
            done.add(q["cause"])
            series, declined = _loss_series(q["cause"], rungs, latest, horizons)
            median, ci = _ensemble(series, horizons, kind="loss")
            lq = _loss_question(q["cause"], spec)
            questions.append({
                **lq,
                "horizons": horizons,
                "horizonLabels": {h: horizon_label(h, spec, as_of) for h in horizons},
                "resolvesOn": {h: resolves_on(h, as_of, spec) for h in horizons}
                              if as_of else {},
                "series": series, "declined": declined,
                "median": median, "ci": ci,
                "replicates": max((r.get("replicates", 1) for r in
                                   (latest.get((f"ladder:{q['cause']}:{r}", l))
                                    for r, _ in rungs for l, _ in MODEL_COLORS) if r),
                                  default=0),
                "human": [],
            })
            continue
        series, declined = [], []
        for label, color in MODEL_COLORS:
            r = latest.get((q["id"], label))
            if not r:
                continue
            if not r["forecasts"]:
                declined.append(label)
                continue
            ps = {f["horizon"]: round(100 * f["probability"], 3)
                  for f in r["forecasts"] if f["horizon"] in horizons}
            # The day's raw draws behind each pooled point, and the model's
            # own 95% interval from them: the t-interval on the LOGIT level
            # that the Conditional-on tab draws as its band
            # (redlines.conditional.level_or), carried as an odds ratio and
            # placed on the pooled point. None with a single draw.
            draws = {h: [round(100 * v, 3) for v in vs]
                     for h, vs in (r.get("draws") or {}).items() if h in horizons}
            ci_or = {h: level_or(vs) for h, vs in
                     ((r.get("draws") or {}).items()) if h in horizons}
            ci = {h: [round(100 * x, 3) for x in apply_or(ps[h] / 100, c)]
                  for h, c in ci_or.items() if c and h in ps}
            if ps:
                series.append({"label": label, "color": color, "ps": ps,
                               "draws": draws, "ci": ci, "ciOr": ci_or})
        median, ci = _ensemble(series, horizons)

        questions.append({
            "id": q["id"],
            "short": q.get("short") or q.get("cause_label"),
            # Rail grouping key + the label shown under it. The group is the
            # workbook Category; the label is the rung for an incident, the
            # question name for a cross-cutting one.
            "category": rail["category"],
            "railLabel": rail["railLabel"],
            "color": q.get("color"),
            # The threshold, rendered once, here. The page prints this string;
            # it does not compose its own.
            "severity": severity_label(q),
            "severityShort": severity_label(q, short=True),
            "valueKind": "probability",
            "text": q["text"],
            # The resolution criteria travel with the question. A forecast is
            # only interpretable against the rules it was made under, and those
            # rules are the question set's — the measurement window, the but-for
            # standard, what counts as excess mortality. The panel showed a
            # short rail label and nothing else.
            "criteria": q.get("criteria") or "",
            "details": q.get("details") or None,
            "horizons": horizons,
            "horizonLabels": {h: horizon_label(h, spec, as_of) for h in horizons},
            "resolvesOn": {h: resolves_on(h, as_of, spec) for h in horizons}
                          if as_of else {},
            "series": series,
            "declined": declined,
            "median": median,
            # 95% CI of the median at each horizon (absolute, percent). Empty
            # on a day with one draw per model.
            "ci": ci,
            "replicates": max((r.get("replicates", 1) for r in
                               (latest.get((q["id"], l)) for l, _ in MODEL_COLORS) if r),
                              default=0),
            # Human panel medians, drawn as a reference layer. Empty for every
            # question but the two catastrophe ones — the chart renders what is
            # here and nothing where it is absent.
            "human": _human_series(q["id"], horizons, hdoc),
        })

    run_ids = sorted({r["run_id"] for r in rows})
    return {
        "runs": run_ids,
        "instrumentInfo": instrument_info(rows),
        # None, not a crash: an empty run log is a real state — a fresh
        # checkout, or the window between retiring one question set and
        # running the next. The panel should render empty and say so.
        "latest": max((r["elicited_at"] for r in rows), default=None),
        "grounding": grounding(rows),
        "models": [{"label": l, "color": c} for l, c in MODEL_COLORS if l in present],
        # The rail groups, in workbook order: the cross-cutting categories, then
        # the four incident categories named as the workbook's Category column
        # has them. Built from the questions actually present, so a question-set
        # change relabels the rail without touching this file.
        "categories": categories,
        # Which questions a human panel has already answered, DERIVED from
        # the workbook's own comparison column and the numbers pulled against it —
        # never a sentence typed here. The panel plots none of them yet; the
        # page says so once, here, rather than each chart implying it with a
        # blank.
        "humanCoverage": human_coverage(qs, plotted={q["id"] for q in questions}),
        "questions": questions,
        # The loss rows' axis: the ladder's rungs (deaths) and its rate.
        "rungs": [{"short": r["short"], "label": r["label"], "deaths": r["deaths"]}
                  for r in spec["rungs"]],
        "usdPerDeath": USD_PER_DEATH,
    }


def human_coverage(qs, plotted=None):
    """-> what human numbers exist for these questions, and where they came from.

    `plotted` is the set of question ids this panel actually draws. Since
    2026-08-27 the incident rungs are folded into one expected-loss row per
    cause, so a human number pulled for a rung (LEAP asked the AI-incident
    10k rung at 2050) has no row here to sit on; it goes in `unplotted`,
    named, and the note says so -- a gap stated, not a blank.

    Takes the SPEC questions, not the rendered ones: `human_comparisons` is
    the workbook's column and lives on the spec. Reading it off the rendered dicts
    silently returned nothing.

    Two facts, kept apart because they answer different questions. `wanted` is
    the workbook's "Human comparisons (Project)" column: which cells a prior FRI
    panel has answered, its author's judgement, not ours. `have` is what
    code/fetch_human_baselines.py could actually pull. A cell in `wanted` and
    not in `have` is a gap we should be able to name — P6 bio 2025 has numbers
    at 2045 and no question of ours to attach them to — and the page should say
    that rather than show a blank that reads as "nobody has forecast this".

    The series themselves ride on each question (`human`, built by
    _human_series); this is the coverage statement that names the gaps. Plotting
    was turned back on 2026-08-18 once the panels were pulled with their source
    wording attached — "add them back once we have ourselves sorted".
    """
    doc = load_human_baselines()
    wanted, have, panels = {}, {}, {}
    for q in qs:
        w = human_comparisons_wanted(q)
        if w:
            wanted[q["id"]] = w
        for h in q["horizons"]:
            for b in human_baselines(q["id"], h, doc):
                have.setdefault(q["id"], {}).setdefault(h, []).append(b["project"])
                panels[b["project"]] = b["elicited"].get("date")
    shown = set(have) if plotted is None else set(have) & set(plotted)
    unplotted = {qid: have[qid] for qid in sorted(have) if qid not in shown}
    gap = ""
    if unplotted:
        cells = "; ".join(f"{qid} at {', '.join(sorted(hs))} ({', '.join(sorted({p for ps in hs.values() for p in ps}))})"
                          for qid, hs in unplotted.items())
        gap = (f" A human number also exists for {cells}, a severity rung this "
               "panel folds into its expected-loss row, so it is not drawn here.")
    without = ([qid for qid in sorted(plotted) if qid not in have] if plotted is not None
               else [q["id"] for q in qs if q["id"] not in have])
    return {
        "with": sorted(shown),
        "without": without,
        "unplotted": unplotted,
        "wanted": wanted,
        "have": have,
        # Panel -> the date its forecasts were elicited, so no surface has to
        # print "XPT 2022" as a constant again.
        "panels": {k: panels[k] for k in sorted(panels)},
        "plotted": True,
        "note": "Superforecaster medians from prior FRI panels, and the AI-researcher "
                "median from the 2023 Expert Survey on Progress in AI (ESPAI), are "
                "shown as hollow diamonds, each labelled with its panel (experts "
                "and the public are in the data but not plotted). On the catastrophe "
                "questions they answer close but not identical wordings — XPT counted "
                "deaths where this question set counts attributable excess mortality, and both "
                "XPT and LEAP require the AI's involvement within a year of the "
                "event where she sets no time limit — so they are a dated reference, "
                "not a like-for-like overlay. The extinction questions are asked in "
                "XPT's own words, so those XPT diamonds are like-for-like; the AI "
                "researchers were asked about extinction OR similarly permanent and "
                "severe disempowerment, within 100 years of late 2023, so that "
                "diamond sits at 2100 as the nearest horizon, not the same one. "
                + (f"{len(shown)} of the plotted questions have a prior panel; the "
                   "rest show models alone." if shown else
                   "No plotted question has a prior panel yet.") + gap,
    }
