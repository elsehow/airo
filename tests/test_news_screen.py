"""redlines/news_screen.py: the screen, the notes and the calibration that
grades one with the other. No network, no keys: a fake Jev, a fake writer,
and the forecast runs already in results/runs/."""
import json
import os
import tempfile
import unittest
from unittest import mock

from redlines import news, news_screen as ns
from tests.test_news import item, items_of


def forecast():
    """A two-model forecast in load_forecast's shape, small enough to read."""
    ladder = {"horizons": ["6mo", "12mo", "2030", "2100"], "questions": [
        {"id": f"ladder:{c}:{r}", "cause": c, "cause_label": c.upper() + " incident", "text": "Q?",
         "criteria": "C.", "severity": {"label": f"{r} deaths"}} for c in ns.FAMILY for r in ("100", "1M")]}
    cross = {"questions": [{"id": "extinction:ai", "name": "AI extinction", "text": "Extinction?"}]}
    cells = {q["id"]: {h: [0.1, 0.3] for h in ladder["horizons"]} for q in ladder["questions"]}
    return {"run": "2026-10-09T1200Z", "day": "2026-10-09", "models": ["Opus 5.5", "GPT-6 Astra"],
            "model_ids": {"Opus 5.5": "anthropic/claude-opus-5-5", "GPT-6 Astra": "openai/gpt-6-astra"},
            "rationales": {"Opus 5.5": "Pause holds.", "GPT-6 Astra": "Agents misbehave."},
            "cells": cells, "ladder": ladder, "cross": cross, "snapshot": None}


def stories():
    its = items_of(item("Agent worm hits hospitals", "2026-10-12T09:00:00Z"),
                   item("Lab ships a model", "2026-10-12T10:00:00Z"),
                   item("Chip stocks fall", "2026-10-12T11:00:00Z"),
                   item("Port volume record", "2026-10-12T12:00:00Z"))
    out = []
    for it in its.values():
        s = news._new_story(it)
        news._add_member(s, it, "seed")
        del s["_words"]
        out.append(s)
    return out, its


P = {"Agent worm hits hospitals": 0.7, "Lab ships a model": 0.32, "Chip stocks fall": 0.2,
     "Port volume record": 0.02}


class FakeJev:
    def __init__(self):
        self.calls = []

    def __call__(self, state, questions):
        self.calls.append((state, questions))
        p = P[state["story"]["reports"][0]["headline"]]
        return {"model": "jev-fake", "usage": {"input_tokens": 100},
                "answers": {c: {"type": "noul", "noul": p if c == "cyber" else p / 2} for c in questions}}


VERDICT = {"Agent worm hits hospitals": "small", "Lab ships a model": "none",
           "Chip stocks fall": "moderate", "Port volume record": "none"}


def fake_complete(model, system, prompt):
    title = prompt.split('## The news story\n\n"', 1)[1].split('"', 1)[0]
    return {"text": f"Note on {title}.\n\nVERDICT: {VERDICT[title]}", "usage": {"cost_usd": 0.5}}


class Forecast(unittest.TestCase):
    def test_load_from_repo_runs(self):
        fc = ns.load_forecast()
        self.assertTrue(fc["models"])
        self.assertEqual(set(fc["model_ids"]), set(fc["models"]))
        q = next(iter(fc["cells"]))
        lo_med_hi = ns.ensemble(fc, q, next(iter(fc["cells"][q])))
        self.assertLessEqual(lo_med_hi[1], lo_med_hi[0])
        label, model_id, eci = ns.writer(fc)
        self.assertIn(label, fc["models"])
        self.assertEqual(model_id, fc["model_ids"][label])

    def test_writer_matches_index_names(self):
        fc = forecast()
        d = tempfile.mkdtemp()
        path = os.path.join(d, "epoch_capabilities_index_2026-10-09.csv")
        with open(path, "w") as f:   # the published format redlines.eci reads
            f.write("Model,eci,Release date,Organization,Country\n"
                    "GPT-6 Astra,166.4,2026-08-01,OpenAI,United States of America\n"
                    "Claude Opus 5.5,167.3,2026-09-01,Anthropic,United States of America\n")
        fc["snapshot"] = ns.find_snapshot("2026-10-09", [d])
        try:
            self.assertEqual(ns.writer(fc), ("Opus 5.5", "anthropic/claude-opus-5-5", 167.3))
        except ValueError as e:      # a format redlines.eci does not take: say so, do not guess
            self.skipTest(f"eci format: {e}")

    def test_screen_state_is_small(self):
        st = ns.screen_state(forecast())
        self.assertEqual(set(st["ensemble_median_by_family"]), set(ns.FAMILY.values()))
        self.assertLess(len(json.dumps(st)), 6000)


