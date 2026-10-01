"""The human comparisons come from the workbook's column, and only from it.

The failure this guards against has happened twice on this dashboard, both
times because a number arrived without the question it answered. Graph 2 grew
catastrophe "anchors" nobody asked for (project lead, 2026-08-18), and Graph 1
carried XPT medians beside questions whose wording had moved under them
("these don't match"). Both looked like data and were editorial.

So the chain is checked end to end rather than trusted: her "Human comparisons
(Project)" column says which question x horizon cells have a human panel and
which panel; the generator carries that into each question's
`human_comparisons`; code/fetch_human_baselines.py pulls those and only those.
Every test below asserts one link of that chain, and the strongest of them is
test_no_baseline_the_workbook_did_not_ask_for.
"""
import json
import unittest

from redlines.config import REPO_ROOT
from redlines.questions import (all_questions, human_baselines,
                                human_comparisons_wanted, load_human_baselines,
                                load_ladder)

BASELINES = REPO_ROOT / "data" / "human_baselines.json"


def asked_for():
    """-> {(question_id, horizon, project)} exactly as her workbook asks."""
    out = set()
    for qid, q in all_questions().items():
        for horizon, projects in human_comparisons_wanted(q).items():
            for project in projects:
                out.add((qid, horizon, project))
    return out


class TestWorkbookIsTheSourceOfTruth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc = load_human_baselines()
        cls.have = {(b["question_id"], b["horizon"], b["project"])
                    for b in cls.doc["baselines"]}
        cls.want = asked_for()

    def test_the_workbook_asks_for_something(self):
        """A vacuous pass here would hide every other test in this file."""
        self.assertTrue(self.want, "no question carries human_comparisons — "
                                   "regenerate with code/make_autoarc_questions.py")

    def test_no_baseline_the_workbook_did_not_ask_for(self):
        """The one that stops a number from appearing because we liked it."""
        extra = sorted(self.have - self.want)
        self.assertEqual(extra, [], f"human numbers with no row in Bridget's "
                                    f"comparison column asking for them: {extra}")

    def test_every_asked_for_cell_is_pulled_or_explained(self):
        explained = {(u["question_id"], u["horizon"], u["project"])
                     for u in self.doc["unavailable"]}
        missing = sorted(self.want - self.have - explained)
        self.assertEqual(missing, [], f"cells her sheet asks for that are "
                                      f"neither pulled nor listed unavailable "
                                      f"with a reason: {missing}")

    def test_unavailable_entries_say_why(self):
        for u in self.doc["unavailable"]:
            self.assertTrue((u.get("reason") or "").strip(),
                            f"{u['question_id']} @{u['horizon']} is unavailable "
                            f"with no reason given")


class TestBaselineShape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc = load_human_baselines()
        cls.questions = all_questions()
        cls.prior = load_ladder().get("prior_work", [])

    def test_every_baseline_resolves_to_a_real_question_and_horizon(self):
        for b in self.doc["baselines"]:
            with self.subTest(b["question_id"], h=b["horizon"]):
                q = self.questions.get(b["question_id"])
                self.assertIsNotNone(q, f"unknown question {b['question_id']!r}")
                self.assertIn(b["horizon"], q["horizons"],
                              f"{b['question_id']} has no horizon {b['horizon']}")

    def test_values_are_percent(self):
        """Percent, as both panels elicited. A 0.05 here would draw at 0.05%."""
        for b in self.doc["baselines"]:
            self.assertEqual(b["units"], "percent")
            for group, v in b["groups"].items():
                with self.subTest(b["question_id"], h=b["horizon"], g=group):
                    # A published number (ESPAI) carries the paper's IQR width,
                    # not the quartiles, so p25/p75 are checked when present.
                    for k in ("median", "mean", "p25", "p75"):
                        if k in ("p25", "p75") and v.get(k) is None:
                            continue
                        self.assertGreaterEqual(v[k], 0)
                        self.assertLessEqual(v[k], 100)
                    self.assertGreater(v["n"], 0)
                    if v.get("p25") is not None and v.get("p75") is not None:
                        self.assertLessEqual(v["p25"], v["p75"])

    def test_every_baseline_carries_the_question_its_panel_answered(self):
        """A median without its wording is what made the diamonds wrong."""
        texts = {r["text"] for r in self.prior}
        for b in self.doc["baselines"]:
            with self.subTest(b["question_id"], h=b["horizon"], p=b["project"]):
                src = b["source_question"]
                self.assertTrue((src.get("text") or "").strip())
                self.assertIn(src["text"], texts,
                              "source_question.text is not verbatim from her "
                              "'Questions from prior FRI work' sheet")
                self.assertTrue((b["our_question"].get("text") or "").strip())

    def test_nothing_is_silently_adjusted(self):
        self.assertIs(self.doc.get("adjusted"), False,
                      "the file claims an adjustment was applied; the pairing "
                      "between wordings is a judgement and does not belong in "
                      "a fetch script")

    def test_elicitation_date_travels_with_every_number(self):
        for b in self.doc["baselines"]:
            with self.subTest(b["question_id"], p=b["project"]):
                self.assertTrue((b["elicited"].get("date") or "").strip(),
                                "no elicitation date — a 2022 panel and a 2026 "
                                "panel cannot be told apart without one")


