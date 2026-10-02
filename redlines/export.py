"""The dataset behind the dashboard, as one CSV: every forecast from every
model in every run, unconditional and conditional alike.

One line per (call, question, horizon, condition). Unconditional rows come
from the published run log (redlines.runlog.load_runlog: results/runs/ plus
the legacy file), so the CSV's unconditional series is exactly the one the
panels draw; conditional rows come from the published instrument logs --
results/conditional_runs_combined.jsonl (the combined instrument, the
published set since 2026-08-28) and results/conditional_runs.jsonl (the
policy instrument before it) -- taking only the rows that carry a condition
(their unconditional siblings are already in the run log -- see
code/run_unified.py --joint, which writes each joint call to both), and only
the canonical panel's (redlines.runlog.panel_rows: the same rule the run log
applies, so the download shows exactly what the dashboard shows and nothing
of the models it replaced).

Two protocols appear, told apart by the `protocol` column: unified-joint-v1
(the single instrument, the published series since 2026-08-27) and its
predecessors (unified-batch-v2 unconditional runs; the 2026-08-27 separate-
call pilot for conditionals, experiment leap-wave12-pilot). They are not to
be pooled -- the joint unconditional runs about 2x lower than the same-day
separate call (docs/conditional-forecasts.md) -- which is why the column is
there.

Project lead, 2026-08-27: a big "download forecasts" button, all forecasts
from all models over all time. Built by `python3 -m redlines build --views csv`,
published beside index.html by code/publish_dashboard.sh.

A SECOND FILE, results/rationales.csv (2026-09-08; project lead: all
forecasts and rationales, including those from legacy models, must be
available): one line per (call, question, condition) -- the model's written
rationale for that question in that call, and the sources it cited -- from
the same rows as the forecasts file, joined on `call_id` + `question_id` +
`condition`. Separate because a rationale is per question per call while
the forecasts file is per horizon: repeating a 2,000-character rationale
on every horizon line would multiply the download several times over.

EVERYTHING (2026-09-08; project lead: include everything, even if it
requires a .zip). Both CSVs now carry every row the logs hold -- every
model that ever ran, panel or not, every instrument, every pilot -- with
`panel_set`/`panel_snapshot` columns so the dashboard's own view (panel
rows only) is one filter away, and `protocol`/`experiment` to tell the
elicitations apart. And results/redlines-data.zip (bundle_zip) wraps the
two CSVs with the raw JSONL logs verbatim (every search and page read the
models made), the retired per-question archive, the question set, the
condition sets, the ECI snapshots, and a README naming each. The Download
button serves the zip; the CSVs sit beside it for a quick look.
"""
import csv
import json
from pathlib import Path
from functools import lru_cache

from .conditional import CONDITIONAL_LOG
from .logs import iter_rows, log_exists, log_files, log_names
from .questions import all_questions
from .runlog import RUNLOG, RUNS_DIR
from .runlog import load_runlog, panel_rows
from .instrument import CURRENT_INSTRUMENT

from .config import REPO_ROOT
from .superseded import superseded_note

# Anchored to the repo root: `python3 -m redlines build --views csv` from any
# working directory writes beside the other results/ mirrors.
OUT = REPO_ROOT / "results" / "forecasts.csv"
RATIONALES_OUT = REPO_ROOT / "results" / "rationales.csv"
# The debriefs (2026-09-15): one line per (call, question group) -- what the
# model said drove its numbers, asked after submission (code/run_unified.py
# debrief_tool). JSON in the two list columns.
DEBRIEFS_OUT = REPO_ROOT / "results" / "debriefs.csv"
# Per QUESTION since 2026-09-16 (key = question_id, group derived); the
# 2026-09-15 and 2026-09-16 12:00 UTC calls were per GROUP (key = group,
# question_id empty) and keep their pathway/base_rate/compelling_arguments.
DEBRIEF_COLUMNS = ["elicited_at", "run_id", "protocol", "experiment", "model", "model_id",
                   "run_date", "condition_set", "call_id", "key", "group", "question_id",
                   "rationale", "key_sources", "weakest_link",
                   "compelling_arguments", "pathway", "base_rate", "complete", "problems",
                   "panel_set", "panel_snapshot"]
BUNDLE_OUT = REPO_ROOT / "results" / "redlines-data.zip"

