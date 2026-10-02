"""The extinction pair: data/auto-arc/addendum-extinction-2026-09-15.json.

The project team, 2026-09-15: add extinction probabilities so the models' numbers
can be set beside AI researchers'. What that needs, and what each test pins:

  * the pair is in the set, in XPT's wording, verbatim -- the comparison with
    XPT's superforecasters and experts is like-for-like or it is nothing;
  * a run made BEFORE the pair entered the set is still a complete run, and a
    run made after it is not complete without it (questions_asked_on);
  * the views do not draw an empty panel for a question no run has answered;
  * the AI-extinction-under-general-extinction relation is audited;
  * the human baselines carry XPT at every horizon it answered and the
    AI-researcher survey's number at 2100, with the wording difference stated;
  * the instrument tag moved, so rows elicited beside the pair are told apart.

Run with:  python3 -m unittest tests.test_extinction_addendum -v
"""
import copy
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from redlines.coherence import audit, load_spec
from redlines.conditional import COMBINED_PROTOCOL, newest_protocol, protocol_line
from redlines.questions import (all_questions, human_baselines, load_crosscutting,
                                load_crosscutting_doc, load_human_baselines,
                                questions_asked_on, severity_deaths)
from redlines.runlog import complete_panel_rows
from redlines.views import graph1, graph2, timeline

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "legacy-questions" / "starter_questions.json"
ADDENDUM = ROOT / "data" / "auto-arc" / "addendum-extinction-2026-09-15.json"
RUN_BEFORE = ROOT / "results" / "runs" / "2026-09-14T1553Z.jsonl"   # 35 questions
PAIR = ("extinction:general", "extinction:ai")
SINCE = "2026-09-15"
XPT_SETS = {"extinction:general": "10. Total Extinction Risk",
            "extinction:ai": "4. AI Extinction Risk"}


def _rows(path=RUN_BEFORE):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _with_pair(rows):
    """`rows` plus synthetic extinction rows, one per catastrophe row, so a
    complete 35-question run becomes a complete 37-question one."""
    out = copy.deepcopy(rows)
    twin = {"catastrophe:general": "extinction:general", "catastrophe:ai": "extinction:ai"}
    for r in rows:
        if r["question_id"] in twin:
            c = copy.deepcopy(r)
            c["question_id"] = twin[r["question_id"]]
            for f in c["forecasts"]:
                f["probability"] = f["probability"] / 10
            out.append(c)
    return out


def _dated(rows, day):
    out = copy.deepcopy(rows)
    for r in out:
        r["run_date"] = day
        r["elicited_at"] = f"{day}T12:00:00+00:00"
    return out


class TestThePairIsInTheSet(unittest.TestCase):

    def test_two_questions_with_since_and_an_extinction_severity(self):
        cross = {q["id"]: q for q in load_crosscutting()}
        for qid in PAIR:
            with self.subTest(qid):
                q = cross[qid]
                self.assertEqual(q["since"], SINCE)
                self.assertEqual(q["source"], "data/auto-arc/addendum-extinction-2026-09-15.json")
                self.assertEqual(q["severity"]["kind"], "extinction")
                self.assertEqual(q["severity"]["floor_population"], 5000)
                # Placed at the whole population on the shared axis -- the same
                # number Graph 2's Extinction reference mark is drawn at.
                self.assertEqual(severity_deaths(q), load_crosscutting_doc()["world_pop"])
                self.assertEqual(q["horizons"], cross["catastrophe:ai"]["horizons"])
        marks = json.load(open(ROOT / "data" / "historical_events.json"))["events"]
        ext = next(e for e in marks if e["id"] == "extinction")
        self.assertEqual(ext["severity"]["central"], severity_deaths(cross["extinction:ai"]))

    def test_the_workbook_questions_carry_no_since(self):
        for q in load_crosscutting():
            if q["id"] not in PAIR:
                self.assertNotIn("since", q, q["id"])

    def test_wording_is_xpts_verbatim(self):
        """The comparison with XPT's panel is only like-for-like if the question
        is the one they answered. The archive holds XPT's text; ours must be it,
        with only the horizon list re-rendered on the set's grid."""
        archive = {q["id"]: q for q in json.load(open(ARCHIVE))["questions"]}
        cross = {q["id"]: q for q in load_crosscutting()}
        for qid, set_name in XPT_SETS.items():
            with self.subTest(qid):
                theirs = archive[set_name]["text"]
                head, _, tail = theirs.partition("\n\n")
                stem = head.split(" by the end of 2030/2050/2100?")[0]
                self.assertTrue(cross[qid]["text"].startswith(stem + " within 6 months / within 12 months / "))
                self.assertTrue(cross[qid]["text"].endswith("by the end of 2100?"))
                for para in filter(None, tail.split("\n")):
                    self.assertIn(para.strip(), cross[qid]["criteria"],
                                  f"XPT's criteria paragraph is not carried verbatim: {para[:60]}")

    def test_addendum_states_its_provenance_and_review_status(self):
        doc = json.load(open(ADDENDUM))
        self.assertIn("project team", doc["provenance"]["requested_by"])
        self.assertIn("PENDING REVIEW", doc["provenance"]["status"])
        prov = load_crosscutting_doc()["provenance"]
        self.assertEqual([a["file"] for a in prov["addenda"]],
                         [str(ADDENDUM.relative_to(ROOT)),
                          "data/auto-arc/addendum-extinction-rung-2026-09-16.json"])
        self.assertEqual(prov["addenda"][0]["questions"], list(PAIR))


