"""redlines.autoreg -- a model the index ranks into the panel joins it with no hand step.

THE GAP (2026-10-07). Since 2026-10-01 the box fetches Epoch's index before
every run, so the panel re-ranks on its own -- but only among models with a
row in redlines/registry.py. GPT-6.1 Sol ranked third on the 2026-10-07
snapshot and sat out that day's run because nobody had typed its row, which
defeats the point of fetching the index (project lead: the panel must follow
the index without anyone checking on it).

WHAT THIS DOES. Run after the fetch (code/cron_run.sh), it walks the newest
snapshot the way registry.panel() does -- best first, one seat per family --
and for each model above the cut that has no row, it

  1. finds the provider from Epoch's `Organization` column and lists that
     provider's models with the key already in the env file;
  2. matches Epoch's display name to exactly one API id: the same letters and
     digits ("GPT-6.1 Sol" = gpt-6.1-sol, "Claude Opus 5.5" = claude-opus-5-5),
     allowing only a trailing date, "preview" or "latest". No match, or two,
     and the model stays out and is paged, as before;
  3. probes it: one short request through the harness's own request path
     (redlines.llm, the configured reasoning effort and its step-down) with
     one tool offered, which must come back as a tool call. A model the run
     would fail on never takes a seat, since one failed model blocks the
     date's publication;
  4. writes the row to data/auto_models.json, which registry.py reads.

The derived fields follow the hand-typed rows' conventions: the label is the
display name without "Claude " ("Opus 5.5"); the family is the name without
its version numbers ("GPT-6.1 Sol" -> gpt-sol, the family GPT-5.6 Sol's row
already has, so the one-seat rule holds across hand and automatic rows); the
color is the spare (SPARE_COLORS) farthest, by OKLab distance under normal,
protan and deutan vision, from the panel members it joins -- only panel
members are drawn in color (registry.RETIRED_COLOR), so that is the set it
has to stand apart from. The color is chosen once and kept, so a model's
color never moves. An entry is never rewritten: a past run's panel is
re-derived from its snapshot through the registry, so the row must outlive
the model's seat. A hand row for the same model always wins.

    python3 -m redlines.autoreg            # resolve and record; exit 0
    python3 -m redlines.autoreg --dry-run  # list what it would add; no probe, no write
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date

from . import eci as _eci
from .config import REPO_ROOT

AUTO_MODELS = REPO_ROOT / "data" / "auto_models.json"

# Epoch `Organization` (lowercased, matched as a substring) -> how to list the
# provider's models and how litellm addresses one. OpenAI goes through the
# Responses bridge: on /v1/chat/completions OpenAI refused function tools for
# GPT-6 Astra (registry.py, 2026-09-08), and every current OpenAI model takes
# the Responses API.
PROVIDERS = [
    ("anthropic", {"key": "ANTHROPIC_API_KEY", "route": "anthropic/{id}",
                   "url": "https://api.anthropic.com/v1/models?limit=1000",
                   "headers": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}}),
    ("openai", {"key": "OPENAI_API_KEY", "route": "openai/responses/{id}",
                "url": "https://api.openai.com/v1/models",
                "headers": lambda k: {"Authorization": f"Bearer {k}"}}),
    ("google", {"key": "GEMINI_API_KEY", "route": "gemini/{id}",
                "url": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
                "headers": lambda k: {"x-goog-api-key": k}}),
    ("xai", {"key": "XAI_API_KEY", "route": "xai/{id}",
             "url": "https://api.x.ai/v1/models",
             "headers": lambda k: {"Authorization": f"Bearer {k}"}}),
]

# Spares for automatic rows, each inside the light surface's lightness band,
# above the chroma floor and at 3:1 against it (the dataviz validator,
# 2026-10-07), and none a hue the hand-typed panel colors already hold.
SPARE_COLORS = ["#c0399b", "#5f8f1f", "#b3261e", "#2d8a4e", "#e05a6f", "#5c4ab0",
                "#9c6b00", "#d14f8c"]

_SUFFIX = re.compile(r"(?:preview|latest|\d{4,8})*")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_id(name, ids):
    """The one API id in `ids` that spells Epoch's `name`, or None. Exact
    (letters and digits) first; else ids that add only a date, "preview" or
    "latest", shortest first. Two equally good candidates are no match."""
    n = norm(name)
    exact = [i for i in ids if norm(i) == n]
    if exact:
        return exact[0] if len(exact) == 1 else None
    near = sorted((i for i in ids if norm(i).startswith(n) and _SUFFIX.fullmatch(norm(i)[len(n):])),
                  key=lambda i: (len(i), i))
    if not near or (len(near) > 1 and len(near[0]) == len(near[1])):
        return None
    return near[0]


def label_for(name):
    return name[len("Claude "):] if name.startswith("Claude ") else name


def family_for(name):
    """The name without its version numbers: 'GPT-6.1 Sol' -> 'gpt-sol',
    'Claude Opus 5.5' -> 'claude-opus', 'DeepSeek-V3' -> 'deepseek'."""
    words = (re.sub(r"[^a-z0-9]", "", w) for w in re.split(r"[\s\-]+", name.lower())
             if not re.fullmatch(r"v?\d+(?:\.\d+)*", w))
    return "-".join(w for w in words if w)


def provider_for(organization):
    org = (organization or "").lower()
    return next(((name, p) for name, p in PROVIDERS if name in org), (None, None))


def list_models(provider):
    """The provider's model ids, with the key from the env (redlines.llm.load_keys)."""
    key = os.environ.get(provider["key"])
    if not key:
        raise RuntimeError(f"{provider['key']} is not set")
    req = urllib.request.Request(provider["url"], headers=provider["headers"](key))
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    items = data.get("data") or data.get("models") or []
    return [(m.get("id") or m.get("name") or "").removeprefix("models/") for m in items]