COLUMNS = ["elicited_at", "run_id", "protocol", "experiment", "model", "model_id",
           "question_id", "question", "horizon", "resolves_on",
           "instrument_version", "instrument_version_source", "run_date", "onset_start", "onset_end", "onset_timezone", "harm_years", "prompt_sha256",
           "condition", "condition_label", "condition_source",
           "probability", "arm", "call_id", "grounded", "panel_set", "panel_snapshot"]


def _panel(row):
    p = row.get("panel") or {}
    return p.get("set", ""), p.get("snapshot", "")


def _resolves_on(row, h):
    r = row.get("resolves_on")
    if isinstance(r, dict):
        return r.get(h, "")
    return r or ""


def _instrument_version(row):
    if row.get("instrument_version"):
        return row["instrument_version"]
    # The published v4 joint instrument used the archived August 31 text.
    # Do not apply this mapping to earlier protocols or unrecorded variants.
    if row.get("protocol") == "unified-joint-combined-v4":
        return "legacy-2026-08-31"
    return "legacy-unversioned"


def _version_source(row):
    if row.get("instrument_version"):
        return "recorded"
    return "protocol-mapped" if _instrument_version(row) == "legacy-2026-08-31" else "unknown"


@lru_cache(maxsize=1)
def _legacy_questions():
    root = Path(__file__).resolve().parents[1] / "data/instruments/legacy-2026-08-31"
    out = {}
    for name in ("autoarc_ladder.json", "autoarc_crosscutting.json"):
        path = root / name
        if path.exists():
            out.update({q["id"]: q for q in json.loads(path.read_text())["questions"]})
    return out


def _question_text(row, questions):
    # Never attach today's rewritten question to an unstamped old answer.
    # Legacy raw logs lack exact question text; preserve that uncertainty.
    if row.get("question_text"):
        return row["question_text"]
    if row.get("instrument_version") == CURRENT_INSTRUMENT:
        return questions.get(row["question_id"], {}).get("text", "")
    if _instrument_version(row) == "legacy-2026-08-31":
        return _legacy_questions().get(row["question_id"], {}).get("text", "")
    return ""


def _lines(rows, qs):
    for r in rows:
        cond = r.get("condition") or {}
        q = qs.get(r["question_id"], {})
        for f in r.get("forecasts") or []:
            window = (r.get("counting_window") or {}).get(f["horizon"], {})
            yield {
                "elicited_at": r.get("elicited_at", ""),
                "run_id": r.get("run_id", ""),
                "protocol": r.get("protocol", ""),
                "experiment": r.get("experiment") or "",
                "model": r.get("label", ""),
                "model_id": r.get("model", ""),
                "question_id": r["question_id"],
                "question": _question_text(r, qs),
                "instrument_version": _instrument_version(r),
                "instrument_version_source": _version_source(r),
                "run_date": r.get("run_date", ""),
                "onset_start": window.get("start", ""),
                "onset_end": window.get("end", ""),
                "onset_timezone": window.get("timezone", ""),
                "harm_years": window.get("harm_years", ""),
                "prompt_sha256": r.get("prompt_sha256", ""),
                "horizon": f["horizon"],
                "resolves_on": _resolves_on(r, f["horizon"]),
                "condition": cond.get("id", ""),
                "condition_label": cond.get("label", ""),
                "condition_source": cond.get("source", ""),
                "probability": f["probability"],
                "arm": r.get("arm") or "",
                "call_id": r.get("call_id") or "",
                "grounded": "" if r.get("grounded") is None else int(bool(r.get("grounded"))),
                "panel_set": _panel(r)[0], "panel_snapshot": _panel(r)[1],
            }


COMBINED_LOG = CONDITIONAL_LOG.parent / "conditional_runs_combined.jsonl"

RATIONALE_COLUMNS = ["elicited_at", "run_id", "protocol", "experiment", "model", "model_id",
                     "instrument_version", "instrument_version_source", "run_date", "counting_window", "prompt_sha256",
                     "question_id", "question", "condition", "condition_label", "arm",
                     "call_id", "grounded", "search_hits", "rationale", "sources",
                     "panel_set", "panel_snapshot"]