class TestRunsBeforeTheAddendumStayComplete(unittest.TestCase):

    def test_questions_asked_on(self):
        before, on = questions_asked_on("2026-09-14"), questions_asked_on(SINCE)
        # The extinction RUNG (a second addendum) entered a day after the pair.
        rung = {f"ladder:{c}:extinction" for c in ("ai", "bio", "cyber", "misalign")}
        self.assertEqual(set(all_questions()) - set(before), set(PAIR) | rung)
        self.assertEqual(set(all_questions()) - set(on), rung)
        self.assertEqual(set(questions_asked_on("2026-09-16")), set(all_questions()))

    def test_complete_before_incomplete_after_complete_with_the_pair(self):
        rows = _rows()
        self.assertEqual(len(complete_panel_rows(rows)), len(rows),
                         "the 2026-09-14 run is a complete 35-question reading")
        # Dated the pair's own day: the extinction rung (since 2026-09-16) is
        # not yet owed, so the pair alone completes it.
        later = _dated(rows, "2026-09-15")
        self.assertEqual(complete_panel_rows(later), [],
                         "a run on or after the pair's `since` owes the pair")
        filled = _with_pair(later)
        self.assertEqual(len(complete_panel_rows(filled)), len(filled))

    def test_views_draw_the_pair_only_once_a_run_answers_it(self):
        rows = _rows()
        with patch.object(graph1, "load_runlog", return_value=rows):
            ids = {q["id"] for q in graph1.build()["questions"]}
        self.assertFalse(set(PAIR) & ids)
        with patch.object(graph1, "load_runlog", return_value=_with_pair(_dated(rows, "2026-09-15"))):
            b = graph1.build()
        ids = {q["id"] for q in b["questions"]}
        self.assertTrue(set(PAIR) <= ids)
        q = next(q for q in b["questions"] if q["id"] == "extinction:ai")
        self.assertTrue(q["median"], "the synthetic rows should give a median")
        self.assertIn("XPT", {h["panel"] for h in q["human"]})
        self.assertIn(("ESPAI", "ai_researcher"), {(h["panel"], h["group"]) for h in q["human"]})
        with patch.object(timeline, "load_runlog", return_value=rows):
            ids = {q["id"] for q in timeline.build()["questions"]}
        self.assertFalse(set(PAIR) & ids)
        with patch.object(timeline, "load_runlog", return_value=_with_pair(_dated(rows, "2026-09-15"))):
            ids = {q["id"] for q in timeline.build()["questions"]}
        self.assertTrue(set(PAIR) <= ids)


class TestSeverityChartAnchors(unittest.TestCase):
    """Graph 2 drew the pair as diamonds at the Extinction mark from 2026-09-15
    until the extinction RUNG joined every ladder on 2026-09-16 (project lead:
    show the probabilities like normal). No anchors are drawn now, whether or
    not a run answered the pair; the curves end at extinction themselves."""

    def test_no_anchors_before_a_run_answers_the_pair(self):
        with patch.object(graph2, "load_runlog", return_value=_rows()):
            b = graph2.build()
        self.assertTrue(all(v["anchors"] == [] for v in b["byHorizon"].values()))
        self.assertIsNone(b["anchorsNote"])

    def test_no_anchors_once_answered_either(self):
        rows = _with_pair(_dated(_rows(), "2026-09-15"))
        with patch.object(graph2, "load_runlog", return_value=rows):
            b = graph2.build()
        h = "2030"
        self.assertEqual(b["byHorizon"][h]["anchors"], [])
        # The curves carry one point per rung the run answered, and the pair
        # is never a point of a curve.
        for c in b["byHorizon"][h]["causes"]:
            self.assertEqual(len(c["rungs"]), len([r for r in b["rungs"] if r["rung"] != "extinction"]))
        self.assertIsNone(b["anchorsNote"])

