"""Superseded runs: rows every view skips, kept on disk (2026-09-16).

A run is superseded when the same day re-asked the same models under a
newer instrument or a repaired harness, and the project lead said the later
draw REPLACES the earlier one (project lead, 2026-09-16: "use this to replace the
last (Wednesday) forecast"). Nothing is deleted or rewritten: the rows stay
in results/runs/ and the conditional log, the download bundle still carries
them (project lead, 2026-09-08: include everything), and the CSVs' run_id
column lets a reader apply or lift this rule. The views -- the timeline,
Graph 1, Graph 2, the conditional and capability tabs, the paper's numbers
-- read through load_runlog() and load_conditional(), which drop these rows,
so a day never holds two draws of one model where one was meant to replace
the other.

Keyed by run_id (the run's UTC stamp, also its file name under
results/runs/); the labels are the models whose rows are superseded, or
None for the whole run.
"""

SUPERSEDED = {
    # The 12:00 UTC scheduled run of 2026-09-16 ran the 35-question instrument
    # (the box lagged main: no extinction pair, per-group debrief) and was
    # replaced the same afternoon by the 16:45 UTC run on the extinction-rung
    # instrument (unified-joint-combined-v7) with the per-question debrief.
    "2026-09-16T1200Z": (None, "replaced the same day by the 16:45 UTC run on the "
                               "extinction-rung instrument with the per-question debrief"),
    # In the 16:45 UTC run the Anthropic API refused the per-question debrief
    # tool (property keys may not contain ':'), so Fable 5.1 and Opus 5 have
    # forecasts but no debrief there; both were re-run the same evening with
    # the key fix, and those draws are the day's reading for the two.
    "2026-09-16T1645Z": ({"Fable 5.1", "Opus 5"}, "debrief turn refused by the API; "
                                                  "re-run the same day with the fix"),
}


def is_superseded(row):
    """True when a row belongs to a superseded (run, model)."""
    entry = SUPERSEDED.get(row.get("run_id"))
    if not entry:
        return False
    labels, _ = entry
    return labels is None or row.get("label") in labels


def superseded_note():
    """One paragraph for the download bundle's README."""
    lines = []
    for run_id, (labels, why) in sorted(SUPERSEDED.items()):
        who = "every model" if labels is None else ", ".join(sorted(labels))
        lines.append(f"  {run_id} ({who}): {why}")
    return "\n".join(lines)
