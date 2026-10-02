"""The METHOD blob: the elicitation as the FAQ shows it (web/demo/79-faq.jsx).

Two things the "How do you elicit the forecasts?" and "Which models are in
the ensemble?" answers render live instead of by hand:

  * the whole prompt -- the system prompt and the single-instrument user
    prompt (code/run_unified.py build_prompt_joint, the published COMBINED
    condition set, every question x horizon cell) -- rebuilt from the same
    question and condition files the cron reads, so the page shows what the
    models are actually sent. The prompt is dated: "Today is ..." and the
    rolling horizons' resolves-on dates come from the day. Here that day is
    the LATEST RUN's run_date in the runlog, not the wall clock, so the blob
    is a function of the tracked data alone (the golden tests rebuild it and
    compare bytes) and reads as the prompt the latest forecasts answered.

  * the panel -- redlines.registry.panel_provenance(): the k highest-ECI
    runnable models in the newest tracked ECI snapshot, the selection the
    next run makes. age_days is left out (wall clock).

code/run_unified.py is a script, not a package module; it is loaded the way
tests/test_conditional.py loads it.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

from ..config import REPO_ROOT
from ..registry import panel_provenance
from ..runlog import current_rows, load_runlog
from ..instrument import instrument_rows
from ..questions import load_ladder, questions_asked_on


def _runner():
    spec = importlib.util.spec_from_file_location("run_unified", REPO_ROOT / "code" / "run_unified.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def latest_run_date(rows=None):
    """The newest run_date among the current-protocol rows, as a date."""
    rows = instrument_rows(current_rows(load_runlog()) if rows is None else rows)
    days = [r["run_date"] for r in rows if r.get("run_date")]
    # Deterministic preview when the new instrument has not run yet. Never
    # rebuild new wording with the date of an old-version forecast.
    preview = Path(load_ladder()["provenance"]["source_definitions"]).stem[-10:]
    return date.fromisoformat(max(days) if days else preview)


def build(today=None):
    ru = _runner()
    rows = instrument_rows(current_rows(load_runlog()))
    recorded = max((r for r in rows if r.get("prompt")),
                   key=lambda r: r["elicited_at"], default=None) if today is None else None
    today = today or (date.fromisoformat(recorded["run_date"]) if recorded else latest_run_date())
    policies = ru.load_policies(ru.COMBINED)
    conds = ru.expand_conditions(["all"], policies)
    groups, by_group, horizons, _skipped, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
    # The set AS OF that day (redlines.questions.questions_asked_on): a question
    # added since the latest run (the extinction pair, 2026-09-15) is not in
    # the prompt those forecasts answered, so the counts below describe the
    # recorded prompt and not the next run's.
    asked = questions_asked_on(today)
    by_group = {k: [q for q in qs if q["id"] in asked] for k, qs in by_group.items()}
    horizons = ru.set_horizons(policies, horizons)
    prompt, n, cells = ru.build_prompt_joint(groups, by_group, horizons, spec, conds, policies, today)
    if recorded:
        prompt = recorded["prompt"]
    prov = panel_provenance()
    return {
        "today": today.isoformat(),
        "promptRecorded": bool(recorded),
        "promptSha256": recorded.get("prompt_sha256") if recorded else None,
        "system": ru.SYSTEM,
        "prompt": prompt,
        # The tag the recorded prompt was sent under, else the one the next
        # run will carry.
        "protocol": (recorded.get("protocol") if recorded else None) or ru.set_protocol(policies),
        "conditionSet": ru.set_slug(policies),
        "nQuestions": n,
        "cells": cells,
        "k": len(conds) + 1,
        "chars": len(prompt),
        "panel": {k: v for k, v in prov.items() if k != "age_days"},
    }