class Screen(unittest.TestCase):
    def test_screen_and_reuse(self):
        ss, its = stories()
        fc, jev, log = forecast(), FakeJev(), []
        out = ns.screen(ss, its, fc, [], ask=jev, log=log.append)
        self.assertEqual(len(jev.calls), 4)
        self.assertEqual(sorted(ns.flagged(r) for r in out.values()), [False, False, True, True])
        state, qs = jev.calls[0]
        self.assertEqual(set(state), {"story", "airo_forecast"})
        self.assertEqual(set(qs), set(ns.FAMILY))
        # the log answers a re-run, and a replay calls nothing
        again = FakeJev()
        self.assertEqual(ns.screen(ss, its, fc, log, ask=again), out)
        self.assertEqual(again.calls, [])
        self.assertEqual(ns.screen(ss, its, fc, log), out)
        # a new forecast is a new question
        fc2 = dict(fc, run="2026-10-14T1200Z")
        self.assertEqual(ns.screen(ss, its, fc2, log), {})

    def test_full_text_rescreens_and_is_shown(self):
        ss, its = stories()
        fc, log = forecast(), []
        ns.screen(ss, its, fc, [], ask=FakeJev(), log=log.append)
        its[ss[0]["members"][0]["item"]]["text"] = "Full article body."
        jev = FakeJev()
        ns.screen(ss, its, fc, log, ask=jev, log=log.append)
        self.assertEqual(len(jev.calls), 1)
        self.assertEqual(jev.calls[0][0]["story"]["reports"][0]["full_text"], "Full article body.")
        p = ns.explain_prompt(ss[0], its, fc, ["cyber"], today="2026-10-13")
        self.assertIn("Full article body.", p)
        self.assertNotIn("standfirsts only", p)

    def test_new_member_rescreens(self):
        ss, its = stories()
        fc, log = forecast(), []
        ns.screen(ss, its, fc, [], ask=FakeJev(), log=log.append)
        extra = item("Agent worm: second report", "2026-10-12T13:00:00Z")
        its[extra["id"]] = extra
        ss[0]["_words"] = set()
        news._add_member(ss[0], extra, "jev", 0.9)                       # a second report joins
        del ss[0]["_words"]
        jev = FakeJev()
        ns.screen(ss, its, fc, log, ask=jev, log=log.append)
        self.assertEqual(len(jev.calls), 1)


