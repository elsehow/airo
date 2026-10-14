"""News stories, step 2: how much does the week's news move the forecast?

Step 1 (redlines/news.py) folds feed items into stories, one per real-world
event. This module takes every story first reported after the latest AIRO
forecast was elicited and gives all of them, in one call, to the panel's
highest-ECI model, which says how much the news, taken together, should move
the AI-related incident ladder (data/autoarc_ladder.json, cause "ai"): one
odds ratio per severity rung and horizon, the 9 x 6 table the forecast itself
fills, and a short rationale citing the stories that drive it.

WHAT THE MODEL SEES OF A STORY: its brief (`brief`). The headline, outlet and
date of up to three reports, the publisher's standfirst where the feed gave
one, and the opening BRIEF_WORDS words of the first report whose article could
be read, in member order. A story none of whose articles could be read is
marked headline only. Every story gets the same budget, so none reads as
weightier for having more text, and every condition sees the same briefs.

TWO FRAMES. "airo": the model sees the forecast (ensemble medians with the
panel's range, and each panel model's rationale, abridged) and is asked how
it should move. "generic": it sees the ladder's questions but no numbers, and
is asked how a careful forecaster's probabilities should move. Both answer in
odds ratios, so the two are comparable cell by cell.

ORDER. The stories are labelled S1.. in one fixed shuffle; "reversed" lists
the same labels back to front, a check on position effects.

WHICH FORECAST. The newest run in results/runs/ (redlines/runlog.py), pooled
per (question, model) as the dashboard does, the ensemble being the median
across the panel. `runs_dir` points elsewhere, e.g. at the raw/runs/ of the
public download (redlines-data.zip), when this checkout lags production.

WHICH WRITER. The highest-ECI model among the forecast's panel, ranked by the
ECI snapshot that run chose its panel from, and called by the litellm id the
run itself used. One call, thinking only: no tools.

Each call is logged append-only to update.jsonl in the state directory.
"""
import json
import os
import random
import re
import statistics
from datetime import date
from pathlib import Path

from . import news

ROOT = Path(news.ROOT)
DATA = ROOT / "data"

CAUSE = "ai"              # the ladder the model answers for: AI-related incidents of any kind
BRIEF_WORDS = 250         # of the article's opening, per story
RATIONALE_CHARS = 2500    # per panel model, in the airo frame
WRITER_MAX_TOKENS = 64000 # max-effort thinking used 40k on one note (2026-10-13)
SEED = 0
FRAMES = ("airo", "generic")
ORDERS = ("forward", "reversed")
LOG = "update.jsonl"


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
    {qid: {horizon: [p per model]}}, rationales {label: text}, ladder, snapshot}."""
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
            "snapshot": find_snapshot(snap_day, snapshot_dirs) if snap_day else None}


def ensemble(fc, qid, h):
    """(median, min, max) across the panel, or None."""
    ps = fc["cells"].get(qid, {}).get(h)
    return (_median(ps), min(ps), max(ps)) if ps else None


def rungs(fc):
    """The ladder's questions for CAUSE, least severe first."""
    return [q for q in fc["ladder"]["questions"] if q["cause"] == CAUSE]


def horizons(fc):
    return list(fc["ladder"]["horizons"])


def base_table(fc):
    """[[median per horizon] per rung]: the forecast the odds ratios apply to."""
    return [[(ensemble(fc, q["id"], h) or (None,))[0] for h in horizons(fc)] for q in rungs(fc)]


def writer(fc):
    """(label, litellm id, eci) of the forecast panel's highest-ECI model. The
    index names models with their maker ("Claude Opus 5.5"), the panel by
    label ("Opus 5.5")."""
    from . import eci
    snap = fc["snapshot"] or eci.latest()
    for r in eci.ranked(snap[1]):
        for m in fc["models"]:
            if r["model"] == m or r["model"].endswith(" " + m):
                return m, fc["model_ids"][m], r["eci"]
    raise ValueError(f"no panel model ({fc['models']}) in {snap[1].name}")


def forecast_time(fc):
    """When the forecast was elicited, from the run id ("2026-10-09T1200Z")."""
    d, t = fc["run"].split("T")
    return f"{d}T{t[:2]}:{t[2:4]}:00Z"


def first_report(story, items):
    return min(news.item_time(items[m["item"]]) for m in story["members"])


def after_forecast(stories, items, fc):
    """Stories whose first report came out after the forecast was elicited: the
    only news the forecast cannot already reflect."""
    cut = forecast_time(fc)
    return [s for s in stories if first_report(s, items) > cut]


# ---------------------------------------------------------------- briefs

