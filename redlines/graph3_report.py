"""Render the Graph 3 comparability tables in docs/methodology.md from data.

`code/graph3_comparability.py` measures the config / round / vintage
decomposition and writes `results/graph3_comparability.json`. This module turns
that JSON into the markdown tables the methodology doc cites, so the numbers are
never copied by hand.

The doc carries marked regions:

    <!-- BEGIN GENERATED graph3:<name> (python3 -m redlines.graph3_report) -->
    ...table...
    <!-- END GENERATED graph3:<name> -->

and this module rewrites only what sits between a BEGIN/END pair. Prose around
the tables is left alone.

    python3 -m redlines.graph3_report            # rewrite docs/methodology.md
    python3 -m redlines.graph3_report --check    # exit 1 if the doc is stale
    python3 -m redlines.graph3_report --print    # print the tables, touch nothing

Stdlib only, like the build stage. The test suite runs the --check comparison
(tests/test_graph3_report.py), so the doc and the JSON cannot drift apart.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "results" / "graph3_comparability.json"
DOC_PATH = ROOT / "docs" / "methodology.md"

MINUS = "\u2212"   # the doc uses a typographic minus for negative changes
ARROW = "\u2192"

# Version-bump rows name models the way the prose does: drop the
# " (zero shot)" config suffix, and shorten the names whose ForecastBench ids
# carry a snapshot date nobody reads. GPT ids keep their dates, as in the doc.
SHORT_NAMES = {
    "Claude-Sonnet-4-5-20250929": "Claude-Sonnet-4-5",
    "Grok-4.20-0309-Reasoning": "Grok-4.20-Reasoning",
}

BEGIN_RE = re.compile(
    r"^<!-- BEGIN GENERATED graph3:(?P<name>[a-z0-9-]+)[^>]*-->\n"
    r"(?P<body>.*?)"
    r"^<!-- END GENERATED graph3:(?P=name) -->$",
    re.MULTILINE | re.DOTALL,
)


# --- formatting --------------------------------------------------------------

def _signed(x: float, places: int = 3) -> str:
    """+0.017 / −0.012 (typographic minus), the doc's convention for changes."""
    s = f"{x:+.{places}f}"
    return s.replace("-", MINUS)


def _short(model: str) -> str:
    name = model.removesuffix(" (zero shot)")
    return SHORT_NAMES.get(name, name)


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# --- the tables --------------------------------------------------------------

def decomposition(report: dict) -> str:
    """The headline config / round / vintage table."""
    return _table(
        ["source of variation", "effect on Brier", "how it was measured"],
        [
            ["prompt config", f"**{report['config_spread']:.3f}**",
             "same round, same questions, scaffold varied"],
            ["round (question set + horizon mix)", f"**{report['round_effect']:.3f}**",
             "*the same model*, scored across rounds"],
            ["model vintage", f"**{report['vintage_effect']:.3f}**",
             "one round, one question set, older models vs frontier"],
        ],
    )


def horizons(report: dict) -> str:
    """Resolved rows per round and the share at 90-day horizons or longer."""
    rows = []
    for round_, h in sorted(report["horizons"].items()):
        pct = 100 * h["ge90d"] / h["total"] if h["total"] else 0.0
        rows.append([round_, f"{h['total']:,}", f"{pct:.0f}%"])
    return _table(["round", "resolved rows", "\u226590-day"], rows)


def vintage(report: dict) -> str:
    """Older-vs-frontier crowd Brier inside each round."""
    rows = []
    for round_, v in sorted(report["vintage"].items()):
        rows.append([round_, f"{v['older']['brier']:.4f}", f"{v['frontier']['brier']:.4f}",
                     f"{v['gap']:+.3f}", f"{v['within_round_model_spread']:.3f}"])
    return _table(["round", "older", "frontier", "gap",
                   "spread between individual models"], rows)


def version_bumps(report: dict) -> str:
    """Consecutive versions from one lab and tier, best improvement first.

    The largest improvement and the largest regression are bolded."""
    pairs = []
    for key, v in report["family_pairs"].items():
        round_, rest = key.split(" ", 1)
        old, new = rest.split(" -> ")
        pairs.append((round_, old, new, v))
    rounds = sorted({p[0] for p in pairs})
    if len(rounds) != 1:
        raise ValueError(f"version-bump table expects one round, got {rounds}")
    pairs.sort(key=lambda p: -p[3]["gap"])
    hi, lo = pairs[0][3]["gap"], pairs[-1][3]["gap"]
    rows = []
    for _, old, new, v in pairs:
        change = _signed(v["gap"])
        if v["gap"] in (hi, lo):
            change = f"**{change}**"
        rows.append([f"{_short(old)} {ARROW} {_short(new)}",
                     f"{v['old']['brier']:.4f} {ARROW} {v['new']['brier']:.4f}", change])
    return _table([f"version bump ({rounds[0]})", "Brier", "change"], rows)


SECTIONS = {
    "decomposition": decomposition,
    "horizons": horizons,
    "vintage": vintage,
    "version-bumps": version_bumps,
}


# --- doc sync ----------------------------------------------------------------

def render_all(report: dict) -> dict[str, str]:
    return {name: fn(report) for name, fn in SECTIONS.items()}


def regions(doc: str) -> dict[str, str]:
    """{name: current body} for every generated region in the doc."""
    return {m["name"]: m["body"].rstrip("\n") for m in BEGIN_RE.finditer(doc)}


def sync(doc: str, rendered: dict[str, str]) -> str:
    """The doc with every generated region replaced by its rendered table.

    Raises if a section has no region in the doc, or the doc names a region
    this module does not know — either means the markers and code disagree."""
    found = regions(doc)
    missing = sorted(set(rendered) - set(found))
    unknown = sorted(set(found) - set(rendered))
    if missing or unknown:
        raise ValueError(f"generated regions out of step with the generator: "
                         f"missing from doc {missing}, unknown in doc {unknown}")

    def repl(m: re.Match) -> str:
        begin = m.group(0).split("\n", 1)[0]
        return f"{begin}\n{rendered[m['name']]}\n<!-- END GENERATED graph3:{m['name']} -->"

    return BEGIN_RE.sub(repl, doc)


def stale(doc: str, rendered: dict[str, str]) -> list[str]:
    """Names of regions whose body differs from what the JSON renders."""
    found = regions(doc)
    return [n for n in rendered if found.get(n) != rendered[n]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", type=Path, default=JSON_PATH)
    ap.add_argument("--doc", type=Path, default=DOC_PATH)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="exit 1 if the doc's generated regions disagree with the JSON")
    mode.add_argument("--print", action="store_true", dest="print_",
                      help="print the rendered tables and exit")
    a = ap.parse_args(argv)

    rendered = render_all(json.loads(a.json.read_text()))
    if a.print_:
        for name, body in rendered.items():
            print(f"## {name}\n\n{body}\n")
        return 0

    doc = a.doc.read_text()
    new = sync(doc, rendered)   # validates the markers either way
    if a.check:
        bad = stale(doc, rendered)
        if bad:
            print(f"{a.doc}: generated regions out of date: {', '.join(bad)}\n"
                  f"  re-run: python3 -m redlines.graph3_report", file=sys.stderr)
            return 1
        print(f"{a.doc}: generated regions match {a.json.name}")
        return 0
    if new != doc:
        a.doc.write_text(new)
        print(f"rewrote {a.doc}")
    else:
        print(f"{a.doc}: already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
