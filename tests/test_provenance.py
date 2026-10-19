"""Tests for redlines.provenance: the deterministic stamps on every blob.

The page-level guarantee (a fresh assemble, PROVENANCE blob included,
reproduces index.html byte for byte) is tests/test_assemble_golden.py's job.
This file checks the parts that test cannot see:

  * the stamp is a function of file CONTENT -- same bytes, same stamp;
    one changed byte, a different stamp naming that file;
  * the open() trace records reads, not writes, and only under known roots;
  * the static code closure follows imports into fri_forecaster;
  * results/provenance.json and the page's window.__PROVENANCE__ agree;
  * nothing a view reads escapes the trace: building a view in a fresh
    interpreter with open() hooked BEFORE redlines is imported (so the
    registry's import-time reads are seen too) reads exactly the files its
    tracked entry lists.

Run with:  python3 -m pytest tests/test_provenance.py -q   (from the repo root)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from redlines import provenance  # noqa: E402


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.outside = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(provenance, "REPO_ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()
        self.outside.cleanup()

    def _write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_records_reads_under_root_only(self):
        a = self._write("data/a.json", '{"x": 1}')
        b = self._write("data/b.txt", "b")
        out = Path(self.outside.name) / "elsewhere.txt"
        out.write_text("not an input")

        def build():
            with open(a, encoding="utf-8") as f:
                x = json.load(f)["x"]
            b.read_text()                       # pathlib goes through io.open
            out.read_text()                     # outside every root: ignored
            (self.root / "written.txt").write_text("output")  # a write: ignored
            try:
                open(self.root / "missing.json")  # a failed probe: ignored
            except FileNotFoundError:
                pass
            return x

        result, files = provenance.trace(build)
        self.assertEqual(result, 1)
        self.assertEqual(list(files), ["data/a.json", "data/b.txt"])

    def test_open_restored_even_on_error(self):
        import builtins
        import io
        before = builtins.open, io.open
        with self.assertRaises(RuntimeError):
            provenance.trace(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertEqual((builtins.open, io.open), before)

    def test_stamp_is_a_function_of_content(self):
        a = self._write("data/a.json", '{"x": 1}')

        def build():
            return a.read_text()

        def stamp():
            provenance._HASHES.clear()
            with mock.patch.object(provenance, "code_closure", return_value={"m.py": "0" * 64}), \
                    mock.patch.object(provenance, "package_version", return_value="0.0.0"):
                return provenance.make_entry("m", provenance.trace(build)[1])

        first, again = stamp(), stamp()
        self.assertEqual(first, again)
        self.assertRegex(first["stamp"], r"^[0-9a-f]{64}$")

        a.write_text('{"x": 2}')
        changed = stamp()
        self.assertNotEqual(changed["stamp"], first["stamp"])
        self.assertNotEqual(changed["inputs"]["files"]["data/a.json"],
                            first["inputs"]["files"]["data/a.json"])

        a.write_text('{"x": 1}')                # back to the original bytes
        self.assertEqual(stamp()["stamp"], first["stamp"])

    def test_external_roots_are_labelled_not_absolute(self):
        ext = Path(os.path.realpath(self.outside.name))
        (ext / "sets").mkdir()
        f = ext / "sets" / "r.json"
        f.write_text("{}")
        with mock.patch.object(provenance, "FB_DATASETS_ROOT", ext):
            self.assertEqual(provenance.label(f), "<FB_DATASETS_ROOT>/sets/r.json")


class TestCodeClosure(unittest.TestCase):
    def test_follows_imports_into_the_harness_package(self):
        mods = provenance.code_closure("redlines.views.causal")
        self.assertIn("redlines/views/causal.py", mods)
        self.assertIn("redlines/registry.py", mods)
        self.assertIn("redlines/eci.py", mods)
        self.assertIn("packages/fri-forecaster/fri_forecaster/eci.py", mods)
        # A module causal never imports does not move its stamp.
        self.assertNotIn("redlines/views/graph1.py", mods)
        self.assertNotIn("redlines/provenance.py", mods)

    def test_deterministic(self):
        self.assertEqual(provenance.code_closure("redlines.views.graph1"),
                         provenance.code_closure("redlines.views.graph1"))


class TestTrackedProvenance(unittest.TestCase):
    def test_page_blob_matches_mirror(self):
        html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
        m = re.search(r"<script>window\.__PROVENANCE__ = (.*?);</script>", html)
        self.assertIsNotNone(m, "index.html has no window.__PROVENANCE__ blob")
        page = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(page, provenance.page_blob(provenance.load_tracked()))

    def test_every_manifest_blob_is_stamped(self):
        manifest = json.loads((REPO_ROOT / "web" / "demo" / "manifest.json").read_text())
        names = set(manifest["blobs"]) - {provenance.NAME}
        self.assertEqual(set(provenance.load_tracked()), names)

    def test_no_wall_clock_or_commit_in_stamps(self):
        text = provenance.MIRROR.read_text(encoding="utf-8")
        self.assertNotRegex(text, r'"(built_?at|time|timestamp|commit|head)"')

    def test_frozen_entry_passes_tracked_entry_through(self):
        tracked = provenance.load_tracked()
        for name, view, mirror in (("GRAPH3", "graph3", "graph3_data.json"),
                                   ("GRAPH4", "graph4", "graph4_combined.json")):
            self.assertEqual(
                provenance.frozen_entry(name, f"redlines.views.{view}", REPO_ROOT / "results" / mirror),
                tracked[name])


# Built in a fresh interpreter with open() hooked before redlines is
# imported. graph3/graph4 are excluded: frozen, slow, and machine-dependent.
_PROBE = textwrap.dedent("""
    import builtins, io, json, os, sys
    sys.path.insert(0, sys.argv[1])
    seen = set()
    _open = builtins.open
    def hooked(f, mode="r", *a, **k):
        if isinstance(f, (str, bytes, os.PathLike)) and not any(c in mode for c in "wax+"):
            seen.add(os.fsdecode(f))
        return _open(f, mode, *a, **k)
    builtins.open = io.open = hooked
    import importlib
    view = importlib.import_module("redlines.views." + sys.argv[2])
    view.build(**json.loads(sys.argv[3]))
    builtins.open = io.open = _open
    from redlines import provenance
    print(json.dumps(sorted({provenance.label(p) for p in seen
                             if os.path.isfile(p) and provenance.label(p)})))
""")


class TestTraceIsComplete(unittest.TestCase):
    CASES = [("CAUSAL", "causal", {}), ("GRAPH1", "graph1", {}),
             ("DATABANK", "databank", {"include_canaries": False}),
             ("CAPABILITY", "capability", {})]

    def test_fresh_process_reads_match_tracked_inputs(self):
        tracked = provenance.load_tracked()
        for name, view, kwargs in self.CASES:
            with self.subTest(view=view):
                out = subprocess.run(
                    [sys.executable, "-c", _PROBE, str(REPO_ROOT), view, json.dumps(kwargs)],
                    capture_output=True, text=True, check=True, cwd=REPO_ROOT)
                read = json.loads(out.stdout.strip().splitlines()[-1])
                self.assertEqual(read, sorted(tracked[name]["inputs"]["files"]))


if __name__ == "__main__":
    unittest.main()
