"""redlines/news.py: feeds into items, items into stories. No network, no
keys: fixture feeds (tests/fixtures/news/, synthetic) and a fake Jev that
answers from a hidden event label per headline."""
import json
import os
import tempfile
import unittest
from unittest import mock

from redlines import news

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "news")


def fixture(name):
    return open(os.path.join(FIX, name), "rb").read()


FEEDS = [
    {"id": "wire", "source": "Synthetic Wire", "url": "https://feeds.test/wire", "ai_only": True,
     "open_access": False},
    {"id": "gadgets", "source": "Gadget Blog", "url": "https://feeds.test/gadgets", "ai_only": False,
     "open_access": True},
    {"id": "wire_gnews", "source": "Synthetic Wire", "url": "https://feeds.test/gnews",
     "ai_only": True, "open_access": False, "resolve": "google_news"},
]
BODIES = {"https://feeds.test/wire": fixture("rss.xml"),
          "https://feeds.test/gadgets": fixture("atom.xml"),
          "https://feeds.test/gnews": fixture("gnews.xml")}


def fake_get(url, **kw):
    if url in BODIES:
        return 200, BODIES[url], None
    return 404, b"", "HTTP 404"


def fake_resolve(link):
    return {"https://news.google.com/rss/articles/CBMiFAKEID1?oc=5":
            "https://example-wire.test/2026/10/12/example-lab-model-nine"}.get(link)


# the hidden truth the fake Jev answers from
EVENT = {"Example Lab releases Model Nine": "nine", "Example Lab’s Model Nine is out": "nine",
         "Ransomware gang uses AI agent against hospital network": "ransom",
         "Hospital confirms AI-assisted ransomware attack": "ransom-response",
         "Example Lab releases Model Ten": "ten",
         "A new phone with a bigger screen": None}
ABOUT_AI = {"A new phone with a bigger screen": 0.05}


