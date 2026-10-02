#!/usr/bin/env python3
"""Generate the question sets from the Auto-ARC source files. THE source of truth.

Project lead, 2026-08-17: the data source that hydrates all of the language on
the dashboard must be the same one that hydrates what the superforecasters were
asked and what the models are asked, so the two can never come apart.

This script is what makes that true. Everything downstream — the model prompt,
the graph titles, the axis labels, the modal, the data bank, the coherence
relations — reads the JSON this writes, and this reads only the two source files
under data/auto-arc/. Nothing is hand-typed twice.

WHY THAT MATTERS, CONCRETELY. Before this existed the dashboard's headline read
"Catastrophic = >= 10 million deaths (or >= $1T economic damage)", typed into
web/demo/80-app.jsx, while the question it labelled asked about 10% of humans
alive — about 820 million. Off by a factor of eighty, in the headline, for as
long as anyone had looked. It was caught on the call, by eye. Prose that is not
generated from the question data will drift from it; the only fix that holds is
to stop writing it by hand.

    python3 code/make_autoarc_questions.py            # write both files
    python3 code/make_autoarc_questions.py --check    # verify, write nothing

--check is what tests/test_autoarc_generator.py runs: regenerate in memory and
compare byte-for-byte against what is tracked. A hand edit to either JSON file
fails the build, which is the property "no way for them to become disentangled"
expressed as something a machine can enforce.

INPUTS (vendored, so a rebuild needs no network and no path outside the repo)
  data/auto-arc/questions-<date>.xlsx     composition: which question x severity
                                          x horizon cells exist. Sheet
                                          "Auto-ARC questions - long" is the
                                          authority; the summary sheet is a
                                          human-readable digest of it.
  data/auto-arc/definitions-<date>.md     the definitions and resolution
                                          criteria, parsed by section heading.
                                          the author's prose is used verbatim —
                                          never re-typed here — so a wording
                                          change lands by replacing the file.

OUTPUTS
  data/autoarc_crosscutting.json   general catastrophe, AI catastrophe, human
                                   disempowerment. Severity does not vary; only
                                   dates do (project lead, 2026-08-18). So these are
                                   three questions, not a ladder.
  data/autoarc_ladder.json         the 4 x 8 incident grid, plus causes, rungs,
                                   the coherence relations, and the ids Graph 1
                                   features.

Needs openpyxl (the only non-stdlib import in the build path, which is why this
lives in code/ and not in the stdlib-only redlines/ package).
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "data", "auto-arc")
XLSX = os.path.join(SRC, "questions-2026-08-31.xlsx")
DEFS = os.path.join(SRC, "definitions-2026-09-10.md")
# ADDENDA: questions added to the set AFTER her workbook, each in its own dated
# file beside her two (data/auto-arc/addendum-<topic>-<date>.json). The first
# is the extinction pair the project team asked for on 2026-09-15. An addendum is
# an INPUT of the same standing as the workbook -- generated from, never typed
# into the output -- and it says in its own provenance block who asked for it,
# whose wording it carries and whose review it is pending. It is not a way to
# edit her questions: it may only ADD cross-cutting questions, relations and
# prior-work rows, and every question it adds carries `since`, the date it
# entered the set, so a run made before that date is still a complete one.
ADDENDA = sorted(glob.glob(os.path.join(SRC, "addendum-*.json")))
sys.path.insert(0, ROOT)
from redlines.instrument import CURRENT_INSTRUMENT
OUT_CROSS = os.path.join(ROOT, "data", "autoarc_crosscutting.json")
OUT_LADDER = os.path.join(ROOT, "data", "autoarc_ladder.json")

SHEET = "Auto-ARC questions - long"
# The workbook's third sheet: the prior FRI panels whose numbers its "Human
# comparisons (Project)" column points at. It is read, not summarised — the
# comparison question's own wording is what tells anyone whether a human median
# transfers to ours, so it travels with the mapping instead of living in a note.
PRIOR_SHEET = "Questions from prior FRI work"

# World population, used ONLY to place the 10%-of-population questions on the
# same log-death axis as the incident rungs. It is not a threshold: those
# questions resolve on a share, so the number floats with population and the
# rungs do not. Kept here rather than in a view because it is a property of the
# question set, and graph2.py should not be the place that decides it.
WORLD_POP = 8.2e9

# ── the four incident causes ─────────────────────────────────────────────────
# Colors are the four values already validated for this dashboard (CVD +
# separation + chroma/lightness, dataviz six-checks). They are REASSIGNED, not
# rechosen: nuclear leaves the set and "AI-related incident" inherits the slate
# that "All causes" used to carry, because it now plays that containing role.
# The set's own definition licenses that: an AI-related incident "could be an
# AI-related human-caused epidemic, an AI-related cyber incident, a misaligned
# AI incident, or a different type of AI-related incident."
CAUSES = [
    # `sheet` is the workbook's Category value; `def_key` is the bullet heading
    # its definition sits under in the definitions markdown. Both are lookup keys
    # into the source files, so neither is ours to rename.
    {"key": "ai",       "color": "#3a4150", "sheet": "AI-related incident",
     "def_key": "AI-related incident", "container": True},
    {"key": "bio",      "color": "#a63d76", "sheet": "Biorisk",
     "def_key": "AI-related human-caused epidemic"},
    {"key": "cyber",    "color": "#a1801a", "sheet": "Cyber",
     "def_key": "AI-related cyber incident"},
    {"key": "misalign", "color": "#33a8bd", "sheet": "Misalignment",
     "def_key": "Misaligned AI incident"},
]

# NOTE what is NOT in CAUSES above: the label, and the phrase that goes into
# her question template. Both were hand-written here and both were mine, not
# hers — "AI-enabled epidemic" against her "AI-related human-caused epidemic".
# Writing our own names for her questions is the same failure as writing our own
# thresholds for them, one layer up, so both are now read from her "Incident
# options" list by cause_label() / incident_phrase() below.
#
# What remains is a join key and a display colour. `sheet` is her workbook's
# Category value and `def_key` is her markdown's bullet heading: neither is
# content, and neither can be derived, because "Biorisk" and "AI-related
# human-caused epidemic" share no text. crosscheck() fails the build if either
# stops resolving.

# ── rolling near-term horizons ───────────────────────────────────────────────
# The paper's lead author, 2026-08-17: the set also needs near-term horizons --
# the next year, the next six months -- because part of the idea is a dashboard
# that shows when the very near-term risk is suddenly elevated.
#
# ROLLING (project lead, 2026-08-18): the window moves with the run date, because
# the level is the signal and a fixed date decays toward certainty as it nears.
# Each run stamps an ABSOLUTE resolves_on so a rolling forecast can still be
# found and scored later — that is the whole reason these are worth asking. They
# are the only cells in the set that resolve inside the paper's life.
#
# Applied to the WHOLE set since 2026-08-28 (project lead: re-elicit the
# cross-cutting ones at shorter durations for consistency). Until then the three
# were asked at 2030/2050/2100 only, on the reasoning that P(10% of humanity dies
# within six months) is noise and the near-term signal lives on the incident ladder.
# That kept Graph 1's two rail groups on different x-axes: four expected-loss
# rows spanning 6mo..2100 beside three catastrophe panels starting at 2030, which
# cannot be read against each other at the near end. Expect the near-term
# cross-cutting points to be round-number floors; they are a tripwire (does the
# level MOVE?), not a level worth reading on its own.
ROLLING = [
    {"id": "6mo",  "months": 6,  "label": "within 6 months"},
    {"id": "12mo", "months": 12, "label": "within 12 months"},
]


def unescape(md):
    r"""Drop markdown's backslash escapes. The source file writes \[2030\]; the
    brackets are the author's, the backslashes are the editor's."""
    return re.sub(r"\\([\[\]*_`])", r"\1", md).strip()


def read_definitions(path=DEFS):
    """-> {top-level section: {"body": prose, "blocks": {sub-heading: prose}}}

    The parse has to nest. The file uses "**Question details**" FOUR times, once
    under each question's own heading, so a flat {heading: prose} map silently
    concatenates all four and hands every question the union of everybody's
    criteria — which is how the first version of this function gave the
    disempowerment question the epidemic severity rules.

    Parsing rather than transcribing is the point: a definition typed into this
    file would be exactly the second copy the SSOT exists to prevent.
    """
    text = open(path, encoding="utf-8").read()
    parts = re.split(r"^(#{1,3} .+|\*\*[A-Z][^*]+\*\*)\s*$", text, flags=re.M)
    out, section = {}, None
    i = 1
    while i < len(parts) - 1:
        head, body = parts[i].strip(), parts[i + 1]
        if head.startswith("#"):
            section = head.lstrip("#").strip()
            out.setdefault(section, {"body": "", "blocks": {}})
            out[section]["body"] = unescape(body)
        elif section:
            out[section]["blocks"][head.strip("*").strip()] = unescape(body)
        i += 2
    return out


def bullet_split(block):
    """A markdown bullet list -> {first line of each top-level bullet: its subtree}.

    Used to hand each cause only its own incident definition, instead of all
    four. Top-level bullets start at column zero; everything indented under one
    belongs to it.
    """
    out, key, buf = {}, None, []
    for line in block.splitlines():
        if re.match(r"^\*\s+\S", line):
            if key:
                out[key] = "\n".join(buf).strip()
            key = re.sub(r"^\*\s+", "", line).strip().rstrip(":")
            buf = []
        elif key:
            buf.append(line)
    if key:
        out[key] = "\n".join(buf).strip()
    return out


def incident_options(defs):
    """Her four incident names, verbatim, from the "Incident options" list."""
    return [l.strip().lstrip("*").strip()
            for l in defs["Incident options"]["body"].splitlines()
            if l.strip().startswith("*")]


def cause_label(defs, cause):
    """The cause's display name = her name for it."""
    for name in incident_options(defs):
        if name == cause["def_key"]:
            return name
    raise SystemExit(f"{cause['def_key']!r} is not in the markdown's Incident "
                     f"options list: {incident_options(defs)}")