def brief(story, items, words=BRIEF_WORDS):
    """What the model sees of a story: {reports: [{source, published, headline,
    standfirst?}] for up to three reports, excerpt: {source, text} or None}.
    Standfirsts are the publisher's own; one written from the article
    (news.load_items) is left off, since the excerpt carries the article."""
    reports = []
    for m in story["members"][:news.STORY_REPORTS]:
        it = items[m["item"]]
        r = {"source": it["source"], "published": news.item_time(it)[:10], "headline": it["title"]}
        if it.get("summary") and it.get("summary_from") != "article":
            r["standfirst"] = it["summary"]
        reports.append(r)
    it = news.first_readable(story, items)
    text = news.opening(it["text"], it["title"], words) if it else ""
    return {"reports": reports, "excerpt": {"source": it["source"], "headline": it["title"], "text": text}
            if text else None}


def brief_text(label, story, items):
    """A story's brief as the prompt shows it."""
    b = brief(story, items)
    n = len(story["members"])
    lines = [f"### {label} ({n} report{'s' if n > 1 else ''})"]
    for r in b["reports"]:
        lines.append(f"- {r['source']} ({r['published']}): \"{r['headline']}\""
                     + (f" — {r['standfirst']}" if r.get("standfirst") else ""))
    if b["excerpt"]:
        lines.append(f"\nOpening of the {b['excerpt']['source']} article:\n> {b['excerpt']['text']}")
    else:
        lines.append("\n(Headline only: no article could be read.)")
    return "\n".join(lines)


def listing(stories, seed=SEED, order="forward"):
    """[(label, story)]: one fixed shuffle, labelled S1.. in that order; "reversed"
    lists the same labels back to front, to test for position effects."""
    ss = sorted(stories, key=lambda s: s["id"])
    random.Random(seed).shuffle(ss)
    out = [(f"S{i + 1}", s) for i, s in enumerate(ss)]
    return out[::-1] if order == "reversed" else out


# ---------------------------------------------------------------- prompt

SYSTEM = ("You are a member of AIRO's forecasting panel. AIRO publishes ensemble forecasts of "
          "AI-related catastrophic risk, elicited from a panel of frontier models. When AI news "
          "breaks, AIRO publishes a short note on whether and how the news bears on its current "
          "forecast.")
SYSTEM_GENERIC = ("You forecast catastrophic risk from AI. When AI news breaks, you write a short note "
                  "on whether and how it should change forecasts of AI-related catastrophic risk.")


def _ladder(fc, numbers):
    qs, hz = rungs(fc), horizons(fc)
    head = (f"Question (one per severity rung, R1 least severe): {qs[0]['text']}\n\n"
            f"Resolution criteria (abridged): {qs[0]['criteria'][:1500]}\n\n"
            "Horizons: 6mo and 12mo run from the forecast date; the years mean by the end of that year.\n\n")
    if not numbers:
        return head + "\n".join(f"- R{i + 1}: {q['severity']['label']}" for i, q in enumerate(qs))
    rows = [f"| rung | " + " | ".join(hz) + " |", "|---|" + "---|" * len(hz)]
    for i, q in enumerate(qs):
        cs = [ensemble(fc, q["id"], h) for h in hz]
        rows.append(f"| R{i + 1}: {q['severity']['label']} | " + " | ".join(
            f"{_pct(c[0])} ({_pct(c[1])}–{_pct(c[2])})" if c else "–" for c in cs) + " |")
    return head + "Each cell is the ensemble median across the panel, with the panel's range in brackets.\n\n" \
        + "\n".join(rows)


def answer_rule(fc):
    n, hz = len(rungs(fc)), horizons(fc)
    return f"""End with exactly these final lines, and nothing after them:

ODDS RATIOS ({", ".join(hz)})
{chr(10).join(f"R{i + 1}: <{len(hz)} numbers>" for i in range(n))}
STORIES: <ids>

Each number is your median estimate of the odds ratio for that rung and horizon: the factor by which the odds, p/(1-p), should be multiplied in light of this news. 1 means no change, above 1 more likely, below 1 less likely; give two or more decimals (e.g. 1.00, 1.04, 0.97). The {len(hz)} numbers on a line are the horizons in the order above, comma-separated. <ids> lists the stories that drive the change, comma-separated (e.g. S12, S40), or "none"."""


