"""Forecast run-log loading: results/forecast_runs.jsonl + results/runs/*.jsonl.

Ported from code/make_demo_graph1.py::load_runlog, with a defensive read guard
applied to every row's `forecasts` field before it's handed back — the
semantics of the inline timeline script's forecasts_of (ported 2026-08-13) and
archive/legacy-questions/run_forecasts.py::clean_forecasts, ported here so
every caller (graph1, graph2, timeline, and whatever views come next) gets the
same protection without repeating it.

WHY THE GUARD EXISTS
A 2026-08-10 bug had a model (Fable 5) hand back its forecast array as a
truthy, malformed JSON *string* instead of a parsed list. `if not
row["forecasts"]:` doesn't catch that (a non-empty string is truthy), so
naive iteration over row["forecasts"] treats the string as an iterable of
1-character strings and crashes on the first `f["horizon"]` lookup.
run_forecasts.py::clean_forecasts stops new rows like this from landing; this
guard makes every *read* of the existing log safe regardless.

GUARANTEE
Every row this module returns has row["forecasts"] as a (possibly empty)
list of dicts. This does not change what the current materializers compute
from the current run log: the one malformed historical row is for
("16. State Actor Bioweapon 1k Deaths", "Fable 5") on 2026-08-10, and is
always shadowed by a later, well-formed row for the same (question, model)
key — so it never survives latest_per() or the per-day dedup either way.
"""
import json
import statistics
from collections import defaultdict
from datetime import date

from .conditional import AGENTIC_SINCE, COMBINED_PROTOCOL, protocol_line
from .config import REPO_ROOT
from .instrument import CURRENT_INSTRUMENT, instrument_rows
from .superseded import is_superseded

# The live log, written by code/run_unified.py under the unified-batch protocol:
# one call per model covering every question, so the panels are mutually
# coherent rather than separately plausible (docs/coherence-experiment.md).
#
# The pre-2026-08-14 per-question forecasts are RETIRED, not deleted — they live
# in archive/legacy-forecasts/ and no panel reads them. They cannot be spliced
# onto this series: 23% of their Graph-1-vs-Graph-2 pairs contradict each other,
# and a protocol change inside a time series whose purpose is to show movement
# would read as news. See that directory's README.
RUNLOG = REPO_ROOT / "results" / "forecast_runs_unified.jsonl"
RUNS_DIR = REPO_ROOT / "results" / "runs"

# What grounded a run, for the provenance line the panels print. Keyed by the
# protocol tag the rows carry, because the tools and the prompt changed under
# the same questions on 2026-09-02 (redlines/tools.py: the Metaculus lookup
# left, a page reader joined, and the prompt asks for iterative search) and a
# page built from older rows must not describe them with the newer words.
GROUNDING_LEGACY = "shared web search (Tavily) + Metaculus cross-check"
GROUNDING_AGENTIC = "agentic web search (Tavily): iterative search + page reads"
# Every protocol tag the run log has carried, oldest first: the plain batch,
# the joint pilots, then the combined instrument's lineage
# (redlines.conditional.PROTOCOL_LINEAGE, the one registry of those tags).
LEGACY_PROTOCOLS = ("unified-batch-v1", "unified-batch-v2",
                    "unified-joint-v1", "unified-joint-v2", "unified-joint-v3",
                    "unified-joint-v4", "unified-joint-v5", "unified-joint-v6")
COMBINED_PROTOCOLS = tuple(reversed(protocol_line(COMBINED_PROTOCOL)))
KNOWN_PROTOCOLS = LEGACY_PROTOCOLS + COMBINED_PROTOCOLS
AGENTIC_PROTOCOLS = set(COMBINED_PROTOCOLS[COMBINED_PROTOCOLS.index(AGENTIC_SINCE):])


# THE SERIES STARTS HERE. The agentic harness went live on 2026-09-02: one
# call per model per run, grounded by iterative search and page reads. What
# came before -- the frontier five's plain batch, the joint pilots, and the
# 2026-08-28 three-draw pilot with its re-run bands -- was elicited
# differently, and the Timeline does not draw it on the same axis (project
# lead, 2026-09-08: only the current methodology). Those rows stay in
# results/runs/, in git and in the CSV export; only the over-time panel
# starts here. Bump this the next time the elicitation changes under the
# questions, rather than splicing two methods into one line.
SERIES_START = "2026-09-02"


def elicitation_date(row):
    """The common batch date governs current windows, even across midnight."""
    if row.get("instrument_version") == CURRENT_INSTRUMENT and row.get("run_date"):
        return row["run_date"]
    return row["elicited_at"][:10]