class TestLookup(unittest.TestCase):

    def test_human_baselines_returns_every_panel_for_a_cell(self):
        """A cell can have two panels that disagree, and both must survive."""
        got = human_baselines("catastrophe:ai", "2100")
        if not got:
            self.skipTest("no baselines pulled for catastrophe:ai @2100")
        self.assertEqual(len(got), len({b["project"] for b in got}),
                         "one project appears twice for the same cell")
        self.assertGreaterEqual(len(got), 1)

    def test_a_question_with_no_comparison_returns_nothing(self):
        self.assertEqual(human_baselines("disempowerment", "2100"), [],
                         "disempowerment has no prior panel in her column")


class TestGraph1Coverage(unittest.TestCase):
    """The panel states coverage; it must state it from the data."""

    @classmethod
    def setUpClass(cls):
        path = REPO_ROOT / "results" / "graph1_data.json"
        if not path.exists():
            raise unittest.SkipTest("graph1_data.json not built")
        cls.cov = json.loads(path.read_text())["humanCoverage"]
        cls.doc = load_human_baselines()

    def test_with_and_without_partition_the_panel(self):
        both = set(self.cov["with"]) & set(self.cov["without"])
        self.assertEqual(both, set(), f"listed as both covered and not: {both}")

    def test_covered_questions_really_have_a_number(self):
        for qid in self.cov["with"]:
            with self.subTest(qid):
                got = [b for b in self.doc["baselines"] if b["question_id"] == qid]
                self.assertTrue(got, f"{qid} claims a human number and has none")

    def test_uncovered_questions_really_have_none(self):
        have = {b["question_id"] for b in self.doc["baselines"]}
        for qid in self.cov["without"]:
            self.assertNotIn(qid, have,
                             f"{qid} is listed as having no human number while "
                             f"one was pulled for it")

    def test_panel_names_are_dated(self):
        """So no surface ever prints 'XPT 2022' as a constant again."""
        for panel, when in self.cov["panels"].items():
            self.assertRegex(when or "", r"^\d{4}-\d{2}-\d{2}$",
                             f"panel {panel} carries no elicitation date")

    def test_humans_are_plotted(self):
        """Reversed 2026-08-18: humans come back now that the panels are pulled
        with their source wording. Every covered question must carry a
        non-empty series; every uncovered one must carry none — the chart draws
        what is there and nothing where it is absent."""
        self.assertIs(self.cov["plotted"], True)
        qs = {q["id"]: q for q in self._blob()["questions"]}
        for qid in self.cov["with"]:
            self.assertTrue(qs[qid].get("human"),
                            f"{qid} is covered but carries no plotted series")
        for qid in self.cov["without"]:
            self.assertFalse(qs.get(qid, {}).get("human"),
                             f"{qid} is uncovered but a series was plotted")

    def test_plotted_points_match_the_baselines(self):
        """Every drawn point is a real panel median, so the chart can never
        show a number the source-of-truth file does not hold."""
        for qid in self.cov["with"]:
            q = {x["id"]: x for x in self._blob()["questions"]}[qid]
            for hm in q["human"]:
                for h, v in hm["ps"].items():
                    src = [b for b in self.doc["baselines"]
                           if b["question_id"] == qid and b["horizon"] == h
                           and b["project"] == hm["panel"]]
                    self.assertTrue(src, f"{qid} {h} {hm['panel']} drawn with "
                                         f"no baseline behind it")
                    self.assertAlmostEqual(
                        src[0]["groups"][hm["group"]]["median"], v, places=6,
                        msg=f"{qid} {h} {hm['panel']} {hm['group']} drawn as "
                            f"{v}, baseline says otherwise")

    def _blob(self):
        path = REPO_ROOT / "results" / "graph1_data.json"
        return json.loads(path.read_text())


if __name__ == "__main__":
    unittest.main()