def prompt(lst, items, fc, frame="airo", today=None):
    """The user prompt: every story's brief, the ladder (with the forecast's
    numbers in the airo frame), and the task."""
    today = today or news._now()[:10]
    cut = forecast_time(fc)
    stories = "\n\n".join(brief_text(label, s, items) for label, s in lst)
    if frame == "airo":
        head = (f"Today is {today}. The latest AIRO ensemble forecast was elicited on {fc['day']} from a panel "
                f"of {len(fc['models'])} models ({', '.join(fc['models'])}).")
        rationales = "\n\n".join(f"**{m}**: {fc['rationales'][m][:RATIONALE_CHARS]}" for m in fc["models"])
        forecast = (f"## The current forecast: AI-related incidents of any kind\n\n{_ladder(fc, True)}\n\n"
                    f"### The panel's rationales (each model's own, abridged; they cover the whole question set)\n\n"
                    f"{rationales}")
        scope = "AIRO's forecast"
    else:
        head = f"Today is {today}."
        forecast = (f"## The questions: AI-related incidents of any kind\n\nForecasters of catastrophic risk from AI "
                    f"give a probability for each severity rung at each horizon.\n\n{_ladder(fc, False)}")
        scope = "a careful forecaster's probabilities for these questions"
    return f"""{head}

## The news

Every AI news story first reported since {cut[:10]} {cut[11:16]} UTC, one entry per real-world event (duplicate write-ups have been merged), {len(lst)} stories in no particular order. For each: the headline, outlet and date of up to three reports, the publisher's standfirst where there is one, and the opening of one article where an article could be read, cut at {BRIEF_WORDS} words ("…" marks the cut).

{stories}

{forecast}

## Your task

Judge how much this news, taken together, should move {scope}. Most stories will not matter; a week of news usually moves a forecast of rare catastrophic incidents little or not at all, and saying so plainly is a good answer. Several weak stories pointing the same way can add up; say so where they do.

In 200–400 words of plain prose: which stories, if any, bear on these questions (cite them by id, e.g. S12), through what mechanism, at which severities and horizons, and in which direction; and what would have to come out next for this news to matter more. Work only from what the briefs say; where they leave something unknown, say so rather than assume.

{answer_rule(fc)}"""


NUM = r"[0-9]*\.?[0-9]+(?:e-?[0-9]+)?"


def parse(text, labels, n_rungs, n_horizons):
    """(prose, odds [[ratio per horizon] per rung] or None, [story ids], error or None).
    `labels` maps S-labels to story ids; unknown labels are dropped."""
    odds, cites, keep = {}, None, []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*\**\s*R(\d+)\s*\**\s*:\s*(.*)$", line)
        if m and 1 <= int(m[1]) <= n_rungs and re.fullmatch(rf"\s*{NUM}(\s*,\s*{NUM})*\s*\**\s*", m[2]):
            odds[int(m[1])] = [float(x) for x in re.findall(NUM, m[2])]
            continue
        m = re.match(r"^\s*\**\s*STORIES\s*\**\s*:\s*(.*)$", line, re.I)
        if m:
            cites = [labels[x] for x in re.findall(r"S\d+", m[1]) if x in labels]
            continue
        if re.match(r"^\s*\**\s*ODDS RATIOS", line, re.I):
            continue
        keep.append(line)
    table, error = None, None
    if sorted(odds) != list(range(1, n_rungs + 1)):
        error = f"odds ratios for {len(odds)} of {n_rungs} rungs"
    elif any(len(r) != n_horizons for r in odds.values()):
        error = f"a rung without {n_horizons} odds ratios"
    elif any(x <= 0 for r in odds.values() for x in r):
        error = "an odds ratio at or below 0"
    else:
        table = [odds[i] for i in range(1, n_rungs + 1)]
    return "\n".join(keep).strip(), table, cites or [], error


def default_complete(model, system, user):
    """One call through the repo's litellm wrapper (production settings:
    max reasoning effort for the Claude family)."""
    from . import llm
    llm.load_keys()
    r = llm._litellm_complete(model, [{"role": "system", "content": system},
                                      {"role": "user", "content": user}],
                              max_tokens=WRITER_MAX_TOKENS, temperature=1.0)
    return {"text": r.get("content"), "usage": r.get("usage")}


def update(stories, items, fc, frame="airo", order="forward", complete=None, now=None):
    """One read of every story after the forecast. Returns the row to log; raises
    if the writer returns no text. An answer whose table cannot be parsed is
    still logged, with `error` saying why."""
    label, model_id, eci = writer(fc)
    lst = listing(after_forecast(stories, items, fc), order=order)
    user = prompt(lst, items, fc, frame, today=(now or news._now())[:10])
    system = SYSTEM if frame == "airo" else SYSTEM_GENERIC
    r = (complete or default_complete)(model_id, system, user)
    if not (r.get("text") or "").strip():
        raise RuntimeError(f"{label} returned no text for {frame}/{order} (usage {r.get('usage')})")
    labels = {lab: s["id"] for lab, s in lst}
    text, odds, cites, error = parse(r["text"], labels, len(rungs(fc)), len(horizons(fc)))
    return {"at": now or news._now(), "frame": frame, "order": order, "run": fc["run"],
            "cutoff": forecast_time(fc), "stories": len(lst), "labels": labels,
            "writer": label, "model": model_id, "eci": eci, "text": text, "odds": odds,
            "cites": cites, "error": error, "raw": r["text"] if error else None,
            "usage": r.get("usage"), "prompt_chars": len(system) + len(user)}


