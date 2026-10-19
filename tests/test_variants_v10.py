"""combined-v10: the minimal instrument under five prompt variants.

The set declares both (data/combined_conditions.json "instrument", "variants");
run_unified asks one call per model per variant; the Timeline draws one line
per variant beside the pooled median."""
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

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
        self.assertEqual(set(ru.set_variants(cb)), set(ru.VARIANTS))

    def test_a_set_without_them_is_one_standard_call(self):
        leap = ru.load_policies(ru.POLICIES)
        self.assertEqual(ru.set_variants(leap), ["none"])
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

    def _call(self, variant, answer_cells=True):
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
                                    pol["conditions"], pol, today=today, harness="pi",
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


if __name__ == "__main__":
    unittest.main()
