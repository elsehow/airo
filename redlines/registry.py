"""redlines.registry — the single model table: ids, labels, ECI, colors, architecture.

Before this module the model set was defined in five places under five naming
conventions:

  code/eci_scores.py     DEMO_MODEL_SET (9) + GAP_FILLERS (2) + ALT_HIGH_ANCHOR (1)
  archive/legacy-questions/run_forecasts.py  MODELS -- the frontier five
  code/make_demo_graph1.py  MODEL_COLORS      -- frontier-five display colors
  code/pandemic_smoke.py    SMOKE_MODELS      -- hand-typed ECI integers (!)
  code/make_demo_graph3.py  DASH_MODELS       -- ForecastBench display names

MODELS below is the union: one row per distinct model, tagged with every role
it plays. ECI is always looked up from a dated snapshot of the official Epoch
Capabilities Index by epoch_name at import time -- never hand-copied
(docs/model-set.md). Which snapshots exist, which is newest and how old it is
are redlines.eci's business; this module only says which vintage each number
comes from.

THE MODEL PANEL (since 2026-08-28) is not a hand-typed list. It is the
PANEL_K highest-ECI models in the NEWEST snapshot that this table can run
(panel()), re-ranked every time it is asked for -- the rule measured in
~/Projects/forecastbench-ensembling (docs/eci-top4-arm.md): average the top
3-4 by ECI; the specific list goes stale fast, so never inherit one. The
hand-typed frontier five survive as the named set `frontier5`, the panel the
series ran on until then.
"""
from datetime import date
import functools
import json
import sys
from pathlib import Path

from . import eci as _eci

REPO_ROOT = Path(__file__).resolve().parent.parent
# Graph 4's vintage. Models already in this file keep its values, so the
# ladder and every tracked artifact stay byte-identical -- refreshing those
# values is a separate, deliberate change that has to be re-baselined against
# tests/. The 2026-09-08 snapshot (eci.SUPPLEMENT), then the newest, are
# consulted ONLY for models the pinned file predates (Claude Opus 5 shipped
# 2026-07-24, GPT-5.6 Sol 2026-07-09).
EPOCH_CSV = _eci.snapshot_path(_eci.PINNED)


def load_epoch_index(csv_path: Path = EPOCH_CSV, supplement: Path | None = None) -> dict[str, dict]:
    """Official Epoch Capabilities Index, keyed by exact model name -> row dict.

    The pinned snapshot wins; the supplements fill in only models it never
    had -- `supplement` if given, else the frozen eci.SUPPLEMENT snapshot and
    then the newest one, in that order (so a fetched snapshot adds new
    models without moving the ones already drawn).
    """
    idx = _eci.load(csv_path)
    chain = [supplement] if supplement else [_eci.snapshot_path(_eci.SUPPLEMENT), _eci.latest()[1]]
    for sup in chain:
        if sup and Path(sup).exists() and Path(sup) != Path(csv_path):
            for name, rec in _eci.load(sup).items():
                idx.setdefault(name, rec)
    return idx


