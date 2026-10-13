"""News stories, steps 2 and 3: does a story move the AIRO forecast, and how.

Step 1 (redlines/news.py) folds feed items into stories. This module takes
the stories from there:

  SCREEN (step 2). Per story, one Jev call with the story and the latest AIRO
  ensemble forecast in the state, and one Noul per cause family
  (data/autoarc_ladder.json: ai, bio, cyber, misalign): "would a forecaster
  holding this forecast change its probabilities after reading this story?"
  A story is flagged when any family reaches SCREEN_AT.

  EXPLAIN (step 3). For a flagged story, the panel's highest-ECI model writes
  the note AIRO would publish: whether the story moves the forecast, which
  questions, rungs and horizons, which way, how much in words, and why. It
  ends with a one-word VERDICT the code parses.

  CALIBRATE. Opus-class notes are the judgment the screen is a cheap proxy
  for, so they grade it. Notes are written for the flagged stories AND for a
  sample just below the threshold (`audit_below`): flagged stories alone can
  show a threshold that is too low (flags the writer says do not move
  anything) but never one that is too high (stories it missed). `calibrate`
  sets Jev's p against the writer's verdicts and suggests a threshold.

WHY THE SCREEN SEES THE FORECAST. The first PoC screen (2026-10-13) asked
whether a story was ABOUT a cause family, and flagged every frontier launch;
the writer then said those launches moved nothing, because the panel had
priced them in. Whether news moves a forecast depends on what the forecast
already assumes, so the state carries the ensemble medians and the panel's own
reasoning, abridged (Jev's notes on large states: keep it short).

WHICH FORECAST. The newest run in results/runs/ (redlines/runlog.py), pooled
per (question, model) as the dashboard does, the ensemble being the median
across the panel. `runs_dir` points elsewhere, e.g. at the raw/runs/ of the
public download (redlines-data.zip), when this checkout lags production.

WHICH WRITER. The highest-ECI model among the forecast's panel, ranked by the
ECI snapshot that run chose its panel from, and called by the litellm id the
run itself used (the row's `model`), so a model the production box added on
its own (redlines/autoreg) is still callable here.

Every decision is logged append-only in the state directory, like the reduce:
  screen.jsonl   one row per (story, forecast, members shown): p per family
  notes.jsonl    one row per note: writer, text, verdict, usage
and reused on the next run when its key matches, so a re-run costs nothing.
"""
import json
import os
import re
import statistics
from datetime import date
from pathlib import Path

from . import news

ROOT = Path(news.ROOT)
DATA = ROOT / "data"

SCREEN_AT = 0.3         # p(moves the forecast) at which a story is flagged. Deliberately
                        # low: a miss is never explained, a false flag costs one note.
                        # `calibrate` says whether the writer's verdicts agree.
SCREEN_HORIZONS = ("12mo", "2030", "2100")   # what the screen's forecast table shows
RATIONALE_CHARS = 1500  # per panel model, in the screen's state
NOTE_RATIONALE_CHARS = 2500
WRITER_MAX_TOKENS = 64000   # max-effort thinking used 40k on one note (2026-10-13);
                            # 20k left a note with no text
VERDICTS = ("none", "negligible", "small", "moderate", "large")
MOVES = ("small", "moderate", "large")   # a verdict that counts as "moves the forecast"

FAMILY = {"ai": "AI-related incidents (any kind)", "cyber": "AI-related cyber incidents",
          "bio": "AI-related human-caused epidemics", "misalign": "misaligned-AI incidents"}


# ------------------------------------------------------------- forecast

def _median(xs):
    return statistics.median(xs) if xs else None


def _pct(p):
    if p is None:
        return "–"
    return f"{p * 100:.3g}%" if p >= 0.001 else f"{p * 100:.2g}%"


def find_snapshot(day, dirs):
    """(date, path) of the ECI snapshot for `day` in the first of `dirs` that
    holds it, else None."""
    for d in dirs:
        p = Path(d) / f"epoch_capabilities_index_{day}.csv"
        if p.exists():
            return date.fromisoformat(day), p
    return None