def _rationale_lines(rows, qs):
    for r in rows:
        cond = r.get("condition") or {}
        q = qs.get(r["question_id"], {})
        yield {
            "elicited_at": r.get("elicited_at", ""),
            "run_id": r.get("run_id", ""),
            "protocol": r.get("protocol", ""),
            "experiment": r.get("experiment") or "",
            "model": r.get("label", ""),
            "model_id": r.get("model", ""),
            "question_id": r["question_id"],
            "question": _question_text(r, qs),
            "instrument_version": _instrument_version(r),
            "instrument_version_source": _version_source(r),
            "run_date": r.get("run_date", ""),
            "counting_window": json.dumps(r["counting_window"], sort_keys=True) if r.get("counting_window") else "",
            "prompt_sha256": r.get("prompt_sha256", ""),
            "condition": cond.get("id", ""),
            "condition_label": cond.get("label", ""),
            "arm": r.get("arm") or "",
            "call_id": r.get("call_id") or "",
            "grounded": "" if r.get("grounded") is None else int(bool(r.get("grounded"))),
            "search_hits": r.get("search_hits") if r.get("search_hits") is not None else "",
            "rationale": r.get("rationale") or "",
            "sources": " | ".join(s for s in (r.get("key_sources") or []) if isinstance(s, str)),
            "panel_set": _panel(r)[0], "panel_snapshot": _panel(r)[1],
        }


def _debrief_group(key):
    """The question group a debrief entry belongs to: a ladder id's cause, a
    cross-cutting id's group, or the key itself when it already is a group."""
    if key.startswith("ladder:"):
        parts = key.split(":")
        return parts[1] if len(parts) > 2 else key
    if ":" in key or key in ("disempowerment",):
        return "crosscutting"
    return key


def _debrief_lines(rows):
    """One line per (call, entry) from the rows that carry a debrief (the
    call's first row); a call without one contributes nothing. An entry is a
    question (since 2026-09-16) or a group (the two earlier calls)."""
    seen = set()
    for r in rows:
        d = r.get("debrief")
        if not isinstance(d, dict) or r.get("call_id") in seen:
            continue
        seen.add(r.get("call_id"))
        st = r.get("debrief_status") or {}
        for key, g in d.items():
            if not isinstance(g, dict):
                continue
            is_question = ":" in key or key == "disempowerment"
            yield {
                "elicited_at": r.get("elicited_at", ""), "run_id": r.get("run_id", ""),
                "protocol": r.get("protocol", ""), "experiment": r.get("experiment") or "",
                "model": r.get("label", ""), "model_id": r.get("model", ""),
                "run_date": r.get("run_date", ""), "condition_set": r.get("condition_set") or "",
                "call_id": r.get("call_id") or "", "key": key, "group": _debrief_group(key),
                "question_id": key if is_question else "",
                "rationale": g.get("rationale") or "",
                "key_sources": json.dumps(g.get("key_sources") or [], ensure_ascii=False),
                "weakest_link": g.get("weakest_link") or "",
                "compelling_arguments": json.dumps(g.get("compelling_arguments") or [], ensure_ascii=False),
                "pathway": g.get("pathway") or "", "base_rate": g.get("base_rate") or "",
                "complete": "" if st.get("complete") is None else int(bool(st.get("complete"))),
                "problems": " | ".join(st.get("problems") or []),
                "panel_set": _panel(r)[0], "panel_snapshot": _panel(r)[1],
            }


RESULTS = CONDITIONAL_LOG.parent


def conditional_logs():
    """Every instrument log: results/conditional_runs*.jsonl, the LEAP policy
    instrument and the combined one first, then the rest by name."""
    first = [COMBINED_LOG, CONDITIONAL_LOG]
    rest = [p for p in log_names(RESULTS) if p not in first]
    return [p for p in first if log_exists(p)] + rest


def _published_rows(conditional_log=CONDITIONAL_LOG, combined_log=COMBINED_LOG):
    """The rows both CSVs are built from: EVERY row of the run log (every
    model that ever ran, stamped or not) plus the conditional rows of every
    instrument log. Nothing is filtered here; the panel_set column lets a
    reader apply the dashboard's own rule (panel rows only)."""
    rows = list(load_runlog(panel_only=False))
    logs = [Path(combined_log), Path(conditional_log)]
    logs += [p for p in conditional_logs() if p not in logs]
    for p in logs:
        for r in iter_rows(p):
            if r.get("condition"):
                r["forecasts"] = r.get("forecasts") or []
                rows.append(r)
    return rows


def rationales_csv(out=RATIONALES_OUT, conditional_log=CONDITIONAL_LOG, combined_log=COMBINED_LOG):
    """Write the rationales CSV; return the number of data lines."""
    qs = all_questions()
    lines = sorted(_rationale_lines(_published_rows(conditional_log, combined_log), qs),
                   key=lambda d: (d["elicited_at"], d["model"], d["question_id"],
                                  d["condition"], d["arm"], d["call_id"]))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RATIONALE_COLUMNS)
        w.writeheader()
        w.writerows(lines)
    return len(lines)


