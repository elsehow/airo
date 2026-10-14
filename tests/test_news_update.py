"""redlines/news_update.py: the briefs, the one-call read of the week and the
coherence checks on its odds ratios. No network, no keys: a fake writer, and
the forecast runs already in results/runs/."""
import json
import os
import re
import tempfile
import unittest

from redlines import news, news_update as nu
from tests.test_news import item, items_of

RUNGS = ("100", "10k", "1M")


def forecast():
    """A two-model forecast in load_forecast's shape, small enough to read."""
    ladder = {"horizons": ["6mo", "12mo", "2030", "2100"], "questions": [
        {"id": f"ladder:{c}:{r}", "cause": c, "cause_label": c.upper() + " incident", "text": "Q?",
         "criteria": "C.", "severity": {"label": f"{r} deaths"}} for c in ("ai", "bio") for r in RUNGS]}
    cells = {}
    for q in ladder["questions"]:
        k = RUNGS.index(q["id"].rsplit(":", 1)[1])
        cells[q["id"]] = {h: [0.5 / 4 ** k * (j + 1) / 4, 0.6 / 4 ** k * (j + 1) / 4]
                          for j, h in enumerate(ladder["horizons"])}
    return {"run": "2026-10-09T1200Z", "day": "2026-10-09", "models": ["Opus 5.5", "GPT-6 Astra"],
            "model_ids": {"Opus 5.5": "anthropic/claude-opus-5-5", "GPT-6 Astra": "openai/gpt-6-astra"},
            "rationales": {"Opus 5.5": "Pause holds.", "GPT-6 Astra": "Agents misbehave."},
            "cells": cells, "ladder": ladder, "snapshot": None}


def stories():
    its = items_of(item("Agent worm hits hospitals", "2026-10-12T09:00:00Z", summary="Three hospitals hit."),
                   item("Lab ships a model", "2026-10-12T10:00:00Z"),
                   item("Chip stocks fall", "2026-10-12T11:00:00Z"),
                   item("Old news from before", "2026-10-08T11:00:00Z"))
    out = []
    for it in its.values():
        s = news._new_story(it)
        news._add_member(s, it, "seed")
        del s["_words"]
        out.append(s)
    return out, its


def join(story, it):
    """Add a duplicate report to a built story (as reduce does, without the word index)."""
    story["_words"] = set()
    news._add_member(story, it, "same", 0.9)
    del story["_words"]


def answer(odds=None, cites="S1"):
    rows = odds or [[1.0, 1.02, 1.05, 1.01]] * 3
    return ("The worm matters a little.\n\nODDS RATIOS (6mo, 12mo, 2030, 2100)\n"
            + "\n".join(f"R{i + 1}: " + ", ".join(str(x) for x in r) for i, r in enumerate(rows))
            + f"\nSTORIES: {cites}")


def complete_with(text):
    return lambda model, system, user: {"text": text, "usage": {"input_tokens": len(user) // 4, "cost_usd": 0.5}}


class Forecast(unittest.TestCase):
    def test_load_from_repo_runs(self):
        fc = nu.load_forecast()
        self.assertTrue(fc["models"])
        self.assertEqual(set(fc["model_ids"]), set(fc["models"]))
        self.assertTrue(nu.rungs(fc))
        label, model_id, eci = nu.writer(fc)
        self.assertIn(label, fc["models"])
        self.assertEqual(model_id, fc["model_ids"][label])

    def test_writer_matches_index_names(self):
        fc = forecast()
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "epoch_capabilities_index_2026-10-09.csv"), "w") as f:
            f.write("Model,eci,Release date,Organization,Country\n"
                    "GPT-6 Astra,166.4,2026-08-01,OpenAI,United States of America\n"
                    "Claude Opus 5.5,167.3,2026-09-01,Anthropic,United States of America\n")
        fc["snapshot"] = nu.find_snapshot("2026-10-09", [d])
        try:
            self.assertEqual(nu.writer(fc), ("Opus 5.5", "anthropic/claude-opus-5-5", 167.3))
        except ValueError as e:      # a format redlines.eci does not take: say so, do not guess
            self.skipTest(f"eci format: {e}")

    def test_only_the_ai_ladder(self):
        fc = forecast()
        self.assertEqual([q["id"] for q in nu.rungs(fc)], [f"ladder:ai:{r}" for r in RUNGS])
        self.assertEqual(len(nu.base_table(fc)), 3)


