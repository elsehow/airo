"""Deterministic build-provenance stamps for the window.__NAME__ blobs.

Every blob a page embeds gets an entry in one more blob,
window.__PROVENANCE__, saying what it was built from:

    window.__PROVENANCE__ = {
      "format": 1,
      "blobs": {
        "CAUSAL": {
          "basis": "inputs",
          "stamp":  "<sha256>",                        # of code + inputs below
          "code":   {"version": "0.1.0", "modules": 9, "sha256": "<sha256>"},
          "inputs": {"files": 11, "sha256": "<sha256>"}
        }, ...
      }
    }

results/provenance.json is the same document with the detail the page leaves
out: `code.modules` and `inputs.files` there are {path: sha256} maps rather
than counts, so the stamp can be recomputed (and an input that moved can be
named) without rebuilding.

The stamp is a pure function of the build's inputs. It is NOT a timestamp and
NOT a git commit -- either would make two builds of the same inputs differ,
and `build`/`assemble` must reproduce the tracked files byte for byte
(tests/test_build_golden.py, tests/test_assemble_golden.py). Its parts:

  inputs  every file the view's build() opened for reading, found by tracing
          open() while it runs (builtins.open and io.open, which pathlib's
          read_text/open go through), plus the files the model registry
          reads at import time (redlines.registry._build_models: the ECI
          snapshots and data/auto_models.json), which a per-call trace cannot
          see. Paths are recorded relative to the repo, or as
          <FB_DATASETS_ROOT>/..., <FBSIM_ROOT>/..., <XRISK_CANARIES_ROOT>/...
          for the external checkouts, so a stamp does not depend on where a
          machine keeps them. Files outside those roots (the stdlib, site-
          packages) are ignored. Each file contributes the sha256 of its bytes.
  code    the package version (pyproject.toml) and the sha256 of every
          module in the view's static import closure: redlines/views/<view>.py
          and whatever redlines.* / fri_forecaster.* modules it imports,
          transitively, including imports inside functions (found with ast,
          not by importing). Editing a module a view does not import does not
          move that view's stamp.

Caches are cleared before each traced build (every functools.lru_cache in a
loaded redlines.* module), so a view's recorded inputs do not depend on which
views ran before it in the same process.

Graph 3 and Graph 4 are frozen artifacts (redlines.__main__.g3_blob /
g4_blob): when their external inputs are absent the tracked mirror is spliced
in unchanged, and so is the tracked provenance entry for it -- the stamp
describes the build that produced the mirror, not the machine that copied it.
A frozen blob that has never been stamped from its real inputs gets
"basis": "mirror", whose inputs are the mirror file itself.

Stdlib only, like the rest of the build stage.
"""
from __future__ import annotations

import ast
import builtins
import functools
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

from .config import FB_DATASETS_ROOT, FBSIM_ROOT, REPO_ROOT, XRISK_CANARIES_ROOT

FORMAT = 1
NAME = "PROVENANCE"
MIRROR = REPO_ROOT / "results" / "provenance.json"

# Where an import of each first-party top-level package resolves, statically.
_PACKAGE_DIRS = {
    "redlines": REPO_ROOT / "redlines",
    "fri_forecaster": REPO_ROOT / "packages" / "fri-forecaster" / "fri_forecaster",
}


def _roots():
    """(label, resolved root) pairs, most specific first; read at call time so
    a test can point a root elsewhere."""
    roots = [("<FB_DATASETS_ROOT>", FB_DATASETS_ROOT), ("<FBSIM_ROOT>", FBSIM_ROOT),
             ("<XRISK_CANARIES_ROOT>", XRISK_CANARIES_ROOT), ("", REPO_ROOT)]
    out = []
    for label, root in roots:
        try:
            out.append((label, Path(os.path.realpath(root))))
        except OSError:
            continue
    # An external checkout nested inside the repo must win over the repo.
    return sorted(out, key=lambda lr: -len(str(lr[1])))


def label(path) -> str | None:
    """A machine-independent name for `path`, or None when it is outside every
    root the build reads from."""
    real = Path(os.path.realpath(path))
    for name, root in _roots():
        try:
            rel = real.relative_to(root)
        except ValueError:
            continue
        rel = rel.as_posix()
        if rel.startswith(".git/") or "/__pycache__/" in f"/{rel}":
            return None
        return f"{name}/{rel}" if name else rel
    return None


_HASHES: dict = {}


def file_sha256(path) -> str:
    """sha256 of a file's bytes, memoized on (path, size, mtime_ns)."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    if key not in _HASHES:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _HASHES[key] = h.hexdigest()
    return _HASHES[key]


# --- tracing reads ----------------------------------------------------------

_READ_MODES = re.compile(r"[wax+]")


def trace(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) recording every file it opens for reading.

    Returns (result, {label: sha256}) -- only files that exist, sit under a
    known root, and were opened read-only. open() is restored on exit,
    including when fn raises.
    """
    seen: set[str] = set()
    real_open, real_io_open = builtins.open, io.open

    def traced_open(file, mode="r", *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)) and not _READ_MODES.search(mode):
            seen.add(os.fsdecode(file))
        return real_open(file, mode, *a, **k)

    builtins.open = io.open = traced_open
    try:
        result = fn(*args, **kwargs)
    finally:
        builtins.open, io.open = real_open, real_io_open
    files = {}
    for p in seen:
        name = label(p)
        if name is not None and os.path.isfile(p):
            files[name] = file_sha256(p)
    return result, dict(sorted(files.items()))


