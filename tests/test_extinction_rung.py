"""The extinction rung (data/auto-arc/addendum-extinction-rung-2026-09-16.json):
a ninth rung on every incident ladder, a population floor with no dollar leg,
entered 2026-09-16; the loss fold ignores it; runs before it stay complete."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from redlines.conditional import expected_loss, ladder_rungs
from redlines.questions import load_ladder, questions_asked_on, severity_deaths, severity_label
from redlines.runlog import complete_panel_rows
from redlines.views import graph2

ROOT = Path(__file__).resolve().parent.parent
RUNG = [f"ladder:{c}:extinction" for c in ("ai", "bio", "cyber", "misalign")]


class TestTheRung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_ladder()
        cls.qs = {q["id"]: q for q in cls.spec["questions"]}

    def test_one_per_cause_with_since_and_no_dollar_leg(self):
        self.assertEqual([r["short"] for r in self.spec["rungs"]][-1], "extinction")
        for qid in RUNG:
            q = self.qs[qid]
            self.assertEqual(q["since"], "2026-09-16")
            self.assertEqual(q["source"], "data/auto-arc/addendum-extinction-rung-2026-09-16.json")
            self.assertEqual(q["severity"]["kind"], "extinction")
            self.assertIsNone(q["severity"]["damages_usd"])
            self.assertEqual(q["severity"]["floor_population"], 5000)
            self.assertIn("human extinction (a reduction of the global population below 5,000)", q["text"])
            self.assertNotIn("economic damages", q["text"])
            self.assertEqual(q["horizons"], self.spec["horizons"])
            self.assertEqual(severity_deaths(q), 8.2e9)
            self.assertEqual(severity_label(q, short=True), "extinction")

    def test_same_floor_as_the_pair(self):
        pair = json.loads((ROOT / "data" / "auto-arc" / "addendum-extinction-2026-09-15.json").read_text())
        self.assertEqual(self.qs["ladder:ai:extinction"]["severity"]["floor_population"],
                         pair["severity"]["floor_population"])

    def test_loss_fold_ignores_the_rung(self):
        rungs = ladder_rungs(self.spec)
        self.assertEqual([r for r, _ in rungs][-1], "1B")
        self.assertEqual(len(rungs), 8)
        survival = {r: 0.5 ** i for i, (r, _) in enumerate(rungs)}
        self.assertIsNotNone(expected_loss(survival, rungs))   # no extinction key needed

    def test_runs_before_the_rung_stay_complete(self):
        self.assertFalse(set(RUNG) & set(questions_asked_on("2026-09-15")))
        self.assertTrue(set(RUNG) <= set(questions_asked_on("2026-09-16")))

    def test_severity_chart_carries_the_rung_at_the_extinction_mark(self):
        b = graph2.build()
        self.assertEqual(b["rungs"][-1]["rung"], "extinction")
        self.assertIsNone(b["rungs"][-1]["damages"])
        marks = json.load(open(ROOT / "data" / "historical_events.json"))["events"]
        ext = next(e for e in marks if e["id"] == "extinction")["severity"]["central"]
        self.assertEqual(b["rungs"][-1]["deaths"], ext)


if __name__ == "__main__":
    unittest.main()
