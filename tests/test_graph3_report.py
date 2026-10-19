"""docs/methodology.md's Graph 3 tables are generated from the committed JSON.

If this fails, the doc and results/graph3_comparability.json disagree. After a
re-run of code/graph3_comparability.py, regenerate the tables with

    python3 -m redlines.graph3_report

and re-read the surrounding prose: it cites some of the same numbers.
"""
import json
import unittest

from redlines import graph3_report as g3

REPORT = json.loads(g3.JSON_PATH.read_text())
DOC = g3.DOC_PATH.read_text()


class DocMatchesJSON(unittest.TestCase):
    def test_every_section_has_a_region(self):
        self.assertEqual(sorted(g3.regions(DOC)), sorted(g3.SECTIONS))

    def test_generated_regions_match_json(self):
        rendered = g3.render_all(REPORT)
        for name in g3.SECTIONS:
            with self.subTest(region=name):
                self.assertEqual(g3.regions(DOC)[name], rendered[name],
                                 "re-run: python3 -m redlines.graph3_report")

    def test_check_mode_passes_on_committed_doc(self):
        self.assertEqual(g3.main(["--check"]), 0)

    def test_rewrite_is_a_no_op(self):
        self.assertEqual(g3.sync(DOC, g3.render_all(REPORT)), DOC)

    def test_prose_figures_match_json(self):
        """Numbers the prose quotes outside the generated tables."""
        cfg = REPORT["config"]
        anchors = REPORT["anchors"]
        expected = [
            # "Config is not the problem"
            f"{cfg['scratchpad + news']['brier']:.4f} (scratchpad+news, "
            f"{cfg['scratchpad + news']['models']}",
            f"{cfg['scratchpad']['brier']:.4f} (scratchpad, {cfg['scratchpad']['models']})",
            f"{cfg['zero shot']['brier']:.4f} (zero-shot, {cfg['zero shot']['models']})",
            f"a {REPORT['config_spread']:.3f} spread",
            # "The round is the problem"
            f"swings {anchors['GPT-4.1-2025-04-14 (zero shot)']['swing']:.3f} Brier",
            f"Claude-Haiku-4-5 swings {anchors['Claude-Haiku-4-5-20251001 (zero shot)']['swing']:.3f}",
            f"GPT-5-Mini {anchors['GPT-5-Mini-2025-08-07 (zero shot)']['swing']:.3f}",
            f"Claude-Sonnet-4-5 {anchors['Claude-Sonnet-4-5-20250929 (zero shot)']['swing']:.3f}",
            f"Mean swing **{REPORT['round_effect']:.3f}**",
            f"still swings\n**{anchors['Claude-3-5-Sonnet-20240620 (zero shot)']['swing']:.3f}**",
            # "Version bumps"
            f"Mean **{REPORT['family_pair_effect']:+.3f}**",
        ]
        for s in expected:
            with self.subTest(figure=s):
                self.assertIn(s, DOC)


class Rendering(unittest.TestCase):
    """The generator against a hand-made report, independent of the real data."""

    def setUp(self):
        self.r = json.loads(json.dumps(REPORT))   # deep copy

    def test_stale_region_is_detected(self):
        self.r["vintage_effect"] = 0.0991
        rendered = g3.render_all(self.r)
        self.assertEqual(g3.stale(DOC, rendered), ["decomposition"])
        self.assertIn("**0.099**", g3.sync(DOC, rendered))

    def test_negative_change_uses_typographic_minus(self):
        self.assertEqual(g3._signed(-0.0116), "\u22120.012")
        self.assertEqual(g3._signed(0.0231), "+0.023")

    def test_missing_region_raises(self):
        doc = DOC.replace("graph3:horizons", "graph3:horizonz")
        with self.assertRaises(ValueError):
            g3.sync(doc, g3.render_all(self.r))

    def test_only_region_bodies_change(self):
        self.r["horizons"]["2026-06-21"] = {"total": 2000, "ge90d": 1000, "main": {}}
        new = g3.sync(DOC, g3.render_all(self.r))
        self.assertIn("| 2026-06-21 | 2,000 | 50% |", new)
        strip = lambda d: g3.BEGIN_RE.sub("", d)
        self.assertEqual(strip(new), strip(DOC))


if __name__ == "__main__":
    unittest.main()
