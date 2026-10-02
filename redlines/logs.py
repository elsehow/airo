"""Instrument logs, one file per run.

A conditional log keeps its name -- results/conditional_runs_<slug>.jsonl --
but lives on disk as a folder of the same name without the suffix, holding
one <run_id>.jsonl per run. A single growing file passed GitHub's 100 MB
limit with the 2026-09-18 run (every row carries its call's rationale and
sources). Callers keep passing the .jsonl name; these helpers resolve it. A
path that is an actual file (an experiment's own log) is read as it is.
"""
import json
from pathlib import Path


def shard_dir(path):
    p = Path(path)
    return p.with_suffix("") if p.suffix == ".jsonl" else p


def log_files(path):
    """The files that make up a log, oldest run first."""
    p = Path(path)
    if p.is_file():
        return [p]
    d = shard_dir(p)
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def log_exists(path):
    return bool(log_files(path))


def iter_rows(path):
    for f in log_files(path):
        with open(f) as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def run_file(path, run_id):
    """Where a run's rows go: <log folder>/<run_id>.jsonl, folder created."""
    d = shard_dir(path)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{run_id}.jsonl"


def log_names(results_dir, prefix="conditional_runs"):
    """Every log under results_dir by its .jsonl name, from files or folders."""
    names = {p.with_suffix(".jsonl") if p.is_dir() else p
             for p in Path(results_dir).glob(prefix + "*") if p.is_dir() or p.suffix == ".jsonl"}
    return sorted(names)