def load_forecast(runs_dir=None, questions_dir=DATA, snapshot_dirs=(DATA,)):
    """The latest ensemble forecast: {run, day, models, model_ids, cells
    {qid: {horizon: [p per model]}}, rationales {label: text}, ladder, cross,
    snapshot}."""
    from . import runlog
    runs_dir = Path(runs_dir) if runs_dir else runlog.RUNS_DIR
    rows = runlog.load_runlog(runlog=runs_dir / "__none__.jsonl", runs_dir=runs_dir)
    if not rows:
        raise ValueError(f"no forecast rows under {runs_dir}")
    day = max(runlog.elicitation_date(r) for r in rows)
    pooled = [r for r in runlog.latest_pooled(rows).values() if runlog.elicitation_date(r) == day]
    cells = {}
    for r in pooled:
        for f in r["forecasts"]:
            cells.setdefault(r["question_id"], {}).setdefault(f["horizon"], []).append(f["probability"])
    models = sorted({r["label"] for r in pooled})
    first = {}
    for r in sorted(pooled, key=lambda r: r["question_id"]):
        first.setdefault(r["label"], r)
    snap_day = ((pooled[0].get("panel") or {}).get("snapshot"))
    return {"run": max(r["run_id"] for r in pooled), "day": str(day), "models": models,
            "model_ids": {m: first[m]["model"] for m in models},
            "rationales": {m: first[m].get("rationale") or "" for m in models},
            "cells": cells,
            "ladder": json.load(open(Path(questions_dir) / "autoarc_ladder.json")),
            "cross": json.load(open(Path(questions_dir) / "autoarc_crosscutting.json")),
            "snapshot": find_snapshot(snap_day, snapshot_dirs) if snap_day else None}


def ensemble(fc, qid, h):
    """(median, min, max) across the panel, or None."""
    ps = fc["cells"].get(qid, {}).get(h)
    return (_median(ps), min(ps), max(ps)) if ps else None


def writer(fc):
    """(label, litellm id, eci) of the forecast panel's highest-ECI model. The
    index names models with their maker ("Claude Opus 5.5"), the panel by
    label ("Opus 5.5")."""
    from . import eci
    snap = fc["snapshot"] or eci.latest()
    ranked = eci.ranked(snap[1])
    for r in ranked:
        for m in fc["models"]:
            if r["model"] == m or r["model"].endswith(" " + m):
                return m, fc["model_ids"][m], r["eci"]
    raise ValueError(f"no panel model ({fc['models']}) in {snap[1].name}")


def screen_state(fc):
    """The forecast as the screen sees it: medians for each family's ladder at
    a few horizons, and each panel model's reasoning, abridged."""
    def table(c):
        return {q["severity"]["label"]: {h: _pct((ensemble(fc, q["id"], h) or (None,))[0])
                                         for h in SCREEN_HORIZONS}
                for q in fc["ladder"]["questions"] if q["cause"] == c}
    return {"elicited": fc["day"], "panel": fc["models"],
            "what_it_forecasts": "the probability that AI-related incidents cumulatively cause "
                                 "deaths or economic damages at each severity level, by each horizon",
            "ensemble_median_by_family": {FAMILY[c]: table(c) for c in FAMILY},
            "panel_reasoning": {m: fc["rationales"][m][:RATIONALE_CHARS] for m in fc["models"]}}


# --------------------------------------------------------------- screen

def screen_question(c):
    return {"type": "noul",
            "instructions": f"Would a forecaster holding `airo_forecast` change any of its "
                            f"probabilities for {FAMILY[c]} after reading `story`?",
            "criteria": {
                "true": "Yes: `story` reports a new event or finding that the forecast's reasoning has "
                        "not already accounted for and that bears on how likely these incidents are: "
                        "an incident that counts toward or approaches a severity level, a new "
                        "dangerous-capability or safety finding, or a change to safeguards, restraints "
                        "or policies the panel relies on.",
                "false": "No: `story` is expected or already accounted for in the forecast's reasoning, "
                         "or does not bear on how likely these incidents are: business, markets, "
                         "earnings, routine launches at or near the existing frontier, jobs, culture "
                         "or opinion."}}


def story_reports(story, items, n=3):
    return [news.item_view(items[m["item"]]) for m in story["members"][:n]]


