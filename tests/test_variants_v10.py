"""combined-v10: the minimal instrument under five prompt variants, and the
unpooled sixth.

The set declares both (data/combined_conditions.json "instrument", "variants");
run_unified asks one call per model per variant; the Timeline draws one line
per variant beside the pooled median. Since 2026-10-19 evening the set also
declares one UNPOOLED variant ("unpooled_variants": ai-banned, the baseline
prompt with the AI-forecast ban and a per-call URL guard): asked beside the
five, drawn on the Timeline, never in the published number."""
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _runner():
    spec = importlib.util.spec_from_file_location("run_unified", REPO / "code" / "run_unified.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ru = _runner()


class TestTheSet(unittest.TestCase):
    def test_v10_declares_the_minimal_instrument_and_five_variants(self):
        cb = ru.load_policies(ru.COMBINED)
        self.assertEqual(ru.set_protocol(cb), "unified-joint-combined-v10")
        self.assertEqual(ru.set_instrument(cb), "minimal")
        self.assertEqual(ru.set_variants(cb), ["none", "independent", "recent", "critical", "two-step"])
        self.assertEqual(set(ru.set_asked_variants(cb)), set(ru.VARIANTS))

    def test_the_sixth_is_declared_unpooled_with_its_guard(self):
        cb = ru.load_policies(ru.COMBINED)
        self.assertEqual(list(ru.set_unpooled(cb)), ["ai-banned"])
        guard = ru.set_unpooled(cb)["ai-banned"]["url_block_patterns"]
        # The `both` arm of the anchor-guard experiment (2026-10-16), verbatim.
        self.assertEqual(guard, r"forecastingresearch\.org/pdf/airo,forecastingresearch\.org/research/airo,"
                                r"airo\.forecastingresearch\.org")
        self.assertEqual(ru.VARIANTS["ai-banned"],
                         "Forecasts produced by AI systems, including any automated forecasting dashboard "
                         "or model ensemble, carry no information beyond their inputs. Do not consult them "
                         "or use them as evidence.")
        ru.check_patterns(guard)                                        # compiles
        with self.assertRaises(ru.re.error):
            ru.check_patterns("ok,(unclosed")
        self.assertEqual(ru.set_asked_variants(cb), ru.set_variants(cb) + ["ai-banned"])
        self.assertNotIn("ai-banned", ru.set_variants(cb))              # not a pooled variant
        # The guard blocks AIRO's pages and nothing else, case-insensitively.
        from redlines.tools import blocked_patterns, is_blocked
        with patch.dict("os.environ", {ru.BLOCK_ENV: guard}):
            pats = blocked_patterns()
        for url in ("https://forecastingresearch.org/pdf/airo-working-paper.pdf",
                    "https://forecastingresearch.org/research/airo", "https://AIRO.forecastingresearch.org/"):
            self.assertTrue(is_blocked(url, pats), url)
        for url in ("https://forecastingresearch.org/xpt", "https://www.lesswrong.com/posts/x/airo"):
            self.assertFalse(is_blocked(url, pats), url)

    def test_a_set_without_them_is_one_standard_call(self):
        leap = ru.load_policies(ru.POLICIES)
        self.assertEqual(ru.set_variants(leap), ["none"])
        self.assertEqual(ru.set_unpooled(leap), {})
        self.assertEqual(ru.set_asked_variants(leap), ["none"])
        self.assertEqual(ru.set_instrument(leap), "standard")


class TestMinimalPrompt(unittest.TestCase):
    def _prompt(self):
        today = date(2026, 10, 19)
        pol = ru.resolve_set(ru.load_policies(ru.COMBINED), today)
        g, b, h, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
        h = ru.set_horizons(pol, h)
        return ru.build_prompt_joint(g, b, h, spec, pol["conditions"], pol, today)[0]

    def test_cuts_only_the_guidance(self):
        p = self._prompt()
        m = ru.minimal_joint_prompt(p)
        for gone in ("forecasting questions, grouped by cause", "Research before answering",
                     "3-6 sentence rationale", "After it is accepted"):
            self.assertIn(gone, p)
            self.assertNotIn(gone, m)
        blocks = p[p.index("===== AI-RELATED INCIDENT"):p.index("\nHorizons: ")]
        self.assertIn(blocks, m)                       # questions and conditions byte for byte
        self.assertIn("Deliver the probabilities with submit_cells", m)
        self.assertLess(len(m.encode()), 131072)       # pi takes the prompt as one argv string

    def test_each_variant_adds_only_its_instruction_before_delivery(self):
        base = ru.minimal_joint_prompt(self._prompt())
        for v, text in ru.VARIANTS.items():
            m = ru.minimal_joint_prompt(self._prompt(), v)
            if not text:
                self.assertEqual(m, base)
                continue
            self.assertEqual(m.replace(text + "\n\n", "", 1), base)
            self.assertLess(m.index(text), m.index("Deliver the probabilities"))

    def test_minimal_tools_drop_cause_and_advice(self):
        research, _ = ru.research_tools([{"key": "ai", "label": "AI"}])
        out = ru.minimal_tools(research)
        ws = next(t for t in out if t["name"] == "web_search")
        self.assertEqual(ws["description"], ru.MINIMAL_TOOLS["web_search"])
        self.assertNotIn("cause", ws["parameters"]["properties"])
        self.assertIn("cause", next(t for t in research if t["name"] == "web_search")["parameters"]["properties"])


class TestRunOneJoint(unittest.TestCase):
    """One call per variant through a fake loop: what the loop is given, and the rows."""

    def _call(self, variant, answer_cells=True, harness="pi"):
        today = date(2026, 10, 19)
        pol = ru.load_policies(ru.COMBINED)
        g, b, h, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
        h = ru.set_horizons(pol, h)
        seen = {}
        rp = ru.resolve_set(pol, today)
        cond_ids = [c["id"] for c in rp["conditions"]]

        def fake(model, prompt, tools, final_tool, **kw):
            seen.update(prompt=prompt, tools=tools, **kw)
            cells = [{"question_id": q["id"], "horizon": hz,
                      "probabilities": {k: 0.01 for k in ["unconditional"] + cond_ids}}
                     for gg in g for q in b[gg["key"]] for hz in h if hz in q["horizons"]] if answer_cells else []
            return {"forecasts": cells, "rationale": "r",
                    "eci_forecast": {"p10": 168, "p25": 170, "p50": 172, "p75": 175, "p90": 178}}, []

        orig = ru.loop_for
        ru.loop_for = lambda harness: fake
        try:
            rows = ru.run_one_joint("M", "anthropic/x", g, b, h, "2026-10-19T0000Z", 0, spec,
                                    pol["conditions"], pol, today=today, harness=harness,
                                    variant=variant, minimal=True)
        finally:
            ru.loop_for = orig
        return rows, seen

    def test_rows_and_loop_settings(self):
        rows, seen = self._call("independent")
        self.assertEqual(seen["system"], ru.MINIMAL_SYSTEM)
        self.assertEqual(seen["min_evidence"], 0)
        self.assertIsNone(seen["coverage"])
        self.assertIsNone(seen["debrief"])
        self.assertEqual(seen["max_iters"], ru.MINIMAL_MAX_TURNS)
        self.assertIn(ru.VARIANTS["independent"], seen["prompt"])
        self.assertEqual({r["variant"] for r in rows}, {"independent"})
        self.assertTrue(rows[0]["call_id"].endswith(":independent"))
        self.assertEqual(rows[0]["protocol"], "unified-joint-combined-v10")   # a declared variant: the set's tag
        self.assertEqual(rows[0]["system_prompt"], ru.MINIMAL_SYSTEM)
        self.assertTrue(all(r["forecasts"] for r in rows))
        # A pooled call: no guard reaches the loop, and the rows are as before.
        self.assertNotIn("env", seen)
        self.assertFalse(any("url_block_patterns" in r or "pooled" in r for r in rows))

    def test_the_sixth_runs_guarded_and_its_rows_say_so(self):
        cb = ru.load_policies(ru.COMBINED)
        guard = ru.set_unpooled(cb)["ai-banned"]["url_block_patterns"]
        rows, seen = self._call("ai-banned")
        # The sentence where a variant's text goes; the guard to THIS call only.
        self.assertIn(ru.VARIANTS["ai-banned"], seen["prompt"])
        self.assertLess(seen["prompt"].index(ru.VARIANTS["ai-banned"]), seen["prompt"].index("Deliver the probabilities"))
        self.assertEqual(seen["env"], {ru.BLOCK_ENV: guard})
        self.assertNotIn(ru.BLOCK_ENV, ru.os.environ)
        self.assertEqual(seen["system"], ru.MINIMAL_SYSTEM)
        # The rows: the variant, the guard, unpooled; the protocol stays v10.
        self.assertEqual({r["variant"] for r in rows}, {"ai-banned"})
        self.assertEqual({r["url_block_patterns"] for r in rows}, {guard})
        self.assertEqual({r["pooled"] for r in rows}, {False})
        self.assertEqual({r["protocol"] for r in rows}, {"unified-joint-combined-v10"})
        self.assertTrue(rows[0]["call_id"].endswith(":ai-banned"))
        self.assertTrue(all(r["forecasts"] for r in rows))

    def test_a_guarded_variant_needs_pi(self):
        with self.assertRaisesRegex(RuntimeError, "URL guard"):
            self._call("ai-banned", harness="litellm")

    def test_a_process_environment_guard_is_stamped_as_an_experiment_would_be(self):
        # #5's stamping: a guard in os.environ reaches every call and every row says so.
        with patch.dict("os.environ", {ru.BLOCK_ENV: "example\\.org"}):
            rows, seen = self._call("none")
        self.assertNotIn("env", seen)
        self.assertEqual({r["url_block_patterns"] for r in rows}, {"example\\.org"})
        self.assertFalse(any("pooled" in r for r in rows))

    def test_baseline_call_id_is_unchanged(self):
        rows, _ = self._call("none")
        self.assertFalse(rows[0]["call_id"].endswith(":none"))

    def test_no_forecasts_is_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, "no forecasts"):
            self._call("none", answer_cells=False)