# ── The model table ─────────────────────────────────────────────────────────
# roles are a subset of:
#   frontier5      archive/legacy-questions/run_forecasts.py MODELS (news-grounded runner)
#   g4_ladder      code/eci_scores.py DEMO_MODEL_SET (the base 9-model ECI ladder;
#                  since 2026-08-27 also GPT-5.5 / Gemini 3.1 Pro / Grok 4.20, so
#                  every model the dashboard runs sits on Graph 4's ladder)
#   g4_gapfiller   code/eci_scores.py GAP_FILLERS (the +2 137/143 gap-fillers)
#   pandemic_smoke code/pandemic_smoke.py SMOKE_MODELS
#   graph3_dash    code/make_demo_graph3.py DASH_MODELS (ForecastBench display names)
#
# architecture: public facts only -- never guessed. One of:
#   "moe"          -- publicly documented mixture-of-experts (DeepSeek-V3's
#                      technical report).
#   "dense"        -- publicly documented dense transformer (Llama-3.3-70B's
#                      model card).
#   "distilled"    -- publicly documented distillation from a larger teacher.
#                      No row uses this today; reserved for when one does.
#   "undisclosed"  -- every closed-vendor model (OpenAI/Anthropic/Google/xAI):
#                      the lab has not published architecture details. This is
#                      not "we didn't check" -- it's the honest label for
#                      "the vendor keeps it private."
#
# TODO.md Phase 2's Graph-4 subset rule (redlines/views/graph4.py build()):
# the CLEAN SUBSET excludes architecture in {"moe", "distilled"} -- i.e.
# architectures known to behave differently from a plain dense transformer,
# which is a real confound for a capability-vs-skill trend line -- and keeps
# "dense" + "undisclosed". "undisclosed" stays IN the clean subset: absence of
# a public architecture claim is not evidence of a confounded one, and
# excluding on suspicion rather than fact would just be guessing with extra
# steps.
#
# colors: the frontier five's are the fixed categorical assignments from
# code/make_demo_graph1.py's MODEL_COLORS, CVD-validated against the demo's
# light panel; the 2026-08-28 panel members got theirs with the ECI top-4 arm.
# Every other row carries a muted spare so that, the day the index ranks it
# into the panel, the views can draw it -- none of those has been drawn yet,
# and they are chosen only to sit apart from the eight above and from the
# cause palette (CATEGORIES, data/autoarc_ladder.json).
# family: the line whose versions supersede one another, for the panel's
# within-family rule (project lead, 2026-09-08: skip Fable 5 when Fable 5.1
# is seated). One seat per family, the highest-ranked member takes it. The
# assignment is by hand and is a judgement: Claude's tiers (Fable, Opus,
# Sonnet, Haiku) are separate lines; OpenAI's plain GPT-n are one line, the
# Pro tier another, and the code-named GPT-5.6 Sol / GPT-6 Astra each their
# own -- so the 2026-09-08 panel seats Astra beside GPT-5.5 Pro. Fold two
# families into one here if that ever reads wrong; nothing else changes.
_ROWS = [
    # key,                  family,          label,             litellm_id,                                                fb_name,                       epoch_name,                   color,      architecture,  roles
    ("gpt-3.5-turbo",       "gpt",           "GPT-3.5",         "openai/gpt-3.5-turbo-0125",                                None,                          "GPT-3.5 Turbo (Jan 2024)",  "#6b7280",       "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    ("llama-3.3-70b",       "llama",         "Llama-3.3-70B",   "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo",        None,                          "Llama 3.3 70B",             "#5b8c2a",       "dense",       ["g4_ladder", "pandemic_smoke"]),
    ("gpt-4o",              "gpt",           "GPT-4o",          "openai/gpt-4o",                                            None,                          "GPT-4o (Nov 2024)",         "#b8860b",       "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    ("deepseek-v3",         "deepseek",      "DeepSeek-V3",     "deepinfra/deepseek-ai/DeepSeek-V3",                        None,                          "DeepSeek-V3",               "#1b5e9e",       "moe",         ["g4_ladder", "pandemic_smoke"]),
    ("claude-sonnet-4-5",   "claude-sonnet", "Sonnet 4.5",      "anthropic/claude-sonnet-4-5-20250929",                     None,                          "Claude Sonnet 4.5",         "#c2185b",       "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    ("gpt-5",               "gpt",           "GPT-5",           "openai/gpt-5-2025-08-07",                                  None,                          "GPT-5",                     "#2e7d32",       "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    ("claude-opus-4-6",     "claude-opus",   "Opus 4.6",        "anthropic/claude-opus-4-6",                                None,                          "Claude Opus 4.6",           "#795548",       "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    ("claude-opus-4-8",     "claude-opus",   "Opus 4.8",        "anthropic/claude-opus-4-8",                                "Claude-Opus-4-8",             "Claude Opus 4.8",           "#d97e2e",  "undisclosed", ["g4_ladder", "frontier5", "graph3_dash"]),
    ("claude-fable-5",      "claude-fable",  "Fable 5",         "anthropic/claude-fable-5",                                 None,                          "Claude Fable 5",            "#b52a55",  "undisclosed", ["g4_ladder", "frontier5"]),
    ("gpt-4.1",             "gpt",           "GPT-4.1",         "openai/gpt-4.1-2025-04-14",                                None,                          "GPT-4.1",                   "#00838f",       "undisclosed", ["g4_gapfiller", "pandemic_smoke"]),
    ("claude-haiku-4-5",   "claude-haiku",  "Haiku 4.5",       "anthropic/claude-haiku-4-5-20251001",                      None,                          "Claude Haiku 4.5",          "#e0a020",       "undisclosed", ["g4_gapfiller", "pandemic_smoke"]),
    ("gpt-5.5-pro",         "gpt-pro",       "GPT-5.5 Pro",     "openai/gpt-5.5-pro",                                       None,                          "GPT-5.5 Pro",               "#c25a2e",  "undisclosed", []),  # ALT_HIGH_ANCHOR; in the ECI panel since 2026-08-28
    ("gpt-5.5",             "gpt",           "GPT-5.5",         "openai/gpt-5.5",                                           "GPT-5.5-2026-04-23",          "GPT-5.5",                   "#4a76c9",  "undisclosed", ["g4_ladder", "pandemic_smoke", "frontier5", "graph3_dash"]),
    ("gemini-3.1-pro",      "gemini-pro",    "Gemini 3.1 Pro",  "gemini/gemini-3.1-pro-preview",                            "Gemini-3.1-Pro-Preview",      "Gemini 3.1 Pro",            "#1f8a70",  "undisclosed", ["g4_ladder", "pandemic_smoke", "frontier5", "graph3_dash"]),
    ("grok-4.20",           "grok",          "Grok 4.20",       "xai/grok-4.20",                                            "Grok-4.20-0309-Reasoning",    "Grok 4.20",                 "#8a63c9",  "undisclosed", ["g4_ladder", "pandemic_smoke", "frontier5", "graph3_dash"]),
    # Added 2026-08-28 with the ECI top-4 arm (docs/eci-top4-arm.md), now
    # panel members by rank. On Graph 4's ladder since 2026-08-28 evening
    # (project lead: Graph 4 should get Opus 5 and GPT-5.6 Sol) -- run through both
    # simulators exactly as the rest. Their ECI is the newest snapshot's, not
    # the pinned vintage (neither existed on 2026-07-07); the gap is about a
    # point (docs/model-set.md). GPT-5.5 Pro stays off: ~$100-250 per sim.
    ("claude-opus-5",       "claude-opus",   "Opus 5",          "anthropic/claude-opus-5",                                  None,                          "Claude Opus 5",             "#7a4fa3",  "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    ("gpt-5.6-sol",         "gpt-sol",       "GPT-5.6 Sol",     "openai/gpt-5.6-sol",                                       None,                          "GPT-5.6 Sol",               "#2f6f9f",  "undisclosed", ["g4_ladder", "pandemic_smoke"]),
    # Added 2026-09-08 with the ECI snapshot of that day: the index's new top
    # two. Panel members by rank from the first run after; not on Graph 4's
    # ladder (never run through the simulators). GPT-6 Astra goes through
    # litellm's Responses bridge (openai/responses/...): on /v1/chat/completions
    # OpenAI refuses function tools for it under any reasoning_effort, and the
    # grounding tools are the point (probed on the box 2026-09-08).
    ("claude-fable-5-1",    "claude-fable",  "Fable 5.1",       "anthropic/claude-fable-5-1",                               None,                          "Claude Fable 5.1",          "#8e2a63",  "undisclosed", []),
    ("gpt-6-astra",         "gpt-astra",     "GPT-6 Astra",     "openai/responses/gpt-6-astra",                             None,                          "GPT-6 Astra",               "#0e7c7b",  "undisclosed", []),
    # Added 2026-10-01: Epoch's index of that day ranks them first and third
    # (167.3 and 165.2), so they take the claude-opus seat from Opus 5 and a
    # claude-sonnet seat of their own; GPT-5.5 Pro leaves the panel. Probed on
    # the box the same day: max (adaptive) reasoning accepted, priced by
    # litellm 1.96.2, and -- like Fable 5.1 -- a forced tool_choice refused
    # (redlines/llm.py: NO_FORCED_TOOL_CHOICE). Not on Graph 4's ladder.
    ("claude-opus-5-5",     "claude-opus",   "Opus 5.5",        "anthropic/claude-opus-5-5",                                None,                          "Claude Opus 5.5",           "#4f5bd5",  "undisclosed", []),
    ("claude-sonnet-5-5",   "claude-sonnet", "Sonnet 5.5",      "anthropic/claude-sonnet-5-5",                              None,                          "Claude Sonnet 5.5",         "#d4892a",  "undisclosed", []),
]

# Graph-4 clean-subset rule (TODO.md Phase 2). A model is excluded from the
# "clean subset" trend iff its architecture is a known-confounded one -- see
# the architecture field comment above for what's in/out and why.
CONFOUNDED_ARCHITECTURES = frozenset({"moe", "distilled"})

_FIELDS = ("key", "family", "label", "litellm_id", "fb_name", "epoch_name", "color", "architecture", "roles")


def _build_models() -> list[dict]:
    idx = load_epoch_index()
    out = []
    for row in _ROWS:
        d = dict(zip(_FIELDS, row))
        rec = idx.get(d["epoch_name"]) if d["epoch_name"] else None
        if rec is None:
            raise KeyError(f"Epoch name not in CSV: {d['epoch_name']!r} (key={d['key']!r})")
        # The pinned vintage (Graph 4's), as before. Integers: both formats
        # the pinned file has ever been in carried whole scores.
        d["eci"], d["ci_low"], d["ci_high"] = int(rec["eci"]), rec["ci_low"], rec["ci_high"]
        if d["color"] is None:
            raise ValueError(f"registry row {d['key']!r} has no color; any runnable row "
                             "can be ranked into the panel and must be drawable")
        out.append(d)
    return out


MODELS = _build_models()


# ── Cause-category palette (code/make_demo_graph1.py CATEGORIES, verbatim) ────
# Rail groups. TWO now, not four (Auto-ARC swap, 2026-08-18): the three
# cross-cutting questions, then the incident types Graph 1 features at the 1M
# rung. Nuclear left the question set entirely and Biorisk stopped being a
# top-level category -- it is one of four AI incident types. The per-CAUSE
# palette moved to data/autoarc_ladder.json, where the causes themselves live;
# these two colors are only the rail's group headings.
# Single source of truth -- the timeline page groups its rail the same way.
# Unified cause palette (2026-08-13): one hue per cause across every surface
# (Graph 1/timeline rail dots, Graph 2 curves + supers diamonds), chosen to
# not collide with the model palette above — the old values reused model hues
# (rail purple = Grok, G2 ai-crimson = Fable, bio-teal = Gemini, nuclear-blue
# = GPT-5.5), so the same color meant different things on different graphs.
# Validated (CVD + normal-vision separation + chroma/lightness, dataviz
# six-checks) as the trio #33a8bd/#a63d76/#a1801a on the page surface; slate
# is the deliberate neutral for the aggregate, matching Graph 1's black
# ensemble convention. The cyan's 2.7:1 surface contrast is relieved by
# direct curve-end labels wherever it draws as a line.
# code/make_ladder_questions.py::CAUSES carries the same four values.
CATEGORIES = [
    ("crosscutting", "Catastrophe & disempowerment", "#3a4150"),
    ("incident",     "AI incident types",            "#33a8bd"),
]


def by_role(role: str) -> list[dict]:
    """MODELS entries carrying `role`, in MODELS order."""
    return [m for m in MODELS if role in m["roles"]]


def demo_set_with_eci(include_gap_fillers: bool = False) -> list[dict]:
    """Join the demo ladder (+ optional gap-fillers) to ECI, sorted ascending.

    Byte-exact port of code/eci_scores.py::demo_set_with_eci -- same dict shape
    (model_id, label, epoch_name, access, eci, ci_low, ci_high), same sort, same
    values. Consumed by run_eval.py and make_demo_combined.py.
    """
    roles = {"g4_ladder"} | ({"g4_gapfiller"} if include_gap_fillers else set())
    rows = [m for m in MODELS if roles & set(m["roles"])]
    out = [{"model_id": m["litellm_id"], "label": m["label"], "epoch_name": m["epoch_name"],
            "access": m["litellm_id"].split("/", 1)[0], "eci": m["eci"],
            "ci_low": m["ci_low"], "ci_high": m["ci_high"]}
           for m in rows]
    return sorted(out, key=lambda r: r["eci"])


# archive/legacy-questions/run_forecasts.py's frontier five and
# code/make_demo_graph1.py's MODEL_COLORS share this exact order (by ECI
# descending, as both files had it hand-typed) -- not derivable by sorting
# since it isn't ascending, so it's pinned explicitly.
_FRONTIER_ORDER = ["claude-fable-5", "gpt-5.5", "claude-opus-4-8", "gemini-3.1-pro", "grok-4.20"]



def frontier_models() -> list[tuple[str, str]]:
    """(label, litellm_id) pairs in the legacy runner's original MODELS order
    (archive/legacy-questions/run_forecasts.py): the hand-picked panel the
    series ran on until 2026-08-28."""
    by = {m["key"]: m for m in MODELS}
    return [(by[k]["label"], by[k]["litellm_id"]) for k in _FRONTIER_ORDER]


# ── The panel: top-k by ECI, from the newest snapshot ────────────────────────
# k = 4. ~/Projects/forecastbench-ensembling: averaging the top 3-4 by ECI
# beats the single best-ranked model and closes the gap to the hindsight-best
# one; at 5 the marginal model is already below the frontier. Ties at the cut
# are broken by Epoch's own rank order and WARNed, so a panel that hinges on
# a coin-flip says so in the log. ONE SEAT PER FAMILY (2026-09-08): a model
# whose family already holds a seat is passed over, named in a WARN, and the
# next runnable model takes the seat -- two versions of one model are one
# opinion twice, not two members (see `family` on _ROWS).
PANEL_K = 4
PANEL_SET = "eci_topk"


def _warn(msg):
    print(f"WARN: {msg}", file=sys.stderr)


@functools.lru_cache(maxsize=None)
def _select(k, snapshot):
    """-> (members, warnings): members are (registry row, index record) pairs,
    best first. Cached per (k, snapshot) so a build that asks five views'
    worth of times reads the CSV once and warns once."""
    day, path = snapshot
    by_epoch = {m["epoch_name"]: m for m in MODELS}
    ranked = _eci.ranked(path)
    chosen, unrunnable, passed, warnings = [], [], [], []
    msg = _eci.stale_message()
    if msg:
        warnings.append(msg)
    seated = {}
    for r in ranked:
        m = by_epoch.get(r["model"])
        if m is None:
            unrunnable.append(r)
            continue
        if m["family"] in seated:
            passed.append((m, r, seated[m["family"]]))
            continue
        chosen.append((m, r))
        seated[m["family"]] = m
        if len(chosen) == k:
            break
    for m, r, holder in passed:
        warnings.append(f"passed over {r['model']} ({r['eci']:g}): its family "
                        f"({m['family']}) already holds a seat through {holder['epoch_name']}; "
                        f"the next runnable model took the seat")
    if len(chosen) < k:
        warnings.append(f"only {len(chosen)} of the top {k} in {path.name} are models the "
                        f"registry can run; the panel is short")
    if chosen:
        cut = chosen[-1][1]
        above = [r["model"] for r in unrunnable if (r["eci"], -r["rank"]) > (cut["eci"], -cut["rank"])]
        if above:
            warnings.append(f"the index ranks {', '.join(above)} above the panel's cut but the "
                            f"registry cannot run them (no row in redlines/registry.py); "
                            f"skipped, the next runnable model took the seat")
        tied = [r["model"] for r in ranked if r["eci"] == cut["eci"]
                and r["model"] not in {m["epoch_name"] for m, _ in chosen}]
        if tied:
            warnings.append(f"tie at the cut: {cut['model']} ({cut['eci']:g}) is in the panel "
                            f"and {', '.join(tied)} ({cut['eci']:g}) out, on Epoch's rank order")
    for w in warnings:
        _warn(w)
    return tuple(chosen), tuple(warnings)


def panel(k=PANEL_K, snapshot=None):
    """The model panel: the k highest-ECI runnable models in the newest
    snapshot, best first, as (registry row, index record) pairs. Prints a
    WARN for a stale snapshot, an unrunnable model above the cut, or a tie
    at it (once per process per snapshot)."""
    snapshot = snapshot or _eci.latest()
    members, _ = _select(k, snapshot)
    return list(members)


def snapshot_of(rows):
    """(date, path) of the snapshot the newest stamped row's panel was chosen
    from, or None when no row carries one or that file is not in data/."""
    stamped = [r for r in rows if (r.get("panel") or {}).get("snapshot")]
    if not stamped:
        return None
    newest = max(stamped, key=lambda r: (r.get("run_date") or "", r.get("elicited_at") or ""))
    day = date.fromisoformat(newest["panel"]["snapshot"])
    path = _eci.snapshot_path(day)
    return (day, path) if path.exists() else None


@functools.lru_cache(maxsize=None)
def record_snapshot():
    """(date, path) of the snapshot the newest scheduled run (results/runs/)
    chose its panel from; the newest snapshot when no run says."""
    from .runlog import RUNS_DIR
    for p in sorted(RUNS_DIR.glob("*.jsonl"), reverse=True):
        with open(p, encoding="utf-8") as f:
            first = next((line for line in f if line.strip()), None)
        snap = snapshot_of([json.loads(first)]) if first else None
        if snap:
            return snap
    return _eci.latest()


def published_panel(k=PANEL_K, rows=None):
    """The panel the DASHBOARD draws: the one the newest run was chosen as
    (its rows' stamped snapshot -- `rows` if given, else results/runs/),
    not panel(), the one the NEXT run will be. Since 2026-10-01 the index is
    fetched before every run, so the two differ from the fetch until that
    run lands; the views must not blank or recolor in between. Same rule,
    same registry: a past run's panel is re-derived from its snapshot."""
    snap = (snapshot_of(rows) if rows is not None else None) or record_snapshot()
    return panel(k, snap)


def panel_warnings(k=PANEL_K, snapshot=None):
    snapshot = snapshot or _eci.latest()
    return list(_select(k, snapshot)[1])


def eci_topk_models() -> list[tuple[str, str]]:
    """(label, litellm_id) pairs for the panel, ECI-descending."""
    return [(m["label"], m["litellm_id"]) for m, _ in panel()]


def panel_provenance(model_set=PANEL_SET, k=PANEL_K):
    """What a run should stamp on its rows: which set, and for the panel,
    which snapshot chose it and how old that was."""
    if model_set != PANEL_SET:
        return {"set": model_set}
    day, path = _eci.latest()
    return {"set": model_set, "k": k, "snapshot": day.isoformat(),
            "age_days": _eci.age_days(),
            "members": [{"label": m["label"], "eci": r["eci"], "rank": r["rank"]}
                        for m, r in panel(k)]}


MODEL_SETS = {PANEL_SET: eci_topk_models, "frontier5": frontier_models}
DEFAULT_MODEL_SET = PANEL_SET


# Every model outside the current panel draws in this one muted gray, on
# every chart (project lead, 2026-09-08: current models keep a consistent
# color scheme everywhere; deprecated models, out of the ensemble, are shown
# in gray). A panel member's color is its registry row's, the same on every
# surface; a model that leaves the panel turns gray everywhere the next
# build, and its row keeps its color for the day it returns. Apart from the
# ink (#1f2328), the faint ink (#6e7781) and the model palette.
RETIRED_COLOR = "#a3a9b1"


def color_for(model: dict, members=None) -> str:
    """The color a chart draws `model` (a MODELS row) in: its own if it holds
    a panel seat, RETIRED_COLOR otherwise."""
    if members is None:
        members = {m["key"] for m, _ in published_panel()}
    return model["color"] if model["key"] in members else RETIRED_COLOR


def model_colors() -> list[tuple[str, str]]:
    """(label, color) for every model the views may draw: the published panel
    (published_panel) first, in panel order and in its own colors, then every other registry
    model by ECI descending (newest snapshot's value where it has one, the
    pinned one otherwise), all in RETIRED_COLOR.

    A superset on purpose. The run log holds the retired panels' history and
    the current one's future; a view iterates this list and skips models
    absent from its data, so a panel change needs no edit here.
    """
    members = [m["key"] for m, _ in published_panel()]
    by_key = {m["key"]: m for m in MODELS}
    current = {r["model"]: r["eci"] for r in _eci.ranked(record_snapshot()[1])}
    rest = sorted((m for m in MODELS if m["key"] not in members),
                  key=lambda m: (-current.get(m["epoch_name"], m["eci"]), m["label"]))
    return [(by_key[k]["label"], by_key[k]["color"]) for k in members] + \
           [(m["label"], RETIRED_COLOR) for m in rest]


if __name__ == "__main__":
    for gf in (False, True):
        rows = demo_set_with_eci(include_gap_fillers=gf)
        lo, hi = rows[0]["eci"], rows[-1]["eci"]
        print(f"\nDemo set{' + gap-fillers' if gf else ''} "
              f"({len(rows)} models, ECI {lo} -> {hi}):")
        for r in rows:
            print(f"  {r['eci']:>3}  {r['label']:14s}  {r['model_id']:52s} [{r['access']}]")
    day, path = _eci.latest()
    print(f"\npanel ({PANEL_SET}, k={PANEL_K}) from {path.name}, {_eci.age_days()} days old:")
    for m, r in panel():
        print(f"  {r['eci']:>5g}  rank {r['rank']:2d}  {m['label']:14s}  {m['litellm_id']}")
    for w in panel_warnings():
        print(f"  WARN {w}")
    print(f"\nfrontier5: {frontier_models()}")
    print(f"model_colors: {model_colors()}")