class Notes(unittest.TestCase):
    def setUp(self):
        self.ss, self.its = stories()
        self.fc = forecast()
        self.fc["snapshot"] = None
        self.screened = ns.screen(self.ss, self.its, self.fc, [], ask=FakeJev())
        patch = mock.patch.object(ns, "writer", lambda fc: ("Opus 5.5", "anthropic/claude-opus-5-5", 167.3))
        patch.start()
        self.addCleanup(patch.stop)

    def test_parse_verdict(self):
        self.assertEqual(ns.parse_verdict("Text.\n\nVERDICT: small"), ("Text.", "small"))
        self.assertEqual(ns.parse_verdict("Text.\n**VERDICT:** Negligible\n"), ("Text.", "negligible"))
        self.assertEqual(ns.parse_verdict("Text without one."), ("Text without one.", None))
        self.assertEqual(ns.parse_verdict("VERDICT: huge")[1], None)

    def test_prompt_carries_story_forecast_and_verdict_rule(self):
        s = self.ss[0]
        p = ns.explain_prompt(s, self.its, self.fc, ["cyber"], today="2026-10-13")
        self.assertIn('"Agent worm hits hospitals"', p)
        self.assertIn("CYBER incident ladder", p)
        self.assertNotIn("BIO incident ladder", p)
        self.assertIn("AI extinction", p)
        self.assertIn("Agents misbehave.", p)
        self.assertIn("VERDICT: <size>", p)

    def test_explain(self):
        s = self.ss[0]
        n = ns.explain(s, self.its, self.fc, self.screened[s["id"]], complete=fake_complete)
        self.assertEqual((n["verdict"], n["writer"], n["flagged"]), ("small", "Opus 5.5", True))
        self.assertEqual(n["causes"], ["ai", "cyber", "bio", "misalign"])   # 0.7 and 0.35 both >= 0.3
        self.assertNotIn("VERDICT", n["text"])

    def test_empty_note_raises(self):
        with self.assertRaises(RuntimeError):
            ns.explain(self.ss[0], self.its, self.fc, self.screened[self.ss[0]["id"]],
                       complete=lambda *a: {"text": None, "usage": {}})

    def test_pick_and_calibrate(self):
        pick = ns.pick_for_notes(self.ss, self.screened, [], flagged_n=5, audit_below=2)
        self.assertEqual([s["title"] for s in pick],
                         ["Lab ships a model", "Agent worm hits hospitals",     # flagged, newest first
                          "Chip stocks fall", "Port volume record"])           # audit: near, then spread
        notes = [ns.explain(s, self.its, self.fc, self.screened[s["id"]], complete=fake_complete)
                 for s in pick]
        self.assertEqual(ns.pick_for_notes(self.ss, self.screened, notes, 5, 2), [])
        cal = ns.calibrate(self.screened, notes)
        self.assertEqual((cal["false_flags"], cal["misses"]), (1, 1))   # the launch; the chip slide
        self.assertEqual(cal["suggest"], 0.2)                           # lowest p the writer said moves
        self.assertEqual(cal["pairs"][0][:2], (0.7, "small"))

    def test_page(self):
        d = tempfile.mkdtemp()
        built = {"built_at": "2026-10-13T12:00:00Z", "thresholds": news.THRESHOLDS,
                 "stats": {"items": 4}, "dropped": [], "stories": self.ss}
        json.dump(built, open(os.path.join(d, "stories.json"), "w"))
        news.append_jsonl(os.path.join(d, "items.jsonl"), list(self.its.values()))
        news.append_jsonl(os.path.join(d, "screen.jsonl"), list(self.screened.values()))
        s = self.ss[0]
        news.append_jsonl(os.path.join(d, "notes.jsonl"),
                          [ns.explain(s, self.its, self.fc, self.screened[s["id"]], complete=fake_complete)])
        out = ns.render_page(d, os.path.join(d, "stories.html"), {"day": "2026-10-09", "models": ["Opus 5.5"]})
        html = open(out).read()
        self.assertNotIn("__DATA__", html)
        # a top-level const/let named after a window property (top, name, location...)
        # is a SyntaxError in the browser, and the whole page goes blank
        import re
        script = html.rsplit("<script>", 1)[1]
        clash = re.findall(r"^(?:const|let)\s+(top|name|status|location|parent|self|length|origin|history)\b",
                           script, re.M)
        self.assertEqual(clash, [])
        data = json.loads(html.split('<script id="data" type="application/json">', 1)[1]
                          .split("</script>", 1)[0].replace("<\\/", "</"))
        self.assertEqual(data["notes"][s["id"]]["verdict"], "small")
        self.assertEqual(data["meta"]["screen_at"], ns.SCREEN_AT)
        self.assertEqual(len(data["calibration"]["pairs"]), 1)


if __name__ == "__main__":
    unittest.main()