# ------------------------------------------------------------ coherence

def implied(base, odds):
    """The forecast after the odds ratios: p' = OR p / (1 - p + OR p)."""
    return [[None if p is None else o * p / (1 - p + o * p) for p, o in zip(pr, orow)]
            for pr, orow in zip(base, odds)]


def violations(table, rung_names, horizon_names, tol=1e-9):
    """Where a table breaks the ladder's logic: a more severe rung more likely
    than a less severe one at the same horizon, or a later horizon less likely
    than an earlier one on the same rung (both count cumulative incidents)."""
    out = []
    for i in range(len(table)):
        for j in range(len(table[i])):
            p = table[i][j]
            if p is None:
                continue
            if i and table[i - 1][j] is not None and p > table[i - 1][j] + tol:
                out.append(f"{rung_names[i]} by {horizon_names[j]} ({_pct(p)}) is above "
                           f"{rung_names[i - 1]} ({_pct(table[i - 1][j])})")
            if j and table[i][j - 1] is not None and p < table[i][j - 1] - tol:
                out.append(f"{rung_names[i]} by {horizon_names[j]} ({_pct(p)}) is below "
                           f"{horizon_names[j - 1]} ({_pct(table[i][j - 1])})")
    return out


# ----------------------------------------------------------------- page

PAGE_TEMPLATE = ROOT / "web" / "news" / "stories.html"


def _usage(u):
    u = u or {}
    return {"in": u.get("input_tokens"), "out": u.get("output_tokens"),
            "thinking": u.get("reasoning_tokens"), "usd": u.get("cost_usd")}


def page_data(state_dir, fc):
    """Everything the page draws: the ladder and the forecast, every story after
    the forecast with its brief, and the newest read in each frame and order."""
    built = json.load(open(os.path.join(state_dir, "stories.json")))
    items = news.load_items(state_dir)
    post = after_forecast(built["stories"], items, fc)
    label_of = {s["id"]: lab for lab, s in listing(post)}
    names = [q["severity"]["label"] for q in rungs(fc)]
    base = base_table(fc)
    runs = {}
    for r in news.read_jsonl(os.path.join(state_dir, LOG)):
        if r["run"] != fc["run"]:
            continue
        row = {k: r.get(k) for k in ("at", "text", "odds", "cites", "error", "writer", "eci", "stories")}
        row["usage"] = _usage(r.get("usage"))
        row["violations"] = violations(implied(base, r["odds"]), names, horizons(fc)) if r.get("odds") else []
        runs.setdefault(r["frame"], {})[r["order"]] = row     # the newest of each frame and order wins
    stories = []
    for s in sorted(post, key=lambda s: int(label_of[s["id"]][1:])):
        stories.append({"id": s["id"], "label": label_of[s["id"]], "title": s["title"],
                        "first": s["first_seen"], "last": s["last_seen"], "sources": s["sources"],
                        "brief": brief(s, items),
                        "members": [{"source": m["source"], "title": m["title"], "url": m["url"],
                                     "open": m["open_access"]} for m in s["members"]]})
    fetches = news.read_jsonl(os.path.join(state_dir, "fetches.jsonl"))
    return {"meta": {"items": built["stats"]["items"], "stories": len(built["stories"]), "built": built["built_at"],
                     "polls": len({f["at"] for f in fetches}), "feeds": len({f["feed"] for f in fetches}),
                     "same_at": built["thresholds"]["same_at"], "run": fc["run"], "forecast": fc["day"],
                     "cutoff": forecast_time(fc), "panel": fc["models"], "brief_words": BRIEF_WORDS,
                     "dropped": len(built["dropped"])},
            "ladder": {"rungs": names, "horizons": horizons(fc), "base": base,
                       "base_violations": violations(base, names, horizons(fc))},
            "stories": stories, "runs": runs}


def render_page(state_dir, out_path, fc):
    """The page, as one self-contained HTML file. It embeds headlines and
    article openings, so it is written to the state directory or outside the
    repo, never into it."""
    data = json.dumps(page_data(state_dir, fc), ensure_ascii=False).replace("</", "<\\/")
    html = PAGE_TEMPLATE.read_text().replace("__DATA__", data)
    Path(out_path).write_text(html)
    return out_path