class TestCoherenceAndBaselines(unittest.TestCase):

    def test_ai_extinction_is_audited_under_general_extinction(self):
        spec = load_spec()
        self.assertIn({"narrower": "extinction:ai", "broader": "extinction:general"},
                      [{k: r[k] for k in ("narrower", "broader")} for r in spec["relations"]["subset"]])
        P = {("extinction:ai", "m"): {"2100": 2.0}, ("extinction:general", "m"): {"2100": 1.0}}
        self.assertGreaterEqual(audit(P, spec, labels=["m"], horizons=["2100"])["SUBSET"]["bad"], 1)
        P = {("extinction:ai", "m"): {"2100": 0.5}, ("extinction:general", "m"): {"2100": 1.0}}
        self.assertEqual(audit(P, spec, labels=["m"], horizons=["2100"])["SUBSET"]["bad"], 0)

    def test_xpt_baselines_at_every_horizon_xpt_answered(self):
        doc = load_human_baselines()
        for qid in PAIR:
            for h in ("2030", "2050", "2100"):
                with self.subTest(qid, h=h):
                    xpt = [b for b in human_baselines(qid, h, doc) if b["project"] == "XPT"]
                    self.assertEqual(len(xpt), 1)
                    self.assertEqual(set(xpt[0]["groups"]), {"superforecaster", "expert"})
                    self.assertEqual(xpt[0]["source_question"]["category"].lower().split()[0],
                                     "total" if qid == "extinction:general" else "ai")
        # XPT's published 2100 medians for AI extinction: supers 0.38%, experts 3%.
        b = next(b for b in human_baselines("extinction:ai", "2100", doc) if b["project"] == "XPT")
        self.assertAlmostEqual(b["groups"]["superforecaster"]["median"], 0.375, places=3)
        self.assertAlmostEqual(b["groups"]["expert"]["median"], 3.0, places=3)

    def test_ai_researcher_baseline_carries_its_wording_and_caveat(self):
        doc = load_human_baselines()
        es = [b for b in human_baselines("extinction:ai", "2100", doc) if b["project"] == "ESPAI"]
        self.assertEqual(len(es), 1)
        b = es[0]
        self.assertEqual(b["groups"]["ai_researcher"]["median"], 5.0)
        self.assertEqual(b["groups"]["ai_researcher"]["n"], 655)
        self.assertIn("within the next 100 years", b["source_question"]["text"])
        self.assertIn("similarly permanent and severe disempowerment", b["source_question"]["text"])
        self.assertIn("arXiv:2401.02843", b["published"]["citation"])
        self.assertIn("nearest horizon", b["published"]["horizon_note"])
        self.assertEqual(b["elicited"]["date"], "2023-10-11")
        # No other question carries the survey: it names AI, not any cause.
        self.assertEqual([x["question_id"] for x in doc["baselines"] if x["project"] == "ESPAI"],
                         ["extinction:ai"])


class TestTheQuestionsNameNoSource(unittest.TestCase):
    """2026-10-01: the pair's criteria had said whose number to match ("the
    three points above are the Existential Risk Persuasion Tournament's ...
    own criteria, kept verbatim so the forecasts compare with that panel's"),
    and the 09-16 rationales anchored on it by name. The question-set workbook keeps
    human comparisons in a column, never in the question text; so does the
    instrument now. The LEAP policy descriptions in the CONDITIONS section
    are LEAP's own text and say "FRI will consult ..." by design."""

    NAMES = re.compile(r"\bXPT\b|Persuasion Tournament|\bAIRO\b|\bFRI\b|Forecasting Research", re.I)

    def test_no_question_text_or_criteria_names_a_source(self):
        ladder = json.load(open(ROOT / "data" / "autoarc_ladder.json"))
        for q in load_crosscutting() + ladder["questions"]:
            for field in ("text", "criteria"):
                with self.subTest(q["id"], field=field):
                    self.assertIsNone(self.NAMES.search(q.get(field) or ""))
            for k, v in (q.get("details") or {}).items():
                with self.subTest(q["id"], detail=k):
                    self.assertIsNone(self.NAMES.search(v or ""))

    def test_the_published_prompt_names_no_source_above_the_conditions(self):
        import importlib.util
        from datetime import date
        spec = importlib.util.spec_from_file_location("run_unified", ROOT / "code" / "run_unified.py")
        ru = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ru)
        policies = ru.load_policies(ROOT / "data" / "combined_conditions.json")
        groups, by_group, horizons, _, sp = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
        prompt, _, _ = ru.build_prompt_joint(groups, by_group, horizons, sp,
                                             policies["conditions"], policies, date(2026, 10, 2))
        questions, sep, _ = prompt.partition("===== CONDITIONS =====")
        self.assertTrue(sep)
        self.assertIsNone(self.NAMES.search(questions))
        for name in ("XPT", "Persuasion", "AIRO", "Forecasting Research"):
            self.assertNotIn(name, prompt)


class TestTheTagMoved(unittest.TestCase):

    def test_combined_v8_with_its_lineage(self):
        # v8 (2026-10-01, the pair unnamed) sits above v7 (2026-09-16, the
        # extinction rung) and v6 (the pair); a log holding only v5 and v6
        # rows still reads as v6 until a later run lands.
        self.assertEqual(COMBINED_PROTOCOL, "unified-joint-combined-v8")
        self.assertEqual(protocol_line(COMBINED_PROTOCOL)[1:],
                         ("unified-joint-combined-v7", "unified-joint-combined-v6", "unified-joint-combined-v5",
                          "unified-joint-combined-v4", "unified-joint-combined-v3",
                          "unified-joint-combined-v2", "unified-joint-combined-v1"))
        rows = [{"protocol": "unified-joint-combined-v5"}, {"protocol": "unified-joint-combined-v6"}]
        kept, tag = newest_protocol(rows, protocol_line(COMBINED_PROTOCOL))
        self.assertEqual(tag, "unified-joint-combined-v6")
        self.assertEqual(kept, [rows[1]])


if __name__ == "__main__":
    unittest.main()
