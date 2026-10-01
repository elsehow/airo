"""The historical markers must be generated, never edited, and must stay on the
same severity axis the question set defines.

Two failure modes this guards, both of which would put a wrong number in front
of a reader with nothing to catch it:

  1. Someone corrects a death toll in the JSON instead of in the generator, and
     the citation in the generator no longer matches the figure on the page.
     test_generated_file_is_current diffs byte-for-byte.

  2. The Auto-ARC rungs change their deaths:damages ratio — the $10M value of a
     statistical life — while the marker placement rule keeps dividing by the
     old constant. Every event with a damages leg then lands in the wrong
     place, silently, because nothing else in the pipeline reads both files.
     test_vsl_matches_the_ladder fails the build instead.

Run with:  python3 -m unittest tests.test_historical_events -v
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GEN = REPO / "code" / "make_historical_events.py"
EVENTS = REPO / "data" / "historical_events.json"

from redlines.historical import load_events, markers  # noqa: E402
from redlines.questions import load_ladder  # noqa: E402


def load_generator():
    spec = importlib.util.spec_from_file_location("hist_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGeneratedFile(unittest.TestCase):
    def test_generated_file_is_current(self):
        """Regenerate and diff. A hand-edit to the JSON fails here, by name."""
        gen = load_generator()
        expected = json.dumps(gen.build(), indent=2) + "\n"
        self.assertEqual(
            EVENTS.read_text(), expected,
            f"{EVENTS.name} differs from what {GEN.name} produces. Edit the "
            f"generator — where the citation lives — and re-run it.")

    def test_loads_and_validates(self):
        doc = load_events()
        self.assertTrue(doc["events"])
        self.assertTrue(doc["caveat"].strip())


class TestSeverityAxis(unittest.TestCase):
    def test_vsl_matches_the_ladder(self):
        """The placement rule's VSL must be the one the rungs actually imply."""
        gen = load_generator()
        for r in load_ladder()["rungs"]:
            if r.get("damages_usd") is None:    # the extinction rung has no dollar leg
                continue
            self.assertAlmostEqual(
                r["damages_usd"] / r["deaths"], gen.VSL_USD, delta=1,
                msg=f"rung {r['short']} implies a value of a statistical life "
                    f"of {r['damages_usd'] / r['deaths']:,.0f}, but "
                    f"{GEN.name} places events using {gen.VSL_USD:,.0f}. "
                    f"Every event with a damages leg is now misplaced.")

    def test_placement_takes_the_higher_leg(self):
        """A rung is met on deaths OR damages, so the higher leg sets position."""
        gen = load_generator()
        both = {"deaths": {"low": 1e6, "central": 2e6, "high": 3e6},
                "damages_usd": {"low": 1e12, "central": 1e12, "high": 1e12}}
        # damages leg = 1e12 / 1e7 = 1e5, below every deaths value, so deaths win
        self.assertEqual(gen.coordinate(both)["central"], 2e6)

        damages_only = {"deaths": None,
                        "damages_usd": {"low": 1e10, "central": 1e10, "high": 1e10}}
        self.assertAlmostEqual(gen.coordinate(damages_only)["central"], 1e10 / gen.VSL_USD, delta=1e-6)

    def test_covid_is_placed_on_its_deaths_leg(self):
        """The case the rule exists for: COVID's output loss must not demote it."""
        ev = next(e for e in load_events()["events"] if e["id"] == "covid-19")
        self.assertAlmostEqual(ev["severity"]["central"], 14.83e6, delta=1)

    def test_events_land_inside_the_plotted_axis(self):
        """A band outside the chart's x-domain would render as a sliver at the
        edge and read as a real position. Keep this in step with XLO/XHI in
        web/demo/30-live-graph2.jsx."""
        XLO, XHI = 800, 1.4e10
        for e in markers()["events"]:
            self.assertGreater(e["low"], XLO, f"{e['id']} falls off the left edge")
            self.assertLess(e["high"], XHI, f"{e['id']} falls off the right edge")

    def test_bands_are_ordered_and_positive(self):
        for e in markers()["events"]:
            self.assertLessEqual(e["low"], e["central"], e["id"])
            self.assertLessEqual(e["central"], e["high"], e["id"])
            self.assertGreater(e["low"], 0, e["id"])


class TestSourcing(unittest.TestCase):
    def test_every_event_carries_a_citation(self):
        """The whole point of the SSOT: no figure without its source."""
        for e in load_events()["events"]:
            for key in ("org", "title", "url"):
                self.assertTrue(e["source"][key].strip(),
                                f"{e['id']} has an empty source.{key}")
            self.assertTrue(e["source"]["url"].startswith("https://"),
                            f"{e['id']} source url is not https")
            self.assertTrue(e["note"].strip(), f"{e['id']} has no note")
            self.assertTrue(e["verified"], f"{e['id']} has no verified date")

    def test_every_event_has_a_chart_label(self):
        """`short` is what the chart draws; `label` is what the tooltip says."""
        for e in load_events()["events"]:
            self.assertTrue(e["short"].strip(), f"{e['id']} has no short label")
            self.assertLessEqual(len(e["short"]), len(e["label"]), e["id"])
            self.assertLessEqual(len(e["short"]), 16,
                                 f"{e['id']} short label is too long to sit "
                                 f"rotated inside the plot")

    def test_markers_carry_the_caveat(self):
        """The panel renders this. If it can go missing, it will go missing."""
        self.assertIn("NOT", markers()["caveat"])


if __name__ == "__main__":
    unittest.main()