def series_rows(rows):
    """Current instrument only, without joining earlier definitions into a line."""
    return [r for r in instrument_rows(rows) if elicitation_date(r) >= SERIES_START]


def latest_instrument_rows(rows):
    """One batch date for a latest-reading chart and its incident windows.

    Missing questions on the newest batch stay missing, rather than silently
    borrowing a probability whose prospective start date was different.
    """
    rows = instrument_rows(rows)
    latest = max((elicitation_date(r) for r in rows), default=None)
    return [r for r in rows if elicitation_date(r) == latest]


def complete_panel_rows(rows, labels=None):
    """Publish only one complete four-model reading on a common batch date.

    Filter the configured roster before checking every question/condition/
    horizon cell. A partially completed run cannot redefine the ensemble or
    borrow missing answers from another date. Raw downloads remain unfiltered.
    """
    from .registry import PANEL_K, published_panel
    from .questions import questions_asked_on
    rows = instrument_rows(rows)
    labels = set(labels) if labels is not None else {m["label"] for m, _ in published_panel(rows=rows)}
    if len(labels) != PANEL_K or not rows or any(not r.get("run_date") for r in rows):
        return []
    if len({r["run_date"] for r in rows}) != 1:
        return []
    # The set AS OF this run: a question added later (an addendum's `since`)
    # is not owed by an earlier run (redlines.questions.questions_asked_on).
    questions = questions_asked_on(rows[0]["run_date"])
    rows = [r for r in rows if r["label"] in labels]
    if {r["label"] for r in rows} != labels or {r["question_id"] for r in rows} != set(questions):
        return []
    cells = defaultdict(set)
    expected = set()
    deadlines = {}
    for r in rows:
        condition = (r.get("condition") or {}).get("id")
        # asked_horizons can retain all six general question horizons while
        # an axes instrument elicits only three. resolves_on records the
        # actual instrument deadlines and is required for current rows.
        resolves = r.get("resolves_on")
        question_horizons = set(questions[r["question_id"]]["horizons"])
        if not isinstance(resolves, dict) or not resolves or set(resolves) - question_horizons:
            return []
        actual_horizons = question_horizons.intersection(resolves)
        if {f["horizon"] for f in r.get("forecasts", [])} != actual_horizons:
            return []
        for h in actual_horizons:
            try:
                date.fromisoformat(resolves[h])
            except (TypeError, ValueError):
                return []
            key = (r["question_id"], h)
            if deadlines.setdefault(key, resolves[h]) != resolves[h]:
                return []
            expected.add((r["question_id"], condition, h))
        for f in r.get("forecasts", []):
            p = f.get("probability")
            if isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p <= 1:
                cells[(r["question_id"], condition, f["horizon"])].add(r["label"])
    # A whole question missing from one condition must fail too, even if all
    # four models omitted that cell. Conditions are the selected view group.
    conditions = {(r.get("condition") or {}).get("id") for r in rows}
    horizons = defaultdict(set)
    for q, _, h in expected:
        horizons[q].add(h)
    expected = {(q, condition, h) for q, hs in horizons.items()
                for condition in conditions for h in hs}
    if not expected or any(cells[key] != labels for key in expected):
        return []
    # Capability quantiles feed a separate ensemble chart. They must also
    # cover the full roster, rather than silently taking a three-model median.
    metadata = defaultdict(set)
    def numeric_fields(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from numeric_fields(child, path + (key,))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            yield path
    for r in rows:
        for path in numeric_fields(r.get("elicited") or {}):
            metadata[path].add(r["label"])
    if any(present != labels for present in metadata.values()):
        return []
    return rows


def instrument_info(rows):
    """Display provenance and recorded incident windows; never infer old dates.

    A fixed-year endpoint is still a changing event as the start advances.
    Expose the dates actually sent to the models, including on timeline days.
    """
    rows = instrument_rows(rows)
    day = max((r.get("run_date") or r["elicited_at"][:10] for r in rows), default=None)
    windows = {}
    for r in rows:
        if (r.get("run_date") or r["elicited_at"][:10]) != day:
            continue
        for h, w in (r.get("counting_window") or {}).items():
            if w not in windows.setdefault(h, []):
                windows[h].append(w)
    return {
        "version": CURRENT_INSTRUMENT,
        "available": bool(rows),
        "runDate": day,
        "countingWindows": windows,
        "change": "Incident counting rules changed: only incidents beginning on or after "
                  "the elicitation date qualify. The entire joint forecast series starts "
                  "anew because the questions are elicited together. Earlier forecasts "
                  "remain in the download under their original recorded version or as unversioned legacy rows. "
                  "Current charts require all four panel models on the same elicitation date.",
        "windowChange": "Incident onset starts advance with each elicitation date, including for fixed-year "
                        "deadlines. Changes across runs therefore reflect changing intervals as well as revised beliefs.",
        "archiveUrl": "redlines-data.zip",
    }


def grounding(rows):
    """The grounding line for the newest run among `rows`."""
    latest = max(rows, key=lambda r: r.get("elicited_at") or "", default=None)
    if latest is not None and latest.get("protocol") in AGENTIC_PROTOCOLS:
        return GROUNDING_AGENTIC
    return GROUNDING_LEGACY


def _clean_forecasts(raw):
    """Normalize a row's raw `forecasts` field to a list of dicts.

    Union of the two historical guards, taking the stricter acceptance rule:
    like the inline timeline script's forecasts_of, a JSON-string payload is
    parsed (dropped to [] if it doesn't parse) and a non-list payload (including
    None) becomes []; like the legacy runner's clean_forecasts (the
    write-side gate), a kept item must be a dict with BOTH "horizon" and
    "probability" — every view reads f["probability"], so a horizon-only dict
    would KeyError downstream. No row in the current log trips the stricter
    rule (they all came through clean_forecasts), so this changes nothing
    today; it exists for logs written by other tools or future bugs.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [f for f in raw
            if isinstance(f, dict) and "horizon" in f and "probability" in f]


def load_runlog(runlog=RUNLOG, runs_dir=RUNS_DIR, panel_only=True):
    """All forecast rows: the historical log plus one file per scheduled run.

    `panel_only` (the default) hands back panel rows only (panel_rows: what
    the views draw); False hands back every row in the log -- the download
    bundle wants everything (project lead, 2026-09-08: include everything).

    Scheduled runs (code/cron_run.sh on the exe.dev box) write their own dated
    file instead of appending to the shared log. Two machines appending to the
    tail of one tracked file is a git conflict every single week, and the box's
    checkout is rsynced — one careless --delete would take the accrued history
    with it. Separate files make both failure modes impossible.

    Every returned row has "forecasts" normalized to a list of dicts (see
    module docstring) — callers never need to guard against a string or None
    payload themselves.
    """
    paths = ([runlog] if runlog.exists() else []) + sorted(runs_dir.glob("*.jsonl"))
    rows = []
    for p in paths:
        with open(p) as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                if is_superseded(row):     # redlines.superseded: replaced the same day
                    continue
                row["forecasts"] = _clean_forecasts(row.get("forecasts"))
                rows.append(row)
    return panel_rows(rows) if panel_only else rows


def panel_rows(rows):
    """ONLY panel rows -- every model that has held a panel seat, on every
    day it held one.

    Since 2026-08-28 every row the runner writes is stamped with the model set
    it ran (`panel`: the ECI top-k, chosen from the newest snapshot -- see
    redlines.registry). Rows before that carry no stamp: the hand-picked
    frontier five, whose history (2026-08-18 .. 08-28 morning) stays in
    results/runs/ and in git and is not drawn (project lead, 2026-08-28: only
    the canonical top-k model set is shown, not the old models or their
    forecasts). A model that leaves the panel does NOT take its
    rows with it (project lead, 2026-09-08: preserve those points, colored
    gray to mark them legacy): its stamped rows stay in the log, the Timeline
    draws them in the retired gray, and the latest-reading views take the
    current panel's rows through current_rows(). A log with no stamped row
    at all (a fresh clone before the first panel run, a synthetic test log)
    is returned as it is.
    """
    stamped = [r for r in rows if r.get("panel")]
    return stamped if stamped else rows


def current_panel(rows):
    """The labels that answered on the NEWEST stamped day: the panel of
    record. Every label when nothing is stamped."""
    stamped = [r for r in rows if r.get("panel")]
    if not stamped:
        return {r["label"] for r in rows}
    newest = max(elicitation_date(r) for r in stamped)
    return {r["label"] for r in stamped if elicitation_date(r) == newest}


def current_rows(rows):
    """Only the current panel's rows -- what a latest-reading view (Graph 1,
    the data bank, the ladder) draws, so a model that left the panel is not
    shown beside the panel at a reading from an earlier run. The Timeline
    keeps every row and grays the departed."""
    current = current_panel(rows)
    return [r for r in rows if r["label"] in current]


def latest_per(rows):
    """{(question_id, model_label): row} — each pair's most recently elicited row.

    Canonical version ported from code/make_demo_graph2.py::latest_rows
    (shared, in substance, by graph1's inline "latest" dict and
    the timeline view's by-day dedup).
    """
    out = {}
    for r in sorted(rows, key=lambda r: r["elicited_at"]):
        out[(r["question_id"], r["label"])] = r
    return out


def answered_horizons(rows):
    """{question_id: {horizon, ...}} -- the horizons these rows actually carry.

    A question can gain a horizon in the SPEC before any run has been made over
    it. That happened on 2026-08-28, when the three cross-cutting questions
    moved onto the ladder's six-horizon grid: the spec says 6mo/12mo/2028 and
    the run log will not until the next weekly run. A view that plotted the
    spec's list would draw three empty slots on those panels, which a reader
    reads as "the models would not say", not as "not asked yet".

    So the views take their axis from here, intersected with the spec. The new
    columns appear on their own the first run that answers them, and no page
    needs a date typed into it.
    """
    out = {}
    for r in rows:
        for f in r.get("forecasts") or []:
            out.setdefault(r["question_id"], set()).add(f["horizon"])
    return out


def replicate_order(row):
    """Sort key that puts one day's draws for a (question, model) in a stable
    order: by arm name (unconditional#1, #2, #3 -- see code/run_unified.py
    --unconditional), then elicitation time. Rows from before replication
    carry arm=None and sort first, which for a single draw is the only order
    there is."""
    return (row.get("arm") or "", row["elicited_at"], row.get("call_id") or "")


def pool(reps):
    """[rows for ONE (question, model) on ONE date] -> one synthetic row.

    WHY. From 2026-08-28 the weekly run asks each model THREE times in one
    sitting (code/cron_run.sh, --unconditional 3), because the movement the
    Timeline drew between weeks was indistinguishable from the movement
    between two calls made minutes apart: on 2026-08-27, three same-day calls
    per model differed by a median 0.6pp, p90 10pp, max 74pp across 3,015
    cells, and the Aug 18 -> Aug 21 shift was median 0.8pp, p90 10pp. A
    single draw is one sample from that distribution; the panels should show
    the distribution's centre and width, not the sample.

    WHAT. `forecasts` becomes the per-horizon MEAN over the draws that
    answered that horizon, so every view that reads row["forecasts"] gets the
    centre with no other change; `draws` keeps every raw value ({horizon:
    [p, ...]} in replicate_order) so nothing is hidden; `replicates` is the
    number of calls that day and `answered` how many returned a grid.
    Everything else -- rationale, evidence, call_id -- is copied from the
    LAST draw: those fields belong to a call, and a pooled row has no single
    call. A pooled row with one draw is that draw, exactly (the mean of one
    value is the value; no rounding is applied here).
    """
    reps = sorted(reps, key=replicate_order)
    draws = defaultdict(list)
    answered = 0
    for r in reps:
        if r["forecasts"]:
            answered += 1
        for f in r["forecasts"]:
            draws[f["horizon"]].append(f["probability"])
    out = dict(reps[-1])
    out["forecasts"] = [
        {"horizon": h, "probability": ps[0] if len(ps) == 1 else statistics.mean(ps)}
        for h, ps in sorted(draws.items())]
    out["draws"] = dict(draws)
    out["replicates"] = len(reps)
    out["answered"] = answered
    return out


def latest_pooled(rows):
    """{(question_id, model_label): pooled row} -- every draw from each pair's
    most recent elicitation DATE, pooled by pool().

    The unit is the calendar date, not run_id, to match rows_by_day() and the
    Timeline's doctrine that a day's calls are one "as of" reading. On a log
    with one draw per pair per day this is latest_per() with three extra
    fields; it only differs once a day holds replicates, where latest_per()
    would silently hand back whichever call finished last.

    Which models are here at all is load_runlog()'s business (panel_rows):
    by the time rows reach this function they are the canonical panel's.
    """
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r["question_id"], r["label"])].append(r)
    out = {}
    for key, rs in by_key.items():
        day = max(elicitation_date(r) for r in rs)
        out[key] = pool([r for r in rs if elicitation_date(r) == day])
    return out


def rows_by_day(rows):
    """Partition rows by elicited_at calendar date (UTC ISO date, e.g. "2026-08-10"),
    each day's rows kept in elicited_at order.

    From the timeline view's snapshot construction (ported 2026-08-13). Combine
    with latest_per() on a day's rows to reproduce the timeline's `by_day`
    (one row per (question, model) per day):

        for day, day_rows in rows_by_day(rows).items():
            latest_that_day = latest_per(day_rows)  # {(qid, label): row}
    """
    out = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["elicited_at"]):
        out[elicitation_date(r)].append(r)
    return dict(out)
