"""The ECI-ranked roster the two conditional benches ran on: data/causal/models.csv.

Twenty-four models, every one reachable through OpenRouter, ranked by the
Epoch Capabilities Index as Epoch published it on 2026-08-27 (the `eci`
column; code/causal/model_scores.csv is the list it was resolved from). It is
the roster of the causal bench's locked dataset (data/causal/README.md) and,
since 2026-08-28, of the observational bench's roster run
(code/observational/run_roster.py) -- one x-axis for both "Why trust this?"
conditional charts.

ECI VINTAGE. This is a third vintage next to the two redlines.eci manages:
Graph 4 is pinned to 2026-07-07 and the panel is chosen from the newest
snapshot (a leaderboard top-17 that does not reach the roster's weaker
models). The roster's values are part of the locked dataset -- re-deriving
them from a later snapshot would move a published headline (the causal
rho) -- so they are read from the dataset and never recomputed. The
difference is small (Fable 5: 162.49 here, 162 in the 2026-08-28 snapshot)
and is stated on the charts.

Labels are the dashboard's (redlines.registry) where the model is in the
registry, so the same model reads the same everywhere; the rest are the
OpenRouter display names without the vendor prefix.
"""
from __future__ import annotations

import csv
from functools import lru_cache

from .config import REPO_ROOT
from .registry import MODELS, RETIRED_COLOR, color_for, published_panel

ROSTER = REPO_ROOT / "data" / "causal" / "models.csv"
# The Graph 4 ladder's models the causal roster lacks (GPT-3.5 .. Opus 4.8),
# resolved to OpenRouter ids for the observational bench's roster run; their
# ECI is the registry's pinned vintage (`eci_source`), since the roster's
# 2026-08-27 vintage never listed them. Project lead, 2026-08-28: Graph 5
# should carry at least the models Graph 4 does.
ROSTER_EXTRA = REPO_ROOT / "data" / "observational" / "roster_extra.csv"

# OpenRouter display name (vendor prefix stripped) -> short label. Registry
# labels first (looked up by epoch_name at import time), then the rest.
_SHORT = {
    "Claude Fable": "Fable 5",
    "Claude Sonnet 5": "Sonnet 5",
    "Qwen3 235B A22B": "Qwen3 235B",
    "Gemini 3.1 Flash Lite Preview": "Gemini 3.1 Flash Lite",
    "Gemini 3 Flash Preview": "Gemini 3 Flash",
    "DeepSeek V4 Flash 0731": "DeepSeek V4 Flash",
    "o4 Mini": "o4-mini",
}

# The 2026-08-20 observational run called the Anthropic API directly; its
# model ids map onto the roster's OpenRouter ids like this.
ANTHROPIC_IDS = {
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-opus-5": "anthropic/claude-opus-5",
    "claude-fable-5": "anthropic/claude-fable-5",
}


def _registry_by_epoch_name():
    return {m["epoch_name"]: m for m in MODELS}


# OpenRouter display name -> the registry's epoch_name where they differ.
_EPOCH_ALIASES = {"Claude Fable": "Claude Fable 5", "DeepSeek V3": "DeepSeek-V3"}


def _registry_row(display_name: str):
    name = display_name.split(": ", 1)[-1]
    return _registry_by_epoch_name().get(_EPOCH_ALIASES.get(name, name))


def short_label(display_name: str) -> str:
    name = display_name.split(": ", 1)[-1]
    reg = _registry_row(display_name)
    return reg["label"] if reg else _SHORT.get(name, name)


@lru_cache(maxsize=1)
def load():
    """[{id, label, name, eci, reasoning, inPanel, color}] sorted by ECI ascending.

    `inPanel`: the model is in the dashboard's current panel
    (redlines.registry.panel -- matched on the litellm id, which for the
    models in question is the OpenRouter id). `color`: a panel member's
    registry colour, the same on every chart; RETIRED_COLOR for everyone
    else, registry row or not (project lead, 2026-09-08).
    """
    by_key = {m["key"]: m for m in MODELS}
    panel_ids = {row["litellm_id"] for row, _ in published_panel()}
    members = {row["key"] for row, _ in published_panel()}
    out = []
    with open(ROSTER, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            reg = _registry_row(r["name"])
            out.append({
                "id": r["openrouter_id"],
                "label": short_label(r["name"]),
                "name": r["name"],
                "eci": float(r["eci"]),
                "eciSource": "data/causal/models.csv (2026-08-27)",
                "source": "causal",
                "reasoning": r["reasoning_capable"].lower() == "true",
                "inPanel": r["openrouter_id"] in panel_ids,
                "color": color_for(reg, members) if reg else RETIRED_COLOR,
            })
    ids = {m["id"] for m in out}
    if ROSTER_EXTRA.exists():
        with open(ROSTER_EXTRA, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["openrouter_id"] in ids:
                    raise ValueError(f"{ROSTER_EXTRA.name}: {r['openrouter_id']} is already on the causal roster")
                reg = by_key[r["registry_key"]]
                out.append({
                    "id": r["openrouter_id"],
                    "label": reg["label"],
                    "name": r["name"],
                    "eci": float(r["eci"]),
                    "eciSource": r["eci_source"],
                    "source": "g4",
                    "reasoning": r["reasoning_capable"].lower() == "true",
                    "inPanel": reg["litellm_id"] in panel_ids,
                    "color": color_for(reg, members),
                })
    out.sort(key=lambda m: m["eci"])
    return out


def by_id():
    return {m["id"]: m for m in load()}
