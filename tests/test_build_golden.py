"""Golden test for `python3 -m redlines build`.

Each view's freshly rebuilt blob must equal the TRACKED mirror committed
under results/ -- a self-referential golden: a refactor that silently changes
a view's output NUMBERS (not just its file format) fails this test, without
needing an external "expected" fixture to keep in sync by hand.

All six mirrors (results/graph1_data.json, graph2_data.json, graph3_data.json,
graph4_combined.json, databank_data.json, timeline_data.json) are committed,
so they exist on a fresh clone. What is NOT guaranteed on a fresh clone is the
external data two views need to actually COMPUTE their blob:

  * graph3 reads processed ForecastBench rounds from FB_DATASETS_ROOT, a
    sibling checkout (see docs/methodology.md for how to populate it).
  * graph4 reads FBSIM_ROOT's low-probability question set (another sibling
    checkout) AND results/eval_full.json, which is gitignored
    (results/eval_*.json -- regenerated, not tracked) so it is absent right
    after cloning even though the repo itself is complete.

Both tests skipTest cleanly when their inputs are missing, rather than
failing, so `python3 -m unittest discover tests` is green on a fresh clone.
The other four views need only files already tracked in this repo, so they
always run.

Run with:  python3 -m unittest tests.test_build_golden -v   (from the repo root)
"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from redlines.config import FBSIM_ROOT, FB_DATASETS_ROOT  # noqa: E402
from redlines.views import (axes, capability, causal, databank, graph1, graph2, graph3, graph4,  # noqa: E402
                            observational, rationales, timeline)

RESULTS = REPO_ROOT / "results"


def _tracked_mirror(name):
    """Load the committed results/<name>.json mirror as a dict.

    All six mirrors this test checks are tracked in git (unlike
    results/eval_*.json), so a missing file here means something is wrong
    with the checkout, not an expected fresh-clone gap -- fail loudly rather
    than skip.
    """
    path = RESULTS / f"{name}.json"
    if not path.exists():
        raise AssertionError(
            f"{path} is missing but should be tracked in git -- "
            f"check `git ls-files {path.relative_to(REPO_ROOT)}`"
        )
    return json.loads(path.read_text())


class TestGraph1Golden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(graph1.build(), _tracked_mirror("graph1_data"))


class TestGraph2Golden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(graph2.build(), _tracked_mirror("graph2_data"))


class TestGraph3Golden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        processed = FB_DATASETS_ROOT / "processed_forecast_sets"
        if not processed.is_dir():
            raise unittest.SkipTest(
                f"FB_DATASETS_ROOT processed sets not found at {processed} -- "
                "graph3 needs the ForecastBench processed_forecast_sets tarball "
                "(see docs/methodology.md / README.md)"
            )
        self.assertEqual(graph3.build(), _tracked_mirror("graph3_data"))


class TestGraph4Golden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        eval_path = RESULTS / "eval_full.json"
        questions_path = FBSIM_ROOT / "data" / "lowprob" / "lowprob_questions.json"
        pandemic_preds_path = RESULTS / "pandemic" / "smoke_preds.json"
        missing = [p for p in (eval_path, questions_path, pandemic_preds_path) if not p.exists()]
        if missing:
            raise unittest.SkipTest(
                "graph4 needs FBSIM_ROOT's low-probability question set and "
                "results/eval_full.json (gitignored, regenerated -- see README.md); "
                "missing: " + ", ".join(str(p) for p in missing)
            )
        # code/make_demo_combined.py's shim (and `redlines build`'s g4 view)
        # always write the tracked mirror with --final, i.e. final=True.
        blob = graph4.build(eval_path, questions_path, pandemic_preds_path, final=True)
        self.assertEqual(blob, _tracked_mirror("graph4_combined"))


class TestDatabankGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        # v1 ships bottom-line only (canaries gated off by default -- see
        # redlines/views/databank.py); the tracked mirror is the v1 shape.
        self.assertEqual(databank.build(include_canaries=False), _tracked_mirror("databank_data"))


class TestTimelineGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(timeline.build(), _tracked_mirror("timeline_data"))


class TestCapabilityGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(capability.build(), _tracked_mirror("capability_data"))


class TestAxesGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(axes.build(), _tracked_mirror("axes_data"))


class TestRationalesGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(rationales.build(), _tracked_mirror("rationales_data"))


class TestObservationalGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(observational.build(), _tracked_mirror("observational_data"))


class TestCausalGolden(unittest.TestCase):
    def test_build_matches_tracked_mirror(self):
        self.assertEqual(causal.build(), _tracked_mirror("causal_data"))


if __name__ == "__main__":
    unittest.main()