class FakeJev:
    def __init__(self):
        self.calls = []

    def __call__(self, state, questions):
        self.calls.append((state, questions))
        answers = {}
        if "item" in state:
            h = state["item"]["headline"]
            answers["about_ai"] = {"type": "noul", "noul": ABOUT_AI.get(h, 0.95)}
        else:
            h = state["new_item"]["headline"]
            for qid, q in questions.items():
                theirs = {EVENT.get(r["headline"]) for r in q["instructions"]["story"]["reports"]}
                if qid.startswith("same_"):
                    p = 0.92 if EVENT.get(h) in theirs else 0.04
                else:   # follow-up: the response to the ransomware attack
                    p = 0.8 if EVENT.get(h) == "ransom-response" and "ransom" in theirs else 0.03
                answers[qid] = {"type": "noul", "noul": p}
        return {"model": "jev-fake", "answers": answers,
                "usage": {"input_tokens": len(json.dumps([state, questions])) // 4}}


class Parse(unittest.TestCase):
    def test_rss(self):
        e = news.parse_feed(fixture("rss.xml"))
        self.assertEqual(len(e), 2)
        self.assertEqual(e[0]["title"], "Example Lab releases Model Nine")
        self.assertEqual(e[0]["summary"], "The lab says Model Nine beats its predecessor.")
        self.assertEqual(e[0]["published"], "2026-10-12T09:00:00Z")
        self.assertEqual(e[0]["categories"], ["Artificial Intelligence"])
        self.assertTrue(e[0]["link"].startswith("https://www.example-wire.test/"))  # not the empty atom:link

    def test_atom(self):
        e = news.parse_feed(fixture("atom.xml"))
        self.assertEqual(e[0]["link"], "https://gadgets.example.test/ai/123/example-lab-model-nine")
        self.assertEqual(e[0]["title"], "Example Lab’s Model Nine is out")
        self.assertEqual(e[0]["published"], "2026-10-12T11:00:00Z")   # -04:00 to UTC

    def test_not_a_feed(self):
        with self.assertRaises(Exception):
            news.parse_feed(b"<html><body>Access denied")

    def test_canonical_url(self):
        c = news.canonical_url
        self.assertEqual(c("http://www.FT.com/content/abc?syn-25#x"), "https://ft.com/content/abc")
        self.assertEqual(c("https://ft.com/content/abc/"), "https://ft.com/content/abc")
        self.assertEqual(c("https://www.theverge.com/?p=1010344"), "https://theverge.com?p=1010344")

    def test_gnews_title(self):
        self.assertEqual(news._gnews_title("Big news - Reuters", "Reuters"), "Big news")
        self.assertEqual(news._gnews_title("Big news", "Reuters"), "Big news")

    def test_resolve_google_news(self):
        page = b'<c-wiz data-n-a-id="CBMiX" data-n-a-ts="1791912583" data-n-a-sg="AbIa"></c-wiz>'
        decoded = (b")]}'\n\n[[\"wrb.fr\",\"Fbv4je\",\"[\\\"garturlres\\\",\\\"https://www.reuters.com/"
                   b"world/a-story-2026-10-12/\\\",1]\",null,null,null,\"generic\"]]")
        sent = []

        def get(url, data=None, headers=None):
            sent.append((url, data))
            return (200, decoded, None) if data else (200, page, None)
        self.assertEqual(news.resolve_google_news("https://news.google.com/rss/articles/CBMiX", get),
                         "https://www.reuters.com/world/a-story-2026-10-12/")
        self.assertIn(b"CBMiX", sent[1][1])
        self.assertIsNone(news.resolve_google_news("x", lambda *a, **k: (200, b"<html/>", None)))


class Poll(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def poll(self, now="2026-10-12T16:00:00Z", get=fake_get):
        return news.poll(FEEDS, self.dir, get=get, resolve=fake_resolve, now=now)

    def test_poll_dedupes_by_canonical_url(self):
        rows = self.poll()
        self.assertEqual([r["new"] for r in rows], [2, 2, 0])   # the Google item IS the wire item
        items = news.load_items(self.dir)
        self.assertEqual(len(items), 4)
        nine = items[news.item_id("https://example-wire.test/2026/10/12/example-lab-model-nine")]
        self.assertEqual(nine["feeds"], ["wire", "wire_gnews"])
        self.assertFalse(nine["open_access"])

    def test_second_poll_adds_nothing(self):
        self.poll()
        rows = self.poll(now="2026-10-12T16:15:00Z")
        self.assertEqual([r["new"] for r in rows], [0, 0, 0])
        self.assertEqual(len(news.read_jsonl(os.path.join(self.dir, "items.jsonl"))), 5)
        self.assertEqual(len(news.read_jsonl(os.path.join(self.dir, "fetches.jsonl"))), 6)

    def test_broken_feed_is_logged_not_raised(self):
        def get(url, **kw):
            if url.endswith("wire"):
                return 403, b"", "HTTP 403"
            if url.endswith("gadgets"):
                return 200, b"<html>blocked</html", None
            return fake_get(url)
        rows = self.poll(get=get)
        self.assertEqual(rows[0]["error"], "HTTP 403")
        self.assertTrue(rows[1]["error"].startswith("not a feed"))
        self.assertEqual(rows[2]["new"], 1)
        self.assertIn("Feeds that broke", news.report(self.dir))


def item(title, published, feed="wire", source="Synthetic Wire", fetched=None, summary=""):
    url = "https://example.test/" + title.lower().replace(" ", "-")
    return {"id": news.item_id(url), "feed": feed, "feeds": [feed], "source": source,
            "title": title, "summary": summary, "url": url, "link": url,
            "published": published, "first_fetched": fetched or published,
            "open_access": source != "Synthetic Wire", "ai_only_feed": feed != "gadgets",
            "categories": []}


def items_of(*its):
    return {it["id"]: it for it in its}


AI_FEEDS = {"wire", "blog"}


class Reduce(unittest.TestCase):
    def corpus(self):
        return items_of(
            item("Example Lab releases Model Nine", "2026-10-12T09:00:00Z"),
            item("Example Lab’s Model Nine is out", "2026-10-12T11:00:00Z", feed="blog",
                 source="Gadget Blog"),
            item("Example Lab releases Model Ten", "2026-10-12T12:00:00Z"),
            item("Ransomware gang uses AI agent against hospital network", "2026-10-12T15:30:00Z"),
            item("Hospital confirms AI-assisted ransomware attack", "2026-10-13T10:00:00Z",
                 feed="blog", source="Gadget Blog"),
            item("A new phone with a bigger screen", "2026-10-12T08:00:00Z", feed="gadgets",
                 source="Gadget Blog"))

    def fold(self, its, decisions=(), ask=None):
        log = []
        stories, dropped, stats = news.fold(its, list(decisions), ask=ask, log=log.append,
                                            now="2026-10-13T12:00:00Z", ai_feeds=AI_FEEDS)
        return stories, dropped, stats, log

    def test_one_event_one_story(self):
        its = self.corpus()
        stories, dropped, stats, log = self.fold(its, ask=FakeJev())
        by_title = {s["title"]: s for s in stories}
        nine = by_title["Example Lab releases Model Nine"]
        self.assertEqual(len(nine["members"]), 2)
        self.assertEqual(nine["sources"], ["Synthetic Wire", "Gadget Blog"])
        self.assertEqual(nine["members"][1]["p_same"], 0.92)
        self.assertEqual(nine["members"][1]["via"], "jev")
        self.assertEqual((nine["first_seen"], nine["last_seen"]),
                         ("2026-10-12T09:00:00Z", "2026-10-12T11:00:00Z"))
        # same lab, same day, a different announcement: its own story
        self.assertIn("Example Lab releases Model Ten", by_title)
        self.assertEqual(len(dropped), 1)                  # the phone, gated out
        self.assertEqual(len(stories), 4)
        self.assertEqual(set(nine["screen"]), set(news.CAUSES))
        self.assertEqual(stats["calls"], len(log))

    def test_followup_seeds_a_related_story(self):
        stories, *_ = self.fold(self.corpus(), ask=FakeJev())
        resp = next(s for s in stories if s["title"].startswith("Hospital confirms"))
        attack = next(s for s in stories if s["title"].startswith("Ransomware gang"))
        self.assertEqual(len(resp["members"]), 1)
        self.assertEqual(resp["related"][0]["story"], attack["id"])

    def test_no_candidates_no_call(self):
        jev = FakeJev()
        stories, _, stats, log = self.fold(items_of(
            item("Example Lab releases Model Nine", "2026-10-12T09:00:00Z"),
            item("Ransomware gang uses AI agent against hospital network", "2026-10-12T15:30:00Z")),
            ask=jev)
        self.assertEqual(len(stories), 2)
        self.assertEqual(jev.calls, [])     # no shared words, nothing to ask

    def test_window(self):
        jev = FakeJev()
        stories, *_ = self.fold(items_of(
            item("Example Lab releases Model Nine", "2026-10-01T09:00:00Z"),
            item("Example Lab’s Model Nine is out", "2026-10-12T11:00:00Z", feed="blog")),
            ask=jev)
        self.assertEqual(len(stories), 2)    # eleven days apart: never a candidate
        self.assertEqual(jev.calls, [])

    def test_questions_are_one_story_each(self):
        jev = FakeJev()
        self.fold(self.corpus(), ask=jev)
        state, qs = next(c for c in jev.calls if "new_item" in c[0])
        self.assertEqual(set(state), {"new_item"})
        self.assertNotIn("url", json.dumps(state))
        q = qs["same_0"]
        self.assertEqual(q["type"], "noul")
        self.assertEqual(set(q["instructions"]), {"story", "question"})

    def test_replay_is_deterministic_and_free(self):
        its = self.corpus()
        first, d1, _, log = self.fold(its, ask=FakeJev())
        again, d2, stats, log2 = self.fold(its, decisions=log, ask=None)
        self.assertEqual(json.dumps(first), json.dumps(again))
        self.assertEqual((stats["calls"], log2), (0, []))
        # and a run with a live client asks nothing the log already holds
        jev = FakeJev()
        self.fold(its, decisions=log, ask=jev)
        self.assertEqual(jev.calls, [])

    def test_replay_applies_new_thresholds(self):
        its = self.corpus()
        _, _, _, log = self.fold(its, ask=FakeJev())
        old = news.SAME_AT
        try:
            news.SAME_AT = 0.95                  # stricter than any logged p_same
            stories, _, stats, _ = self.fold(its, decisions=log)
        finally:
            news.SAME_AT = old
        self.assertTrue(all(len(s["members"]) == 1 for s in stories))
        self.assertEqual(stats["calls"], 0)

    def test_run_reduce_and_report(self):
        d = tempfile.mkdtemp()
        news.poll(FEEDS, d, get=fake_get, resolve=fake_resolve, now="2026-10-12T16:00:00Z")
        jev = FakeJev()
        stats = news.run_reduce(d, ask=jev, now="2026-10-12T16:05:00Z")
        built = json.load(open(os.path.join(d, "stories.json")))
        self.assertEqual(built["stats"], stats)
        self.assertEqual(len(news.read_jsonl(os.path.join(d, "decisions.jsonl"))), stats["calls"])
        self.assertEqual(stats["dropped"], 1)             # the phone (gadgets is not AI-only)
        text = news.report(d)
        for heading in ("In and out", "closest merge calls", "AI gate", "Feeds that broke"):
            self.assertIn(heading, text)
        # replay from disk, no client
        self.assertEqual(news.run_reduce(d, replay=True)["stories"], stats["stories"])

    def test_no_key_refuses(self):
        old = os.environ.pop("TYPESAFE_API_KEY", None)
        try:
            with self.assertRaises(news.JevError):
                news.run_reduce(tempfile.mkdtemp())
        finally:
            if old is not None:
                os.environ["TYPESAFE_API_KEY"] = old


class JevClient(unittest.TestCase):
    def test_retries_then_succeeds(self):
        seen = []

        def post(url, body, headers):
            seen.append(json.loads(body))
            if len(seen) == 1:
                return 429, b"", "HTTP 429"
            return 200, b'{"model": "jev-1.13.0", "answers": {}, "usage": {}}', None
        news.time.sleep, real = (lambda s: None), news.time.sleep
        try:
            r = news.jev_ask({"x": 1}, {"q": {"type": "noul", "instructions": "?"}}, key="k", post=post)
        finally:
            news.time.sleep = real
        self.assertEqual(r["model"], "jev-1.13.0")
        self.assertEqual(seen[0]["model"], "jev-latest")
        self.assertEqual(len(seen), 2)

    def test_bad_request_raises(self):
        with self.assertRaises(news.JevError):
            news.jev_ask({}, {}, key="k", post=lambda *a: (422, b"", "HTTP 422"))


class FullText(unittest.TestCase):
    def test_extract(self):
        ok = lambda *a: (200, json.dumps({"results": [{"raw_content": "Body."}]}).encode(), None)
        self.assertEqual(news.extract_text("https://x/a", key="k", post=ok)["text"], "Body.")
        failed = lambda *a: (200, json.dumps({"results": [], "failed_results": [{"error": "paywall"}]}).encode(), None)
        self.assertEqual(news.extract_text("https://x/a", key="k", post=failed)["error"], "paywall")
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": ""}), self.assertRaises(RuntimeError):
            news.extract_text("https://x/a")

    def test_fetch_once_and_load(self):
        d = tempfile.mkdtemp()
        its = items_of(item("Worm hits hospitals", "2026-10-12T09:00:00Z"))
        news.append_jsonl(os.path.join(d, "items.jsonl"), list(its.values()))
        calls = []
        ext = lambda url: calls.append(url) or {"url": url, "text": "The whole article.", "chars": 18}
        news.fetch_fulltext(list(its), its, state_dir=d, extract=ext)
        news.fetch_fulltext(list(its), its, state_dir=d, extract=ext)   # read once, not twice
        self.assertEqual(len(calls), 1)
        self.assertEqual(next(iter(news.load_items(d).values()))["text"], "The whole article.")


if __name__ == "__main__":
    unittest.main()
