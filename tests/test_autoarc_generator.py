"""The question files must be generated, never edited. This is what enforces it.

Project lead, 2026-08-17: the data source that hydrates all of the language on
the dashboard must be the same one that hydrates what the superforecasters were
asked and what the models are asked, so the two can never come apart.

A promise like that decays the first time someone fixes a typo in the JSON
instead of in the source files. test_generated_files_are_current is the whole
guarantee: regenerate from data/auto-arc/ and diff byte-for-byte against what is
tracked. Hand-edit either file and the build fails, naming the file.

The rest of the tests here guard the SHAPE of the set, because the generator
reads a spreadsheet someone else maintains. A renamed sheet column or a dropped
row would otherwise produce a smaller, perfectly valid-looking question set, and
the dashboard would quietly plot less than it claims to.

Run with:  python3 -m unittest tests.test_autoarc_generator -v
"""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GEN = REPO / "code" / "make_autoarc_questions.py"
CROSS = REPO / "data" / "autoarc_crosscutting.json"
LADDER = REPO / "data" / "autoarc_ladder.json"

try:
    import openpyxl  # noqa: F401
    HAVE_XLSX = True
except ImportError:
    HAVE_XLSX = False


def load_generator():
    spec = importlib.util.spec_from_file_location("autoarc_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_XLSX, "openpyxl not installed")
class TestGeneratedFilesAreCurrent(unittest.TestCase):
    """The tracked JSON must be exactly what the generator produces today."""

    def test_generated_files_are_current(self):
        gen = load_generator()
        cross_doc, ladder_doc = gen.render(gen.read_rows(), gen.read_definitions())
        for path, doc in ((CROSS, cross_doc), (LADDER, ladder_doc)):
            with self.subTest(file=path.name):
                self.assertEqual(
                    gen.dumps(doc), path.read_text(encoding="utf-8"),
                    f"{path.name} is not what code/make_autoarc_questions.py "
                    "produces from data/auto-arc/. Either it was edited by hand "
                    "— which breaks the single source of truth, so make the "
                    "change in Bridget's files instead — or the generator moved "
                    "and the output was not regenerated. Run: python3 "
                    "code/make_autoarc_questions.py")


class TestSetShape(unittest.TestCase):
    """Guards against a source change silently shrinking the question set."""

    @classmethod
    def setUpClass(cls):
        cls.cross = json.loads(CROSS.read_text(encoding="utf-8"))
        cls.ladder = json.loads(LADDER.read_text(encoding="utf-8"))

    def test_counts(self):
        """41 questions: 5 cross-cutting (3 from the workbook, the extinction
        pair from the 2026-09-15 addendum), and 4 causes x 9 rungs (the
        workbook's eight plus the extinction rung, the 2026-09-16 addendum)."""
        self.assertEqual(len(self.cross["questions"]), 5)
        self.assertEqual([q["id"] for q in self.cross["questions"] if q.get("since")],
                         ["extinction:general", "extinction:ai"])
        self.assertEqual(len(self.ladder["causes"]), 4)
        self.assertEqual(len(self.ladder["rungs"]), 9)
        self.assertEqual(len(self.ladder["questions"]), 36)
        self.assertEqual([q["id"] for q in self.ladder["questions"] if q.get("since")],
                         [f"ladder:{c}:extinction" for c in ("ai", "bio", "cyber", "misalign")])

    def test_every_cause_spans_every_rung(self):
        """The ladder's whole point: causes comparable at equal severity.

        A cause missing a rung is not a gap in a chart, it is a cause that
        cannot be compared with the others at that severity.
        """
        rungs = {r["short"] for r in self.ladder["rungs"]}
        for c in self.ladder["causes"]:
            got = {q["rung"] for q in self.ladder["questions"]
                   if q["cause"] == c["key"]}
            with self.subTest(cause=c["key"]):
                self.assertEqual(got, rungs, f"{c['key']} is missing {rungs - got}")

    def test_severity_is_structured_never_prose(self):
        """No threshold may reach a view as a string it has to parse.

        This is the defect that produced the 80x error in the live headline:
        "10 million deaths" typed into JSX, next to a question about 10% of
        humans alive. Every consumer reads numbers from here instead.
        """
        for q in self.ladder["questions"]:
            with self.subTest(q=q["id"]):
                s = q["severity"]
                if q.get("since"):   # the extinction rung: a population floor, no dollar leg
                    self.assertEqual(s["kind"], "extinction")
                    self.assertIsInstance(s["deaths"], (int, float))
                    self.assertIsNone(s["damages_usd"])
                    continue
                self.assertEqual(s["kind"], "deaths_or_damages")
                self.assertIsInstance(s["deaths"], (int, float))
                self.assertIsInstance(s["damages_usd"], (int, float))
        for q in self.cross["questions"]:
            with self.subTest(q=q["id"]):
                self.assertIn(q["severity"]["kind"], ("population_share", "none", "extinction"))

    def test_the_two_severity_legs_agree_with_the_stated_vsl(self):
        """Deaths and dollars must stay one ladder, not two.

        The criteria state a value of a statistical life ($10M until the set's
        2026-08-31 revision, $2.2M since), so each rung's dollar leg should be
        that many times its death leg. If that ratio drifts, the two legs
        disagree about which rung is harder and the axis stops being monotone
        — at which point a curve on Graph 2 means nothing. The number is
        parsed from the definitions (make_autoarc_questions.stated_vsl) and
        written to the ladder's notes, and every consumer of the exchange
        rate reads or pins THAT, never a typed 1e7.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location("gen", REPO / "code" / "make_autoarc_questions.py")
        gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)
        vsl = gen.stated_vsl(gen.read_definitions())
        self.assertEqual(vsl, 2.2e6)
        self.assertEqual(self.ladder["notes"]["vsl_usd"], vsl)
        for r in self.ladder["rungs"]:
            if r.get("damages_usd") is None:    # the extinction rung has no dollar leg
                continue
            with self.subTest(rung=r["short"]):
                self.assertAlmostEqual(r["damages_usd"] / r["deaths"], vsl, delta=1.0)
        from redlines.conditional import USD_PER_DEATH
        from redlines.config import REPO_ROOT  # noqa: F401
        self.assertEqual(USD_PER_DEATH, vsl)
        hist = json.load(open(REPO / "data" / "historical_events.json"))
        self.assertEqual(hist["conversion"]["vsl_usd"], vsl)

    def test_rungs_ascend(self):
        deaths = [r["deaths"] for r in self.ladder["rungs"]]
        self.assertEqual(deaths, sorted(deaths))

    def test_rolling_horizons_carry_a_window(self):
        """A rolling horizon without a window cannot be resolved to a date.

        Project lead, 2026-08-18: rolling, but track the ABSOLUTE resolution
        date so the forecast can be seen and resolved over time. The months
        field is what lets a run stamp that date.
        """
        self.assertEqual([h["id"] for h in self.ladder["rolling"]], ["6mo", "12mo"])
        for h in self.ladder["rolling"]:
            with self.subTest(h=h["id"]):
                self.assertGreater(h["months"], 0)
        for h in self.ladder["rolling"]:
            self.assertIn(h["id"], self.ladder["horizons"])

    def test_every_question_is_on_the_same_horizon_grid(self):
        """One x-axis for the whole set, cross-cutting questions included.

        Reversed on 2026-08-28 (project lead: re-elicit the cross-cutting ones at
        shorter durations for consistency). Until then this test asserted the
        opposite -- the cross-cutting three carried no rolling horizon, on the
        reasoning that P(10% of humanity dies within 6 months) is noise. The
        cost was that Graph 1's two rail groups could not be read against each
        other at the near end: four expected-loss rows from 6mo, three
        catastrophe panels starting at 2030.

        The grid is a SUPERSET of what the workbook asks of the cross-cutting
        rows (2030/2050/2100). The extra cells are ours. What stays the
        workbook's is human_wanted -- checked below, because no re-elicitation
        of ours can add a horizon to a panel that has already reported.
        """
        grid = self.ladder["horizons"]
        self.assertEqual(grid[:2], [h["id"] for h in self.ladder["rolling"]])
        for q in self.cross["questions"] + self.ladder["questions"]:
            with self.subTest(q=q["id"]):
                self.assertEqual(q["horizons"], grid)
        rolling = {h["id"] for h in self.ladder["rolling"]}
        for q in self.cross["questions"]:
            with self.subTest(q=q["id"]):
                # A human panel answered the years it answered.
                self.assertEqual(set(q["human_wanted"]) & (rolling | {"2028"}), set())

    def test_resolution_year_is_scoped_where_the_window_rule_uses_it(self):
        """A question may not be asked at a horizon its own criteria exclude.

        The cross-cutting window rule ends "December 31 of the resolution
        year (2030, 2050, or 2100)" -- its three horizons inside the rule. Since
        2026-08-28 we also ask at 6mo/12mo/2028, so without a scope note the
        model gets a question and a criterion that disagree.

        The note attaches by the phrase, never by parsing years: human
        disempowerment defines a STATE, carries no measurement window, and must
        not pick one up.
        """
        for q in self.cross["questions"]:
            with self.subTest(q=q["id"]):
                rule = "the resolution year" in q["criteria"]
                scoped = "Scope of \"the resolution year\"" in q["criteria"]
                self.assertEqual(scoped, rule)
                if scoped:
                    # It opens the slot; it does not restate the window.
                    self.assertIn("December 31, 2025", q["criteria"])
                    self.assertIn("at most five years", q["criteria"])

    def test_featured_ids_exist_and_are_not_duplicated(self):
        """Graph 1 plots these BY REFERENCE, so they must resolve.

        A featured id that matches no question is a blank row on the headline
        panel; a featured question copied into the cross-cutting file instead
        would be elicited twice and pollute the coherence lattice.
        """
        ids = {q["id"] for q in self.ladder["questions"]}
        cross_ids = {q["id"] for q in self.cross["questions"]}
        self.assertTrue(self.ladder["featured"])
        for fid in self.ladder["featured"]:
            with self.subTest(featured=fid):
                self.assertIn(fid, ids)
                self.assertNotIn(fid, cross_ids)

    def test_every_question_carries_its_own_criteria(self):
        """Criteria must be per question, not the union of everybody's.

        The source writes "**Question details**" once under each question, so a
        flat parse concatenates all four and hands the disempowerment question
        the epidemic severity rules. That bug shipped in the first draft of the
        generator and is why this test exists.
        """
        seen = {}
        for q in self.cross["questions"]:
            with self.subTest(q=q["id"]):
                self.assertTrue(q["criteria"].strip(), "empty criteria")
                self.assertNotIn(q["criteria"], seen,
                                 f"{q['id']} shares criteria with {seen.get(q['criteria'])}")
                seen[q["criteria"]] = q["id"]
        by_cause = {}
        for q in self.ladder["questions"]:
            by_cause.setdefault(q["cause"], set()).add(q["criteria"])
        for cause, texts in by_cause.items():
            with self.subTest(cause=cause):
                self.assertEqual(len(texts), 1, "one definition per cause")
                self.assertTrue(next(iter(texts)).strip(), "empty criteria")
        self.assertEqual(len({next(iter(t)) for t in by_cause.values()}),
                         len(by_cause), "two causes share a definition")

    def test_no_markdown_escapes_survive(self):
        r"""\[2030\] is the editor's backslash, not the author's bracket."""
        for path in (CROSS, LADDER):
            with self.subTest(file=path.name):
                self.assertNotIn("\\\\[", path.read_text(encoding="utf-8"))

    def test_ai_catastrophe_criteria_resolve_their_back_reference(self):
        """Her AI-catastrophe criteria open "The points above also apply".

        In a prompt there is no above. If the referenced section is not carried
        forward, the model gets a dangling pointer and none of the definitions
        it points at — including the whole measurement-window rule.
        """
        q = next(q for q in self.cross["questions"] if q["id"] == "catastrophe:ai")
        general = next(q2 for q2 in self.cross["questions"]
                       if q2["id"] == "catastrophe:general")
        self.assertIn("Carried forward", q["criteria"])
        self.assertIn(general["criteria"].strip()[:120], q["criteria"])

    def test_relations_reference_real_questions(self):
        """A relation naming a question that does not exist checks nothing.

        Which reads as 0/0 = 0.0% — indistinguishable from perfect coherence in
        every report we publish.
        """
        qids = ({q["id"] for q in self.ladder["questions"]}
                | {q["id"] for q in self.cross["questions"]})
        causes = {c["key"] for c in self.ladder["causes"]}
        rungs = {r["short"] for r in self.ladder["rungs"]}
        rel = self.ladder["relations"]

        self.assertIn(rel["cross"]["container"], causes)
        for k in rel["cross"]["contained"]:
            self.assertIn(k, causes)
        self.assertNotIn(rel["cross"]["container"], rel["cross"]["contained"])

        for b in rel["bracket"]:
            with self.subTest(bracket=b["narrower"]):
                self.assertIn(b["narrower"], qids)
                self.assertIn(b["cause"], causes)
                self.assertIn(b["rung"], rungs)
        for p in rel["subset"]:
            with self.subTest(subset=p["narrower"]):
                self.assertIn(p["narrower"], qids)
                self.assertIn(p["broader"], qids)

    def test_the_bracket_rung_is_the_side_the_wording_licenses(self):
        """Only one side of the 10%-of-population bracket is safe.

        ~820M deaths sits between the 100M and 1B rungs. The >=100M rung is a
        strictly easier event on both legs, so it bounds the catastrophe
        question. The >=1B rung does NOT: 820M is below 1B on deaths, but that
        rung also resolves on $10Q, so neither event contains the other.
        Asserting the bound is a rung BELOW the threshold is what keeps a future
        edit from quietly checking the unlicensed side.
        """
        share = next(q["severity"] for q in self.cross["questions"]
                     if q["id"] == "catastrophe:ai")
        equiv = share["deaths_equiv"]
        by_short = {r["short"]: r for r in self.ladder["rungs"]}
        for b in self.ladder["relations"]["bracket"]:
            with self.subTest(bracket=b["narrower"]):
                self.assertLess(by_short[b["rung"]]["deaths"], equiv)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_XLSX, "openpyxl not installed")
class TestInputsAgree(unittest.TestCase):
    """The set needs two files. Nothing else stops them drifting apart.

    The workbook carries composition and no criteria at all — its text column
    tops out at 310 characters. Every definition lives in the markdown. So a
    revision that touches one file and not the other yields a set whose
    composition and whose definitions describe different questions, and the
    generator would emit it without complaint.
    """

    @classmethod
    def setUpClass(cls):
        cls.gen = load_generator()
        cls.rows = cls.gen.read_rows()
        cls.defs = cls.gen.read_definitions()

    def test_the_shipped_inputs_agree(self):
        self.gen.crosscheck(self.rows, self.defs)   # raises SystemExit on drift

    def test_crosscheck_catches_an_undefined_incident_type(self):
        """A new incident type in the workbook must not be dropped in silence.

        This is the drift that would cost most: the ladder would build, every
        panel would render, and one whole cause would simply be absent.
        """
        rows = self.rows + [dict(self.rows[-1], **{
            "Category": "AI-related supply chain incident",
            "Human comparisons (Project)": "-"})]
        with self.assertRaises(SystemExit) as e:
            self.gen.crosscheck(rows, self.defs)
        self.assertIn("map to no cause", str(e.exception))

    def test_crosscheck_catches_a_severity_the_markdown_does_not_define(self):
        rows = self.rows + [dict(self.rows[-1], **{
            "Category": "Cyber",
            "Human comparisons (Project)": "-",
            "Severity": "500 deaths (or equivalent morbidity) or $5 billion"})]
        with self.assertRaises(SystemExit) as e:
            self.gen.crosscheck(rows, self.defs)
        self.assertIn("no definition in the markdown", str(e.exception))


class TestNoThresholdLiteralsInPageSource(unittest.TestCase):
    """No page chunk may state a threshold. This is the SSOT, enforced.

    Project lead, 2026-08-17: the page text and the questions must never come
    apart. There was exactly one way they could, and it had already happened —
    web/demo/80-app.jsx announced "Catastrophic = >= 10 million deaths (or >=
    $1T economic damage)" beside a question asking about 10% of humans alive,
    roughly 820 million. Eighty times out, in the headline, until someone
    caught it by eye.

    Nothing structural prevented that. Prose in a JSX file has no link to the
    question it describes, so it cannot be wrong in a way anything notices.
    This test is the link: every threshold a reader sees must arrive through a
    blob field rendered by redlines/questions.py::severity_label.

    Comments are stripped before scanning — the fix's own comment quotes the
    string it replaced, which is the right place for it.
    """

    WEB = REPO / "web"
    # Patterns that only appear when someone has written a threshold by hand.
    BANNED = [
        r"\d+\s*million\s+deaths",
        r"\d+\s*billion\s+deaths",
        r"\$\s*\d+\s*(?:trillion|quadrillion)\b",
        r"\$\d+\s*[TQ]\b",
        r"\d+\s*%\s+of\s+(?:the\s+)?(?:population|humans)",
    ]

    @staticmethod
    def strip_comments(src):
        """Blank comments but keep every newline, so line numbers stay true.

        Deleting them shifts every line after a block comment, and a failure
        that points at the wrong line sends the reader hunting.
        """
        def blank(m):
            return re.sub(r"[^\n]", " ", m.group(0))
        src = re.sub(r"/\*.*?\*/", blank, src, flags=re.S)
        return re.sub(r"//[^\n]*", blank, src)

    def test_no_threshold_literals(self):
        offenders = []
        for path in sorted(self.WEB.rglob("*.jsx")):
            # The mock chunks are the lead author's original prototype with invented
            # numbers, kept verbatim as the fallback when no blob is injected.
            # They describe nothing real, so they cannot disagree with it.
            if "mock" in path.name:
                continue
            body = self.strip_comments(path.read_text(encoding="utf-8"))
            for pat in self.BANNED:
                for m in re.finditer(pat, body, re.I):
                    line = body[:m.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(REPO)}:{line}  {m.group(0)!r}")
        self.assertEqual(
            offenders, [],
            "threshold(s) written by hand into page source:\n  "
            + "\n  ".join(offenders)
            + "\n\nRender it from the question data instead — the blob fields "
              "`severity` (Graph 1 questions) and `rungs[].label` (Graph 2) "
              "come from redlines/questions.py::severity_label, so they cannot "
              "disagree with the question they describe.")


@unittest.skipUnless(HAVE_XLSX, "openpyxl not installed")
class TestNothingIsHandWritten(unittest.TestCase):
    """Every word describing a question must come from the source files.

    The generator is the one place where hardcoding is most tempting and least
    visible — it is a build step, so a typed-in value looks derived. The first
    draft of it did exactly that in three places: it hardcoded 0.10 for the
    catastrophe threshold rather than parsing "10% of population" from the
    Severity column, and it invented display names ("AI-enabled epidemic" for
    her "AI-related human-caused epidemic") and template phrases.

    None of those would have been caught by the threshold-literal ban, which
    only reads page source. These tests read the generator's OUTPUT back
    against her INPUT.
    """

    @classmethod
    def setUpClass(cls):
        cls.gen = load_generator()
        cls.rows = cls.gen.read_rows()
        cls.defs = cls.gen.read_definitions()
        cls.cross = json.loads(CROSS.read_text(encoding="utf-8"))
        cls.ladder = json.loads(LADDER.read_text(encoding="utf-8"))

    def test_cause_labels_are_her_words(self):
        """Not ours. A shorter name we prefer is still a second wording."""
        hers = set(self.gen.incident_options(self.defs))
        for c in self.ladder["causes"]:
            with self.subTest(cause=c["key"]):
                self.assertIn(c["label"], hers)

    def _addenda(self):
        """{question id: (its addendum doc, its entry)} for every addendum question.
        An addendum is an input of the same standing as the workbook (the
        extinction pair, 2026-09-15): its names and severities are checked
        against ITS file, exactly as hers are checked against hers."""
        out = {}
        for doc in self.gen.read_addenda():
            for q in doc["questions"]:
                out[q["id"]] = (doc, q)
        return out

    def test_cross_cutting_names_are_her_category_values(self):
        cats = {r["Category"] for r in self.rows}
        addenda = self._addenda()
        for q in self.cross["questions"]:
            with self.subTest(q=q["id"]):
                if q["id"] in addenda:
                    self.assertEqual(q["name"], addenda[q["id"]][1]["name"])
                    self.assertEqual(q["since"], addenda[q["id"]][0]["since"])
                else:
                    self.assertNotIn("since", q)
                    self.assertIn(q["name"], cats)

    def test_every_severity_quotes_the_workbook_verbatim(self):
        """source_text must appear in the Severity column, character for character
        (or, for an addendum question, in its addendum's severity block)."""
        sevs = {r["Severity"].strip() for r in self.rows}
        addenda = self._addenda()
        for q in self.ladder["questions"] + self.cross["questions"]:
            src = q["severity"].get("source_text")
            if q["severity"]["kind"] == "none":
                continue
            with self.subTest(q=q["id"]):
                if q["id"] in addenda:
                    self.assertEqual(src, addenda[q["id"]][0]["severity"]["source_text"])
                    continue
                if q.get("source"):   # an addendum RUNG: its own file's severity text
                    doc = json.loads((REPO / q["source"]).read_text())
                    self.assertEqual(src, doc["severity"]["source_text"])
                    continue
                self.assertIn(src, sevs,
                              f"{q['id']} severity {src!r} is not a value in "
                              "her Severity column — it was composed here")

    def test_a_changed_threshold_flows_through(self):
        """Move the source threshold and the output must move with it.

        The sharpest test of the whole SSOT claim: if the author changes what a
        catastrophe means, nothing in this repo should need editing. Mutate the
        Severity column in memory and check the number, the label and the
        death-equivalent all follow.
        """
        rows = [dict(r) for r in self.rows]
        for r in rows:
            if r["Category"] in ("General catastrophe", "AI catastrophe"):
                r["Severity"] = "25% of population"
        cross, _ = self.gen.render(rows, self.defs)
        q = next(q for q in cross["questions"] if q["id"] == "catastrophe:ai")
        self.assertEqual(q["severity"]["share"], 0.25)
        self.assertIn("25%", q["severity"]["label"])
        self.assertAlmostEqual(q["severity"]["deaths_equiv"],
                               0.25 * self.gen.WORLD_POP)

    def test_a_renamed_incident_type_flows_through(self):
        """Rename a cause in her markdown and the label and question text follow."""
        defs = json.loads(json.dumps(self.defs))
        body = defs["Incident options"]["body"]
        defs["Incident options"]["body"] = body.replace(
            "AI-related cyber incident", "AI-enabled cyber operation")
        blocks = defs["Incident options"]["blocks"]["Incident definitions"]
        defs["Incident options"]["blocks"]["Incident definitions"] = blocks.replace(
            "AI-related cyber incident", "AI-enabled cyber operation")
        for c in self.gen.CAUSES:
            if c["key"] == "cyber":
                c = dict(c)
        gen_causes = [dict(c, def_key="AI-enabled cyber operation")
                      if c["key"] == "cyber" else c for c in self.gen.CAUSES]
        old, self.gen.CAUSES[:] = list(self.gen.CAUSES), gen_causes
        try:
            _, ladder = self.gen.render(self.rows, defs)
            cyber = next(c for c in ladder["causes"] if c["key"] == "cyber")
            self.assertEqual(cyber["label"], "AI-enabled cyber operation")
            q = next(q for q in ladder["questions"] if q["cause"] == "cyber")
            self.assertIn("AI-enabled cyber operations", q["text"])
        finally:
            self.gen.CAUSES[:] = old

    def test_an_unparseable_severity_is_an_error_not_a_default(self):
        """A severity we cannot read must stop the build, not become 'none'.

        Silently treating an unrecognised threshold as "no severity" would drop
        a question off the axis while everything still rendered.
        """
        rows = [dict(r) for r in self.rows]
        for r in rows:
            if r["Category"] == "AI catastrophe":
                r["Severity"] = "a quarter of everyone"
        with self.assertRaises(SystemExit) as e:
            self.gen.render(rows, self.defs)
        self.assertIn("needs a parser", str(e.exception))


class TestEmittedWorkbook(unittest.TestCase):
    """The workbook we propose back to its author must be joinable, row by row.

    The Question ID column exists so the author can line one of their rows up
    with one of our forecasts. It shipped with the string "ladder:<cause>:<rung>"
    in all 128 ladder rows — a placeholder that was never substituted, so 32
    rows of a cause shared one id and the column did the opposite of its job.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import openpyxl
        except ImportError:
            raise unittest.SkipTest("openpyxl not installed")
        path = REPO / "results" / "autoarc_workbook_with_details.xlsx"
        if not path.exists():
            raise unittest.SkipTest(
                "workbook not emitted; run "
                "python3 code/make_autoarc_questions.py --emit-workbook")
        ws = openpyxl.load_workbook(path)["Auto-ARC questions - long"]
        cls.head = [c.value for c in ws[1]]
        cls.rows = [r for r in ws.iter_rows(min_row=2, values_only=True)
                    if r[cls.head.index("Question ID")]]

    def col(self, name):
        return self.head.index(name)

    def test_no_unsubstituted_placeholders(self):
        bad = sorted({r[self.col("Question ID")] for r in self.rows
                      if "<" in str(r[self.col("Question ID")])})
        self.assertEqual(bad, [], f"placeholder(s) left in the id column: {bad}")

    def test_every_id_matches_its_rows_severity(self):
        """The id names a rung; the row names a severity. They must agree."""
        ladder = json.loads((REPO / "data" / "autoarc_ladder.json").read_text())
        by_id = {q["id"]: q for q in ladder["questions"]}
        sev_col, id_col = self.col("Severity"), self.col("Question ID")
        checked = 0
        for r in self.rows:
            q = by_id.get(r[id_col])
            if not q:
                continue          # cross-cutting or the P6-bio comparison rows
            checked += 1
            self.assertEqual(
                q["severity"]["source_text"], str(r[sev_col]).strip(),
                f"{r[id_col]} is on a row whose severity is "
                f"{r[sev_col]!r}, but that id's rung is "
                f"{q['severity']['source_text']!r}")
        self.assertEqual(checked, 128,
                         "expected the 4 causes x 8 rungs x 4 of her horizons; "
                         f"matched {checked}")

    def test_every_ladder_question_appears(self):
        ladder = json.loads((REPO / "data" / "autoarc_ladder.json").read_text())
        # An addendum rung is generated from its own file, not from her sheet.
        want = {q["id"] for q in ladder["questions"] if not q.get("since")}
        got = {r[self.col("Question ID")] for r in self.rows}
        self.assertEqual(want - got, set(),
                         "ladder question(s) missing from the workbook")
