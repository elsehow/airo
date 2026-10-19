"""redlines.pi_loop: call_tools's contract with pi as the loop. A fake
`run` stands in for agent-box, so this needs neither pi nor the network; the
validator test runs agent-box's own `tool_cli validate` when it is installed."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_conditional import _load_runner  # noqa: E402

from redlines import pi_loop

REPO = Path(__file__).resolve().parent.parent


class FakeRun:
    """Records the harness.run call and plays back a finished pi call."""

    def __init__(self, answer, pieces=(), debrief=None, usage=None):
        self.answer, self.pieces, self.debrief = answer, pieces, debrief
        self.usage = usage or {"turns": 5, "input_tokens": 100, "output_tokens": 20,
                               "cached_tokens": 900, "cost_usd": 0.25}
        self.kw = None

    def __call__(self, **kw):
        self.kw = kw
        work = tempfile.mkdtemp()
        with open(os.path.join(work, "pieces.jsonl"), "w") as f:
            for p in self.pieces:
                f.write(json.dumps({"forecasts": p}) + "\n")
        return {"rc": 0, "seconds": 61.0, "answer": self.answer, "forced": False, "workdir": work,
                "evidence": [{"tool": "web_search", "args": {"query": "q"}, "result": {"results": []}, "error": None}],
                "usage": dict(self.usage), "debrief": self.debrief, "trace": os.path.join(work, "events.jsonl")}


class PiLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.groups, cls.by_group, _, _, _ = cls.ru.load_batch(cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)
        cls.research, cls.coverage = cls.ru.research_tools(cls.groups)
        cls.qids = [q["id"] for g in cls.groups for q in cls.by_group[g["key"]]]

    def call(self, run, model="openai/responses/gpt-6-astra", **kw):
        got = []
        partial = {**self.ru.submit_cells_tool(self.qids, ["2027"], ["unconditional"]),
                   "fn": lambda forecasts=None, **_: got.append(forecasts)}
        usage = {"turns": 1, "cost_usd": 1.0}       # a failed earlier attempt's
        debrief = self.ru.debrief_state(self.groups, self.by_group)
        out = pi_loop.call_tools(model, "P", self.research,
                                 self.ru.submit_tool_joint(self.qids, ["2027"], ["unconditional"]),
                                 system="S", max_iters=40, min_evidence=10, usage=usage,
                                 partial_tool=partial, coverage=self.coverage, debrief=debrief,
                                 allowed_keys=["a|2027"], run=run, **kw)
        return out, got, usage, debrief

    def test_runs_the_instrument_rules_through_pi(self):
        run = FakeRun({"forecasts": [], "rationale": "r"})
        self.call(run)
        kw = run.kw
        self.assertEqual(kw["model"], "openai/gpt-6-astra")          # pi's id, not litellm's route
        self.assertEqual(kw["thinking"], "xhigh")                    # redlines.llm.reasoning_for
        self.assertEqual((kw["min_research"], kw["floor_counts"], kw["max_turns"]), (10, "returned", 40))
        self.assertTrue(kw["withhold_final"])
        self.assertFalse(kw["warn_missing_keys"])
        self.assertEqual(kw["coverage"], self.coverage)
        self.assertEqual(kw["tool_parameters"]["web_search"]["properties"]["cause"]["enum"], self.coverage)
        self.assertIn("submit_cells", kw["tool_parameters"])
        self.assertEqual(kw["allowed_keys"], ["a|2027"])
        self.assertEqual(kw["debrief"]["validator"]["function"], "validate_debrief")
        json.dumps(kw["debrief"])                                     # it goes into spec.json
        self.assertEqual(self.call(FakeRun({"rationale": "r"}), model="anthropic/claude-opus-5-5")[0][0]["rationale"], "r")

    def test_pieces_usage_and_debrief_come_back(self):
        state = {"result": {"x": 1}, "complete": True, "attempts": 2, "problems": [], "error": None}
        run = FakeRun({"forecasts": [{"question_id": "a"}], "rationale": "r"},
                      pieces=[[{"question_id": "p1"}], [{"question_id": "p2"}]], debrief=state)
        (answer, evidence), got, usage, debrief = self.call(run)
        self.assertEqual(got, [[{"question_id": "p1"}], [{"question_id": "p2"}]])   # in order
        self.assertEqual(evidence, [{"tool": "web_search", "args": {"query": "q"}, "result": {"results": []}}])
        self.assertEqual((usage["turns"], usage["cost_usd"]), (6, 1.25))             # added to the earlier attempt's
        self.assertEqual(usage["harness"]["name"], "pi")
        self.assertEqual({k: debrief[k] for k in state}, state)

    def test_no_answer_raises_for_the_retry(self):
        with self.assertRaises(RuntimeError):
            self.call(FakeRun({}))

    def test_validator_runs_out_of_process(self):
        try:
            from fri_forecaster.tool_cli import validate
        except ImportError:
            self.skipTest("agent-box (fri_forecaster) not installed")
        v = self.ru.debrief_state(self.groups, self.by_group)["validator"]
        qs = v["kwargs"]["questions"]
        problems = validate(**json.loads(json.dumps({**v, "value": {}})))["problems"]
        self.assertEqual(len(problems), len(qs))
        self.assertTrue(problems[0].endswith(": missing"))


class HarnessFlagTest(unittest.TestCase):
    def setUp(self):
        self.ru = _load_runner()

    def test_the_set_names_its_loop(self):
        cb = json.load(open(REPO / "data" / "combined_conditions.json"))
        self.assertEqual(self.ru.set_harness(cb), "pi")                        # since combined-v9
        self.assertEqual(self.ru.row_protocol(cb, "pi"), "unified-joint-combined-v10")
        self.assertEqual(self.ru.row_protocol(cb, "litellm"), "unified-joint-combined-v10+litellm")
        legacy = {"protocol": "unified-joint-v6"}                              # a set naming none: litellm
        self.assertEqual(self.ru.row_protocol(legacy, "litellm"), "unified-joint-v6")
        self.assertEqual(self.ru.row_protocol(legacy, "pi"), "unified-joint-v6+pi")

    def test_another_loop_only_as_an_experiment(self):
        r = subprocess.run([sys.executable, str(REPO / "code" / "run_unified.py"), "--joint", "--harness", "litellm"],
                           capture_output=True, text=True, cwd=REPO)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("this set is elicited through pi; another loop runs only as an --experiment", r.stderr)


if __name__ == "__main__":
    unittest.main()
