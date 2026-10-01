"""redlines.paper: numbers.tex is golden against the tracked file; figures render.

The numbers test is the same contract as test_build_golden.py -- fresh output
vs. the tracked artifact -- so a blob change that moves a quoted number fails
here until `python3 -m redlines paper` is re-run and the result committed.
The figure test only checks that each figure renders without TeX (agg
backend); it skips if matplotlib is not installed.
"""
import tempfile
import unittest
from pathlib import Path

from redlines.config import REPO_ROOT
from redlines.paper import FIG_ORDER, numbers

TRACKED = REPO_ROOT / "paper" / "numbers.tex"


class TestNumbersGolden(unittest.TestCase):
    def test_numbers_tex_matches_tracked(self):
        self.assertTrue(TRACKED.exists(), f"{TRACKED} missing: run python3 -m redlines paper")
        fresh = numbers.render()
        tracked = TRACKED.read_text(encoding="utf-8")
        if fresh != tracked:
            import difflib
            diff = "".join(difflib.unified_diff(tracked.splitlines(True), fresh.splitlines(True),
                                                "tracked", "fresh", n=1))
            self.fail("paper/numbers.tex is stale; re-run python3 -m redlines paper\n" + diff[:4000])

    def test_keys_are_unique_and_tex_safe(self):
        vals = numbers.collect()
        for k, v in vals.items():
            self.assertNotIn("{", k)
            self.assertNotIn("}", k)
            self.assertNotIn("\n", v)
            self.assertFalse(v.startswith("??"))

    def test_headline_keys_present(self):
        vals = numbers.collect()
        for k in ("g1:catastrophe:general:2030:median",
                  "g4:rho", "g4:rhoClean", "g3:sup:brier", "g3:tools:brier",
                  "cond:catastrophe:ai:2030:p5:ratio", "g2:audit:bad",
                  "cond:catastrophe:ai:2030:sq:priced", "coh:chain:byChain:p",
                  "coh:ladder:control:cross:bad:pct", "prompt:system",
                  "cap:catastrophe:ai:2030:eci_p75:ratio", "cap:catastrophe:ai:2030:perPoint:pct",
                  "cap:eci:ensemble:p50",
                  "prompt:question:catastrophe:ai"):
            self.assertIn(k, vals)

    def test_ai_catastrophe_is_not_overwritten_by_incident_top_rung(self):
        """The mortality headline and deaths-OR-damages ladder are distinct."""
        import json
        vals = numbers.collect()
        g1 = json.loads((REPO_ROOT / "results/graph1_data.json").read_text())
        g2 = json.loads((REPO_ROOT / "results/graph2_data.json").read_text())
        q = next(q for q in g1["questions"] if q["id"] == "catastrophe:ai")
        # The top of the deaths-OR-damages ladder: the extinction rung above it
        # (2026-09-16) has no dollar leg and is answered only from that date.
        top = [r for r in g2["rungs"] if r.get("damages") is not None][-1]["rung"]
        distinct = False
        for h, median in q["median"].items():
            cause = next(c for c in g2["byHorizon"][h]["causes"] if c["key"] == "ai")
            rung = next(r for r in cause["rungs"] if r["rung"] == top)
            self.assertEqual(vals[f"g1:catastrophe:ai:{h}:median"], numbers.fmt_pct(median))
            self.assertEqual(vals[f"g2:ladder:ai:{top}:{h}:median"], numbers.fmt_pct(rung["median"]))
            distinct |= median != rung["median"]
        self.assertTrue(distinct, "Fixture must distinguish the two outcomes to detect namespace collisions")

    def test_coherence_blob_is_fresh(self):
        """results/coherence_experiment.json is golden against its inputs."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "coherence_blob", REPO_ROOT / "code" / "coherence_blob.py")
        cb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cb)
        import json
        tracked = json.loads(Path(cb.OUT).read_text(encoding="utf-8"))
        self.assertEqual(cb.build(), tracked,
                         "results/coherence_experiment.json is stale; run python3 code/coherence_blob.py")

    def test_prompt_macros_are_ascii_and_balanced(self):
        vals = numbers.collect()
        for k, v in vals.items():
            if not k.startswith("prompt:"):
                continue
            self.assertTrue(v.isascii(), k)
            self.assertEqual(v.count("{"), v.count("}"), k)
            self.assertFalse(v.startswith("\\newline"), k)


class TestConditionalNumbers(unittest.TestCase):
    def test_absolute_medians_are_not_products_of_medians(self):
        # Model baselines [1, 10, 100], conditions [2, 50, 100]:
        # median level = 50, but median baseline * median ratio = 20.
        out = {}
        numbers._condition_family(out, "cap", [{
            "id": "test", "valueKind": "probability",
            "byHorizon": {"2030": {"baselineMedian": 10, "bars": [
                {"id": "high", "ratio": 2, "pMedian": 50},
                {"id": "zero", "ratio": 0, "pMedian": 0},
                {"id": "missing", "ratio": 1},
            ]}},
        }])
        self.assertEqual(out["cap:test:2030:high:median"], "50.0")
        self.assertEqual(out["cap:test:2030:high:level"], "20.0")
        self.assertEqual(out["cap:test:2030:high:median:priced"], "80")
        self.assertEqual(out["cap:test:2030:high:priced"], "50")
        self.assertEqual(out["cap:test:2030:zero:median"], "0.00")
        self.assertNotIn("cap:test:2030:zero:median:priced", out)
        self.assertNotIn("cap:test:2030:zero:priced", out)
        self.assertNotIn("cap:test:2030:missing:median", out)


class TestFiguresRender(unittest.TestCase):
    def setUp(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed (uv sync --extra paper)")

    def test_every_figure_renders_without_tex(self):
        from redlines.paper import render_all

        with tempfile.TemporaryDirectory() as d:
            paths = render_all(Path(d), backend="agg", fmt="png")
            self.assertEqual([p.stem for p in paths], FIG_ORDER)
            for p in paths:
                self.assertGreater(p.stat().st_size, 1000, p)


if __name__ == "__main__":
    unittest.main()