class TestTimelineVariants(unittest.TestCase):
    def test_variant_text_matches_the_runner(self):
        from redlines.views.timeline import VARIANT_TEXT
        self.assertEqual(VARIANT_TEXT, ru.VARIANTS)

    def test_variant_medians(self):
        from redlines.views.timeline import variant_medians
        mk = lambda label, v, p: {"run_date": "2026-10-19", "elicited_at": "2026-10-19T12:00:00+00:00",
                                  "question_id": "catastrophe:ai", "label": label, "variant": v,
                                  "forecasts": [{"horizon": "2030", "probability": p}]}
        rows = [mk("A", "none", 0.01), mk("B", "none", 0.03), mk("A", "independent", 0.02), mk("B", "independent", 0.04)]
        out = variant_medians(rows, ["2026-10-19"])
        self.assertEqual(out[("2026-10-19", "catastrophe:ai")]["none"]["2030"], 2.0)
        self.assertEqual(out[("2026-10-19", "catastrophe:ai")]["independent"]["2030"], 3.0)
        self.assertEqual(variant_medians(rows[:2], ["2026-10-19"]), {})       # one prompt: no lines

    def test_variant_info_reads_the_stamp_off_the_rows(self):
        from redlines.views.timeline import variant_info
        rows = [{"elicited_at": "2026-10-19T12:00:00+00:00", "variant": "none"},
                {"elicited_at": "2026-10-19T12:00:00+00:00", "variant": "ai-banned",
                 "pooled": False, "url_block_patterns": "x\\.org"}]
        self.assertEqual(variant_info(rows), {"none": {"pooled": True, "guard": None},
                                              "ai-banned": {"pooled": False, "guard": "x\\.org"}})


