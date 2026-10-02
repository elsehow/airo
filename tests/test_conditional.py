"""The conditional arm must change nothing but the condition.

Three guarantees, each of which the conditional panel's numbers depend on:

  1. With no condition, the runner's prompt is exactly the weekly run's
     prompt. The {condition} slot renders empty, so the same-session
     unconditional arms ARE the published protocol and can stand as the
     zero line.
  2. Every condition renders, carries LEAP's exogeneity instruction
     verbatim, and states no relation between the questions -- the same
     ban tests/test_coherence.py enforces on the unconditional prompt,
     extended to the rendered condition text, which comes from data.
  3. data/leap_policies.json is what code/make_leap_policies.py produces
     from the vendored survey documents. The policy text a model sees is
     traceable to the document, never hand-edited in the JSON.

Run with:  python3 -m unittest tests.test_conditional -v
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The LEAP survey pull under data/leap/ is internal and not published; the
# generators that read it exit with a message on a public clone, and the tests
# that regenerate from it skip. The tracked extract data/leap_reference.json
# (code/make_leap_reference.py) is what the views and these tests read.
LEAP_RAW_DIR = REPO / "data" / "leap"
LEAP_RAW = LEAP_RAW_DIR / "axes-2026-09-02.json"
HAVE_LEAP_RAW = LEAP_RAW.exists()
LEAP_REFERENCE = REPO / "data" / "leap_reference.json"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from redlines.conditional import expected_loss, summarize, table  # noqa: E402

# The shape of one call: 35 questions, and the question x horizon cells the
# prompt asks for. Written out rather than recomputed, because the point of the
# assertion is that the prompt asks for the number of cells we MEANT to ask for.
# 201 -> 210 on 2026-08-28, when the three cross-cutting questions moved onto
# the ladder's six-horizon grid (3 questions x 3 added horizons); 210 -> 222 on
# 2026-09-15, when the extinction pair joined (2 questions x 6 horizons).
QUESTIONS, CELLS = 41, 246

# Our framing (the CONDITION_BLOCK literal) may state neither a relation
# between the questions -- the same ban tests/test_coherence.py puts on the
# unconditional prompt -- nor a direction for the policy's effect.
BANNED_RELATION = ["must respect", "non-decreasing", "non-increasing",
                   "must not increase", "may not exceed", "strictly harder",
                   "contains every specific cause", "consistent with each other",
                   "logical relation"]
BANNED_DIRECTION = ["should lower", "should reduce", "should raise", "will reduce",
                    "will lower", "will increase", "expect the policy to",
                    "less risky", "safer world"]
# LEAP's policy text is carried verbatim and is not ours to police for
# relation phrases ("a federal maximum that states may not exceed" is P1's
# own definition of ceiling preemption). It is checked for direction only.


def _load_runner():
    """Import code/run_unified.py.

    This used to stub `forecast.cruxgen._llm` and `.tools` into sys.modules,
    because importing the runner reached into the xrisk-canaries checkout. Those
    two modules were vendored here on 2026-08-28 (redlines/llm.py,
    redlines/tools.py) and neither imports litellm at module scope, so the real
    imports now resolve offline and the stub is gone.
    """
    spec = importlib.util.spec_from_file_location("run_unified", REPO / "code" / "run_unified.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConditionBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.policies = cls.ru.load_policies()
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)

    def _prompt(self, cond):
        groups, by_group, horizons, _, spec = self.batch
        p, n, cells = self.ru.build_prompt(groups, by_group, horizons, spec,
                                           date(2026, 8, 27), False, cond, self.policies)
        return p, n, cells

    def test_unconditional_prompt_has_no_condition_slot_residue(self):
        p, n, cells = self._prompt(None)
        self.assertNotIn("CONDITION", p)
        self.assertNotIn("{condition}", p)
        # The slot sits between the date line and the question header, and
        # renders to exactly the blank line that was always there.
        self.assertIn("Today is 2026-08-27.\n\nBelow are 41 forecasting", p)
        self.assertEqual((n, cells), (QUESTIONS, CELLS))

    def test_every_condition_renders_with_leap_instruction(self):
        instr = self.policies["conditioning"]["instruction"]
        self.assertIn("treat the policy implementation as exogenous", instr)
        for c in self.policies["conditions"]:
            p, n, cells = self._prompt(c)
            self.assertEqual((n, cells), (QUESTIONS, CELLS), c["id"])
            self.assertIn(f"===== CONDITION: {c['label']} =====", p)
            self.assertIn(instr, p)
            self.assertIn(c["assume"], p)
            self.assertIn(self.policies["conditioning"]["frontier_model"], p)
            # The questions follow the block unchanged.
            self.assertIn("Below are 41 forecasting questions", p)
            self.assertTrue(p.index("=====\n\nBelow are") < p.index("===== AI-RELATED INCIDENT"))

    def test_condition_text_states_no_relation_or_direction(self):
        lit = self.ru.CONDITION_BLOCK.lower()
        found = [b for b in BANNED_RELATION + BANNED_DIRECTION if b in lit]
        self.assertEqual(found, [], f"CONDITION_BLOCK literal: {found}")
        for c in self.policies["conditions"]:
            blob = self.ru.condition_block(c, self.policies).lower()
            found = [b for b in BANNED_DIRECTION if b in blob]
            self.assertEqual(found, [], f"{c['id']}: {found}")

    def test_conditions_are_the_eight_policies_not_the_outcomes(self):
        ids = [c["id"] for c in self.policies["conditions"]]
        self.assertEqual(ids, ["sq", "p1", "p2a", "p2b", "p3a", "p3b", "p4", "p5"])
        self.assertTrue(all(not c["policy"].startswith("O") for c in self.policies["conditions"]))
        self.assertIn("O1", self.policies["policies"])  # parsed for the record only

    def test_no_export_escapes_survive(self):
        text = json.dumps(self.policies["conditions"]) + json.dumps(self.policies["conditioning"])
        self.assertEqual(re.findall(r"\\\\[.)(\[\]#&_+-]", text), [])
        self.assertNotIn("**", text)

    def test_policies_json_is_current(self):
        if not LEAP_RAW_DIR.exists():
            self.skipTest("internal LEAP survey documents not present; the tracked set stands")
        r = subprocess.run([sys.executable, str(REPO / "code" / "make_leap_policies.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestSummarize(unittest.TestCase):
    """The delta arithmetic, on a hand-built log."""

    def _row(self, qid, label, p2030, cond=None, run="r1"):
        return {"run_id": run, "question_id": qid, "label": label,
                "forecasts": [{"horizon": "2030", "probability": p2030},
                              {"horizon": "2050", "probability": min(1, 3 * p2030)}],
                "condition": ({"id": cond, "leap_id": cond.upper(), "label": cond} if cond else None),
                "experiment": "t"}

    def test_per_model_then_ensemble(self):
        rows = [
            self._row("q", "A", 0.010), self._row("q", "A", 0.012),   # two unconditional arms
            self._row("q", "A", 0.005, "p2b"),
            self._row("q", "B", 0.100), self._row("q", "B", 0.100),
            self._row("q", "B", 0.150, "p2b"),
        ]
        policies = {"conditions": [{"id": "p2b", "label": "cap", "leap_id": "P2 (b)"}],
                    "source": {"wave": "t"}}
        s = summarize(rows, policies)
        cell = s["questions"]["q"]["2030"]
        a, b = cell["models"]["A"], cell["models"]["B"]
        self.assertAlmostEqual(a["baseline"], 0.011)
        self.assertAlmostEqual(a["conditions"]["p2b"]["delta_pp"], -0.6)
        self.assertAlmostEqual(b["conditions"]["p2b"]["delta_pp"], 5.0)
        # A lowered, B raised; the ensemble median of the two deltas sits between.
        e = cell["ensemble"]["p2b"]
        self.assertEqual((e["raised"], e["lowered"]), (1, 1))
        self.assertAlmostEqual(e["delta_pp"], 2.2)
        # Noise: A's two unconditional calls differ by 0.2pp; B's by 0.
        self.assertAlmostEqual(a["noise"]["pp"], 0.2)
        self.assertAlmostEqual(cell["noise"]["pp"], 0.1)
        self.assertIn("baseline (unconditional)", table(s, "q", "2030"))

    def test_model_without_baseline_is_skipped_not_borrowed(self):
        rows = [self._row("q", "A", 0.01), self._row("q", "B", 0.2, "p1")]
        policies = {"conditions": [{"id": "p1", "label": "x", "leap_id": "P1"}],
                    "source": {"wave": "t"}}
        cell = summarize(rows, policies)["questions"]["q"]["2030"]
        self.assertNotIn("B", cell["models"])
        self.assertEqual(cell["ensemble"], {})


class TestJointInstrument(unittest.TestCase):
    """--joint: one call per model carrying every cell under every condition."""

    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.policies = cls.ru.load_policies()
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)
        cls.conds = cls.policies["conditions"]

    def test_joint_prompt_carries_the_questions_and_every_condition(self):
        groups, by_group, horizons, _, spec = self.batch
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                                 self.conds, self.policies, date(2026, 8, 27))
        self.assertEqual((n, cells), (QUESTIONS, CELLS))
        # cells x (unconditional + one pass per condition).
        self.assertIn(f"{CELLS * (1 + len(self.conds))} probabilities", p)
        # The question blocks are build_prompt's, unchanged, and come first.
        base, _, _ = self.ru.build_prompt(groups, by_group, horizons, spec, date(2026, 8, 27))
        qblock = base[base.index("===== AI-RELATED INCIDENT"):base.index("\nHorizons: ")]
        self.assertIn(qblock, p)
        self.assertLess(p.index("===== AI-RELATED INCIDENT"), p.index("===== CONDITIONS ====="))
        for c in self.conds:
            self.assertIn(f"--- {c['id']} ---", p)
            self.assertIn(c["assume"], p)
        self.assertIn("--- unconditional ---", p)
        self.assertIn(self.policies["conditioning"]["unconditional_forecast"], p)
        self.assertIn(self.policies["conditioning"]["instruction"], p)

    def test_joint_framing_states_no_relation_or_direction(self):
        lit = (self.ru.PROMPT_JOINT + self.ru.CONDITIONS_BLOCK + self.ru.CONDITION_ITEM).lower()
        found = [b for b in BANNED_RELATION + BANNED_DIRECTION if b in lit]
        self.assertEqual(found, [], f"joint literals: {found}")
        # And nothing about which condition should be higher or lower.
        for w in ("lower than", "higher than", "at most", "at least as", "bundle should"):
            self.assertNotIn(w, lit)

    def test_joint_tool_requires_every_condition_per_cell(self):
        t = self.ru.submit_tool_joint(["q"], ["2030"], [c["id"] for c in self.conds])
        ps = t["parameters"]["properties"]["forecasts"]["items"]["properties"]["probabilities"]
        self.assertEqual(ps["required"], ["unconditional"] + [c["id"] for c in self.conds])
        self.assertEqual(len(ps["properties"]), 9)

    def test_joint_cleaner_splits_by_condition(self):
        raw = [{"question_id": "q", "horizon": "2030",
                "probabilities": {"unconditional": 0.1, "sq": 0.12, "p5": 0.02, "bogus": 0.5}},
               {"question_id": "q", "horizon": "6mo", "probabilities": {"unconditional": 0.01}},
               {"question_id": "zz", "horizon": "2030", "probabilities": {"unconditional": 0.3}}]
        g = self.ru.clean_forecasts_joint(raw, {"q": {"2030"}}, ["2030"], ["sq", "p5"])
        self.assertEqual(set(g), {"unconditional", "sq", "p5"})
        self.assertEqual(g["sq"]["q"], [{"horizon": "2030", "probability": 0.12}])
        self.assertEqual(g["unconditional"]["q"], [{"horizon": "2030", "probability": 0.1}])
        self.assertIsNone(self.ru.clean_forecasts_joint("not json", {"q": {"2030"}}, ["2030"], ["sq"]))

    def test_joint_protocol_tag_is_its_own(self):
        self.assertNotEqual(self.ru.PROTOCOL_JOINT, self.ru.PROTOCOL)
        self.assertIn("joint", self.ru.PROTOCOL_JOINT)


class TestProtocolTransition(unittest.TestCase):
    """The Policy-levers tab accepts two joint tags without ever pooling them.

    Accepting both was a deliberate, temporary allowance for the additive
    v1 -> v2 bump (2026-08-28) so the tab does not go blank in the week between
    the bump and the first v2 run. The thing it must never become is a summary
    computed over two instruments at once: v1 and v2 asked different question
    sets, and their unconditional arms are different elicitations.
    """

    def _rows(self, *specs):
        return [{"question_id": "catastrophe:ai", "label": "m", "protocol": proto,
                 "elicited_at": f"{day}T12:00:00+00:00", "experiment": None,
                 "forecasts": [{"horizon": "2030", "probability": 0.01}],
                 "condition": None}
                for proto, day in specs]

    def test_newest_protocol_on_the_latest_day_wins_and_the_other_is_dropped(self):
        from redlines.views.conditional import PROTOCOLS
        self.assertEqual(PROTOCOLS[0], "unified-joint-v6")
        self.assertIn("unified-joint-v1", PROTOCOLS)
        rows = self._rows(("unified-joint-v1", "2026-08-28"),
                          ("unified-joint-v2", "2026-08-28"))
        day = max(r["elicited_at"][:10] for r in rows)
        kept = [r for r in rows if r["elicited_at"][:10] == day]
        proto = min({r["protocol"] for r in kept}, key=PROTOCOLS.index)
        kept = [r for r in kept if r["protocol"] == proto]
        self.assertEqual([r["protocol"] for r in kept], ["unified-joint-v2"])

    def test_v1_still_renders_while_no_v2_run_exists(self):
        """The point of the allowance: no blank week."""
        from redlines.views.conditional import PROTOCOLS
        rows = self._rows(("unified-joint-v1", "2026-08-27"))
        proto = min({r["protocol"] for r in rows}, key=PROTOCOLS.index)
        self.assertEqual(proto, "unified-joint-v1")

    def test_the_pilot_protocol_is_still_excluded(self):
        from redlines.views.conditional import PROTOCOLS
        self.assertNotIn("unified-batch-v2", PROTOCOLS)


class TestOutsideNoise(unittest.TestCase):
    def test_range_separation(self):
        from redlines.conditional import outside_noise
        self.assertTrue(outside_noise([0.01], [0.02, 0.03, 0.025]))
        self.assertTrue(outside_noise([0.04, 0.05], [0.02, 0.03]))
        self.assertFalse(outside_noise([0.025], [0.02, 0.03]))
        self.assertFalse(outside_noise([0.01, 0.04], [0.02, 0.03]))   # straddles
        self.assertIsNone(outside_noise([], [0.02, 0.03]))
        self.assertIsNone(outside_noise([0.01], [0.02]))      # one unconditional value is not a range

    def test_paired_ci_decides(self):
        def row(label, p, cond=None, call="u"):
            return {"run_id": "r", "question_id": "q", "label": label, "call_id": f"r:{call}:{label}",
                    "forecasts": [{"horizon": "2030", "probability": p}],
                    "condition": ({"id": cond, "leap_id": "P5", "label": cond} if cond else None)}
        policies = {"conditions": [{"id": "p5", "label": "b", "leap_id": "P5"}], "source": {"wave": "t"}}
        # Three models, three repeats each, the SAME call answering both sides:
        # the ratio is paired within the call, so between-call wander cancels.
        rows = []
        for lbl, us in (("A", (0.10, 0.14, 0.12)), ("B", (0.30, 0.20, 0.25)), ("C", (0.05, 0.06, 0.04))):
            for k, u in enumerate(us):
                rows.append(row(lbl, u, call=f"j{k}"))
                rows.append(row(lbl, u * 0.5, "p5", call=f"j{k}"))      # always exactly half
        cell = summarize(rows, policies, rungs=[])["questions"]["q"]["2030"]
        a = cell["models"]["A"]["conditions"]["p5"]
        self.assertTrue(a["paired"]); self.assertEqual(a["n_pairs"], 3)
        self.assertAlmostEqual(a["ratio"], 0.5)
        self.assertAlmostEqual(a["ci"][0], 0.5); self.assertAlmostEqual(a["ci"][1], 0.5)   # zero spread
        self.assertTrue(a["outside"])
        e = cell["ensemble"]["p5"]
        self.assertAlmostEqual(e["ratio"], 0.5)
        self.assertTrue(e["outside"]); self.assertEqual(e["n_outside_dir"], 3)
        # Repeats that disagree in sign: the interval straddles 1x.
        rows2 = [row("A", 0.10, call="j0"), row("A", 0.05, "p5", call="j0"),
                 row("A", 0.10, call="j1"), row("A", 0.20, "p5", call="j1"),
                 row("A", 0.10, call="j2"), row("A", 0.11, "p5", call="j2")]
        a2 = summarize(rows2, policies, rungs=[])["questions"]["q"]["2030"]["models"]["A"]["conditions"]["p5"]
        self.assertFalse(a2["outside"]); self.assertLess(a2["ci"][0], 1); self.assertGreater(a2["ci"][1], 1)
        # One repeat: no interval, no verdict.
        solo = [row("A", 0.10, call="j0"), row("A", 0.05, "p5", call="j0")]
        s1 = summarize(solo, policies, rungs=[])["questions"]["q"]["2030"]
        self.assertIsNone(s1["models"]["A"]["conditions"]["p5"]["ci"])
        self.assertIsNone(s1["ensemble"]["p5"]["outside"])

    def test_unpaired_fallback_for_separate_calls(self):
        # Different calls on each side (the 2026-08-27 pilot): Welch interval.
        def row(label, p, cond=None, call="u"):
            return {"run_id": "r", "question_id": "q", "label": label, "call_id": f"r:{call}:{label}",
                    "forecasts": [{"horizon": "2030", "probability": p}],
                    "condition": ({"id": cond, "leap_id": "P5", "label": cond} if cond else None)}
        policies = {"conditions": [{"id": "p5", "label": "b", "leap_id": "P5"}], "source": {"wave": "t"}}
        rows = [row("A", 0.10, call="u1"), row("A", 0.12, call="u2"), row("A", 0.11, call="u3"),
                row("A", 0.02, "p5", call="p5")]
        a = summarize(rows, policies, rungs=[])["questions"]["q"]["2030"]["models"]["A"]["conditions"]["p5"]
        self.assertFalse(a["paired"]); self.assertIsNotNone(a["ci"]); self.assertTrue(a["outside"])


RUNGS = [("100", 100.0), ("1k", 1e3), ("10k", 1e4), ("100k", 1e5),
         ("1M", 1e6), ("10M", 1e7), ("100M", 1e8), ("1B", 1e9)]


class TestExpectedLoss(unittest.TestCase):
    """The ladder folded to one number: a floor on E[loss], in death-equivalents."""

    def test_floor_values_each_band_at_its_lower_rung(self):
        # P(>=100)=1, P(>=1k)=0.5, everything above zero: mass 0.5 in [100,1k)
        # valued at 100, mass 0.5 in [1k, 10k) valued at 1k -> 50 + 500.
        s = {r: 0.0 for r, _ in RUNGS}
        s["100"], s["1k"] = 1.0, 0.5
        e = expected_loss(s, RUNGS)
        self.assertAlmostEqual(e["value"], 1.0 * 100 + 0.5 * 900)
        self.assertEqual(e["repaired"], 0)

    def test_top_rungs_dominate_and_share_is_reported(self):
        s = {r: 0.5 ** i for i, (r, _) in enumerate(RUNGS)}   # halves each rung
        e = expected_loss(s, RUNGS)
        self.assertGreater(e["top_share"], 0.8)
        self.assertAlmostEqual(e["value"], sum(t for t in e["terms"]))

    def test_non_monotone_ladder_is_lowered_not_raised(self):
        s = {r: 0.5 ** i for i, (r, _) in enumerate(RUNGS)}
        s["10M"] = s["1M"] * 2                     # a higher rung more likely
        e = expected_loss(s, RUNGS)
        mono = dict(s); mono["10M"] = s["1M"]      # the repair lowers 10M to 1M's value
        self.assertAlmostEqual(e["value"], expected_loss(mono, RUNGS)["value"])
        self.assertEqual(e["repaired"], 1)

    def test_missing_rung_gives_none(self):
        s = {r: 0.1 for r, _ in RUNGS[:-1]}
        self.assertIsNone(expected_loss(s, RUNGS))

    def test_summarize_folds_ladder_into_loss_row(self):
        def row(rung, label, p, cond=None, call="u0"):
            return {"run_id": "r", "question_id": f"ladder:ai:{rung}", "label": label,
                    "call_id": f"r:{call}:{label}", "grounded": True,
                    "forecasts": [{"horizon": "2030", "probability": p}],
                    "condition": ({"id": cond, "leap_id": "P5", "label": cond} if cond else None)}
        rows = []
        for i, (r, _) in enumerate(RUNGS):
            rows.append(row(r, "A", 0.5 ** i))                       # arm 0
            rows.append(row(r, "A", 0.5 ** i, call="u1"))            # arm 1, identical
            rows.append(row(r, "A", 0.5 ** i / 2, cond="p5"))        # every rung halved
        policies = {"conditions": [{"id": "p5", "label": "bundle", "leap_id": "P5"}],
                    "source": {"wave": "t"}}
        s = summarize(rows, policies, rungs=RUNGS)
        cell = s["questions"]["loss:ai"]["2030"]
        self.assertEqual(cell["value_kind"], "loss")
        a = cell["models"]["A"]
        self.assertEqual(a["baseline_n"], 2)
        self.assertAlmostEqual(a["conditions"]["p5"]["ratio"], 0.5)   # linear in S
        self.assertIsNone(a["conditions"]["p5"]["delta_pp"])
        self.assertAlmostEqual(cell["ensemble"]["p5"]["ratio"], 0.5)
        self.assertEqual((cell["ensemble"]["p5"]["lowered"], cell["ensemble"]["p5"]["raised"]), (1, 0))
        self.assertIn("expected loss", table(s, "loss:ai", "2030", "ratio"))
        # The rung rows themselves are still summarised.
        self.assertIn("ladder:ai:1B", s["questions"])


if __name__ == "__main__":
    unittest.main()


class TestConditionSets(unittest.TestCase):
    """--conditions: the capability set renders through the same instrument
    and the published (LEAP) text is pinned byte-for-byte."""

    # The LEAP conditions block as stamped (condition.sha256) on every joint row
    # in results/conditional_runs.jsonl since 2026-08-27, and the whole joint
    # prompt at a fixed date. If either changes, the weekly instrument has
    # changed: bump the protocol tag, do not edit here.
    #
    # The block SHA has NOT moved across the v1 -> v2 bump and must not -- LEAP's
    # text is the one thing the question-set change was not allowed to touch.
    # The prompt SHA did, once, on 2026-08-28: v1's value is kept below so the
    # bump stays legible as a bump, and any later drift still fails this test.
    LEAP_BLOCK_SHA = "0fa0e1b45ae81db64381f8ec330042858e3e1e00b28e1b6dbd00d7811222938b"
    # The whole LEAP-set prompt, pinned by content. History: V1 = the 201-cell
    # prompt (2026-08-27); 2026-08-28 = the cross-cutting three on the six-
    # horizon grid (210 cells); 2026-09-02 = the agentic harness's research
    # paragraph, then Bridget's 2026-08-31 question revisions. LEAP_BLOCK_SHA
    # -- the conditions' wording, LEAP's own text -- never moved, which is the
    # pin that matters. A changed prompt must arrive WITH a changed tag: rows
    # in the log were elicited under the prompt of their tag.
    LEAP_PROMPT_SHA_V1 = "b8cb19508626977838c1d452a060be87b6e7716672e3c45fe5cace80b6771d1b"
    LEAP_PROMPT_SHA_2026_08_28 = "d9b774b4df13e6180ec4768fbc54f81c1e05434f131ec7c776b52788597f87f7"
    # 2026-09-02 evening: the grid delivered in pieces (submit_cells) -- the closing paragraph changed.
    LEAP_PROMPT_SHA_2026_09_02 = "49bf81839161af1449da291549d001c71a671d2e24906e34d5eacfd912fea876"
    # September 10: approved prospective incident windows/campaign boundaries;
    # the unchanged LEAP condition block is still pinned separately above.
    LEAP_PROMPT_SHA_2026_09_10 = "581693c3278bb7515ed335d7f738b529c31ad8f507b259155856d47b2f47a28e"
    # 2026-09-15: the debrief turn (redlines.llm.call_tools `debrief`) -- the
    # closing paragraph now tells the model it will be asked, per question
    # group, what drove its numbers. Project lead, 2026-09-11: harness changes
    # between runs do not bump the protocol tag; the pin moves with a dated
    # line here, and every row's prompt_sha256 still tells the prompts apart.
    LEAP_PROMPT_SHA_2026_09_15 = "d81b3791ae3dbc7a9fdf501761370a882bc49b1a8200d29228d35bdf03d842e8"
    # 2026-09-15, later the same day: the extinction pair (35 -> 37 questions,
    # 210 -> 222 cells), with the tag bumped to unified-joint-v4 / combined-v6.
    LEAP_PROMPT_SHA_2026_09_15_EXTINCTION = "ce234d7918b369899cd64fa71fb55b9aa557a040219d1aee4b09b6c0022d61d0"
    # 2026-09-16: the debrief asked PER QUESTION (project lead: the standard
    # elicitation plus a rationale per rung per outcome) -- the closing
    # paragraph's priming sentence changed. Harness change, tag unchanged.
    LEAP_PROMPT_SHA_2026_09_16_DEBRIEF = "e0fd7f850d00a4733f738a7b00620258937497806cf46479713b399751ac0e38"
    # 2026-09-16, later: the extinction RUNG on every incident ladder
    # (data/auto-arc/addendum-extinction-rung-2026-09-16.json): 37 -> 41
    # questions, 222 -> 246 cells, tag unified-joint-v5 / combined-v7.
    LEAP_PROMPT_SHA_2026_09_16_RUNG = "cbe9b29179d740e3f2860242d3c9e8d5e42b1bd570852c451aa73e048794f6aa"
    # 2026-10-01: the extinction pair's criteria stop naming their source
    # (XPT, AIRO); same rules, same cells. Tag unified-joint-v6 / combined-v8.
    LEAP_PROMPT_SHA_CURRENT = "5f9f47b8c3c25dec3e6f35b255e9494bc9fdac4debe05c4b9225e28d9dc4fef0"
    # The archived 2026-08-31 definitions rendered by the CURRENT template
    # (test_archived_definitions_reproduce_the_old_prompt): stable while the
    # archive is untouched; moves whenever the template does, as on 2026-09-15
    # and 2026-09-16.
    LEAP_PROMPT_SHA_ARCHIVED = "b705585878ec49a2d202490cf0225dda2a04b049f8e285c4e6d76f5053a9b3d4"

    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.leap = cls.ru.load_policies()
        cls.eci = cls.ru.load_policies(REPO / "data" / "eci_conditions.json")
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)

    def test_leap_text_is_pinned(self):
        import hashlib
        groups, by_group, horizons, _, spec = self.batch
        block = self.ru.conditions_block(self.leap["conditions"], self.leap)
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), self.LEAP_BLOCK_SHA)
        p, _, _ = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                             self.leap["conditions"], self.leap, date(2026, 8, 28))
        self.assertEqual(hashlib.sha256(p.encode()).hexdigest(), self.LEAP_PROMPT_SHA_CURRENT)
        self.assertNotIn(self.LEAP_PROMPT_SHA_CURRENT, (self.LEAP_PROMPT_SHA_V1, self.LEAP_PROMPT_SHA_2026_08_28,
                                                        self.LEAP_PROMPT_SHA_2026_09_02, self.LEAP_PROMPT_SHA_2026_09_10,
                                                        self.LEAP_PROMPT_SHA_2026_09_15,
                                                        self.LEAP_PROMPT_SHA_2026_09_15_EXTINCTION,
                                                        self.LEAP_PROMPT_SHA_2026_09_16_DEBRIEF,
                                                        self.LEAP_PROMPT_SHA_2026_09_16_RUNG))

    def test_archived_definitions_reproduce_the_old_prompt(self):
        import hashlib
        archive = REPO / "data" / "instruments" / "legacy-2026-08-31"
        groups, by_group, horizons, _, spec = self.ru.load_batch(
            archive / "autoarc_ladder.json", archive / "autoarc_crosscutting.json", self.ru.UNBATCHED)
        prompt, _, _ = self.ru.build_prompt_joint(
            groups, by_group, horizons, spec, self.leap["conditions"], self.leap, date(2026, 8, 28))
        # The archive's definitions under today's template: a stable prompt
        # that differs from the current one only by the definitions.
        self.assertEqual(hashlib.sha256(prompt.encode()).hexdigest(), self.LEAP_PROMPT_SHA_ARCHIVED)
        self.assertNotEqual(self.LEAP_PROMPT_SHA_ARCHIVED, self.LEAP_PROMPT_SHA_CURRENT)
        self.assertEqual(self.ru.PROTOCOL_JOINT, "unified-joint-v6")
        self.assertEqual(self.ru.set_protocol(self.leap), self.ru.PROTOCOL_JOINT)
        self.assertEqual(self.ru.set_slug(self.leap), "leap")

    def test_eci_set_is_current_and_shaped_like_the_policies(self):
        r = subprocess.run([sys.executable, str(REPO / "code" / "make_eci_conditions.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c["id"] for c in self.eci["conditions"]], ["eci174", "eci186", "eci210"])
        self.assertEqual([c["projection"]["percentile"] for c in self.eci["conditions"]], [10, 50, 90])
        proj = json.load(open(REPO / "data" / "eci_projection_2026-08-21.json"))
        for c in self.eci["conditions"]:
            self.assertEqual(c["projection"]["value"], proj["projection"]["2027EOY"][f"p{c['projection']['percentile']}"])
            self.assertEqual(int(c["id"][3:]), round(c["projection"]["value"]))
            for k in ("label", "assume", "description"):
                self.assertTrue(c[k])
        self.assertEqual(self.ru.set_protocol(self.eci), "unified-joint-eci-v1")
        self.assertNotEqual(self.ru.set_protocol(self.eci), self.ru.PROTOCOL_JOINT)
        self.assertEqual(self.ru.set_slug(self.eci), "eci")

    def test_eci_prompt_carries_the_levels_and_not_the_percentiles(self):
        groups, by_group, horizons, _, spec = self.batch
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                                 self.eci["conditions"], self.eci, date(2026, 8, 28))
        self.assertEqual((n, cells), (QUESTIONS, CELLS))
        self.assertIn(f"{CELLS * (1 + len(self.eci['conditions']))} probabilities", p)
        self.assertIn("under each capability condition", p)
        for c in self.eci["conditions"]:
            self.assertIn(f"--- {c['id']} ---", p)
            self.assertIn(c["assume"], p)
        self.assertIn(self.eci["conditioning"]["definitions"], p)
        self.assertIn("Claude Fable 5 (Jun 2026) 162", p)
        # The question blocks are the same ones the policy instrument carries.
        base, _, _ = self.ru.build_prompt(groups, by_group, horizons, spec, date(2026, 8, 28))
        qblock = base[base.index("===== AI-RELATED INCIDENT"):base.index("\nHorizons: ")]
        self.assertIn(qblock, p)
        # No percentile, no pace verdict, no policy text.
        cond = p[p.index("===== CONDITIONS ====="):]
        for w in ("percentile", "p10", "p50", "p90", "median", "slow", "fast",
                  "Status Quo", "preemption", "liability"):
            self.assertNotIn(w, cond, w)
        lit = (self.eci["conditioning"]["instruction"] + self.eci["conditioning"]["definitions"]
               + "".join(c["assume"] + c["description"] for c in self.eci["conditions"])).lower()
        found = [b for b in BANNED_RELATION + BANNED_DIRECTION if b in lit]
        self.assertEqual(found, [], f"eci text: {found}")

    def test_summarize_takes_the_eci_set(self):
        from redlines.conditional import summarize
        def row(label, p, cond=None, call="u"):
            return {"run_id": "r", "question_id": "catastrophe:ai", "label": label, "grounded": True,
                    "protocol": "unified-joint-eci-v1", "call_id": call,
                    "forecasts": [{"horizon": "2030", "probability": p}, {"horizon": "2100", "probability": p}],
                    "condition": ({"id": cond} if cond else None)}
        rows = [row("m", 0.01, call="c1"), row("m", 0.02, "eci210", "c1"),
                row("m", 0.012, call="c2"), row("m", 0.024, "eci210", "c2")]
        s = summarize(rows, policies=self.eci, horizons=("2030",), rungs=[])
        self.assertEqual([c["id"] for c in s["conditions"]], ["eci174", "eci186", "eci210"])
        self.assertIsNone(s["conditions"][0]["leap_id"])
        self.assertEqual(s["meta"]["condition_set"], "eci")
        e = s["questions"]["catastrophe:ai"]["2030"]["ensemble"]["eci210"]
        self.assertAlmostEqual(e["ratio"], 2.0, places=6)
        self.assertIsNone(s["questions"]["catastrophe:ai"]["2100"]["horizon_note"])


class TestSelfElicitedSet(unittest.TestCase):
    """data/eci_self_conditions.json: the model forecasts the frontier ECI at
    end of 2030 (p10/p25/p50/p75/p90) and conditions on its own numbers."""

    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.leap = cls.ru.load_policies()
        cls.es = cls.ru.load_policies(REPO / "data" / "eci_self_conditions.json")
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)

    @staticmethod
    def live_frontier():
        """The frontier the generator quotes: the newest Epoch snapshot's
        (redlines.eci.frontier_history), in the shape history_line reads."""
        sys.path.insert(0, str(REPO))
        from redlines import eci
        return [{"date": d, "score": sc, "model": m} for d, sc, m in eci.frontier_history()]

    @staticmethod
    def history_line(entry):
        """One line of the prompt's frontier history, as the generator renders it
        (code/make_eci_self_conditions.py::frontier_history)."""
        return f"  {entry['date']}  {entry['score']:6.1f}  {entry['model']}"

    def test_set_is_current_and_keyed_by_percentile(self):
        r = subprocess.run([sys.executable, str(REPO / "code" / "make_eci_self_conditions.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c["id"] for c in self.es["conditions"]],
                         ["eci_p10", "eci_p25", "eci_p50", "eci_p75", "eci_p90"])
        # Five percentiles asked since 2026-09-02; a condition on each of them
        # since 2026-09-03 (the tails were whiskers only until then).
        self.assertEqual(self.es["elicit"]["fields"], ["p10", "p25", "p50", "p75", "p90"])
        self.assertEqual([c["field"] for c in self.es["conditions"]], ["p10", "p25", "p50", "p75", "p90"])
        self.assertEqual(self.ru.set_protocol(self.es), "unified-joint-eciself-v2")
        self.assertEqual(self.ru.set_slug(self.es), "eciself")
        # Since 2026-10-01 the history is the newest FETCHED Epoch snapshot
        # (2026-09-10 to then a METR scrape, before that a vendored CSV), and
        # the trend is computed at analysis time rather than baked in.
        live = self.live_frontier()
        self.assertEqual(self.es["history"][0]["model"], live[0]["model"])
        self.assertEqual(self.es["history"][-1]["model"], live[-1]["model"])
        self.assertIsNone(self.es.get("trend"))

    def test_leap_has_no_elicit_and_is_still_pinned(self):
        import hashlib
        self.assertIsNone(self.ru.set_elicit(self.leap))
        self.assertEqual(self.ru.submit_extra(self.leap), "")
        t = self.ru.submit_tool_joint(["q"], ["2030"], ["sq"])
        self.assertNotIn("eci_forecast", t["parameters"]["properties"])
        block = self.ru.conditions_block(self.leap["conditions"], self.leap)
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), TestConditionSets.LEAP_BLOCK_SHA)

    def test_prompt_has_the_history_two_steps_and_no_trend(self):
        groups, by_group, horizons, _, spec = self.batch
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                                 self.es["conditions"], self.es, date(2026, 8, 28))
        self.assertEqual((n, cells), (QUESTIONS, CELLS))
        cond = p[p.index("===== CONDITIONS ====="):]
        self.assertIn("Step 1 -- Forecast the frontier ECI on December 31, 2030", cond)
        self.assertIn("Step 2 --", cond)
        self.assertLess(cond.index("Step 1"), cond.index("Step 2"))
        live = self.live_frontier()
        self.assertIn(self.history_line(live[0]), cond)
        self.assertIn(self.history_line(next(e for e in live if "Fable 5" in e["model"])), cond)
        self.assertNotIn("LLaMA", cond)
        self.assertIn("with your eci_forecast (5 numbers) and a 3-6 sentence rationale", p)
        for c in self.es["conditions"]:
            self.assertIn(f"--- {c['id']} ---", p)
            self.assertIn(c["assume"], p)
        self.assertNotIn("\n\n\n\n", cond)      # bare conditions, no blank-line residue
        # The trend projection is what the answers are compared to; never shown.
        for w in ("231", "210.4", "262", "metr", "trend", "percentile of the projection",
                  "Status Quo", "liability"):
            self.assertNotIn(w, cond, w)
        lit = (self.es["conditioning"]["instruction"] + self.es["conditioning"]["definitions"]
               + self.es["elicit"]["text"] + "".join(c["assume"] for c in self.es["conditions"])).lower()
        found = [b for b in BANNED_RELATION + BANNED_DIRECTION if b in lit]
        self.assertEqual(found, [], f"self-set text: {found}")

    def test_tool_requires_the_forecast_and_cleaner_enforces_order(self):
        el = self.ru.set_elicit(self.es)
        t = self.ru.submit_tool_joint(["q"], ["2030"], ["eci_p25", "eci_p50", "eci_p75"], el)
        self.assertEqual(t["parameters"]["required"][0], "eci_forecast")
        self.assertEqual(t["parameters"]["properties"]["eci_forecast"]["required"],
                         ["p10", "p25", "p50", "p75", "p90"])
        five = {"p10": 190, "p25": 200, "p50": 220, "p75": "250", "p90": 270}
        self.assertEqual(self.ru.clean_elicit(five, el),
                         {"p10": 190.0, "p25": 200.0, "p50": 220.0, "p75": 250.0, "p90": 270.0})
        self.assertIsNone(self.ru.clean_elicit({**five, "p25": 230}, el))
        self.assertIsNone(self.ru.clean_elicit({"p25": 200, "p50": 220, "p75": 250}, el))
        self.assertIsNone(self.ru.clean_elicit("nope", el))
        self.assertIsNone(self.ru.clean_elicit({**five, "p90": 1001}, el))   # over the set's maximum
        self.assertEqual(self.ru.clean_elicit({k: 1 for k in five}, el), {k: 1.0 for k in five})


class TestRollingSelfElicitedSet(unittest.TestCase):
    """data/eci_self6mo_conditions.json: the target is run date + 6 months,
    filled in by run_unified.resolve_set when the prompt is built."""

    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.leap = cls.ru.load_policies()
        cls.es = cls.ru.load_policies(REPO / "data" / "eci_self6mo_conditions.json")
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)

    def test_set_is_current_and_carries_the_placeholder(self):
        r = subprocess.run([sys.executable, str(REPO / "code" / "make_eci_self_conditions.py"),
                            "--months", "6", "--out", str(REPO / "data" / "eci_self6mo_conditions.json"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.es["elicit"]["target_months"], 6)
        self.assertIsNone(self.es["elicit"]["target_date"])
        self.assertIsNone(self.es["trend"])
        self.assertEqual(self.ru.set_protocol(self.es), "unified-joint-eciself6mo-v2")
        self.assertEqual(self.ru.set_slug(self.es), "eciself6mo")
        for text in (self.es["elicit"]["text"], self.es["conditioning"]["instruction"],
                     self.es["conditioning"]["unconditional_forecast"], self.es["conditioning"]["horizon"],
                     *(c["assume"] for c in self.es["conditions"])):
            self.assertIn("{target_date}", text)
        self.assertNotIn("2030", self.es["elicit"]["text"])

    def test_add_months_matches_the_rolling_horizons(self):
        from redlines.questions import resolves_on
        spec = {"rolling": [{"id": "6mo", "months": 6, "label": "within 6 months"}]}
        for d in (date(2026, 8, 28), date(2026, 8, 31), date(2026, 12, 31), date(2027, 2, 28), date(2028, 8, 29)):
            self.assertEqual(self.ru.add_months(d, 6).isoformat(), resolves_on("6mo", d, spec))
        self.assertEqual(self.ru.add_months(date(2026, 8, 31), 6), date(2027, 2, 28))

    def test_resolve_set_fills_the_date_and_leaves_other_sets_alone(self):
        r = self.ru.resolve_set(self.es, date(2026, 8, 28))
        self.assertEqual(r["elicit"]["target_date"], "2027-02-28")
        self.assertIn("February 28, 2027", r["elicit"]["text"])
        self.assertIn("February 28, 2027", r["conditioning"]["instruction"])
        self.assertIn("February 28, 2027", r["conditions"][0]["assume"])
        shown = [r["elicit"]["text"], *(v for v in r["conditioning"].values() if isinstance(v, str)),
                 *(c["assume"] + c["label"] for c in r["conditions"])]
        self.assertFalse(any("{target_date}" in t for t in shown))       # (notes may name it)
        self.assertIn("{target_date}", self.es["elicit"]["text"])       # the source set is untouched
        self.assertIs(self.ru.resolve_set(self.leap, date(2026, 8, 28)), self.leap)
        fixed = self.ru.load_policies(REPO / "data" / "eci_self_conditions.json")
        self.assertIs(self.ru.resolve_set(fixed, date(2026, 8, 28)), fixed)

    def test_prompt_carries_the_resolved_date_and_leap_is_still_pinned(self):
        import hashlib
        groups, by_group, horizons, _, spec = self.batch
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                                 self.es["conditions"], self.es, date(2026, 8, 28))
        self.assertEqual((n, cells), (QUESTIONS, CELLS))
        cond = p[p.index("===== CONDITIONS ====="):]
        self.assertIn("Step 1 -- Forecast the frontier ECI on February 28, 2027", cond)
        self.assertIn("within 6 months (by 2027-02-28)", p)    # the 6mo horizon lands on the same day
        self.assertNotIn("{target_date}", p)
        self.assertNotIn("2030", cond[:cond.index("\nHorizons:")])    # the horizons line names 2030 itself
        # A different run date, a different target.
        p2, _, _ = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                              self.es["conditions"], self.es, date(2026, 10, 31))
        self.assertIn("Forecast the frontier ECI on April 30, 2027", p2)
        block = self.ru.conditions_block(self.leap["conditions"], self.leap)
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), TestConditionSets.LEAP_BLOCK_SHA)
        pl, _, _ = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                              self.leap["conditions"], self.leap, date(2026, 8, 28))
        self.assertEqual(hashlib.sha256(pl.encode()).hexdigest(), TestConditionSets.LEAP_PROMPT_SHA_CURRENT)


class TestCombinedSet(unittest.TestCase):
    """data/combined_conditions.json: the LEAP policies and the six-month
    capability conditions in ONE instrument -- side by side, never crossed.
    Policy conditions sit on the model's own median capability trajectory;
    capability conditions assume whatever policy it expects unconditionally.
    (Nick, 2026-08-28.)"""

    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.leap = cls.ru.load_policies()
        cls.es = cls.ru.load_policies(REPO / "data" / "eci_self6mo_conditions.json")
        cls.cb = cls.ru.load_policies(REPO / "data" / "combined_conditions.json")
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)

    def test_set_is_current_and_composed_of_the_two_components(self):
        import hashlib
        r = subprocess.run([sys.executable, str(REPO / "code" / "make_combined_conditions.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cb = self.cb
        self.assertEqual([c["id"] for c in cb["conditions"]],
                         [c["id"] for c in self.leap["conditions"]] + [c["id"] for c in self.es["conditions"]])
        self.assertEqual([g["key"] for g in cb["groups"]], ["policy", "capability"])
        self.assertEqual([c["group"] for c in cb["conditions"]], ["policy"] * 8 + ["capability"] * 5)
        self.assertEqual(self.ru.set_protocol(cb), "unified-joint-combined-v8")   # October 1: the pair unnamed; September 15: the extinction pair (v5 = September 10 counting version)
        self.assertEqual(self.ru.set_slug(cb), "combined")
        self.assertNotIn(self.ru.set_protocol(cb), (self.ru.PROTOCOL_JOINT, self.ru.set_protocol(self.es)))
        self.assertEqual(cb["elicit"], self.es["elicit"])
        # Each component is pinned by content, so --check fails when either moves.
        for comp in cb["source"]["components"]:
            self.assertEqual(comp["sha256"], hashlib.sha256(open(REPO / comp["file"], "rb").read()).hexdigest())
        # The component text is carried verbatim; only the four authored sentences are ours.
        pol, cap = cb["groups"]
        self.assertEqual(pol["instruction"], self.leap["conditioning"]["instruction"])
        self.assertEqual(pol["horizon"], self.leap["conditioning"]["horizon"])
        self.assertEqual(pol["definitions"], self.ru._definitions(self.leap))
        self.assertEqual(cap["instruction"], self.es["conditioning"]["instruction"])
        self.assertEqual(cap["horizon"], self.es["conditioning"]["horizon"])
        self.assertEqual(cb["conditioning"]["definitions"], self.es["conditioning"]["definitions"])
        for c, src in zip(cb["conditions"], self.leap["conditions"] + self.es["conditions"]):
            self.assertEqual({k: v for k, v in c.items() if k != "group"}, src)
        # The two assumptions say what each group holds the other at, and nothing else.
        self.assertIn("50th-percentile value from eci_forecast", pol["assumption"])
        self.assertIn("eci_p50", pol["assumption"])
        self.assertIn("No policy condition applies", cap["assumption"])
        self.assertIn("unconditional forecast", cap["assumption"])
        ours = (cb["conditioning"]["instruction"] + cb["conditioning"]["unconditional_forecast"]
                + pol["assumption"] + cap["assumption"]).lower()
        found = [b for b in BANNED_RELATION + BANNED_DIRECTION if b in ours]
        self.assertEqual(found, [], f"authored text: {found}")

    def test_prompt_carries_both_sections_and_the_leap_items_byte_for_byte(self):
        groups, by_group, horizons, _, spec = self.batch
        conds = self.cb["conditions"]
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, horizons, spec, conds, self.cb, date(2026, 8, 28))
        # The same questions and cells as the unconditional prompt, whatever
        # the set's grid is this week.
        base, n0, cells0 = self.ru.build_prompt(groups, by_group, horizons, spec, date(2026, 8, 28))
        self.assertEqual((n, cells), (n0, cells0))
        k = len(conds) + 1
        self.assertEqual(k, 14)
        self.assertIn(f"under each of the {k} conditions", p)
        self.assertIn(f"({cells * k} probabilities, keyed by condition id)", p)
        self.assertIn("its 2 groups (policy conditions and capability conditions)", p)
        self.assertIn("no\ncondition from one group is combined with a condition from another", p)
        # The question blocks are the policy instrument's, unchanged.
        qblock = base[base.index("===== AI-RELATED INCIDENT"):base.index("\nHorizons: ")]
        self.assertIn(qblock, p)
        cond = p[p.index("===== CONDITIONS ====="):]
        # Step 1 and the ECI definitions before anything else; then the key
        # list; then the unconditional; then the two sections in order.
        order = ["===== CONDITIONS =====", "Frontier ECI history", "Step 1 -- Forecast the frontier ECI on February 28, 2027",
                 "Step 2 -- each question x horizon cell takes 14 probabilities",
                 "unconditional, then the 8 policy conditions (POLICY CONDITIONS), then the 5 capability conditions (CAPABILITY CONDITIONS)",
                 "--- unconditional ---", "===== POLICY CONDITIONS =====", "--- sq ---", "--- p5 ---",
                 "===== CAPABILITY CONDITIONS =====", "--- eci_p10 ---", "--- eci_p25 ---", "--- eci_p75 ---", "--- eci_p90 ---"]
        idx = [cond.index(s) for s in order]
        self.assertEqual(idx, sorted(idx), order)
        # LEAP's items render byte-for-byte as in the policy instrument.
        leap_block = self.ru.conditions_block(self.leap["conditions"], self.leap)
        for c in self.leap["conditions"]:
            item = self.ru._condition_items([c])
            self.assertIn(item, leap_block)
            self.assertIn(item, cond)
        self.assertIn(self.leap["conditioning"]["instruction"], cond)
        self.assertIn(self.ru._definitions(self.leap), cond)
        self.assertIn(self.es["conditioning"]["instruction"].replace("{target_date}", "February 28, 2027"), cond)
        for c in self.es["conditions"]:
            self.assertIn(c["assume"].replace("{target_date}", "February 28, 2027"), cond)
        # The authored lines, dated.
        self.assertIn("frontier ECI on February 28, 2027 is approximately your 50th-percentile value", cond)
        self.assertIn("No policy condition applies here.", cond)
        self.assertIn("whatever level of AI capability you expect to be reached by February 28, 2027", cond)
        self.assertNotIn("{target_date}", p)
        # The policy section precedes the capability one and each carries its own horizon line.
        pol = cond[cond.index("===== POLICY CONDITIONS"):cond.index("===== CAPABILITY CONDITIONS")]
        cap = cond[cond.index("===== CAPABILITY CONDITIONS"):]
        self.assertIn("Horizon: every condition is implemented immediately", pol)
        self.assertIn("Horizon: every condition is a level of the frontier ECI on February 28, 2027", cap)
        self.assertNotIn("eci_p", pol.split("In every policy condition")[0])   # no capability id before the assumption
        # A different run date, a different target, in the assumptions too.
        p2, _, _ = self.ru.build_prompt_joint(groups, by_group, horizons, spec, conds, self.cb, date(2026, 10, 31))
        self.assertIn("frontier ECI on April 30, 2027 is approximately your 50th-percentile", p2)
        r = self.ru.resolve_set(self.cb, date(2026, 10, 31))
        self.assertIn("April 30, 2027", r["groups"][0]["assumption"])
        self.assertIn("{target_date}", self.cb["groups"][0]["assumption"])      # the source set is untouched

    def test_tool_and_cleaner_take_fourteen_keys_and_the_forecast(self):
        ids = [c["id"] for c in self.cb["conditions"]]
        t = self.ru.submit_tool_joint(["q"], ["2030"], ids, self.ru.set_elicit(self.cb))
        ps = t["parameters"]["properties"]["forecasts"]["items"]["properties"]["probabilities"]
        self.assertEqual(ps["required"], ["unconditional"] + ids)
        self.assertEqual(len(ps["properties"]), 14)
        self.assertEqual(t["parameters"]["required"][0], "eci_forecast")
        raw = [{"question_id": "q", "horizon": "2030",
                "probabilities": {"unconditional": 0.1, "p5": 0.05, "eci_p75": 0.2}}]
        g = self.ru.clean_forecasts_joint(raw, {"q": {"2030"}}, ["2030"], ids)
        self.assertEqual(set(g), {"unconditional", "p5", "eci_p75"})

    def test_leap_alone_is_still_pinned(self):
        # The shared item renderer was factored out for the grouped block; the
        # policy instrument's bytes must not have moved by a single character.
        import hashlib
        groups, by_group, horizons, _, spec = self.batch
        block = self.ru.conditions_block(self.leap["conditions"], self.leap)
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), TestConditionSets.LEAP_BLOCK_SHA)
        pl, _, _ = self.ru.build_prompt_joint(groups, by_group, horizons, spec,
                                              self.leap["conditions"], self.leap, date(2026, 8, 28))
        self.assertEqual(hashlib.sha256(pl.encode()).hexdigest(), TestConditionSets.LEAP_PROMPT_SHA_CURRENT)
        self.assertEqual(self.ru.set_groups(self.leap), [])
        self.assertEqual(self.ru.set_groups(self.es), [])


class TestGroupedSetOnTheTabs(unittest.TestCase):
    """A grouped set is read one group at a time (redlines.conditional.group_view
    / group_rows), and each tab takes the instrument with the newest
    elicitation day -- since the 2026-08-28 pilot, the combined one."""

    @classmethod
    def setUpClass(cls):
        cls.cb = json.load(open(REPO / "data" / "combined_conditions.json"))
        cls.leap = json.load(open(REPO / "data" / "leap_policies.json"))
        cls.es = json.load(open(REPO / "data" / "eci_self6mo_conditions.json"))

    def test_group_view_is_the_component_set_plus_the_assumption(self):
        from redlines.conditional import group_rows, group_view
        pol = group_view(self.cb, "policy")
        self.assertEqual([c["id"] for c in pol["conditions"]], [c["id"] for c in self.leap["conditions"]])
        self.assertEqual(pol["kind"], "policy")
        self.assertEqual(pol["conditioning"]["instruction"], self.leap["conditioning"]["instruction"])
        self.assertEqual(pol["conditioning"]["horizon"], self.leap["conditioning"]["horizon"])
        self.assertEqual(pol["source"]["panel"], "LEAP")
        self.assertIn("eci_p50", pol["conditioning"]["assumption"])
        self.assertEqual(pol["slug"], "combined")                       # the log is still the combined one
        self.assertEqual(pol["protocol"], "unified-joint-combined-v8")
        cap = group_view(self.cb, "capability")
        self.assertEqual([c["field"] for c in cap["conditions"]], ["p10", "p25", "p50", "p75", "p90"])
        self.assertEqual(cap["conditioning"]["instruction"], self.es["conditioning"]["instruction"])
        self.assertEqual(cap["conditioning"]["definitions"], self.es["conditioning"]["definitions"])
        self.assertEqual(cap["elicit"], self.es["elicit"])
        self.assertEqual(cap["history"], self.es["history"])
        self.assertIn("No policy condition applies", cap["conditioning"]["assumption"])
        self.assertIs(group_view(self.leap, "policy"), self.leap)       # a plain set is untouched
        rows = [{"condition": None, "x": 1}, {"condition": {"id": "p5", "group": "policy"}},
                {"condition": {"id": "eci_p50", "group": "capability"}}]
        self.assertEqual([r.get("condition", {}) and r["condition"]["id"] for r in group_rows(rows, "policy")], [None, "p5"])
        self.assertEqual(len(group_rows(rows, "capability")), 2)

    def test_the_tabs_take_the_newest_instrument(self):
        # Both tabs read the newest run in the combined log -- whichever
        # panel and protocol that run carried -- so the pins come from the
        # log, not from a hand-typed panel of the day.
        import json
        from redlines.registry import model_colors
        from redlines.views import capability, conditional
        from redlines.instrument import instrument_rows
        rows = instrument_rows([json.loads(l) for l in open(conditional.SOURCES[0][0])])
        if not rows:
            # A definition change creates an intentionally empty current
            # series until replacement forecasts land; no legacy fallback.
            b = conditional.build()
            v = capability.build()["variants"][0]
            for view in (b, v):
                self.assertEqual(view["questions"], [])
                self.assertEqual(view["models"], [])
                self.assertFalse(view["instrumentInfo"]["available"])
                self.assertEqual(view["protocol"], "unified-joint-combined-v8")
            return
        # Separate provider retries may have distinct run IDs but share the
        # single explicitly recorded elicitation date and incident windows.
        newest = max(r["run_date"] for r in rows)
        newest_rows = [r for r in rows if r["run_date"] == newest]
        protocol = {r["protocol"] for r in newest_rows}
        self.assertEqual(len(protocol), 1)
        protocol = protocol.pop()
        present = {r["label"] for r in newest_rows}
        cap_ids = sorted({r["condition"]["id"] for r in newest_rows
                          if r.get("condition") and r["condition"].get("group") == "capability"})
        target = sorted({(r.get("elicited") or {}).get("target_date") for r in newest_rows} - {None})[-1]

        b = conditional.build()
        self.assertEqual(b["instrument"]["group"], "policy")
        self.assertEqual(b["protocol"], protocol)
        self.assertEqual([c["id"] for c in b["conditions"]], [c["id"] for c in self.leap["conditions"]])
        self.assertEqual(b["source"]["panel"], "LEAP")
        self.assertTrue(b["conditioning"].get("assumption"))
        # The newest run's models, in model_colors() order -- the panel of
        # the day first, in its colors, the rest in the retired gray.
        self.assertEqual([(m["label"], m["color"]) for m in b["models"]],
                         [(l, c) for l, c in model_colors() if l in present])
        # The LEAP log alone, when asked for by name.
        b2 = conditional.build(log_path=str(conditional.CONDITIONAL_LOG))
        self.assertIn(b2["protocol"], conditional.PROTOCOLS)
        self.assertIsNone(b2["instrument"]["group"])
        self.assertNotIn("assumption", b2["conditioning"])
        v = capability.build()["variants"][0]
        self.assertEqual(v["instrument"]["group"], "capability")
        self.assertEqual(v["protocol"], protocol)
        self.assertEqual([c["id"] for c in v["conditions"]], cap_ids)
        self.assertEqual(v["targetDate"], target)
        self.assertTrue(v["conditioning"].get("assumption"))


class TestAxesSets(unittest.TestCase):
    """data/axes_conditions.json and data/paper_axes_conditions.json
    (code/make_axis_conditions.py): risk conditional on FIXED levels of an
    x-axis quantity -- LEAP's revenue and Expert-AGI questions plus the
    frontier ECI for the dashboard; LEAP's GDP, labor-force and METR
    questions for the paper -- at 2030/2050/2100 only, each axis also
    forecast by the model in LEAP's own percentiles."""

    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.dash = cls.ru.load_policies(REPO / "data" / "axes_conditions.json")
        cls.paper = cls.ru.load_policies(REPO / "data" / "paper_axes_conditions.json")
        cls.leap = json.load(open(LEAP_REFERENCE))
        cls.batch = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)

    def _levels(self, spec, group):
        return [c["value"] for c in spec["conditions"] if c["group"] == group]

    def test_extract_is_current(self):
        """data/leap_reference.json is what code/make_leap_reference.py produces
        from the internal pull (checked only where that pull is present)."""
        if not HAVE_LEAP_RAW:
            self.skipTest("internal LEAP pull not present; the tracked extract stands")
        r = subprocess.run([sys.executable, str(REPO / "code" / "make_leap_reference.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_sets_are_current_and_their_own_instruments(self):
        # The tracked sets are the ones the rows were elicited with (the
        # launch validator, code/validate_launch_run.py, replays their prompts
        # against the rows). The generator may be one protocol bump AHEAD of
        # them between a text change and the first run under it; it may never
        # disagree under the SAME tag.
        if HAVE_LEAP_RAW:
            import tempfile
            from redlines.conditional import protocol_line
            with tempfile.TemporaryDirectory() as d:
                r = subprocess.run([sys.executable, str(REPO / "code" / "make_axis_conditions.py"),
                                    "--out-dir", d], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                for fname, tracked in (("axes_conditions.json", self.dash),
                                       ("paper_axes_conditions.json", self.paper)):
                    fresh = json.loads((Path(d) / fname).read_text())
                    if fresh["protocol"] == tracked["protocol"]:
                        self.assertEqual(fresh, tracked, f"{fname}: generator output differs under the same tag")
                    else:
                        self.assertEqual(protocol_line(fresh["protocol"])[1], tracked["protocol"],
                                         f"{fname}: the generator's tag must be the tracked tag's successor")
        for spec, slug, n in ((self.dash, "axes", 16), (self.paper, "paperaxes", 15)):
            self.assertEqual(self.ru.set_slug(spec), slug)
            self.assertEqual(self.ru.set_protocol(spec), f"unified-joint-{slug}-v3")
            self.assertEqual(spec["horizons"], ["2030", "2050", "2100"])
            self.assertEqual(len(spec["conditions"]), n)
            self.assertEqual([g["key"] for g in spec["groups"]], [e["group"] for e in spec["elicits"]])
            for c in spec["conditions"]:
                self.assertIsNotNone(c["value"])
                self.assertNotIn("field", c)
        # The LEAP file the levels came from is pinned by content (checked
        # where the internal pull is present).
        if HAVE_LEAP_RAW:
            import hashlib
            sha = hashlib.sha256(open(LEAP_RAW, "rb").read()).hexdigest()
            self.assertEqual(self.dash["source"]["leap"]["sha256"], sha)

    def test_levels_are_the_superforecasters_percentiles_and_the_trends_pace(self):
        sf = lambda axis, at, p: self.leap["axes"][axis]["answers"][at][p]["superforecaster"]["median"]
        self.assertEqual(self._levels(self.dash, "revenue"), [75, 150, 300, 500, 830])
        self.assertEqual([sf("revenue", "2030-12-31", p) for p in ("p10", "p50")], [150.0, 300.0])
        self.assertAlmostEqual(sf("revenue", "2030-12-31", "p90"), 498.9)
        self.assertEqual(self._levels(self.dash, "agi"), [2030, 2036, 2045, 2060, 2090])
        self.assertEqual([round(sf("agi_year", "none", p)) for p in ("p5", "p25", "p50", "p75", "p95")],
                         [2030, 2036, 2045, 2060, 2090])
        self.assertEqual(self._levels(self.dash, "eci"), [162, 168, 173, 179, 185, 196])
        ref = self.dash["reference"]["eci"]
        self.assertEqual(ref["pace_multiples"], [0, 0.5, 1, 1.5, 2, 3])
        self.assertEqual(ref["reference_target_date"], "2027-03-04")
        self.assertAlmostEqual(ref["trend_at_reference_target"]["p50"], 173.4)
        self.assertEqual(self._levels(self.paper, "gdp"), [-0.5, 1.0, 2.5, 4.3, 6.1])
        self.assertEqual(self._levels(self.paper, "lfpr"), [54.0, 58.0, 62.0, 65.1, 68.2])
        self.assertEqual(self._levels(self.paper, "metr"), [1.3, 2.1, 3.5, 5.5, 8.6])
        # The reference is for the chart, never the prompt.
        for spec in (self.dash, self.paper):
            for c in spec["conditions"]:
                self.assertNotIn("superforecaster", c["label"] + c["assume"])
                self.assertIn("from", c["chart"])

    def test_resolve_set_dates_the_eci_axis_only(self):
        r = self.ru.resolve_set(self.dash, date(2026, 9, 4))
        by = {e["key"]: e for e in self.ru.set_elicits(r)}
        self.assertEqual(by["eci_forecast"]["target_date"], "2027-03-04")
        self.assertEqual(by["revenue_forecast"]["target_date"], "2030-12-31")
        self.assertIsNone(by["agi_forecast"]["target_date"])
        self.assertIn("March 4, 2027", by["eci_forecast"]["text"])
        self.assertIs(self.ru.resolve_set(self.paper, date(2026, 9, 4)), self.paper)

    def test_prompt_renders_each_section_with_its_definitions_forecast_and_levels(self):
        groups, by_group, horizons, _, spec = self.batch
        hz = self.ru.set_horizons(self.dash, horizons)
        self.assertEqual(hz, ["2030", "2050", "2100"])
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, hz, spec, self.dash["conditions"],
                                                 self.dash, date(2026, 9, 4))
        self.assertEqual((n, cells), (QUESTIONS, 3 * QUESTIONS))
        self.assertIn("Horizons: 2030 (by 2030), 2050 (by 2050), 2100 (by 2100).", p)
        self.assertNotIn("6mo", p)
        cond = p[p.index("===== CONDITIONS ====="):]
        for h in ("REVENUE CONDITIONS", "AGI-TIMING CONDITIONS", "CAPABILITY CONDITIONS"):
            self.assertIn(f"===== {h} =====", cond)
        self.assertLess(cond.index("REVENUE CONDITIONS"), cond.index("AGI-TIMING CONDITIONS"))
        # Each section: LEAP's words, then the model's own forecast, then the levels.
        self.assertIn("in billions of 2026 USD) at the end of the following calendar years?", cond)
        self.assertIn("Your forecast -- Forecast the combined annualized revenue run-rate", cond)
        self.assertIn("What is the probability that, before 2100, more than 50% of LEAP panelists", cond)
        self.assertIn("no more than 5x as costly as equivalent human labor", cond)
        # The capability section renders the tracked set's own ECI definitions
        # and frontier history (as elicited), whichever snapshot they came from.
        eci_group = next(g for g in self.dash["groups"] if g["key"] == "eci")
        self.assertIn(eci_group["definitions"], cond)
        self.assertRegex(cond, r"2026-06-09 +16\d\.\d  Claude Fable 5 \(")
        self.assertIn("Frontier ECI on March 4, 2027 ≈ 173.", cond)
        self.assertIn("Assume that on March 4, 2027 the frontier ECI is approximately 196", cond)
        resolved = self.ru.resolve_set(self.dash, date(2026, 9, 4))
        for c in resolved["conditions"]:
            self.assertIn(f"--- {c['id']} ---", cond)
            self.assertIn(c["assume"], cond)
        self.assertIn("with your revenue_forecast (3 numbers), agi_forecast (6 numbers) and "
                      "eci_forecast (5 numbers) and a 3-6 sentence rationale", p)
        self.assertIn("Deliver the probabilities with submit_cells", p)
        self.assertIn("only pages you read", p)
        # No export residue, nothing about where a level came from.
        for w in ("**", "_would not _", "superforecaster", "one step", "pace", "metr_graph", "LEAP median"):
            self.assertNotIn(w, cond, w)
        lit = " ".join([self.dash["conditioning"]["instruction"], self.dash["conditioning"]["unconditional_forecast"]]
                       + [g["instruction"] + g["assumption"] + g["horizon"] for g in self.dash["groups"]]
                       + [e["text"] for e in self.dash["elicits"]]
                       + [c["assume"] + c["label"] for c in self.dash["conditions"]]).lower()
        found = [b for b in BANNED_RELATION + BANNED_DIRECTION if b in lit]
        self.assertEqual(found, [], f"axes text: {found}")

    def test_paper_prompt_has_the_three_leap_sections(self):
        groups, by_group, horizons, _, spec = self.batch
        hz = self.ru.set_horizons(self.paper, horizons)
        p, n, cells = self.ru.build_prompt_joint(groups, by_group, hz, spec, self.paper["conditions"],
                                                 self.paper, date(2026, 9, 4))
        self.assertEqual((n, cells), (QUESTIONS, 3 * QUESTIONS))
        cond = p[p.index("===== CONDITIONS ====="):]
        for h in ("GROWTH CONDITIONS", "LABOR-FORCE CONDITIONS", "TASK-HORIZON CONDITIONS"):
            self.assertIn(f"===== {h} =====", cond)
        self.assertIn("(real GDP in 2030 / real GDP in 2025)", cond)
        self.assertIn("BLS series LNS11300000", cond)
        self.assertIn("longest 80% time horizon", cond)
        self.assertIn("approximately -0.5% (within about 0.2 percentage points of it)", cond)
        self.assertIn("approximately 8.6 hours", cond)
        self.assertIn("with your gdp_forecast (3 numbers), lfpr_forecast (3 numbers) and "
                      "metr_forecast (3 numbers) and a 3-6 sentence rationale", p)

    def test_tool_and_cleaner_take_every_forecast_and_seventeen_keys(self):
        els = self.ru.set_elicits(self.dash)
        ids = [c["id"] for c in self.dash["conditions"]]
        t = self.ru.submit_tool_joint(["q"], ["2030"], ids, els)
        self.assertEqual(t["parameters"]["required"][:3], ["revenue_forecast", "agi_forecast", "eci_forecast"])
        probs = t["parameters"]["properties"]["forecasts"]["items"]["properties"]["probabilities"]
        self.assertEqual(probs["required"], ["unconditional"] + ids)
        self.assertEqual(len(probs["required"]), 17)
        agi = t["parameters"]["properties"]["agi_forecast"]
        self.assertEqual(agi["required"], ["p_before_2100", "p5", "p25", "p50", "p75", "p95"])
        self.assertEqual(agi["properties"]["p_before_2100"], {"type": "number", "minimum": 0, "maximum": 1})
        self.assertEqual(agi["properties"]["p5"], {"type": "number", "minimum": 2026, "maximum": 2100})
        self.assertIn("p5, p25, p50, p75, p95 in non-decreasing order", agi["description"])
        el = next(e for e in els if e["key"] == "agi_forecast")
        good = {"p_before_2100": 0.8, "p5": 2030, "p25": 2036, "p50": 2045, "p75": 2060, "p95": 2090}
        self.assertEqual(self.ru.clean_elicit(good, el), {k: float(v) for k, v in good.items()})
        self.assertIsNone(self.ru.clean_elicit({**good, "p_before_2100": 1.5}, el))   # a probability
        self.assertIsNone(self.ru.clean_elicit({**good, "p25": 2029}, el))            # years in order
        self.assertIsNone(self.ru.clean_elicit({**good, "p5": 2020}, el))             # before the floor
        self.assertIsNone(self.ru.clean_elicit({k: v for k, v in good.items() if k != "p95"}, el))
        rev = next(e for e in els if e["key"] == "revenue_forecast")
        self.assertEqual(self.ru.clean_elicit({"p10": 100, "p50": 250, "p90": 600}, rev),
                         {"p10": 100.0, "p50": 250.0, "p90": 600.0})
        self.assertIsNone(self.ru.clean_elicit({"p10": 300, "p50": 250, "p90": 600}, rev))

    def test_the_axes_sets_are_not_published_series(self):
        for spec_path in ("axes_conditions.json", "paper_axes_conditions.json"):
            self.assertNotIn(str(REPO / "data" / spec_path),
                             [os.path.abspath(p) for p in self.ru.PUBLISHED_SETS])
        # The combined set is untouched by them: still thirteen conditions and
        # one set-level elicit, its LEAP items byte-identical (TestCombinedSet).
        comb = self.ru.load_policies(REPO / "data" / "combined_conditions.json")
        self.assertEqual(len(comb["conditions"]), 13)
        self.assertEqual(len(self.ru.set_elicits(comb)), 1)
        self.assertNotIn("horizons", comb)
