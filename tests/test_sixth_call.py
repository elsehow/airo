"""A synthetic combined-v10 launch run WITH the sixth call: 4 panel models x
(5 pooled prompts + the unpooled "ai-banned"), through run_one_joint with a
fake loop, then the launch validator and the views over those rows.

What this pins (the owner's decisions of 2026-10-19):
  * the validator accepts 24 calls, and the day with a sixth call missing;
    a missing pooled call still fails it;
  * the Timeline draws six variant lines, the sixth flagged unpooled with
    its guard, and every published number -- each model's point, the
    ensemble median, Graph 1's latest reading, the Policy-levers baseline --
    is the mean of the FIVE prompts, the sixth never in it.
No model or search is called (the loop is a fake)."""
import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from redlines import conditional, runlog  # noqa: E402
from redlines.registry import published_panel, record_snapshot  # noqa: E402
from redlines.views import timeline  # noqa: E402


def _runner():
    spec = importlib.util.spec_from_file_location("run_unified", REPO / "code" / "run_unified.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ru = _runner()
TODAY = date(2026, 10, 19)
RUN_ID = "2026-10-19T1200Z"
# Each model's five prompts differ a little; the sixth sits well apart, so a
# mean that let it in would be visibly wrong.
OFFSET = {"none": 0.0, "independent": 0.001, "recent": 0.002, "critical": 0.003, "two-step": 0.004,
          "ai-banned": 0.05}


def synthetic_rows():
    """Every row of a day's run: 4 panel models x the six variants, through
    run_one_joint with a fake loop. -> rows"""
    pol = ru.load_policies(ru.COMBINED)
    g, b, h, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
    h = ru.set_horizons(pol, h)
    cond_ids = [c["id"] for c in ru.resolve_set(pol, TODAY)["conditions"]]
    labels = [m["label"] for m, _ in published_panel()]
    panel = {"set": "eci_topk", "k": len(labels), "snapshot": record_snapshot()[0].isoformat()}
    base = {label: 0.01 * (i + 1) for i, label in enumerate(labels)}

    def fake_for(label, variant):
        p = base[label] + OFFSET[variant]

        def fake(model, prompt, tools, final_tool, **kw):
            cells = [{"question_id": q["id"], "horizon": hz, "probabilities": {k: p for k in ["unconditional"] + cond_ids}}
                     for gg in g for q in b[gg["key"]] for hz in h if hz in q["horizons"]]
            return {"forecasts": cells, "rationale": "synthetic",
                    "eci_forecast": {"p10": 168, "p25": 170, "p50": 172, "p75": 175, "p90": 178}}, []
        return fake

    rows = []
    for v in ru.set_asked_variants(pol):
        for label in labels:
            with patch.object(ru, "loop_for", lambda harness, f=fake_for(label, v): f):
                rows += ru.run_one_joint(label, "x/" + label, g, b, h, RUN_ID, 0, spec, pol["conditions"], pol,
                                         panel=panel, today=TODAY, harness="pi", variant=v, minimal=True)
    return rows


def write_run(results, rows, drop=()):
    """Write a day's run under `results` (results/runs/<id>.jsonl and
    results/conditional_runs_combined/<id>.jsonl), minus the (label, variant)
    calls in `drop`."""
    rows = [r for r in rows if (r["label"], r["variant"]) not in set(drop)]
    runs, cond = results / "runs", results / "conditional_runs_combined"
    runs.mkdir(parents=True), cond.mkdir(parents=True)
    with open(runs / f"{RUN_ID}.jsonl", "w") as f, open(cond / f"{RUN_ID}.jsonl", "w") as fc:
        for r in rows:
            fc.write(json.dumps(r) + "\n")
            if r["condition"] is None:
                f.write(json.dumps(r) + "\n")
    return rows


def validate(results):
    out = results / "report.json"
    r = subprocess.run([sys.executable, str(REPO / "code" / "validate_launch_run.py"), "--results", str(results),
                        "--date", TODAY.isoformat(), "--out", str(out)], capture_output=True, text=True, cwd=REPO)
    return r.returncode, json.loads(out.read_text()), r.stdout + r.stderr


class TestSixthCallLaunch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.results = Path(cls.tmp.name) / "full"
        cls.rows = synthetic_rows()
        write_run(cls.results, cls.rows)
        cls.labels = [m["label"] for m, _ in published_panel()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_run_is_24_calls_with_the_sixth_stamped(self):
        calls = {r["call_id"] for r in self.rows}
        self.assertEqual(len(calls), 24)
        sixth = [r for r in self.rows if r["variant"] == "ai-banned"]
        five = [r for r in self.rows if r["variant"] != "ai-banned"]
        self.assertEqual(len({r["call_id"] for r in sixth}), 4)
        self.assertTrue(all(r["pooled"] is False and r["url_block_patterns"] for r in sixth))
        self.assertFalse(any("pooled" in r or "url_block_patterns" in r for r in five))
        self.assertEqual({r["protocol"] for r in self.rows}, {"unified-joint-combined-v10"})

    def test_the_validator_passes_the_full_day(self):
        rc, report, log = validate(self.results)
        self.assertEqual(rc, 0, log)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["variant_warnings"], [])
        inst = report["instruments"]["combined"]
        self.assertEqual((inst["expected_calls"], inst["pooled_calls"], inst["unpooled_calls"]), (24, 20, 4))
        self.assertEqual(len(inst["calls"]), 24)
        self.assertEqual(inst["probabilities"], inst["expected_probabilities"])
        self.assertEqual(sum(1 for c in inst["calls"] if not c["pooled"]), 4)

    def test_a_missing_sixth_call_is_a_warning_and_a_missing_pooled_call_an_error(self):
        results = Path(self.tmp.name) / "no-sixth"
        write_run(results, self.rows, drop=[(self.labels[0], "ai-banned")])
        rc, report, log = validate(results)
        self.assertEqual(rc, 0, log)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["variant_warnings"],
                         [{"set": "combined", "variant": "ai-banned", "label": self.labels[0], "problem": "no call"}])
        self.assertEqual(report["instruments"]["combined"]["unpooled_calls"], 3)
        self.assertEqual(report["instruments"]["combined"]["probabilities"],
                         report["instruments"]["combined"]["expected_probabilities"])
        results = Path(self.tmp.name) / "no-fifth"
        write_run(results, self.rows, drop=[(self.labels[0], "two-step")])
        rc, report, _ = validate(results)
        self.assertEqual(rc, 1)
        self.assertEqual([e["check"] for e in report["errors"]][:1], ["complete_unique_grid"])

    def _load(self, **kw):
        return runlog.load_runlog(runlog=self.results / "none.jsonl", runs_dir=self.results / "runs", **kw)

    def test_the_published_number_is_the_mean_of_the_five(self):
        rows = self._load()                                     # the views' default read
        self.assertEqual({r["variant"] for r in rows}, set(ru.set_variants(ru.load_policies(ru.COMBINED))))
        latest = runlog.latest_pooled(runlog.current_rows(runlog.complete_panel_rows(runlog.latest_instrument_rows(rows))))
        for label in self.labels:
            pooled = latest[("catastrophe:ai", label)]
            self.assertEqual(pooled["replicates"], 5)
            want = statistics.mean(0.01 * (self.labels.index(label) + 1) + OFFSET[v] for v in ru.set_variants(ru.load_policies(ru.COMBINED)))
            got = next(f["probability"] for f in pooled["forecasts"] if f["horizon"] == "2030")
            self.assertAlmostEqual(got, want, places=12)
        self.assertEqual({r["variant"] for r in self._load(panel_only=False)} - set(ru.VARIANTS), set())
        self.assertIn("ai-banned", {r["variant"] for r in self._load(panel_only=False)})   # the download keeps it

    def test_the_timeline_draws_six_lines_over_a_five_prompt_mean(self):
        with patch.object(timeline, "load_runlog", self._load):
            blob = timeline.build()
        snap = blob["snapshots"][-1]
        self.assertEqual((snap["date"], snap["draws"], snap["calls"]), (TODAY.isoformat(), 5, 20))
        info = {v["id"]: v for v in blob["variants"]}
        self.assertEqual(set(info), set(ru.VARIANTS))
        self.assertFalse(info["ai-banned"]["pooled"])
        self.assertEqual(info["ai-banned"]["guard"], ru.set_unpooled(ru.load_policies(ru.COMBINED))["ai-banned"]["url_block_patterns"])
        self.assertEqual(info["ai-banned"]["text"], ru.VARIANTS["ai-banned"])
        self.assertTrue(all(v["pooled"] and v["guard"] is None for k, v in info.items() if k != "ai-banned"))
        q = next(q for q in blob["questions"] if q["id"] == "catastrophe:ai")
        i = len(blob["snapshots"]) - 1
        self.assertEqual(set(q["variants"]), set(ru.VARIANTS))                  # six lines
        means = {}
        for s in q["series"]:
            if s["ps"]["2030"][i] is None:
                continue
            want = 100 * statistics.mean(0.01 * (self.labels.index(s["label"]) + 1) + OFFSET[v]
                                         for v in ru.set_variants(ru.load_policies(ru.COMBINED)))
            self.assertAlmostEqual(s["ps"]["2030"][i], want, places=3)
            self.assertEqual(len(s["draws"]["2030"][i]), 5)
            self.assertIsNotNone(s["ci"]["2030"][i])                        # five draws: an interval
            means[s["label"]] = s["ps"]["2030"][i]
        self.assertEqual(set(means), set(self.labels))
        self.assertAlmostEqual(q["median"]["2030"][i], statistics.median(means.values()), places=3)
        self.assertIsNone(q["rerun"]["2030"][i])                             # the draws are prompts, not re-asks
        # The sixth's line is the panel median of ITS calls, 5pp above the baseline's.
        self.assertAlmostEqual(q["variants"]["ai-banned"]["2030"][i] - q["variants"]["none"]["2030"][i], 5.0, places=3)

    def test_the_policy_levers_baseline_is_five_calls(self):
        rows = conditional.load_conditional(self.results / "conditional_runs_combined.jsonl")
        self.assertNotIn("ai-banned", {r["variant"] for r in rows})
        pol = conditional.group_view(ru.load_policies(ru.COMBINED), "policy")
        s = conditional.summarize(conditional.group_rows(rows, "policy"), pol, horizons=("2030",))
        cell = s["questions"]["catastrophe:ai"]["2030"]
        for label in self.labels:
            self.assertEqual(cell["models"][label]["baseline_n"], 5)
        all_rows = conditional.load_conditional(self.results / "conditional_runs_combined.jsonl", pooled_only=False)
        self.assertEqual(len({r["call_id"] for r in all_rows}), 24)


if __name__ == "__main__":
    unittest.main()
