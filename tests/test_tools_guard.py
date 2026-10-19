"""redlines.tools URL guard (FORECASTER_BLOCK_URL_PATTERNS), with the network
mocked: off unless set; read_page refuses without calling Tavily; web_search
drops matching results and the answer built from them. A port of agent-box's
tests/test_url_guard.py (branch `url-guard`) against the mirror here, which
tests/test_tools_parity.py keeps identical to agent-box's copy."""
import io
import json
import os
import unittest
from unittest.mock import patch

from redlines import tools

PATTERNS = ("forecastingresearch\\.org/pdf/airo\n"
            "forecastingresearch\\.org/research/airo,airo\\.forecastingresearch\\.org")
PAPER = "https://forecastingresearch.org/pdf/airo-working-paper.pdf"
SEARCH = {"answer": "AIRO says 0.47%", "results": [
    {"title": "AIRO working paper", "url": PAPER, "content": "x"},
    {"title": "Automated Artificial Intelligence Risk Outlook (mirror)",
     "url": "https://example.com/mirror", "content": "x"},
    {"title": "XPT", "url": "https://forecastingresearch.org/xpt", "content": "x"},
    {"title": "Launch post", "url": "https://www.lesswrong.com/posts/abc/airo", "content": "x"},
]}


def reply(data):
    return io.BytesIO(json.dumps(data).encode())


class UrlGuardTest(unittest.TestCase):
    def env(self, patterns=None):
        env = {"TAVILY_API_KEY": "k"}
        if patterns:
            env[tools.BLOCK_ENV] = patterns
        return patch.dict(os.environ, env, clear=True)

    def test_read_page_blocked_without_calling_tavily(self):
        with self.env(PATTERNS), patch("urllib.request.urlopen") as net:
            for url in (PAPER, "https://forecastingresearch.org/research/airo",
                        "https://airo.forecastingresearch.org/",
                        "https://Airo.ForecastingResearch.org/", PAPER.replace("airo", "AIRO")):
                self.assertEqual(tools.read_page(url), {
                    "url": url, "text": "", "error": "page read failed: page unavailable"})
        net.assert_not_called()

    def test_read_page_others_still_fetched(self):
        page = {"results": [{"raw_content": "XPT text"}]}
        for env in (self.env(PATTERNS), self.env()):
            with env, patch("urllib.request.urlopen", return_value=reply(page)) as net:
                self.assertEqual(tools.read_page("https://forecastingresearch.org/xpt")["text"], "XPT text")
            net.assert_called_once()
        with self.env(), patch("urllib.request.urlopen", return_value=reply(page)):
            self.assertEqual(tools.read_page(PAPER)["text"], "XPT text")   # off when unset

    def test_web_search_drops_matches_and_answer(self):
        with self.env(PATTERNS), patch("urllib.request.urlopen", return_value=reply(SEARCH)):
            out = tools.web_search("ai risk")
        self.assertEqual([r["url"] for r in out["results"]],
                         ["https://forecastingresearch.org/xpt", "https://www.lesswrong.com/posts/abc/airo"])
        self.assertIsNone(out["answer"])

    def test_web_search_keeps_answer_when_nothing_dropped(self):
        clean = {"answer": "ok", "results": SEARCH["results"][2:]}
        with self.env(PATTERNS), patch("urllib.request.urlopen", return_value=reply(clean)):
            out = tools.web_search("ai risk")
        self.assertEqual(out["answer"], "ok")
        self.assertEqual(len(out["results"]), 2)

    def test_web_search_unchanged_when_unset(self):
        with self.env(), patch("urllib.request.urlopen", return_value=reply(SEARCH)):
            out = tools.web_search("ai risk")
        self.assertEqual(out["answer"], "AIRO says 0.47%")
        self.assertEqual(len(out["results"]), 4)


if __name__ == "__main__":
    unittest.main()