def incident_phrase(defs, cause):
    """Her name, pluralised, for "one or more [incident] cumulatively ..."."""
    return cause_label(defs, cause) + "s"


def read_rows(path=XLSX, sheet=SHEET):
    """-> the sheet's non-empty data rows as dicts, openpyxl only."""
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - environment, not logic
        sys.exit("openpyxl is required to read Bridget's workbook: pip install openpyxl")
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    keys = [str(c).strip() for c in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(c is not None and str(c).strip() for c in r):
            continue
        out.append({k: ("" if v is None else str(v).strip())
                    for k, v in zip(keys, r)})
    return out


def parse_year(raw):
    """'2030.0' -> '2030'. The sheet stores the horizon as a float."""
    return str(int(float(raw))) if raw else ""


# Severity strings in the sheet look like
#   "1,000 deaths (or equivalent morbidity) or $10 billion"
# Both legs are parsed to numbers so nothing downstream ever reads a threshold
# out of prose. The two legs sit at a constant ratio, which is exactly the
# value of a statistical life the criteria state (stated_vsl), so the ladder
# stays monotone whichever leg binds. $10M until the set's 2026-08-31 revision;
# $2.2M since, which moved every dollar leg ("100 deaths or $220 million").
_MAG = {"million": 1e6, "billion": 1e9, "trillion": 1e12, "quadrillion": 1e15}


def stated_vsl(defs):
    """The value of a statistical life the Severity definitions state, in USD.
    Parsed, never typed: it is the exchange rate between the two legs of every
    rung, and the axis, the expected-loss unit and the historical-events layer
    all read it from the ladder file this writes."""
    block = defs.get("Severity options", {}).get("blocks", {}).get("Severity definitions", "")
    m = re.search(r"value of a statistical life \(VSL\) of \$([\d.]+)\s*(million|billion)", block, re.I)
    if not m:
        raise SystemExit("the Severity definitions no longer state a VSL; the ladder's two legs have no exchange rate")
    return float(m.group(1)) * _MAG[m.group(2).lower()]


def parse_share(raw):
    """'10% of population' -> a structured population-share severity, or None.

    Parsed, not typed. The first version of this file hardcoded 0.10 and wrote
    its own label — which is precisely the defect this whole pipeline exists to
    remove, committed in the tool meant to prevent it. If the source moves the
    catastrophe threshold, the number has to move with it.
    """
    m = re.match(r"([\d.]+)\s*%\s*of\s*population", raw.strip(), re.I)
    if not m:
        return None
    share = float(m.group(1)) / 100
    return {"kind": "population_share", "share": share,
            "deaths_equiv": share * WORLD_POP,
            "label": f"deaths reaching {m.group(1)}% of the population",
            "short": raw.strip(), "source_text": raw.strip()}


def parse_severity(raw):
    """-> a structured severity dict, or None if the row carries no ladder rung."""
    m = re.match(r"([\d,]+)\s*(million|billion)?\s*deaths", raw, re.I)
    if not m:
        return None
    deaths = float(m.group(1).replace(",", ""))
    if m.group(2):
        deaths *= {"million": 1e6, "billion": 1e9}[m.group(2).lower()]
    money = None
    mm = re.search(r"\$([\d.]+)\s*(million|billion|trillion|quadrillion)", raw, re.I)
    if mm:
        money = float(mm.group(1)) * _MAG[mm.group(2).lower()]
    return {"kind": "deaths_or_damages", "deaths": deaths, "damages_usd": money,
            "label": f"{human_count(deaths)} deaths or {human_money(money)}",
            "short": human_count(deaths), "source_text": raw}


def human_count(n):
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            v = n / div
            return f"{v:g}{suf}"
    return f"{n:g}"


def human_money(n):
    if n is None:
        return "—"
    for div, suf in ((1e15, "Q"), (1e12, "T"), (1e9, "B"), (1e6, "M")):
        if n >= div:
            return f"${n / div:g}{suf}"
    return f"${n:g}"


def horizons_for(rows, predicate):
    """Fixed-year horizons present in `rows` matching `predicate`, sorted."""
    ys = sorted({parse_year(r["Date of question resolution"])
                 for r in rows if predicate(r)})
    return [y for y in ys if y]


def set_horizons(rows):
    """THE horizon grid, shared by every question in the set.

    The two rolling windows, then every fixed year the workbook's incident rows
    carry. One grid, computed once, because since 2026-08-28 the cross-cutting
    questions are asked over the same horizons as the ladder (see ROLLING) and
    two lists that must agree are two lists that can disagree.

    It is a SUPERSET of what the workbook asks of the cross-cutting rows, which
    stop at 2030/2050/2100. That is deliberate and it is ours: the extra cells
    are questions we ask the models, not cells the workbook specified. What stays
    keyed to its sheet is `human_wanted` and `human_comparisons` — a prior panel
    answered the horizons it answered, and no re-elicitation of ours adds one.
    """
    incident_rows = [r for r in rows
                     if r["Category"] in {c["sheet"] for c in CAUSES}
                     and r["Human comparisons (Project)"] != "P6 bio"]
    return [h["id"] for h in ROLLING] + horizons_for(incident_rows, lambda r: True)


# "XPT; LEAP" -> ["XPT", "LEAP"]. A dash or a blank means she checked and there
# is no prior panel for that cell, which is different from not having looked;
# both come back as no entry, and only the sheet decides which cells have one.
NO_COMPARISON = {"", "-", "none", "na", "n/a"}


def comparisons_for(rows, predicate):
    """-> {horizon: [project, ...]} from her "Human comparisons (Project)" column.

    This column is the ONLY thing that says which of our question x horizon
    cells a human panel has already answered, and which panel. We do not decide
    it and we do not infer it from wording similarity — she has read both
    question sets and we have read one. Anything we pull from LEAP or XPT is
    pulled BECAUSE a row here names it; a number with no row is a number nobody
    asked for (project lead, 2026-08-18, on the diamonds: nobody asked for them).

    Per horizon, not per question: the prior panels stop at different dates.
    LEAP asked the catastrophe pair at 2030/2050/2100 and the 50-deaths event
    only at 2050, so a per-question flag would claim three comparisons where
    the sheet grants one.
    """
    out = {}
    for r in rows:
        if not predicate(r):
            continue
        y = parse_year(r["Date of question resolution"])
        raw = (r.get("Human comparisons (Project)") or "").strip()
        if not y or raw.lower() in NO_COMPARISON:
            continue
        for name in (n.strip() for n in raw.split(";")):
            if name and name not in out.setdefault(y, []):
                out[y].append(name)
    return {y: out[y] for y in sorted(out)}


def split_comparison(token):
    """-> (project, prior-work id or None) for one entry in her column.

    Today her column names a PROJECT: "XPT; LEAP". That is enough to find the
    panel and not always enough to find the question — LEAP filed three
    different AI-catastrophe questions and the fetch script has to pick one, so
    it carries a join table of its own, which is exactly the kind of knowledge
    that drifts from her file.

    So the parser also accepts "PROJECT:id", where id is a row of her prior-work
    sheet (the ids read_prior_work() assigns, and that --emit-workbook proposes
    back to her). One filled-in cell then replaces one entry in our join table.
    Both forms work; nothing has to change on her side before this ships.
    """
    project, _, ref = token.partition(":")
    return project.strip(), (ref.strip() or None)


def read_prior_work(path=XLSX, sheet=PRIOR_SHEET):
    """-> the prior-FRI-panel questions her comparison column names, verbatim.

    Carried into the JSON so a human baseline can never be shown without the
    question it actually answered. The pairing between her Auto-ARC row and one
    of these is what a reader has to judge; a median alone hides the judgement.
    Joined on (Project, Category) — the pair her comparison column and this
    sheet share.
    """
    out, used = [], {}
    for r in read_rows(path, sheet):
        if not r.get("Project"):
            continue
        # A stable handle for one prior question, so her comparison column can
        # eventually point at a ROW rather than at a project. Built from what
        # she already wrote — project, category, severity — and numbered only
        # where all three collide (her AI-cyber pilot filed two "$10b incident"
        # rows, a worm attack and a grid attack).
        stem = slug(f"{r['Project']}-{r['Category']}-{r['Severity']}")
        used[stem] = used.get(stem, 0) + 1
        qid = stem if used[stem] == 1 else f"{stem}-{used[stem]}"
        out.append({
            "id": qid,
            "project": r["Project"],
            "category": r["Category"],
            "elicited": parse_date(r.get("Date of human forecasts", "")),
            "resolution_dates": [y for y in re.findall(r"\b\d{4}\b",
                                                       r.get("Date of question resolution", ""))],
            "severity": r.get("Severity", ""),
            "text": r.get("Question", ""),
            "criteria": r.get("Question details", ""),
        })
    return out


def slug(text):
    """'P6 Bio - 10m deaths' -> 'p6-bio-10m-deaths'. Ids a human can read."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def parse_date(raw):
    """'2022-10-01 00:00:00' -> '2022-10-01'. openpyxl hands back a datetime."""
    raw = str(raw or "").strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else raw


# The one place the two inputs are known to disagree. The definitions markdown
# names the bio horizon 2044 and the workbook names it 2045; they are the same
# date described from either side, because P6 bio resolves "before January 1,
# 2045". Raised with the author as an FYI, allowed here so the check can be
# strict about everything else.
KNOWN_INPUT_DIFFS = {"2044", "2045"}


def crosscheck(rows, defs):
    """Fail if the workbook and the markdown describe different question sets.

    The set needs BOTH files: the workbook carries composition and the question
    template, and carries no resolution criteria at all — its text column tops
    out at 310 characters. Every definition a forecaster answers from and a
    resolver resolves by lives only in the markdown.

    Two inputs can drift. Revise one and not the other and this generator will
    happily emit a set whose composition and whose definitions describe
    different questions, with nothing to notice. So: every severity and date the
    workbook uses must appear in the markdown's option lists, and every cause
    must have a definition. Raise rather than warn — a silently mismatched
    question set is worse than a failed build.

    (Better still would be one input. The workbook's "prior FRI work" sheet has a
    Question details column carrying full criteria, so the format already
    exists; if the Auto-ARC sheets gain one, the markdown becomes redundant.)
    """
    rows = [r for r in rows if r["Human comparisons (Project)"] != "P6 bio"]
    problems = []

    md_sev = {l.strip().lstrip("*").strip()
              for l in defs["Severity options"]["body"].splitlines()
              if l.strip().startswith("*")}
    x_sev = {r["Severity"] for r in rows if parse_severity(r["Severity"])}
    if x_sev - md_sev:
        problems.append(f"severities in the workbook with no definition in the "
                        f"markdown: {sorted(x_sev - md_sev)}")

    md_dates = set(re.findall(r"\b\d{4}\b", defs["Date options"]["body"]))
    x_dates = {parse_year(r["Date of question resolution"]) for r in rows} - {""}
    stray = (x_dates - md_dates) - KNOWN_INPUT_DIFFS
    if stray:
        problems.append(f"horizons in the workbook not listed in the markdown's "
                        f"date options: {sorted(stray)}")

    md_inc = set(bullet_split(
        defs["Incident options"]["blocks"]["Incident definitions"]))
    missing = [c["def_key"] for c in CAUSES if c["def_key"] not in md_inc]
    if missing:
        problems.append(f"causes with no definition in the markdown: {missing}")

    x_cat = {r["Category"] for r in rows} - {"General catastrophe",
                                             "AI catastrophe",
                                             "Human disempowerment"}
    unmapped = x_cat - {c["sheet"] for c in CAUSES}
    if unmapped:
        problems.append(f"incident categories in the workbook that map to no "
                        f"cause: {sorted(unmapped)} — a new incident type was "
                        f"added and CAUSES was not updated, so it would be "
                        f"dropped from the ladder in silence")

    if problems:
        raise SystemExit(
            "data/auto-arc/ is internally inconsistent — the workbook and the "
            "definitions describe different question sets:\n  - "
            + "\n  - ".join(problems))


def build_crosscutting(rows, defs):
    """The three questions whose severity does not vary — only dates do.

    Severity is a POPULATION SHARE for two of them, which is a different kind of
    threshold from the incident rungs: it floats with population where the rungs
    are absolute, and it has no dollar leg. So these are anchors on the severity
    axis at ~820M, not rungs of any ladder. Project lead, 2026-08-18: a
    catastrophe is defined as 10% of population, so there is no ladder; all
    that varies are dates.
    """
    # (id, her Category value, her markdown section, inherits-criteria-from).
    # Name, short name and severity are all READ from those two sources — none
    # is written here. The id is ours because her files have none; the other two
    # entries are join keys into her workbook and her markdown.
    spec = [
        ("catastrophe:general", "General catastrophe",
         "General large-scale catastrophe", None),
        ("catastrophe:ai", "AI catastrophe",
         "AI-related large-scale catastrophe", "General large-scale catastrophe"),
        ("disempowerment", "Human disempowerment",
         "Human disempowerment", None),
    ]

    out = []
    for qid, category, section, inherits in spec:
        mine = [r for r in rows if r["Category"] == category]
        if not mine:
            raise SystemExit(f"no rows with Category {category!r} — the "
                             f"workbook renamed or dropped a question")
        # The whole set's grid, not this category's workbook rows (which stop
        # at 2030/2050/2100). Since 2026-08-28 the cross-cutting questions are
        # asked over the same horizons as the ladder so Graph 1's two rail
        # groups share an x-axis. See ROLLING and set_horizons().
        hz = set_horizons(rows)
        # Severity from HER severity column. "10% of population" parses to a
        # share; "NA" (human disempowerment) carries no severity axis at all.
        raw_sev = mine[0]["Severity"].strip()
        severity = parse_share(raw_sev)
        if severity is None:
            if raw_sev.upper() not in ("NA", "N/A", "-", ""):
                raise SystemExit(
                    f"{category}: severity {raw_sev!r} is neither a population "
                    f"share nor NA. A new severity kind needs a parser, not a "
                    f"silent fallback to 'no severity'.")
            severity = {"kind": "none", "label": "not applicable", "short": "—",
                        "source_text": raw_sev}
        # Question text comes from the sheet, with the horizon list rebuilt from
        # `hz` so the prose and the horizons field can never disagree.
        base = re.sub(r"\s*by each of the following resolution years.*$", "",
                      mine[0]["Question"].strip(), flags=re.S | re.I).rstrip("?").strip()
        out.append({
            "id": qid,
            # Her Category value is the name. "Global catastrophe" was mine.
            "name": category,
            "short": category,
            "category": "crosscutting",
            "value_kind": "probability",
            "severity": severity,
            "horizons": hz,
            # horizon_phrase, not a joined year list: "by the end of 6mo" is
            # not English, and the rolling windows carry their own preposition.
            "text": f"{base} {horizon_phrase(hz)}?",
            # This question's OWN details block, not the union of all four —
            # plus, where the source text says so, the one it refers back to.
            # The AI-catastrophe criteria open "The points above also apply to
            # this question", and in a prompt there is no above: the model
            # would be handed a dangling reference and none of the definitions
            # it points at. Resolved here, declaratively, rather than by
            # matching that sentence.
            # Her criteria verbatim, with "the resolution year" scoped to the
            # horizons we actually ask over. See with_horizon_scope.
            "criteria": with_horizon_scope(
                criteria_for(defs, section, inherits), hz,
                horizons_for(rows, lambda r, c=category: r["Category"] == c)),
            "human": {},          # filled by attach_human_anchors
            "human_wanted": sorted({parse_year(r["Date of question resolution"])
                                    for r in mine
                                    if r.get("To be completed by humans?") == "y"}),
            # Which horizons a prior FRI panel has already answered, and which
            # panel. Read from her sheet; see comparisons_for().
            "human_comparisons": comparisons_for(
                rows, lambda r, c=category: r["Category"] == c),
        })
    return out


def criteria_for(defs, section, inherits):
    """A section's own details, with any section it refers back to prepended."""
    own = defs.get(section, {}).get("blocks", {}).get("Question details", "")
    if not inherits:
        return own
    parent = defs.get(inherits, {}).get("blocks", {}).get("Question details", "")
    return f"{parent}\n\n[Carried forward from \"{inherits}\"]\n\n{own}"



# The cross-cutting criteria fix the measurement window against "December
# 31 of the resolution year (2030, 2050, or 2100)" -- three horizons written
# into the rule itself. Asking the same questions at 6mo/12mo/2028 (2026-08-28)
# leaves that sentence contradicting the question above it, and a model handed a
# contradiction resolves it however it likes.
#
# So the slot gets opened, in a note marked as ours, rather than by editing her
# markdown -- data/auto-arc/ is her input, not our working copy. "The resolution
# year" was ALREADY a slot in her rule; this says what fills it when the horizon
# is not a year. Nothing else about the window changes: same start floor, same
# five-year ceiling.
#
# It attaches by the phrase, not by parsing which years the text names. Keying
# it to a year list attached the note to human disempowerment, whose criteria
# define a STATE and carry no measurement window to scope at all.
HORIZON_SCOPE_ANCHOR = "the resolution year"
HORIZON_SCOPE_NOTE = (
    "* [Scope of \"the resolution year\", added 2026-08-28 when these questions "
    "moved onto the incident ladder's horizon grid: read it as the resolution "
    "date of whichever horizon you are answering, which for a rolling horizon "
    "is that many months after today's date. The rule is otherwise unchanged -- "
    "the measurement window still begins on or after December 31, 2025, must "
    "end on or before that resolution date, and still spans at most five years.]"
)


def with_horizon_scope(criteria, hz, spec_years):
    """Her criteria, plus the scope note when the grid outruns her year slot.

    Silent in two cases, both of which mean there is nothing to scope: the
    question's criteria never fix the window against a resolution year (human
    disempowerment), or we ask over exactly the horizons her document was
    written for -- so the day her workbook gains these horizons, the note stops
    being emitted without anyone remembering to delete it.
    """
    if HORIZON_SCOPE_ANCHOR not in criteria or set(hz) <= set(spec_years):
        return criteria
    return f"{criteria}\n{HORIZON_SCOPE_NOTE}"


def addendum_rungs(addenda):
    """The ladder rungs the addenda add (`ladder_rung`: true), in the shape
    of a workbook rung plus `since`. The only kind known is `extinction`: a
    population floor placed at the whole population on the log-death axis,
    no dollar leg (no sum of direct losses is an extinction). Project lead,
    2026-09-16: the four incident curves should reach extinction."""
    out = []
    for doc in addenda:
        if not doc.get("ladder_rung"):
            continue
        sev = dict(doc["severity"])
        if sev.get("kind") != "extinction":
            raise SystemExit(f"{doc['_file']}: ladder rung of kind {sev.get('kind')!r} is not "
                             "one this generator knows how to place on the axis")
        out.append({"kind": "extinction", "deaths": WORLD_POP, "deaths_equiv": WORLD_POP,
                    "damages_usd": None, "floor_population": sev["floor_population"],
                    "label": sev["label"], "short": sev.get("short") or "extinction",
                    "source_text": sev["source_text"], "since": doc["since"],
                    "source": doc["_file"]})
    return out


def build_ladder(rows, defs, addenda=()):
    """The incident grid: four causes, the workbook's eight rungs plus any an
    addendum adds (the extinction rung, 2026-09-16), one wording each."""
    incident_rows = [r for r in rows
                     if r["Category"] in {c["sheet"] for c in CAUSES}
                     and r["Human comparisons (Project)"] != "P6 bio"]

    # Rungs, in severity order, taken from the sheet rather than declared here.
    seen, rungs = set(), []
    for r in incident_rows:
        s = parse_severity(r["Severity"])
        if s and s["deaths"] not in seen:
            seen.add(s["deaths"])
            rungs.append(s)
    rungs += addendum_rungs(addenda)
    rungs.sort(key=lambda s: s["deaths"])

    fixed = horizons_for(incident_rows, lambda r: True)
    horizons = set_horizons(rows)

    template = next(r["Question"] for r in incident_rows if r["Question"]).strip()

    # Each cause gets ONLY its own definition; the severity ladder, the date
    # rules and the perfect-knowledge clause are genuinely shared and are
    # carried once rather than pasted into all 32 questions.
    incident_defs = bullet_split(
        defs.get("Incident options", {}).get("blocks", {}).get("Incident definitions", ""))
    incidents = defs.get("AI-related incidents and domain-specific incidents", {})
    shared = {
        "perfect_knowledge": incidents.get("blocks", {}).get("Question details", ""),
        "severity": defs.get("Severity options", {}).get("blocks", {}).get(
            "Severity definitions", ""),
        "dates": defs.get("Date options", {}).get("blocks", {}).get("Date details", ""),
    }

    questions, featured = [], []
    for c in CAUSES:
        mine = [r for r in incident_rows if r["Category"] == c["sheet"]]
        for rung in rungs:
            wanted = sorted({parse_year(r["Date of question resolution"])
                             for r in mine
                             if (parse_severity(r["Severity"]) or {}).get("deaths")
                             == rung["deaths"]
                             and r.get("To be completed by humans?") == "y"})
            qid = f"ladder:{c['key']}:{rung['short']}"
            text = fill_template(template, incident_phrase(defs, c), rung, horizons)
            questions.append({
                "id": qid,
                "cause": c["key"],
                "cause_label": cause_label(defs, c),
                "color": c["color"],
                "category": "incident",
                "value_kind": "probability",
                "severity": rung,
                "rung": rung["short"],
                "horizons": horizons,
                "text": text,
                "criteria": incident_defs.get(c["def_key"], ""),
                "details": shared,
                "human": {},
                "human_wanted": wanted,
                "human_comparisons": comparisons_for(
                    mine, lambda r, d=rung["deaths"]:
                        (parse_severity(r["Severity"]) or {}).get("deaths") == d),
                # An addendum rung's date of entry and file, so a run made
                # before it is still complete (redlines.questions.questions_asked_on).
                **({"since": rung["since"], "source": rung["source"]} if rung.get("since") else {}),
            })
            # Graph 1 plots these BY REFERENCE, so the question is not copied
            # into the cross-cutting file and never elicited twice. The 1M rung
            # is the one the workbook flags for human forecasting at every horizon,
            # so it is the only row with a model-vs-human read across the whole
            # time axis.
            if rung["short"] == "1M":
                featured.append(qid)

    vsl = stated_vsl(defs)
    for r in rungs:
        if r.get("damages_usd") is not None and abs(r["damages_usd"] - r["deaths"] * vsl) > 1.0:
            raise SystemExit(f"rung {r['short']}: the workbook's dollar leg ({r['damages_usd']:g}) is not "
                             f"deaths x the stated VSL ({r['deaths'] * vsl:g}); the two sources disagree")
    causes_out = [{**{k: v for k, v in c.items() if k != "def_key"},
                   "label": cause_label(defs, c)} for c in CAUSES]
    return {
        "title": f"Auto-ARC incident ladder — four AI incident types, {len(rungs)} severity rungs",
        "instrument_version": CURRENT_INSTRUMENT,
        "provenance": {
            "author": "Bridget Williams, FRI",
            "received": "2026-08-18; revised 2026-08-31 (tracked changes in the shared "
                        "doc, applied 2026-09-02 -- see the note atop the definitions file)",
            "source_workbook": os.path.relpath(XLSX, ROOT),
            "source_definitions": os.path.relpath(DEFS, ROOT),
            "sheet": SHEET,
            "generated_by": "code/make_autoarc_questions.py",
            "status": "September 10 counting clarification accepted by Nick Merrill: "
                      "all incident windows start at elicitation; cyber campaign "
                      "onset is the first malicious action against a target. "
                      "Older forecasts answer an earlier instrument. August 31 "
                      "thresholds, attribution and accounting remain unchanged.",
        },
        "notes": {
            "vsl_usd": vsl,
            "severity_axis": "Each rung resolves on deaths OR damages, whichever "
                             f"comes first. The two legs sit at a constant 1:{vsl:g} "
                             f"ratio — the ${vsl / 1e6:g}M value of a statistical life the "
                             "criteria state — so the axis stays monotone and "
                             "log-spaced whichever leg binds.",
            "cyber": "Cyber is on the ladder for the first time. It was held out "
                     "while the axis was deaths-only (per Jason, 2026-08-03: "
                     "cyber belongs on a DAMAGES ladder); the disjunctive "
                     "threshold is what admits it.",
            "container": "'Any AI-related incident' contains the other three by "
                         "Bridget's definition, so it plays the role 'All "
                         "causes' used to. There is NO all-cause ladder in this "
                         "set: nuclear and natural pandemics are outside it, so "
                         "the CROSS check has an AI-internal ceiling only.",
            "rolling": "All incident onset windows start at the elicitation date. "
                       "6mo/12mo end that many months later; fixed-year windows "
                       "end on December 31. Rows retain both boundaries. Harm "
                       "within three years of each eligible onset can occur "
                       "after the deadline; the onset deadline is not necessarily "
                       "the date on which a forecast can be scored.",
        },
        "causes": causes_out,
        "rungs": [{k: v for k, v in r.items() if k != "source"} for r in rungs],
        "horizons": horizons,
        "rolling": ROLLING,
        "fixed_horizons": fixed,
        "featured": featured,
        "relations": build_relations(rungs),
        # The prior FRI panels her comparison column names, verbatim from her
        # third sheet. Every human number we pull is joined back to one of
        # these on (project, category), so the median and the question it
        # answered always travel together.
        "prior_work": read_prior_work(),
        "questions": questions,
    }


def fill_template(template, phrase, rung, horizons):
    """The workbook's template with the incident, severity and date slots filled.

    The severity slot takes its OWN option text verbatim ("1,000 deaths (or
    equivalent morbidity) or $10 billion") rather than a reconstruction of it.
    Re-deriving prose we were handed is the same mistake as typing a threshold
    into a JSX file: it produces a second wording that can drift from the first.

    The template reads "... by [date]", which is wrong for a rolling window —
    "by within 6 months" is not English. So the trailing "by" is absorbed into
    the slot and each horizon supplies its own preposition.
    """
    t = re.sub(r"\[incident:[^\]]*\]", phrase, template)
    severity = (rung["source_text"] if rung.get("kind") == "extinction"
                else f"{rung['source_text']} in economic damages")
    t = re.sub(r"\[severity:[^\]]*\]", severity, t)
    t = re.sub(r"\bby\s*\[date:[^\]]*\]", horizon_phrase(horizons), t)
    return re.sub(r"\s+", " ", t).strip()


def horizon_phrase(horizons):
    """Each horizon carries its own preposition, so rolling and fixed mix."""
    labels = {h["id"]: h["label"] for h in ROLLING}
    return " / ".join(labels.get(h, f"by the end of {h}") for h in horizons)


def build_relations(rungs):
    """The containments the question set states outright. Nothing inferred.

    These used to be two hardcoded dicts in redlines/coherence.py, keyed on XPT
    question ids and carrying, by their own comment, "judgments about English,
    not measurements". Most of those judgments are gone: the set's definitions
    state the containment, so it is read from the set rather than argued for.

    Deliberately small. Project lead, 2026-08-18: minimal coherence checks,
    applied AFTER the fact, warning when there are obvious violations.

    CROSS   every specific incident type is contained in "any AI-related
            incident", per the set's definition of that class.
    BRACKET the AI catastrophe question (10% of population, ~820M deaths) is
            contained in the >=100M rung of the AI ladder. ONE SIDE ONLY: the
            >=1B rung does not bound it, because 820M is below 1B on deaths but
            that rung also resolves on $10Q, so neither event contains the other.
    SUBSET  a global catastrophe caused by AI is a global catastrophe.
    """
    below = [r for r in rungs if r["deaths"] <= 0.10 * WORLD_POP]
    bracket_rung = below[-1]["short"] if below else None
    return {
        "cross": {"container": "ai",
                  "contained": [c["key"] for c in CAUSES if not c.get("container")]},
        "bracket": [
            {"narrower": "catastrophe:ai", "cause": "ai", "rung": bracket_rung,
             "why": "10% of population (~820M) exceeds this rung's threshold on "
                    "deaths, and the rung also resolves on damages, so the "
                    "catastrophe question is strictly contained in it."},
        ],
        "subset": [
            {"narrower": "catastrophe:ai", "broader": "catastrophe:general",
             "why": "an AI-caused global catastrophe is a global catastrophe"},
        ],
    }


def attach_human_anchors(cross, ladder):
    """No human anchors today. The XPT medians were pulled on 2026-08-18.

    They had been attached to catastrophe:general and catastrophe:ai on the
    grounds that XPT 2022 asked "the SAME 10%-of-population threshold and the
    same three horizons, so those medians transfer without adjustment". The
    threshold and the horizons do match. Three things under them do not:

      window       XPT: deaths "within a 5-year period". Auto-ARC: "any
                   contiguous period of AT MOST five years", which must begin
                   on or after 2025-12-31. Ours is a ceiling with a floor on
                   the start date; XPT's was neither.
      what counts  XPT counted humans who "die". Auto-ARC counts ATTRIBUTABLE
                   EXCESS MORTALITY -- deaths beyond the baseline that would
                   have occurred anyway. A pandemic killing 10% of the world
                   resolves both; a famine that raises mortality against a
                   falling baseline may resolve only one.
      causation    All three run the same but-for test, and this was written
                   here as a difference when it is not. What DOES differ is the
                   clock: XPT and LEAP both require the AI's substantial
                   involvement "within one year prior to the event"; Auto-ARC
                   sets no time limit and says so, counting a superweapon built
                   years before it is used. Ours is the wider question.

    Plotting them as diamonds beside our forecasts asserted a comparison that
    the wordings do not support (project lead, 2026-08-18: they do not match our
    questions exactly). The numbers are not lost -- they are in
    archive/legacy-questions/starter_questions.json under "9. Total
    Catastrophic Risk" and "3. AI Catastrophic Risk", with the XPT wording
    beside them, which is where anyone re-deriving an adjusted anchor should
    start.

    What would restore an anchor here: the September superforecaster round,
    which is being asked BRIDGET'S wording and so needs no adjustment at all;
    or LEAP 2026 / P6-bio 2025 once we hold their numbers and can state what
    reconciliation each one needs.
    """
    for q in cross:
        q["human"] = {}
    for q in ladder["questions"]:
        q["human"] = {}
    return cross, ladder


ADDENDUM_KEYS = ("title", "provenance", "since", "severity", "questions")
ADDENDUM_QUESTION_KEYS = ("id", "name", "text", "criteria", "human_comparisons")


def read_addenda(paths=None):
    """-> the addendum docs, oldest first, each stamped with its file path.

    Schema-checked rather than trusted: an addendum is hand-written JSON, so a
    missing key would otherwise surface as a KeyError three stages downstream.
    """
    docs = []
    for p in (ADDENDA if paths is None else paths):
        doc = json.load(open(p, encoding="utf-8"))
        missing = [k for k in ADDENDUM_KEYS if k not in doc]
        if missing:
            raise SystemExit(f"{os.path.relpath(p, ROOT)}: addendum is missing {missing}")
        for q in doc["questions"]:
            missing = [k for k in ADDENDUM_QUESTION_KEYS if k not in q]
            if missing:
                raise SystemExit(f"{os.path.relpath(p, ROOT)}: question "
                                 f"{q.get('id', '<unknown>')!r} is missing {missing}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(doc["since"])):
            raise SystemExit(f"{os.path.relpath(p, ROOT)}: `since` must be an ISO date")
        doc["_file"] = os.path.relpath(p, ROOT)
        docs.append(doc)
    return docs


def build_addendum_questions(rows, addenda):
    """The addenda's questions, on the set's own horizon grid.

    Same shape as build_crosscutting()'s output, so nothing downstream can tell
    an addendum question from a workbook one except by its `since` and
    `source` fields -- which is the point: the runner, the rail, the coherence
    audit and the data bank all read the one cross-cutting file.

    The severity kind is `extinction`: a population floor rather than a death
    count, placed on the shared log-death axis at the whole population
    (deaths_equiv = WORLD_POP), where Graph 2 already draws its Extinction
    reference mark from the same number. That is the only kind an addendum may
    carry today; a new one needs a parser and a place on the axis, not a
    silent pass-through.
    """
    hz = set_horizons(rows)
    out = []
    for doc in addenda:
        sev = dict(doc["severity"])
        if sev.get("kind") != "extinction":
            raise SystemExit(f"{doc['_file']}: severity kind {sev.get('kind')!r} is not "
                             "one this generator knows how to place on the axis")
        sev["deaths_equiv"] = WORLD_POP
        for q in doc["questions"]:
            base = q["text"].strip().rstrip("?").strip()
            out.append({
                "id": q["id"],
                "name": q["name"],
                "short": q.get("short") or q["name"],
                "category": "crosscutting",
                "value_kind": "probability",
                "severity": dict(sev),
                "horizons": hz,
                "text": f"{base} {horizon_phrase(hz)}?",
                "criteria": q["criteria"],
                "human": {},
                "human_wanted": list(q.get("human_wanted") or []),
                "human_comparisons": {y: list(ps) for y, ps in
                                      sorted((q.get("human_comparisons") or {}).items())},
                # The date this question entered the set. A run before it is
                # complete without it (redlines.questions.questions_asked_on).
                "since": doc["since"],
                "source": doc["_file"],
            })
    return out


def apply_addenda(cross, ladder, addenda):
    """Fold the addenda's relations and prior-work rows into the ladder spec.

    Relations may only name cross-cutting questions that exist; a relation
    that points at nothing is a typo the coherence audit would otherwise skip
    in silence.
    """
    ids = {q["id"] for q in cross}
    ladder.setdefault("prior_work", [])
    for doc in addenda:
        for rel in (doc.get("relations") or {}).get("subset", []):
            for side in ("narrower", "broader"):
                if rel[side] not in ids:
                    raise SystemExit(f"{doc['_file']}: relation names {rel[side]!r}, "
                                     "which is not a cross-cutting question")
            ladder["relations"]["subset"].append(dict(rel))
        for pw in doc.get("prior_work", []):
            ladder["prior_work"].append({**pw, "source": doc["_file"]})
    return ladder


def render(rows, defs):
    crosscheck(rows, defs)
    addenda = read_addenda()
    cross = build_crosscutting(rows, defs) + build_addendum_questions(rows, addenda)
    ladder = apply_addenda(cross, build_ladder(rows, defs, addenda), addenda)
    cross, ladder = attach_human_anchors(cross, ladder)
    cross_doc = {
        "title": "Auto-ARC cross-cutting questions — severity fixed, dates vary",
        "provenance": {
            **ladder["provenance"],
            # Every question that is not hers, and where it came from.
            "addenda": [{"file": d["_file"], "since": d["since"],
                         "questions": [q["id"] for q in d["questions"]],
                         **{k: v for k, v in d["provenance"].items()}}
                        for d in addenda],
        },
        "notes": {
            "no_ladder": "Severity does not vary here (Nick, 2026-08-18): a "
                         "catastrophe IS 10% of population. These are "
                         "single questions, not a ladder.",
            "addenda": "Questions with a `since` field entered the set after "
                       "the workbook, from the addendum file their `source` "
                       "names (the extinction pair, 2026-09-15, in XPT's "
                       "wording). A run made before a question's `since` is "
                       "complete without it.",
            "axis": "The two catastrophe questions are ANCHORS on the incident "
                    "ladder's severity axis at ~820M deaths, not rungs of it — "
                    "a population share floats where the rungs are absolute, "
                    "and it has no damages leg.",
            "human": "No human anchor is plotted. Bridget's comparison column "
                     "names XPT 2022 and LEAP 2026 for the two catastrophe "
                     "questions, and code/fetch_human_baselines.py holds their "
                     "medians in data/human_baselines.json — unplotted, "
                     "because the wordings differ: XPT counts deaths where she "
                     "counts attributable excess mortality, and both prior "
                     "panels time-limit the AI's involvement to a year before "
                     "the event where she sets no limit. The September "
                     "superforecaster round is being asked this wording and "
                     "will need no reconciliation at all.",
        },
        "world_pop": WORLD_POP,
        "questions": cross,
    }
    return cross_doc, ladder


def emit_workbook(rows, cross_doc, ladder_doc, path):
    """Write the author's own sheet back, with the criteria column filled in.

    A PROPOSAL, not an input. The set currently needs two files only because the
    Auto-ARC sheets have no criteria column — the "Questions from prior FRI work"
    sheet already has one, carrying up to 4,064 characters, so the format is
    the author's and the gap is an omission rather than a design.

    This writes a copy of the "long" sheet with a Question details column
    populated from the markdown, plus the stable question id we use downstream.
    If she adopts it as her working file, the markdown becomes redundant, this
    generator drops to a single input, and read_definitions()/crosscheck() can
    both go away.

    Deliberately NOT an edit of data/auto-arc/questions-*.xlsx. That file is
    what she sent, and it has to stay that way or we lose the ability to diff
    her next revision against it. Regenerated output cannot drift; a hand-edited
    input silently can.
    """
    import openpyxl

    by_row = {}
    for q in cross_doc["questions"]:
        by_row[q["name"]] = (q["id"], q["criteria"])
    shared = ladder_doc["questions"][0]["details"]
    shared_text = "\n\n".join(
        f"[{k.replace('_', ' ').upper()}]\n{v}" for k, v in shared.items() if v)
    # A ladder row's id needs its RUNG, and the rung is in the row's own
    # Severity cell. This used to write the literal string
    # "ladder:<cause>:<rung>" -- a placeholder that was never substituted, so
    # all 32 rows of a cause carried one id and the column could not join a row
    # to a question, which is the only thing it exists to do. Keyed on
    # (category, deaths) so the rung comes from the sheet, not from row order.
    by_rung = {}
    for c in ladder_doc["causes"]:
        q = next(x for x in ladder_doc["questions"] if x["cause"] == c["key"])
        by_row[c["sheet"]] = (None, f"{q['criteria']}\n\n{shared_text}")
        for x in ladder_doc["questions"]:
            if x["cause"] == c["key"]:
                by_rung[(c["sheet"], x["severity"]["deaths"])] = x["id"]

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb[SHEET]
    head = [c.value for c in ws[1]]
    SEV_COL = head.index("Severity")
    ws.cell(row=1, column=len(head) + 1, value="Question ID")
    ws.cell(row=1, column=len(head) + 2, value="Question details")

    seen, last = set(), 1
    for i, row in enumerate(ws.iter_rows(min_row=2), start=2):
        cat = str(row[0].value or "").strip()
        if not cat:
            continue
        last = i
        # The P6-bio rows share the Biorisk category but are not ladder rungs —
        # they exist to line up with an existing human panel at 2045, on a
        # deaths-only severity. Labelling them ladder:bio:<rung> would invite
        # exactly the confusion the id column is meant to remove.
        if str(row[1].value or "").strip() == "P6 bio":
            ws.cell(row=i, column=len(head) + 1, value="p6bio:comparison")
            continue
        if cat not in by_row:
            continue
        qid, criteria = by_row[cat]
        if qid is None:                       # a ladder row: resolve its rung
            sev = parse_severity(row[SEV_COL].value)
            qid = by_rung.get((cat, sev["deaths"] if sev else None))
            if qid is None:
                raise SystemExit(
                    f"{path}: row {i} of {cat!r} has severity "
                    f"{row[SEV_COL].value!r}, which matches no rung. The "
                    "Question ID column would be wrong, so nothing is written.")
        ws.cell(row=i, column=len(head) + 1, value=qid)
        # Details on the first row of each question only, matching the style of
        # her prior-work sheet — repeating 3,000 characters down 32 rows makes
        # the column unreadable and says nothing extra.
        if cat not in seen:
            ws.cell(row=i, column=len(head) + 2, value=criteria)
            seen.add(cat)

    ws.cell(row=last + 2, column=1,
            value="Question ID and Question details added by the Red Lines "
                  "dashboard pipeline (code/make_autoarc_questions.py), from "
                  "the definitions markdown of the same date. Proposed so the "
                  "workbook can be the single source; nothing here is new "
                  "content.")

    # The prior-work sheet gets ids too, so the comparison column can name a
    # ROW. Today it names a project — "LEAP" — and LEAP filed three different
    # AI-catastrophe questions, so a join table lives in our fetch script
    # deciding which one each cell means. That is a decision about her
    # questions being made in our code. With ids she can write
    # "LEAP:leap-ai-catastrophe-10-of-population" and the table goes away.
    pw = wb[PRIOR_SHEET]
    pw_head = [c.value for c in pw[1]]
    if "Question ID" not in pw_head:
        col = len(pw_head) + 1
        pw.cell(row=1, column=col, value="Question ID")
        ids = iter(read_prior_work())
        for row in pw.iter_rows(min_row=2):
            if not str(row[0].value or "").strip():
                continue
            pw.cell(row=row[0].row, column=col, value=next(ids)["id"])

    wb.save(path)
    return path


def dumps(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-workbook", metavar="PATH", nargs="?",
                    const=os.path.join(ROOT, "results",
                                       "autoarc_workbook_with_details.xlsx"),
                    help="write a copy of Bridget's sheet with the criteria "
                         "column filled, to propose back to her")
    ap.add_argument("--check", action="store_true",
                    help="regenerate in memory and diff against the tracked "
                         "files; write nothing, exit 1 on any difference")
    args = ap.parse_args()

    rows = read_rows()
    defs = read_definitions()
    crosscheck(rows, defs)
    cross_doc, ladder_doc = render(rows, defs)

    pairs = [(OUT_CROSS, cross_doc), (OUT_LADDER, ladder_doc)]
    if args.check:
        bad = []
        for path, doc in pairs:
            want = dumps(doc)
            have = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            if want != have:
                bad.append(os.path.relpath(path, ROOT))
        if bad:
            print(f"STALE or HAND-EDITED: {bad}\n"
                  f"Run: python3 code/make_autoarc_questions.py")
            return 1
        print(f"ok — both files match {os.path.relpath(XLSX, ROOT)}")
        return 0

    for path, doc in pairs:
        open(path, "w", encoding="utf-8").write(dumps(doc))
        print(f"wrote {os.path.relpath(path, ROOT)}")
    if args.emit_workbook:
        os.makedirs(os.path.dirname(args.emit_workbook), exist_ok=True)
        out = emit_workbook(rows, cross_doc, ladder_doc, args.emit_workbook)
        print(f"wrote {os.path.relpath(out, ROOT)}  (proposal for Bridget)")
    n = len(cross_doc["questions"]) + len(ladder_doc["questions"])
    cells = (sum(len(q["horizons"]) for q in cross_doc["questions"])
             + sum(len(q["horizons"]) for q in ladder_doc["questions"]))
    print(f"  {n} questions, {cells} question x horizon cells")
    print(f"  horizons: {', '.join(ladder_doc['horizons'])}")
    print(f"  rungs:    {', '.join(r['short'] for r in ladder_doc['rungs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
