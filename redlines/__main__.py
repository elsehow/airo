#!/usr/bin/env python3
"""CLI entry point: python3 -m redlines <command>

Commands:

    build       rebuild each view's blob and inject()-splice it into its page
                (mirrors results/*.json in each shim's original byte format)
    assemble    reassemble the tracked page (index.html) from web/demo/
                chunks + fresh view blob()s via redlines.pages.hydrate_page
    export-fb   write the provisional ForecastBench-2.0 ingest artifact

Rebuilds each dashboard view's blob, mirrors it to results/ in the exact
per-file byte format its old code/make_demo_*.py shim used, and splices it
into the right page via redlines.hydrate.inject. Every builder below is a
direct transcription of the corresponding shim's __main__ block (see
code/make_demo_graph1.py, make_demo_graph2.py, make_demo_graph3.py,
make_demo_combined.py, make_demo_databank.py, and the inline timeline script
ported 2026-08-13) -- same build() call, same inject() call, same mirror-write,
so `python3 -m redlines build` and running each shim individually produce
byte-identical output.

    python3 -m redlines build                # all six views, in order
    python3 -m redlines build --views g1,g3  # just these, still that order
    python3 -m redlines build --list         # list view names and exit

`assemble` is the web/-is-source counterpart: for each page it runs the
views feeding that page's manifest blobs, calls redlines.pages.hydrate_page
to splice them into the chunks under web/<page>/, and writes the result
straight to the manifest's target page. There is one page since 2026-09-08,
when timeline.html was folded into index.html. It writes no results/*.json
mirrors -- only `build` does that -- so `assemble` then `build` (or vice
versa) round-trip to the same tracked bytes; that mutual idempotence is what
tests/test_assemble_golden.py and W4's gauntlet check.

    python3 -m redlines assemble                  # index.html
    python3 -m redlines assemble --pages demo      # the same, by name

`export-fb` is standalone: it is never run as part of build or assemble.

    python3 -m redlines export-fb                          # -> results/fb_export.json
    python3 -m redlines export-fb --out /tmp/fb_export.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from .config import FB_DATASETS_ROOT, FBSIM_ROOT, REPO_ROOT
from .hydrate import inject
from .pages import hydrate_page

# Canonical build order. --views may name a subset but not reorder it -- the
# views are independent (no view reads another's output) so order only
# affects print order, but we keep it fixed for predictable output.
VIEW_ORDER = ["g1", "g2", "g3", "g4", "observational", "causal", "databank", "timeline", "conditional", "capability", "axes", "method", "rationales", "csv"]


def _build_g1():
    from .views import graph1

    blob = graph1.build()
    path = inject("GRAPH1", blob, json_out="results/graph1_data.json")
    n = sum(len(q["series"]) for q in blob["questions"])
    print(f"g1: {len(blob['questions'])} questions, {n} model series, "
          f"{len(blob['runs'])} run(s) -> {path.name}")


def _build_g2():
    from .views import graph2

    blob = graph2.build()
    path = inject("GRAPH2", blob, json_out="results/graph2_data.json")
    n_causes = sum(len(d["causes"]) for d in blob["byHorizon"].values())
    n_viol = sum(len(d["violations"]) for d in blob["byHorizon"].values())
    print(f"g2: {len(blob['byHorizon'])} horizon(s), {n_causes} cause-curve(s), "
          f"{n_viol} violation(s) -> {path.name}")


# Graph 3 and Graph 4 are FROZEN artifacts: their inputs (the ForecastBench
# processed-forecast tarball under FB_DATASETS_ROOT; forecastbench-sim's
# question set under FBSIM_ROOT plus the gitignored results/eval_full.json) are
# not in this repo. When they are present the blobs are rebuilt and the mirrors
# refreshed; when they are not -- a fresh clone, the cron box -- the tracked
# mirror is spliced in unchanged, so build and assemble work everywhere and the
# page never silently loses a panel.
G3_MIRROR = REPO_ROOT / "results" / "graph3_data.json"
G4_MIRROR = REPO_ROOT / "results" / "graph4_combined.json"
G4_EVAL = REPO_ROOT / "results" / "eval_full.json"
G4_QUESTIONS = FBSIM_ROOT / "data" / "lowprob" / "lowprob_questions.json"
G4_PANDEMIC = REPO_ROOT / "results" / "pandemic" / "smoke_preds.json"


def g3_inputs_present():
    return (FB_DATASETS_ROOT / "processed_forecast_sets").is_dir()


def g4_inputs_present():
    return all(p.exists() for p in (G4_EVAL, G4_QUESTIONS, G4_PANDEMIC))


def _mirror(path):
    return json.loads(path.read_text(encoding="utf-8"))


def g3_blob():
    """(blob, how): rebuilt from FB_DATASETS_ROOT, or the tracked mirror."""
    if g3_inputs_present():
        from .views import graph3
        return graph3.build(), "rebuilt"
    return _mirror(G3_MIRROR), f"tracked mirror (no ForecastBench sets under {FB_DATASETS_ROOT})"


def g4_blob():
    """(blob, how): rebuilt from the eval + FBSIM_ROOT inputs, or the tracked mirror."""
    if g4_inputs_present():
        from .views import graph4
        # code/make_demo_combined.py's shim always ran with --final for the
        # tracked mirror (results/graph4_combined.json has preliminary: false).
        return graph4.build(G4_EVAL, G4_QUESTIONS, G4_PANDEMIC, final=True), "rebuilt"
    missing = [str(p) for p in (G4_EVAL, G4_QUESTIONS, G4_PANDEMIC) if not p.exists()]
    return _mirror(G4_MIRROR), f"tracked mirror (missing {', '.join(missing)})"


def _build_g3():
    blob, how = g3_blob()
    path = inject("GRAPH3", blob, json_out="results/graph3_data.json" if how == "rebuilt" else None)
    print(f"g3: bare n={blob['bare']['n']} tools n={blob['tools']['n']} "
          f"sup n={blob['sup']['n']} [{how}] -> {path.name}")


def _build_g4():
    blob, how = g4_blob()
    if how == "rebuilt":
        # Mirror in the shim's original format: indent=2, NO trailing newline --
        # hydrate.inject's own json_out writer adds one, which would break
        # byte-identical output here, so (matching the shim) this view writes
        # its own mirror and calls inject() without json_out.
        G4_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        with open(G4_MIRROR, "w") as fh:
            json.dump(blob, fh, indent=2)
    path = inject("GRAPH4", blob)
    print(f"g4: {blob['nModels']} models, {blob['nQuestions']} questions [{how}] -> "
          f"{G4_MIRROR.name} + {path.name}")


def _build_observational():
    from .views import observational

    blob = observational.build()
    path = inject("OBSERVATIONAL", blob, json_out="results/observational_data.json")
    print(f"observational: {blob['run']['models']} models, {blob['run']['responses']} responses "
          f"from {blob['source']['run']}, rho(ECI, skill) {blob['rho']:+.2f} -> {path.name}")


def _build_causal():
    from .views import causal

    blob = causal.build()
    path = inject("CAUSAL", blob, json_out="results/causal_data.json")
    h = blob["headline"]
    print(f"causal: {h['n']} models, rho(ECI, pooled intervention skill) {h['rho']:+.2f} "
          f"(p={h['p']}) -> {path.name}")


def _build_databank():
    from .views import databank

    # v1 ships bottom-line only; canaries are gated behind
    # make_demo_databank.py --canaries, off by default here too.
    blob = databank.build(include_canaries=False)
    path = inject("DATABANK", blob, json_out="results/databank_data.json")
    bl_n = blob["counts"]["bottomLine"]
    print(f"databank: {bl_n} bottom-line row(s) -> {path.name}")


def _build_timeline():
    from .views import timeline

    blob = timeline.build()
    path = inject("TIMELINE", blob, json_out="results/timeline_data.json")
    print(f"timeline: {len(blob['questions'])} questions, "
          f"{len(blob['snapshots'])} snapshot(s) -> {path.name}")


def _build_conditional():
    from .views import conditional

    # REDLINES_CONDITIONAL_LOGS=a.jsonl:b.jsonl builds from other logs (a
    # smoke, an experiment file) without touching results/conditional_runs.jsonl.
    logs = os.environ.get("REDLINES_CONDITIONAL_LOGS")
    blob = conditional.build(log_path=logs) if logs else conditional.build()
    path = inject("CONDITIONAL", blob, json_out="results/conditional_data.json")
    print(f"conditional: {len(blob['questions'])} questions, "
          f"{len(blob['conditions'])} conditions, {blob['rows']} rows -> {path.name}")


def _build_axes():
    from .views import axes
    blob = axes.build()
    path = inject("AXES", blob, json_out="results/axes_data.json")
    n = sum(len(a["questions"]) for a in blob["axes"])
    print(f"axes: {len(blob['axes'])} axis/axes, {n} question rows, day {blob['day']} -> {path}")
    return path


def _build_capability():
    from .views import capability

    blob = capability.build()
    path = inject("CAPABILITY", blob, json_out="results/capability_data.json")
    print(f"capability: {len(blob['variants'])} variant(s), "
          f"{sum(v['rows'] for v in blob['variants'])} rows, "
          f"{len(blob['eci']['history'])} ECI history points -> {path.name}")


def _build_csv():
    # Not a view: the dataset itself (redlines/export.py), the target of the
    # page's "Download forecasts" button. Built here so one command refreshes
    # the panels and the download they summarise from the same log.
    from .export import (BUNDLE_OUT, DEBRIEFS_OUT, OUT, RATIONALES_OUT, bundle_zip,
                         debriefs_csv, forecasts_csv, rationales_csv)

    n = forecasts_csv()
    print(f"csv: {n} forecasts -> {OUT}")
    # The rationales beside them: one line per (call, question, condition),
    # joined on call_id + question_id + condition.
    m = rationales_csv()
    print(f"csv: {m} rationales -> {RATIONALES_OUT}")
    # And the debriefs (2026-09-15): one line per (call, question group).
    d = debriefs_csv()
    print(f"csv: {d} debriefs -> {DEBRIEFS_OUT}")
    # And the bundle: both CSVs, the raw logs, questions, conditions, README.
    k = bundle_zip()
    print(f"csv: {k} files -> {BUNDLE_OUT} ({BUNDLE_OUT.stat().st_size / 1e6:.1f} MB)")


def _build_method():
    from .views import method

    blob = method.build()
    path = inject("METHOD", blob, json_out="results/method_data.json")
    print(f"method: prompt as of {blob['today']} ({blob['nQuestions']} questions, {blob['cells']} cells x "
          f"{blob['k']} conditions, {blob['chars']} chars), panel of {len(blob['panel'].get('members', []))} -> {path.name}")


def _build_rationales():
    # The explanations behind the current charts' calls (the "Why these
    # forecasts?" panels). Run-log-driven like g1/g2/timeline, so the box's
    # publish must rebuild it after every run or the panels go stale: they
    # show only calls dated the chart's latest reading.
    from .views import rationales

    blob = rationales.build()
    path = inject("RATIONALES", blob, json_out="results/rationales_data.json")
    print(f"rationales: {len(blob['calls'])} call(s) across {len(blob['questions'])} question(s) -> {path.name}")


BUILDERS = {
    "g1": _build_g1,
    "g2": _build_g2,
    "g3": _build_g3,
    "g4": _build_g4,
    "observational": _build_observational,
    "causal": _build_causal,
    "databank": _build_databank,
    "timeline": _build_timeline,
    "conditional": _build_conditional,
    "capability": _build_capability,
    "axes": _build_axes,
    "method": _build_method,
    "rationales": _build_rationales,
    "csv": _build_csv,
}


def _parse_views(spec):
    names = [v.strip() for v in spec.split(",") if v.strip()]
    unknown = [v for v in names if v not in BUILDERS]
    if unknown:
        raise SystemExit(
            f"redlines build: unknown view(s): {', '.join(unknown)} "
            f"(choose from {', '.join(VIEW_ORDER)})"
        )
    return names


def cmd_build(args):
    if args.list:
        for v in VIEW_ORDER:
            print(v)
        return 0

    views = _parse_views(args.views) if args.views else list(VIEW_ORDER)

    failed = []
    for v in views:
        try:
            BUILDERS[v]()
        except Exception as exc:
            print(f"{v}: FAILED: {exc}", file=sys.stderr)
            traceback.print_exc()
            failed.append(v)

    if failed:
        print(f"redlines build: {len(failed)} view(s) failed: {', '.join(failed)}",
              file=sys.stderr)
        return 1
    return 0


# --- assemble: web/<page>/ chunks + fresh view blob()s -> tracked page ---

# Canonical page order. --pages may name a subset but not reorder it, same
# convention as --views above. One page since 2026-09-08 (the timeline is a
# panel of index.html); the machinery stays general.
PAGE_ORDER = ["demo"]


def _page_dir(name):
    return REPO_ROOT / "web" / name


def _page_manifest(name):
    return json.loads((_page_dir(name) / "manifest.json").read_text(encoding="utf-8"))


def _blobs_for_demo():
    """Build every blob index.html's manifest needs, keyed by
    the manifest's window.__NAME__ names -- same build() calls (same args,
    same graph4 final=True) as the `build` command's g4/g1/g2/databank/g3
    builders, just not mirrored to results/ or inject()-ed to disk here."""
    from .views import (axes, capability, causal, conditional, databank, graph1, graph2,
                        method, observational, timeline, rationales)

    return {
        "GRAPH4": g4_blob()[0],
        "TIMELINE": timeline.build(),
        "GRAPH1": graph1.build(),
        "GRAPH2": graph2.build(),
        "DATABANK": databank.build(include_canaries=False),
        "GRAPH3": g3_blob()[0],
        "CONDITIONAL": conditional.build(),
        "CAPABILITY": capability.build(),
        "AXES": axes.build(),
        "OBSERVATIONAL": observational.build(),
        "CAUSAL": causal.build(),
        "METHOD": method.build(),
        "RATIONALES": rationales.build(),
    }


PAGE_BLOB_BUILDERS = {
    "demo": _blobs_for_demo,
}


def _parse_pages(spec):
    names = [p.strip() for p in spec.split(",") if p.strip()]
    unknown = [p for p in names if p not in PAGE_BLOB_BUILDERS]
    if unknown:
        raise SystemExit(
            f"redlines assemble: unknown page(s): {', '.join(unknown)} "
            f"(choose from {', '.join(PAGE_ORDER)})"
        )
    return names


def _assemble_one(name):
    manifest = _page_manifest(name)
    blobs = PAGE_BLOB_BUILDERS[name]()
    html = hydrate_page(_page_dir(name), blobs)
    target = REPO_ROOT / manifest["target"]
    target.write_text(html, encoding="utf-8")
    return target


def cmd_assemble(args):
    pages = _parse_pages(args.pages) if args.pages else list(PAGE_ORDER)

    failed = []
    for name in pages:
        try:
            target = _assemble_one(name)
            print(f"{name}: -> {target.name}")
        except Exception as exc:
            print(f"{name}: FAILED: {exc}", file=sys.stderr)
            traceback.print_exc()
            failed.append(name)

    if failed:
        print(f"redlines assemble: {len(failed)} page(s) failed: {', '.join(failed)}",
              file=sys.stderr)
        return 1
    return 0


# --- export-fb: standalone ForecastBench-2.0 ingest artifact ---

DEFAULT_FB_EXPORT_OUT = str(REPO_ROOT / "results" / "fb_export.json")


def cmd_export_fb(args):
    from .export import export_forecastbench

    doc = export_forecastbench(args.out)
    print(f"export-fb: {doc['source_rows']} source row(s), {len(doc['forecasts'])} "
          f"forecast(s), {len(doc['models'])} model(s) -> {args.out}")
    return 0


def build_arg_parser():
    ap = argparse.ArgumentParser(prog="redlines")
    sub = ap.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="rebuild dashboard view blobs and hydrate the pages")
    build.add_argument(
        "--views", default=None,
        help=f"comma-separated view names to build, default all, in order "
             f"({','.join(VIEW_ORDER)})",
    )
    build.add_argument(
        "--list", action="store_true",
        help="list available view names (in build order) and exit",
    )
    build.set_defaults(func=cmd_build)

    assemble = sub.add_parser(
        "assemble", help="reassemble the tracked page from web/ chunks and fresh view blobs")
    assemble.add_argument(
        "--pages", default=None,
        help=f"comma-separated page names to assemble, default all, in order "
             f"({','.join(PAGE_ORDER)})",
    )
    assemble.set_defaults(func=cmd_assemble)

    export_fb = sub.add_parser(
        "export-fb", help="write the provisional ForecastBench-2.0 ingest artifact")
    export_fb.add_argument(
        "--out", default=DEFAULT_FB_EXPORT_OUT,
        help="output path for the export JSON (default: results/fb_export.json)",
    )
    export_fb.set_defaults(func=cmd_export_fb)

    paper = sub.add_parser(
        "paper", help="write the paper's figures (paper/fig/*.pdf) and numbers.tex from results/*.json")
    paper.add_argument("--out", default=None, help="output directory (default: paper/)")
    paper.add_argument("--figs", default=None,
                       help="comma-separated figure names, default all, in order (g1,g3,g4,conditional)")
    paper.add_argument("--backend", default="pgf", choices=("pgf", "agg"),
                       help="pgf: text typeset by pdflatex (default); agg: no TeX, STIX fonts")
    paper.add_argument("--font", default="cm", choices=("cm", "times"),
                       help="pgf preamble: Computer Modern (default) or newtx Times")
    paper.add_argument("--fmt", default="pdf", choices=("pdf", "png", "pgf"))
    paper.add_argument("--no-figs", action="store_true", help="write numbers.tex only")
    paper.set_defaults(func=cmd_paper)

    return ap


def cmd_paper(args):
    from pathlib import Path
    from .paper import DEFAULT_OUT, FIG_ORDER, numbers

    out = Path(args.out) if args.out else DEFAULT_OUT
    path = numbers.write(out / "numbers.tex")
    print(f"paper: {len(numbers.collect())} macros -> {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
    if args.no_figs:
        return 0
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("paper: matplotlib not installed -- `uv sync --extra paper`; numbers.tex written, no figures",
              file=sys.stderr)
        return 1
    from .paper import render_all

    figs = None
    if args.figs:
        figs = [f.strip() for f in args.figs.split(",") if f.strip()]
        unknown = [f for f in figs if f not in FIG_ORDER]
        if unknown:
            print(f"paper: unknown figure(s) {unknown}; choose from {FIG_ORDER}", file=sys.stderr)
            return 2
        figs = [f for f in FIG_ORDER if f in figs]
    for p in render_all(out, figs, backend=args.backend, font=args.font, fmt=args.fmt):
        print(f"paper: -> {p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p}")
    return 0


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