def debriefs_csv(out=DEBRIEFS_OUT, conditional_log=CONDITIONAL_LOG, combined_log=COMBINED_LOG):
    """Write the debriefs CSV; return the number of data lines."""
    lines = sorted(_debrief_lines(_published_rows(conditional_log, combined_log)),
                   key=lambda d: (d["elicited_at"], d["model"], d["call_id"], d["group"]))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DEBRIEF_COLUMNS)
        w.writeheader()
        w.writerows(lines)
    return len(lines)


def forecasts_csv(out=OUT, conditional_log=CONDITIONAL_LOG, combined_log=COMBINED_LOG):
    """Write the CSV; return the number of data lines."""
    qs = all_questions()
    lines = sorted(_lines(_published_rows(conditional_log, combined_log), qs),
                   key=lambda d: (d["elicited_at"], d["model"], d["question_id"],
                                  d["horizon"], d["condition"], d["arm"], d["call_id"]))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(lines)
    return len(lines)


# ── the bundle: everything ───────────────────────────────────────────────────
LEGACY_DIR = RESULTS.parent / "archive" / "legacy-forecasts"
DATA_DIR = RESULTS.parent / "data"

BUNDLE_README = """# Redlines data bundle

Every forecast this project has elicited, with the models' rationales and the
raw logs behind them. Built by `python3 -m redlines build --views csv`
(redlines/export.py) at {built}.

## The two CSVs

forecasts.csv -- one line per (call, question, horizon, condition):
  {forecast_columns}

rationales.csv -- one line per (call, question, condition): the model's written
rationale for that question in that call, and the sources it named. Join to
forecasts.csv on call_id + question_id + condition.
  {rationale_columns}

debriefs.csv -- one line per (call, question), from 2026-09-16: what the model
said drove its numbers for that question, asked after its forecasts were
accepted (so it could not move them): a short rationale naming the mechanism
at that severity and the anchor used (rationale), the sources that mattered
most and what each contributed (key_sources, JSON), and the assumption it is
least sure of (weakest_link). key = question_id; group is derived from it.
The two calls of 2026-09-15/16 asked per question GROUP instead: key = group,
question_id empty, and their answers sit in compelling_arguments (JSON),
pathway and base_rate. Join to the other files on call_id (and question_id).
Earlier calls have no line.
  {debrief_columns}

Superseded runs (redlines/superseded.py): these rows are IN these files and
in the raw run files, but every dashboard view skips them, because the same
day re-asked the same models and the later draw replaces the earlier one.
Filter on run_id (and model) to see what the dashboard shows:
{superseded}

Columns worth knowing:
- instrument_version: the question-definition version actually recorded on
  the row, or a documented protocol mapping. instrument_version_source
  distinguishes recorded, protocol-mapped and unknown. The published
  unified-joint-combined-v4 protocol maps to legacy-2026-08-31 and uses its
  archived question text. No other unstamped protocol receives that mapping.
  legacy-unversioned means no version was established; it does not
  imply that the row answered today's definitions. Current dashboard series
  include only airo-incidents-prospective-v1 and start anew at this change.
- question: the recorded question text, or the version-matched current
  specification. Blank on legacy rows whose exact wording was not recorded;
  archived definitions are supplied separately and must not be assumed to
  apply to every earlier run.
- run_date / onset_start / onset_end / onset_timezone / harm_years: the
  incident window actually sent, with inclusive UTC calendar dates. Only
  incidents beginning in that interval count; each contributes its first
  three years of harm, even beyond the onset deadline. Empty on older rows
  and on non-incident questions. Fixed-year windows advance with each run.
- prompt_sha256: identifies the exact joint prompt; its text is retained in
  raw JSONL on the first unconditional row of each new-version call.
- protocol: the elicitation. unified-joint-combined-v* is the single
  instrument (every question x horizon cell, unconditional and under every
  condition, in one call per model); unified-batch-v* the earlier plain
  batch; the pilots carry their own tags. Do not pool across protocols:
  the joint unconditional runs about 2x lower than the same-day separate
  call (docs/conditional-forecasts.md in the repo).
- panel_set / panel_snapshot: which model set the row's run asked, and the
  ECI snapshot that chose it. Empty = the hand-picked frontier five, before
  the panel existed (2026-08-28). The dashboard draws panel rows only
  (panel_set non-empty), narrowed to the current instrument version. The
  earlier series remains in this download and is not joined to the new one.
- experiment: non-empty on pilots and smokes -- not the published series.
- arm: which repeat of the call (joint#1, unconditional#2, ...).
- grounded: 1 if the call had web search; every published run does.

## raw/ -- the logs, verbatim (JSON lines)

raw/runs/*.jsonl              one file per scheduled run: the unconditional
                              slice of each call, one row per (call, question),
                              with the full tool transcript (every search
                              and page read) under `evidence`
raw/forecast_runs_unified.jsonl  the same series before 2026-08-21, one file
raw/conditional_runs*/*.jsonl the whole instruments, one file per run: every (call, question,
                              condition) row, same shape
raw/*_runs/*.jsonl            the capability-condition pilots' own logs
raw/experiments/              pilots and smokes -- NOT the published series
raw/legacy-forecasts/         the retired per-question protocol
                              (before 2026-08-14); see its README

## questions/ and conditions/

questions/autoarc_ladder.json and autoarc_crosscutting.json are the question
set (Bridget Williams, FRI); conditions/*.json the condition sets each
instrument asked under; conditions/epoch_capabilities_index_*.csv the ECI
snapshots the panel was chosen from.

questions/instruments/ retains archived generated questions and source
definitions. legacy-2026-08-31 is an archived specification, not a claim that
every unstamped older response used that wording. questions/sources/ contains
the dated source definitions, including earlier revisions.
"""