def clear_caches():
    """cache_clear() every functools cache in a loaded redlines.* module."""
    for modname, mod in list(sys.modules.items()):
        if mod is None or not (modname == "redlines" or modname.startswith("redlines.")):
            continue
        for obj in list(vars(mod).values()):
            if callable(getattr(obj, "cache_clear", None)) and hasattr(obj, "__wrapped__"):
                obj.cache_clear()


@functools.lru_cache(maxsize=1)
def _import_time_inputs() -> tuple:
    """Files the model registry reads when redlines.registry is imported
    (MODELS = _build_models()) -- re-read here under trace, since an import
    happens once per process and a per-build trace cannot see it."""
    from . import registry
    return tuple(trace(registry._build_models)[1].items())


# --- static code closure ----------------------------------------------------

def _module_file(dotted: str) -> Path | None:
    top, *rest = dotted.split(".")
    base = _PACKAGE_DIRS.get(top)
    if base is None:
        return None
    p = base.joinpath(*rest)
    if (p / "__init__.py").is_file():
        return p / "__init__.py"
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    return None


def _module_name(path: Path) -> str:
    for top, base in _PACKAGE_DIRS.items():
        try:
            rel = path.relative_to(base)
        except ValueError:
            continue
        parts = [top, *rel.with_suffix("").parts]
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)
    raise ValueError(path)


def _imports(path: Path) -> set[str]:
    """Dotted first-party modules `path` imports anywhere in its body."""
    mod = _module_name(path)
    pkg = mod if path.name == "__init__.py" else mod.rpartition(".")[0]
    out = set()
    for node in ast.walk(ast.parse(path.read_bytes(), filename=str(path))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = pkg.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                base = f"{base}.{node.module}" if node.module else base
            else:
                base = node.module or ""
            out.add(base)
            # `from . import stats` / `from .views import graph1` name modules
            out.update(f"{base}.{a.name}" for a in node.names)
    return {m for m in out if _module_file(m) is not None}


def code_closure(module: str) -> dict:
    """{repo-relative path: sha256} of `module` and every first-party module
    it imports, transitively."""
    todo, files = [module], {}
    while todo:
        f = _module_file(todo.pop())
        if f is None:
            continue
        rel = f.relative_to(REPO_ROOT).as_posix()
        if rel in files:
            continue
        files[rel] = file_sha256(f)
        todo.extend(_imports(f))
    return dict(sorted(files.items()))


@functools.lru_cache(maxsize=1)
def package_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "unknown"


# --- entries ----------------------------------------------------------------

def _digest(lines) -> str:
    return hashlib.sha256("".join(f"{line}\n" for line in lines).encode("utf-8")).hexdigest()


def make_entry(module: str, inputs: dict, basis: str = "inputs") -> dict:
    """The full provenance entry for a blob built by `module` from `inputs`
    ({label: sha256})."""
    modules = code_closure(module)
    version = package_version()
    code_sha = _digest([f"version\t{version}", *(f"{p}\t{h}" for p, h in modules.items())])
    inputs_sha = _digest(f"{p}\t{h}" for p, h in sorted(inputs.items()))
    return {
        "basis": basis,
        "stamp": _digest([f"code\t{code_sha}", f"inputs\t{inputs_sha}"]),
        "code": {"version": version, "sha256": code_sha, "modules": modules},
        "inputs": {"sha256": inputs_sha, "files": dict(sorted(inputs.items()))},
    }


def stamped(module: str, fn, *args, **kwargs):
    """(blob, entry): run a view's build under trace and stamp the result.
    `module` is the dotted name of the view module, e.g. 'redlines.views.graph1'."""
    common = dict(_import_time_inputs())
    clear_caches()
    blob, files = trace(fn, *args, **kwargs)
    return blob, make_entry(module, {**common, **files})


def load_tracked() -> dict:
    """{NAME: entry} from the tracked results/provenance.json ({} if absent)."""
    if not MIRROR.exists():
        return {}
    doc = json.loads(MIRROR.read_text(encoding="utf-8"))
    return doc.get("blobs", {})


def frozen_entry(name: str, module: str, mirror: Path) -> dict:
    """The entry for a frozen blob spliced in from its tracked mirror: the
    tracked entry, verbatim, or -- if it was never stamped -- one whose
    inputs are the mirror file itself."""
    tracked = load_tracked().get(name)
    if tracked is not None:
        return tracked
    return make_entry(module, {label(mirror): file_sha256(mirror)}, basis="mirror")


def mirror_doc(entries: dict) -> dict:
    return {"format": FORMAT, "blobs": dict(sorted(entries.items()))}


def page_blob(entries: dict) -> dict:
    """The window.__PROVENANCE__ blob: entries with counts in place of the
    per-file and per-module maps (results/provenance.json has those)."""
    blobs = {}
    for name, e in sorted(entries.items()):
        blobs[name] = {
            "basis": e["basis"],
            "stamp": e["stamp"],
            "code": {"version": e["code"]["version"], "sha256": e["code"]["sha256"],
                     "modules": len(e["code"]["modules"])},
            "inputs": {"sha256": e["inputs"]["sha256"], "files": len(e["inputs"]["files"])},
        }
    return {"format": FORMAT, "blobs": blobs}


def write_mirror(entries: dict) -> Path:
    MIRROR.parent.mkdir(parents=True, exist_ok=True)
    MIRROR.write_text(json.dumps(mirror_doc(entries), indent=2) + "\n", encoding="utf-8")
    return MIRROR