def _screen_key(story, fc):
    return [story["id"], fc["run"], [m["item"] for m in story["members"][:3]]]


def screen(stories, items, fc, decisions, ask=None, log=None, now=None):
    """{story id: screen row} for every story, from the log where its key
    matches (same story, forecast and shown members) and from Jev otherwise.
    With ask=None nothing is called and unlogged stories are left out."""
    logged = {json.dumps(d["key"]): d for d in decisions}
    state_fc = None
    out = {}
    for s in stories:
        key = _screen_key(s, fc)
        row = logged.get(json.dumps(key))
        if row is None and ask is not None:
            state_fc = state_fc or screen_state(fc)
            r = ask({"story": {"reports": story_reports(s, items)}, "airo_forecast": state_fc},
                    {c: screen_question(c) for c in FAMILY})
            row = {"at": now or news._now(), "key": key, "story": s["id"], "title": s["title"],
                   "forecast": fc["run"], "model": r.get("model"), "usage": r.get("usage"),
                   "p_moves": {c: round(float(r["answers"][c]["noul"]), 4) for c in FAMILY},
                   "screen_at": SCREEN_AT}
            log and log(row)
        if row is not None:
            out[s["id"]] = row
    return out


def p_max(row):
    return max(row["p_moves"].values())


def flagged(row, at=None):
    return p_max(row) >= (SCREEN_AT if at is None else at)


# -------------------------------------------------------------- explain

SYSTEM = ("You are a member of AIRO's forecasting panel. AIRO publishes ensemble forecasts of "
          "AI-related catastrophic risk, elicited from a panel of frontier models. When AI news "
          "breaks, AIRO publishes a short note on whether and how the news bears on its current "
          "forecast.")


def _table(fc, rows, label):
    hz = fc["ladder"]["horizons"]
    out = [f"| {label} | " + " | ".join(hz) + " |", "|---|" + "---|" * len(hz)]
    for qid, name in rows:
        cs = [ensemble(fc, qid, h) for h in hz]
        out.append(f"| {name} | " + " | ".join(
            f"{_pct(c[0])} ({_pct(c[1])}–{_pct(c[2])})" if c else "–" for c in cs) + " |")
    return "\n".join(out)


def explain_prompt(story, items, fc, causes, today=None):
    """The writer's user prompt: the story's reports, the ensemble forecast for
    the families the screen flagged plus the cross-cutting questions, the
    panel's reasoning, and the task, ending in a VERDICT line."""
    today = today or news._now()[:10]
    sections = []
    for c in causes or ["ai"]:
        qs = [q for q in fc["ladder"]["questions"] if q["cause"] == c]
        sections.append(f"### {qs[0]['cause_label']} ladder\n\nQuestion (one per severity rung): "
                        f"{qs[0]['text']}\n\nResolution criteria (abridged): {qs[0]['criteria'][:1500]}\n\n"
                        + _table(fc, [(q["id"], q["severity"]["label"]) for q in qs], "severity"))
    cq = fc["cross"]["questions"]
    sections.append("### Cross-cutting questions\n\n"
                    + "\n".join(f"- {q['name']}: {q['text'][:400]}" for q in cq) + "\n\n"
                    + _table(fc, [(q["id"], q["name"]) for q in cq], "question"))
    reports = "\n".join(
        f"- {items[m['item']]['source']} ({(items[m['item']].get('published') or '')[:10]}): "
        f"\"{items[m['item']]['title']}\""
        + (f" — {items[m['item']]['summary']}" if items[m['item']].get("summary") else "")
        for m in story["members"])
    rationales = "\n\n".join(f"**{m}**: {fc['rationales'][m][:NOTE_RATIONALE_CHARS]}" for m in fc["models"])
    return f"""Today is {today}. The latest AIRO ensemble forecast was elicited on {fc['day']} from a panel of {len(fc['models'])} models ({", ".join(fc['models'])}).

## The news story

"{story['title']}" — {len(story['members'])} reports, {story['first_seen'][:10]} to {story['last_seen'][:10]}. You have the headlines and standfirsts only, not the full articles:

{reports}

## The current forecast

Each cell is the ensemble median across the panel, with the panel's range in brackets. Horizons: 6mo and 12mo run from the forecast date; the years mean by the end of that year.

{chr(10).join(sections)}

### The panel's rationales (each model's own, abridged)

{rationales}

## Your task

Write the note AIRO would publish about this story, for a reader who follows AI risk but not the details of AIRO's question set. In 120–250 words of plain prose:

1. Say whether this news should move the forecast at all, and if so which questions, which severity rungs and which horizons, and in which direction. Give the size in words (no change / negligible / small / moderate / large); do not give new numbers.
2. Explain the mechanism: why this kind of development does or does not change the chance of the incidents these questions count, referring to the panel's reasoning where it helps.
3. Name what would have to be true, or come out next, for this story to matter more than you judge it does.

Be calibrated rather than dramatic. Most news should not move a forecast of rare catastrophic incidents, and saying so plainly is a good answer. Work only from what the reports say; where the headlines leave something unknown, say so rather than assume.

End with one final line, on its own, of the form `VERDICT: <size>`, where <size> is one of none, negligible, small, moderate, large: the largest change you judge this story warrants to any question."""