# ── color: OKLab distance, normal and simulated protan/deutan vision ───────
# Machado, Oliveira & Fernandes (2009), severity 1.0, applied in linear sRGB.
_CVD = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
}


def _linear(hex_):
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def _oklab(rgb):
    r, g, b = rgb
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _seen(hex_, vision):
    rgb = _linear(hex_)
    if vision in _CVD:
        rgb = [min(1.0, max(0.0, sum(k * x for k, x in zip(row, rgb)))) for row in _CVD[vision]]
    return _oklab(rgb)


def separation(a, b):
    """The smallest OKLab distance (x100) between two colors under normal,
    protan and deutan vision -- the validator's ΔE, worst case."""
    return min(100 * sum((x - y) ** 2 for x, y in zip(_seen(a, v), _seen(b, v))) ** 0.5
               for v in ("normal", "protan", "deutan"))


def pick_color(neighbours, taken=()):
    """The spare farthest from every color in `neighbours` (the panel it
    joins, and the retired gray); spares another automatic row holds are
    used only when none is left."""
    pool = [c for c in SPARE_COLORS if c not in set(taken)] or SPARE_COLORS
    return max(pool, key=lambda c: (min((separation(c, n) for n in neighbours), default=100),
                                    -SPARE_COLORS.index(c)))


# ── the probe ───────────────────────────────────────────────────────────────
_PING = {"name": "ping", "description": "Acknowledge the request.",
         "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"]}}


def probe(litellm_id):
    """One request through the harness's request path with one tool offered.
    -> {ok, effort?, error?}: ok when the reply is a call to that tool."""
    from .llm import _fn_spec, _litellm_complete
    try:
        r = _litellm_complete(litellm_id, [{"role": "user", "content": "Call the ping tool with ok=true."}],
                              tools=[_fn_spec(_PING)], max_tokens=4000)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    called = any(c.get("name") == "ping" for c in r.get("tool_calls") or [])
    return {"ok": called, "effort": r.get("reasoning_effort"),
            **({} if called else {"error": "answered without calling the tool"})}


# ── the record ──────────────────────────────────────────────────────────────
def load(path=AUTO_MODELS):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save(entries, path=AUTO_MODELS):
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _candidate(r, listed, keys, lister, day, today):
    """The row Epoch's record `r` would get, from its provider's model list
    (fetched once per provider into `listed`). -> (row, None), or (None, why)."""
    name, prov = provider_for(r.get("organization"))
    if prov is None:
        return None, f"no provider for organization {r.get('organization')!r}"
    if name not in listed:
        try:
            listed[name] = lister(prov)
        except Exception as e:
            listed[name] = e
    if isinstance(listed[name], Exception):
        return None, f"could not list {name} models: {listed[name]}"
    api_id = match_id(r["model"], listed[name])
    if api_id is None:
        return None, f"no single {name} model id spells it"
    if api_id in keys:
        return None, f"key {api_id!r} is taken"
    return {"key": api_id, "family": family_for(r["model"]), "label": label_for(r["model"]),
            "litellm_id": prov["route"].format(id=api_id), "fb_name": None,
            "epoch_name": r["model"], "color": None,
            # Epoch's "Accessibility group"; a closed model's architecture is
            # undisclosed by definition, an open one's is not ours to guess.
            "architecture": "undisclosed" if "closed" in (r.get("access") or "closed").lower() else None,
            "roles": [], "organization": r.get("organization"),
            "resolved_on": (today or date.today()).isoformat(), "snapshot": day.isoformat()}, None


def resolve(k=None, snapshot=None, *, dry_run=False, lister=list_models, prober=probe,
            path=AUTO_MODELS, today=None):
    """Walk the newest snapshot as registry.panel() would and add a row for
    each model above the cut that has none. -> (added, skipped): the new
    entries, and (model, reason) for each one left out."""
    from . import registry
    k = k or registry.PANEL_K
    day, snap = snapshot or _eci.latest()
    entries = load(path)
    by_epoch = {m["epoch_name"]: m for m in registry.MODELS}
    for e in entries:
        by_epoch.setdefault(e["epoch_name"], e)
    keys = {m["key"] for m in by_epoch.values()}
    seated, added, skipped, listed = {}, [], [], {}
    for r in _eci.ranked(snap):
        if len(seated) == k:
            break
        m = by_epoch.get(r["model"])
        new = m is None
        if new:
            m, why = _candidate(r, listed, keys, lister, day, today)
            if m is None:
                skipped.append((r["model"], why))
                continue
        if m["family"] in seated:
            continue
        if new:
            if not dry_run:
                m["probe"] = prober(m["litellm_id"])
                if not m["probe"]["ok"]:
                    skipped.append((r["model"], f"{m['litellm_id']} failed the probe: {m['probe'].get('error')}"))
                    continue
            added.append(m)
            by_epoch[r["model"]] = m
            keys.add(m["key"])
        seated[m["family"]] = m
    # Colors last, against the panel each new member joins.
    taken = [e["color"] for e in entries]
    for m in added:
        others = [s["color"] for s in seated.values() if s is not m and s.get("color")]
        m["color"] = pick_color(others + [registry.RETIRED_COLOR], taken)
        taken.append(m["color"])
    if added and not dry_run:
        save(entries + added, path)
    return added, skipped


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from .llm import load_keys
    load_keys()
    added, skipped = resolve(dry_run="--dry-run" in argv)
    for m in added:
        print(f"added {m['epoch_name']} as {m['litellm_id']} (family {m['family']}, color "
              f"{m['color']}){'' if '--dry-run' not in argv else '  [dry run: not probed, not written]'}")
    for name, why in skipped:
        print(f"skipped {name}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