class TestPooledRows(unittest.TestCase):
    """The sixth's rows (`pooled: false`) enter no published number."""

    def test_load_runlog_and_load_conditional_drop_them_unless_asked(self):
        import json
        import tempfile
        from redlines import conditional, runlog
        mk = lambda v, **kw: {"elicited_at": "2026-10-19T12:00:00+00:00", "run_date": "2026-10-19",
                              "question_id": "q", "label": "A", "variant": v, "forecasts": [], **kw}
        rows = [mk("none"), mk("ai-banned", pooled=False, url_block_patterns="x")]
        self.assertEqual([r["variant"] for r in runlog.pooled_rows(rows)], ["none"])
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            runs.mkdir()
            (runs / "2026-10-19T1200Z.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            got = runlog.load_runlog(runlog=Path(d) / "none.jsonl", runs_dir=runs)
            self.assertEqual([r["variant"] for r in got], ["none"])
            got = runlog.load_runlog(runlog=Path(d) / "none.jsonl", runs_dir=runs, panel_only=False)
            self.assertEqual([r["variant"] for r in got], ["none", "ai-banned"])
            log = Path(d) / "cond.jsonl"
            log.write_text("".join(json.dumps(r) + "\n" for r in rows))
            self.assertEqual([r["variant"] for r in conditional.load_conditional(log)], ["none"])
            self.assertEqual([r["variant"] for r in conditional.load_conditional(log, pooled_only=False)],
                             ["none", "ai-banned"])


if __name__ == "__main__":
    unittest.main()