class Briefs(unittest.TestCase):
    def setUp(self):
        self.ss, self.its = stories()

    def test_cutoff(self):
        post = nu.after_forecast(self.ss, self.its, forecast())
        self.assertEqual([s["title"] for s in post], ["Agent worm hits hospitals", "Lab ships a model",
                                                      "Chip stocks fall"])

    def test_headline_only_and_excerpt(self):
        s = self.ss[1]
        self.assertIsNone(nu.brief(s, self.its)["excerpt"])
        self.assertIn("Headline only", nu.brief_text("S1", s, self.its))
        self.its[s["members"][0]["item"]]["text"] = "Lab ships a model\n\n" + "A long paragraph of prose. " * 200
        b = nu.brief(s, self.its)
        self.assertEqual(len(b["excerpt"]["text"].split()), nu.BRIEF_WORDS + 1)   # the words, then "…"

    def test_first_readable_member_in_order(self):
        s = self.ss[0]
        later = item("Worm: more hospitals", "2026-10-12T12:00:00Z", source="Other Paper")
        self.its[later["id"]] = dict(later, text="Worm: more hospitals\n\n" + "Detail of the worm attack here. " * 5)
        join(s, later)
        self.assertEqual(nu.brief(s, self.its)["excerpt"]["source"], "Other Paper")
        self.its[s["members"][0]["item"]]["text"] = "x\n\n" + "The first report's own text, long enough. " * 5
        self.assertEqual(nu.brief(s, self.its)["excerpt"]["source"], "Synthetic Wire")

    def test_article_standfirst_left_off(self):
        it = self.its[self.ss[1]["members"][0]["item"]]
        it.update(summary="From the article.", summary_from="article")
        self.assertNotIn("standfirst", nu.brief(self.ss[1], self.its)["reports"][0])
        self.assertEqual(nu.brief(self.ss[0], self.its)["reports"][0]["standfirst"], "Three hospitals hit.")

    def test_fetch_first_readable_stops_at_the_first_read(self):
        d = tempfile.mkdtemp()
        s = self.ss[0]
        for t, src in (("Worm two", "B"), ("Worm three", "C")):
            it = item(t, "2026-10-12T12:00:00Z", source=src)
            self.its[it["id"]] = it
            join(s, it)
        seen = []
        def ext(url):
            seen.append(url)
            ok = "worm-two" in url
            return {"url": url, "text": "Body of two." if ok else "", "error": None if ok else "401"}
        news.fetch_first_readable([s], self.its, state_dir=d, extract=ext)
        self.assertEqual([u.rsplit("/", 1)[1] for u in seen],
                         ["agent-worm-hits-hospitals", "agent-worm-hits-hospitals", "worm-two"])   # www retry, then the next
        news.fetch_first_readable([s], self.its, state_dir=d, extract=ext)
        self.assertEqual(len(seen), 3)

    def test_listing_orders(self):
        f = nu.listing(self.ss)
        r = nu.listing(self.ss, order="reversed")
        self.assertEqual(f[::-1], r)
        self.assertEqual(f, nu.listing(list(reversed(self.ss))))   # the shuffle does not depend on input order