def parse_verdict(text):
    """(note without the VERDICT line, verdict or None)."""
    m = re.search(r"^\s*\**VERDICT:?\**\s*:?\s*\**\s*([a-z]+)", text or "", re.I | re.M)
    if not m or m[1].lower() not in VERDICTS:
        return (text or "").strip(), None
    return (text[:m.start()] + text[m.end():]).strip(), m[1].lower()


def default_complete(model, system, prompt):
    """One call through the repo's litellm wrapper (production settings:
    max reasoning effort for the Claude family)."""
    from . import llm
    llm.load_keys()
    r = llm._litellm_complete(model, [{"role": "system", "content": system},
                                      {"role": "user", "content": prompt}],
                              max_tokens=WRITER_MAX_TOKENS, temperature=1.0)
    return {"text": r.get("content"), "usage": r.get("usage")}


def explain(story, items, fc, screen_row, complete=None, now=None):
    """One note for one story: the writer's text, its parsed verdict and the
    call's usage. Raises if the writer returns no text (all thinking)."""
    label, model_id, eci = writer(fc)
    causes = [c for c, p in screen_row["p_moves"].items() if p >= SCREEN_AT] if screen_row else []
    prompt = explain_prompt(story, items, fc, causes, today=(now or news._now())[:10])
    r = (complete or default_complete)(model_id, SYSTEM, prompt)
    if not (r.get("text") or "").strip():
        raise RuntimeError(f"{label} returned no text for {story['id']} (usage {r.get('usage')})")
    text, verdict = parse_verdict(r["text"])
    return {"at": now or news._now(), "story": story["id"], "title": story["title"],
            "forecast": fc["run"], "writer": label, "model": model_id, "eci": eci,
            "causes": causes, "p_moves": screen_row and screen_row["p_moves"],
            "flagged": bool(screen_row) and flagged(screen_row), "text": text, "verdict": verdict,
            "usage": r.get("usage"), "prompt_chars": len(SYSTEM) + len(prompt)}


def pick_for_notes(stories, screened, notes, flagged_n=1, audit_below=0):
    """Which stories to write notes for: up to `flagged_n` flagged stories,
    newest first, plus an audit sample of `audit_below` stories under the
    threshold. Half the audit is the highest-p stories just under it (the ones
    a slightly lower threshold would flag); the rest is spread evenly down the
    remaining ranks, because a real mover Jev scored far below the threshold
    is the miss that matters most and the boundary alone never finds it.
    Skips stories that already have a note on this forecast."""
    have = {(n["story"], n["forecast"]) for n in notes}
    rows = [(s, screened[s["id"]]) for s in stories if s["id"] in screened
            and (s["id"], screened[s["id"]]["forecast"]) not in have]
    up = sorted([p for p in rows if flagged(p[1])], key=lambda p: p[0]["last_seen"], reverse=True)
    down = sorted([p for p in rows if not flagged(p[1])], key=lambda p: -p_max(p[1]))
    near = (audit_below + 1) // 2
    rest = down[near:]
    k = audit_below - near
    spread = [rest[round((i + 1) * (len(rest) - 1) / k)] for i in range(k)] if rest and k else []
    audit = down[:near] + [p for i, p in enumerate(spread) if p not in spread[:i]]
    return [s for s, _ in up[:flagged_n]] + [s for s, _ in audit]


