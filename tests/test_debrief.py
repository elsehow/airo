"""The per-question debrief (code/run_unified.py, 2026-09-16): one entry per
question, keyed by id; the validator's terms; the export's lines."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_conditional import _load_runner  # noqa: E402

from redlines import export

REPO = Path(__file__).resolve().parent.parent


class PerQuestionDebrief(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ru = _load_runner()
        cls.groups, cls.by_group, cls.horizons, _, cls.spec = cls.ru.load_batch(
            cls.ru.LADDER, cls.ru.CROSS, cls.ru.UNBATCHED)
        cls.qs = cls.ru.debrief_questions(cls.groups, cls.by_group)

    def test_one_entry_per_question(self):
        import re
        ids = [q["id"] for q in self.qs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 35)
        self.assertIn("ladder:cyber:1B", ids)
        tool = self.ru.debrief_tool(self.qs)
        keys = [self.ru.debrief_key(i) for i in ids]
        self.assertEqual(sorted(tool["parameters"]["required"]), sorted(keys))
        self.assertEqual(sorted(tool["parameters"]["properties"]), sorted(keys))
        # Anthropic's property-key rule (the 2026-09-16 16:45 UTC failure).
        for k in keys:
            self.assertRegex(k, r"^[a-zA-Z0-9_.-]{1,64}$")
            self.assertEqual(self.ru.debrief_qid(k), ids[keys.index(k)])
        for k in ("rationale", "key_sources", "weakest_link"):
            self.assertIn(k, tool["parameters"]["properties"]["ladder__cyber__1B"]["properties"])
        self.assertTrue(tool["parameters"]["properties"]["ladder__cyber__1B"]["description"].startswith("ladder:cyber:1B: "))
        prompt = self.ru.debrief_prompt(self.qs)
        for k in keys:
            self.assertIn(k, prompt)
        self.assertIn("entries merge", prompt)

    def test_answer_is_stored_by_question_id(self):
        state = {"result": {"ladder__cyber__1B": {"rationale": "r"}, "disempowerment": {"rationale": "d"}},
                 "complete": True, "attempts": 1, "problems": [], "error": None}
        f = self.ru.debrief_fields(state, True)
        self.assertEqual(set(f["debrief"]), {"ladder:cyber:1B", "disempowerment"})
        self.assertEqual(self.ru.debrief_fields(state, False), {"debrief": None, "debrief_status": None})

    def test_validator_names_the_question(self):
        good = {self.ru.debrief_key(q["id"]): {"rationale": "Two sentences on the mechanism and the anchor, with a number. "
                                       "And a second one about the horizons.",
                          "key_sources": [{"url": "https://x.example/a", "contribution": "the base rate"}],
                          "weakest_link": "that the outage persists"} for q in self.qs}
        self.assertEqual(self.ru.validate_debrief(good, self.qs), [])
        bad = json.loads(json.dumps(good))
        del bad["ladder__cyber__1B"]
        bad["ladder__bio__1k"]["rationale"] = "short"
        bad["catastrophe__ai"]["key_sources"] = []
        bad["disempowerment"]["weakest_link"] = ""
        problems = self.ru.validate_debrief(bad, self.qs)
        self.assertIn("ladder:cyber:1B: missing", problems)
        self.assertIn("ladder:bio:1k: rationale needs 2-4 sentences", problems)
        self.assertIn("catastrophe:ai: key_sources needs 1-3 items, each with url and contribution", problems)
        self.assertIn("disempowerment: weakest_link missing", problems)
        self.assertEqual(self.ru.validate_debrief("x", self.qs), ["the debrief must be an object keyed by question id"])

    def test_state_carries_retries_and_cap(self):
        st = self.ru.debrief_state(self.groups, self.by_group)
        self.assertEqual(st["retries"], 3)
        self.assertEqual(st["max_tokens"], 48000)
        self.assertEqual(st["tool"]["name"], "submit_debrief")
        self.assertEqual(st["validate"]({}), [f"{q['id']}: missing" for q in self.qs])

    def test_priming_sentence_is_per_question(self):
        for text in (self.ru.PROMPT,):
            self.assertIn("per question: a short", text)
            self.assertNotIn("per question group", text)


class DebriefExport(unittest.TestCase):
    def _row(self, debrief, **over):
        r = {"elicited_at": "2026-09-16T17:00:00", "run_id": "r", "protocol": "p", "label": "M",
             "model": "m/x", "run_date": "2026-09-16", "call_id": "c1", "debrief": debrief,
             "debrief_status": {"complete": True, "problems": []}}
        r.update(over)
        return r

    def test_question_and_group_entries_both_export(self):
        per_q = self._row({"ladder:cyber:1B": {"rationale": "why", "key_sources": [{"url": "u", "contribution": "c"}],
                                               "weakest_link": "w"},
                           "extinction:ai": {"rationale": "why2", "key_sources": [], "weakest_link": "w2"},
                           "disempowerment": {"rationale": "why3", "key_sources": [], "weakest_link": "w3"}})
        per_g = self._row({"cyber": {"pathway": "path", "base_rate": "b", "key_sources": [],
                                     "compelling_arguments": [{"claim": "x"}]}}, call_id="c0")
        lines = {(l["call_id"], l["key"]): l for l in export._debrief_lines([per_q, per_g, per_q])}
        self.assertEqual(len(lines), 4)
        q = lines[("c1", "ladder:cyber:1B")]
        self.assertEqual((q["group"], q["question_id"], q["rationale"], q["weakest_link"]),
                         ("cyber", "ladder:cyber:1B", "why", "w"))
        self.assertEqual(lines[("c1", "extinction:ai")]["group"], "crosscutting")
        self.assertEqual(lines[("c1", "disempowerment")]["group"], "crosscutting")
        g = lines[("c0", "cyber")]
        self.assertEqual((g["group"], g["question_id"], g["pathway"], g["rationale"]), ("cyber", "", "path", ""))
        self.assertEqual(json.loads(g["compelling_arguments"]), [{"claim": "x"}])
        for l in lines.values():
            self.assertEqual(sorted(l), sorted(export.DEBRIEF_COLUMNS))


if __name__ == "__main__":
    unittest.main()