def _bundle_members():
    """[(archive name, path)] for every file the bundle carries."""
    out = []
    for p in sorted(RUNS_DIR.glob("*.jsonl")):
        out.append((f"raw/runs/{p.name}", p))
    if RUNLOG.exists():
        out.append((f"raw/{RUNLOG.name}", RUNLOG))
    for p in conditional_logs():
        for f in log_files(p):
            out.append((f"raw/{f.relative_to(RESULTS)}", f))
    for d in sorted(RESULTS.glob("*_runs")):
        if d.is_dir():
            for p in sorted(d.glob("*.jsonl")):
                out.append((f"raw/{d.name}/{p.name}", p))
    exp = RESULTS / "experiments"
    if exp.is_dir():
        for p in sorted(exp.rglob("*")):
            if p.is_file():
                out.append((f"raw/experiments/{p.relative_to(exp)}", p))
    if LEGACY_DIR.is_dir():
        for p in sorted(LEGACY_DIR.rglob("*")):
            if p.is_file():
                out.append((f"raw/legacy-forecasts/{p.relative_to(LEGACY_DIR)}", p))
    for name in ("autoarc_ladder.json", "autoarc_crosscutting.json", "leap_policies.json"):
        p = DATA_DIR / name
        if p.exists():
            out.append((f"questions/{name}", p))
    for p in sorted((DATA_DIR / "instruments").rglob("*")):
        if p.is_file():
            out.append((f"questions/instruments/{p.relative_to(DATA_DIR / 'instruments')}", p))
    for p in sorted((DATA_DIR / "auto-arc").glob("definitions-*.md")) + \
            sorted((DATA_DIR / "auto-arc").glob("addendum-*.json")):
        out.append((f"questions/sources/{p.name}", p))
    for p in sorted(DATA_DIR.glob("*_conditions.json")) + sorted(DATA_DIR.glob("epoch_capabilities_index_*.csv")):
        out.append((f"conditions/{p.name}", p))
    return out


def bundle_zip(out=BUNDLE_OUT, forecasts=OUT, rationales=RATIONALES_OUT, debriefs=DEBRIEFS_OUT):
    """Write the zip: the CSVs (already written), the raw logs, the
    questions and conditions, and the README. Returns the member count."""
    import zipfile
    from datetime import datetime, timezone
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    members = _bundle_members()
    readme = BUNDLE_README.format(
        built=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
        forecast_columns=", ".join(COLUMNS), rationale_columns=", ".join(RATIONALE_COLUMNS),
        debrief_columns=", ".join(DEBRIEF_COLUMNS),
        superseded=superseded_note())
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("README.md", readme)
        z.write(forecasts, "forecasts.csv")
        z.write(rationales, "rationales.csv")
        if Path(debriefs).exists():
            z.write(debriefs, "debriefs.csv")
        for name, p in members:
            z.write(p, name)
    # The README, the two CSVs, the debriefs CSV when there is one, the members.
    return 3 + int(Path(debriefs).exists()) + len(members)