# ------------------------------------------------------------ calibrate

def calibrate(screened, notes):
    """Set Jev's p against the writer's verdicts. Returns {pairs: [(p, verdict,
    title)], at: SCREEN_AT, false_flags, misses, suggest}. `suggest` is the
    highest threshold that still flags every story the writer said moves the
    forecast (verdict in MOVES), or None when the notes hold no such story; the
    reading is only as good as the sample below the threshold."""
    pairs = sorted(((p_max(screened[n["story"]]), n["verdict"], n["title"]) for n in notes
                    if n["story"] in screened and n.get("verdict")), reverse=True)
    movers = [p for p, v, _ in pairs if v in MOVES]
    return {"pairs": pairs, "at": SCREEN_AT,
            "false_flags": sum(p >= SCREEN_AT and v not in MOVES for p, v, _ in pairs),
            "misses": sum(p < SCREEN_AT and v in MOVES for p, v, _ in pairs),
            "suggest": round(min(movers), 2) if movers else None}


# ----------------------------------------------------------------- page

PAGE_TEMPLATE = ROOT / "web" / "news" / "stories.html"


def page_data(state_dir, fc_meta=None):
    built = json.load(open(os.path.join(state_dir, "stories.json")))
    items = news.load_items(state_dir)
    rows = news.read_jsonl(os.path.join(state_dir, "screen.jsonl"))
    latest_run = max((r["forecast"] for r in rows), default=None)
    screened = {r["story"]: r for r in rows if r["forecast"] == latest_run}
    notes = [n for n in news.read_jsonl(os.path.join(state_dir, "notes.jsonl")) if n["forecast"] == latest_run]
    gate = {d["item"]: d["p_ai"] for d in news.read_jsonl(os.path.join(state_dir, "decisions.jsonl"))
            if d["kind"] == "gate"}
    title_of = {s["id"]: s["title"] for s in built["stories"]}
    stories = [{"id": s["id"], "title": s["title"], "first": s["first_seen"], "last": s["last_seen"],
                "sources": s["sources"], "screen": (screened.get(s["id"]) or {}).get("p_moves", {}),
                "members": [{"source": m["source"], "title": m["title"], "url": m["url"],
                             "open": m["open_access"], "p": m["p_same"]} for m in s["members"]],
                "related": [{"title": title_of.get(r["story"], ""), "p": r["p_followup"]}
                            for r in s["related"]]}
               for s in built["stories"]]
    fetches = news.read_jsonl(os.path.join(state_dir, "fetches.jsonl"))
    cal = calibrate(screened, notes)
    return {"meta": {"items": built["stats"]["items"], "stories": len(stories), "built": built["built_at"],
                     "polls": len({f["at"] for f in fetches}), "feeds": len({f["feed"] for f in fetches}),
                     "same_at": built["thresholds"]["same_at"], "screen_at": SCREEN_AT,
                     "forecast": (fc_meta or {}).get("day") or latest_run,
                     "panel": (fc_meta or {}).get("models") or []},
            "stories": stories,
            "dropped": [{"title": items[i]["title"], "p": gate.get(i)} for i in built["dropped"]],
            "notes": {n["story"]: {k: n[k] for k in ("text", "verdict", "writer", "eci", "flagged")}
                      for n in notes},
            "calibration": {"pairs": cal["pairs"], "false_flags": cal["false_flags"],
                            "misses": cal["misses"], "suggest": cal["suggest"]}}


def render_page(state_dir, out_path, fc_meta=None):
    """The stories page, as one self-contained HTML file. It embeds headlines,
    so it is written to the state directory or outside the repo, never into it."""
    data = json.dumps(page_data(state_dir, fc_meta), ensure_ascii=False).replace("</", "<\\/")
    html = PAGE_TEMPLATE.read_text().replace("__DATA__", data)
    Path(out_path).write_text(html)
    return out_path