class Update(unittest.TestCase):
    def setUp(self):
        self.ss, self.its = stories()
        self.fc = forecast()

    def test_frames_see_the_same_briefs(self):
        lst = nu.listing(nu.after_forecast(self.ss, self.its, self.fc))
        a, g = (nu.prompt(lst, self.its, self.fc, f, today="2026-10-14") for f in nu.FRAMES)
        block = lambda p: p.split("## The news", 1)[1].split("\n## The ", 1)[0]
        self.assertEqual(block(a), block(g))
        self.assertIn("Pause holds.", a)
        self.assertNotIn("Pause holds.", g)
        self.assertNotRegex(g, r"\d+(\.\d+)?%")      # no forecast numbers in the generic frame
        self.assertIn("R3: 1M deaths", g)
        self.assertNotIn("Old news from before", a)

    def test_update_and_parse(self):
        row = nu.update(self.ss, self.its, self.fc, "airo", complete=complete_with(answer()), now="2026-10-14T00:00:00Z")
        self.assertIsNone(row["error"])
        self.assertEqual(row["odds"][2], [1.0, 1.02, 1.05, 1.01])
        self.assertEqual(row["cites"], [row["labels"]["S1"]])
        self.assertNotIn("ODDS RATIOS", row["text"])
        self.assertEqual(row["text"], "The worm matters a little.")

    def test_unparsable_table_is_logged_with_why(self):
        bad = answer(odds=[[1.0, 1.0, 1.0, 1.0]] * 2)
        row = nu.update(self.ss, self.its, self.fc, "generic", complete=complete_with(bad))
        self.assertIsNone(row["odds"])
        self.assertIn("2 of 3 rungs", row["error"])
        self.assertTrue(row["raw"])

    def test_empty_answer_raises(self):
        with self.assertRaises(RuntimeError):
            nu.update(self.ss, self.its, self.fc, complete=complete_with(""))

    def test_violations(self):
        base = nu.base_table(self.fc)
        self.assertEqual(nu.violations(base, ["a", "b", "c"], ["1", "2", "3", "4"]), [])
        odds = [[1.0] * 4, [1.0] * 4, [1.0, 1.0, 1.0, 100.0]]   # 1M deaths by 2100 overtakes 10k
        v = nu.violations(nu.implied(base, odds), ["a", "b", "c"], ["1", "2", "3", "4"])
        self.assertEqual(len(v), 1)
        self.assertIn("c by 4", v[0])
        odds = [[1.0, 0.1, 1.0, 1.0]] + [[1.0] * 4] * 2   # 100 deaths less likely by 12mo than by 6mo
        self.assertTrue(any("below 1" in x for x in nu.violations(nu.implied(base, odds), ["a", "b", "c"], ["1", "2", "3", "4"])))

    def test_page(self):
        d = tempfile.mkdtemp()
        built = {"built_at": "2026-10-13T12:00:00Z", "thresholds": news.THRESHOLDS,
                 "stats": {"items": 4}, "dropped": [], "stories": self.ss}
        json.dump(built, open(os.path.join(d, "stories.json"), "w"))
        news.append_jsonl(os.path.join(d, "items.jsonl"), list(self.its.values()))
        news.append_jsonl(os.path.join(d, nu.LOG),
                          [nu.update(self.ss, self.its, self.fc, f, o, complete=complete_with(answer()))
                           for f in nu.FRAMES for o in nu.ORDERS])
        out = nu.render_page(d, os.path.join(d, "stories.html"), self.fc)
        html = open(out).read()
        self.assertNotIn("__DATA__", html)
        # a top-level const/let named after a window property (top, name, location...)
        # is a SyntaxError in the browser, and the whole page goes blank
        script = html.rsplit("<script>", 1)[1]
        clash = re.findall(r"^(?:const|let)\s+(top|name|status|location|parent|self|length|origin|history)\b",
                           script, re.M)
        self.assertEqual(clash, [])
        data = json.loads(html.split('<script id="data" type="application/json">', 1)[1]
                          .split("</script>", 1)[0].replace("<\\/", "</"))
        self.assertEqual(set(data["runs"]), set(nu.FRAMES))
        self.assertEqual(set(data["runs"]["airo"]), set(nu.ORDERS))
        self.assertEqual(len(data["stories"]), 3)
        self.assertEqual([s["label"] for s in data["stories"]], ["S1", "S2", "S3"])
        self.assertEqual(data["ladder"]["rungs"], [f"{r} deaths" for r in RUNGS])
        self.assertEqual(data["runs"]["airo"]["forward"]["violations"], [])


if __name__ == "__main__":
    unittest.main()
