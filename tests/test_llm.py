"""Guard the two modules vendored out of xrisk-canaries on 2026-08-28.

They arrived here as the acquisition half of the pipeline (redlines/llm.py,
redlines/tools.py) so that a fresh clone can RE-ELICIT and not merely rebuild.
Nothing tested them before the move: they lived in a private sibling checkout
that this repo reached into over sys.path. Three things are worth pinning.

  * IMPORT STAYS STDLIB. `redlines/llm.py` imports litellm inside the call, on
    purpose — tests/ import the runners to inspect their prompts, and the build
    path advertises "no third-party deps". A stray module-scope `import litellm`
    would break both, silently, on any machine that happens to have litellm.

  * load_keys() IS THE REWRITTEN PIECE. Everything else was carried over
    verbatim; this function replaced an upstream one that read GCP Secret
    Manager through a hardcoded macOS path. It has to agree with `set -a; . file`
    on the SAME env file, because code/cron_run.sh sources that file with the
    shell before running us and the two must not drift.

  * THE LOOP STILL LOOPS. call_tools takes an injectable `complete` backend, so
    the tool-call -> tool-result -> submit cycle is checkable offline.
"""
import contextlib
import json
import json
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from redlines import llm, tools  # noqa: E402


class TestImportIsStdlibOnly(unittest.TestCase):
    def test_importing_llm_does_not_import_litellm(self):
        """The whole point of the lazy import: `pip install -e .` (no extras) must
        still be able to load this module."""
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r);"
             "import redlines.llm, redlines.tools;"
             "print('litellm' in sys.modules)" % str(REPO)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "False", "litellm must not be imported at module scope")

    def test_forecast_tools_are_the_two_grounding_tools(self):
        """Search and read, nothing else: the Metaculus lookup left on 2026-09-02
        (redlines/tools.py says why), and a runner that still named it in a
        prompt would be asking for a tool the loop cannot serve."""
        self.assertEqual([t["name"] for t in tools.FORECAST_TOOLS],
                         ["web_search", "read_page"])
        for t in tools.FORECAST_TOOLS:
            self.assertTrue(callable(t["fn"]))
            self.assertIn("parameters", t)
        self.assertFalse(hasattr(tools, "metaculus_lookup"))
        self.assertNotIn("METACULUS_API_KEY", llm.PROVIDER_KEYS)

    def test_runner_prompts_name_only_tools_the_loop_serves(self):
        import importlib.util
        names = {t["name"] for t in tools.FORECAST_TOOLS}
        for runner in ("run_unified", "run_ladder_joint"):
            spec = importlib.util.spec_from_file_location(runner, REPO / "code" / f"{runner}.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for text in (mod.SYSTEM, mod.PROMPT):
                self.assertNotIn("metaculus", text.lower(), runner)
            for name in names:
                self.assertIn(name, mod.SYSTEM, f"{runner}: SYSTEM does not offer {name}")

    def test_recent_days_bounds_the_news_index_by_exact_dates(self):
        """Probed 2026-09-02: exact dates filter on Tavily's news index and not
        on the general one. So recent_days means news + start/end, and no
        recent_days means the general index with no date at all."""
        from datetime import date
        b = tools.search_body("q", 5, recent_days=90, today=date(2026, 9, 2))
        self.assertEqual((b["topic"], b["start_date"], b["end_date"]), ("news", "2026-06-04", "2026-09-02"))
        b = tools.search_body("q", 5)
        self.assertNotIn("topic", b)
        self.assertNotIn("start_date", b)
        self.assertIn("recent_days", tools.WEB_SEARCH_TOOL["parameters"]["properties"])

    def test_prompt_states_the_floor_but_no_maximum(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ru", REPO / "code" / "run_unified.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIn(str(mod.MIN_RESEARCH), mod.SYSTEM)
        self.assertNotIn(str(mod.MAX_ROUNDS), mod.SYSTEM)
        self.assertNotIn("rounds of tool calls", mod.SYSTEM)
        self.assertIn("recent_days", mod.SYSTEM)

    def test_research_tools_narrow_cause_to_the_batch_groups(self):
        """The forecasting run's web_search carries `cause` as a required enum
        of the batch's group keys and the loop's coverage keys are the same
        list; the shared tool definition stays generic and optional."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("ru", REPO / "code" / "run_unified.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        groups = [{"key": "ai", "label": "AI-related incident"},
                  {"key": "crosscutting", "label": "Cross-cutting"}]
        research, keys = mod.research_tools(groups)
        cause = research[0]["parameters"]["properties"]["cause"]
        self.assertEqual(keys, ["ai", "crosscutting"])
        self.assertEqual(cause["enum"], keys)
        self.assertIn("AI-related incident", cause["description"])
        self.assertEqual(research[0]["parameters"]["required"], ["query", "cause"])
        self.assertIs(research[0]["fn"], tools.web_search)
        self.assertEqual(research[1:], tools.FORECAST_TOOLS[1:])
        self.assertNotIn("enum", tools.WEB_SEARCH_TOOL["parameters"]["properties"]["cause"])
        self.assertEqual(tools.WEB_SEARCH_TOOL["parameters"]["required"], ["query"])
        self.assertIn("cause", mod.SYSTEM)
        self.assertEqual(mod.coverage_line([{"evidence": [
            {"tool": "web_search", "args": {"query": "q", "cause": "ai", "recent_days": 30}, "result": {}},
            {"tool": "web_search", "args": {"query": "q", "cause": "bio"}, "result": {}}]}]),
            "coverage ai:1")

    def test_read_page_degrades_without_a_key(self):
        """Same contract as web_search: no key -> an {error} result, never a raise,
        so the loop carries on ungrounded and the runner's TAVILY guard is the
        thing that stops that from being published."""
        saved = os.environ.pop("TAVILY_API_KEY", None)
        try:
            r = tools.read_page("https://example.org/")
        finally:
            if saved is not None:
                os.environ["TAVILY_API_KEY"] = saved
        self.assertIn("error", r)
        self.assertEqual(r["text"], "")

    def test_read_page_windows_a_long_page(self):
        """A page longer than PAGE_CHARS comes back in windows the model can page
        through with `offset`; the loop caps a tool reply at 8000 characters,
        so a window plus its envelope must fit."""
        import json as _json
        import urllib.request as _ur
        long_text = "x" * (tools.PAGE_CHARS * 2 + 10)

        class _Resp:
            def __init__(self, payload):
                self._p = payload
            def read(self):
                return _json.dumps(self._p).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            return _Resp({"results": [{"url": "u", "raw_content": long_text}],
                          "failed_results": []})

        os.environ["TAVILY_API_KEY"] = "t"
        real = _ur.urlopen
        _ur.urlopen = fake_urlopen
        try:
            first = tools.read_page("u")
            second = tools.read_page("u", offset=first["next_offset"])
            last = tools.read_page("u", offset=second["next_offset"])
        finally:
            _ur.urlopen = real
            os.environ.pop("TAVILY_API_KEY", None)
        self.assertEqual(len(first["text"]), tools.PAGE_CHARS)
        self.assertEqual(first["total_chars"], len(long_text))
        self.assertEqual(second["offset"], tools.PAGE_CHARS)
        self.assertNotIn("next_offset", last)
        self.assertEqual(len(_json.dumps(first)), len(_json.dumps(first)))
        self.assertLess(len(_json.dumps(first)), 8000)


class TestLoadKeys(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        for k in llm.PROVIDER_KEYS + ("REDLINES_ENV_FILE",):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def _write(self, text):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "env"
        p.write_text(text)
        os.environ["REDLINES_ENV_FILE"] = str(p)
        return p

    def test_parses_the_shapes_the_shell_accepts(self):
        self._write('# a comment\n\nexport TAVILY_API_KEY=tav-123\n'
                    'OPENAI_API_KEY="oa-456"\nXAI_API_KEY=\'xa-789\'\nJUNK\n')
        got = llm.load_keys()
        self.assertEqual(os.environ["TAVILY_API_KEY"], "tav-123")
        self.assertEqual(os.environ["OPENAI_API_KEY"], "oa-456")
        self.assertEqual(os.environ["XAI_API_KEY"], "xa-789")
        self.assertEqual(got, ["OPENAI_API_KEY", "TAVILY_API_KEY", "XAI_API_KEY"])

    def test_agrees_with_the_shell_on_the_same_file(self):
        """cron_run.sh does `set -a; . "$ENVFILE"` and then runs us; if these two
        parsers disagreed, a key would mean one thing to the cron and another to a
        hand-run of the same command."""
        p = self._write('export TAVILY_API_KEY=tav-123\nOPENAI_API_KEY="oa-456"\n'
                        "XAI_API_KEY='xa-789'\n")
        llm.load_keys()
        r = subprocess.run(
            ["bash", "-c", f'set -a; . "{p}"; set +a; '
                           'echo "$TAVILY_API_KEY|$OPENAI_API_KEY|$XAI_API_KEY"'],
            capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(),
                         "|".join(os.environ[k] for k in
                                  ("TAVILY_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY")))

    def test_environment_beats_the_file(self):
        """cron_run.sh has already sourced the file by the time we run. An
        override on the command line has to survive that."""
        self._write("TAVILY_API_KEY=from-file\n")
        os.environ["TAVILY_API_KEY"] = "from-env"
        llm.load_keys()
        self.assertEqual(os.environ["TAVILY_API_KEY"], "from-env")

    def test_missing_file_is_not_an_error(self):
        """Best-effort by design: a caller that needs a specific key checks for it
        itself (run_unified.py refuses to start without TAVILY_API_KEY)."""
        os.environ["REDLINES_ENV_FILE"] = "/nonexistent/redlines/env"
        self.assertEqual(llm.load_keys(), [])


class TestReasoningLevel(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("REDLINES_REASONING", None)

    def tearDown(self):
        os.environ.pop("REDLINES_REASONING", None)
        if self._saved is not None:
            os.environ["REDLINES_REASONING"] = self._saved

    def test_top_rung_per_provider_family(self):
        self.assertEqual(llm.reasoning_for("anthropic/claude-fable-5"), "max")
        self.assertEqual(llm.reasoning_for("openai/gpt-5.6-sol"), "xhigh")
        self.assertEqual(llm.reasoning_for("gemini/gemini-3.1-pro-preview"), llm.REASONING_DEFAULT)

    def test_override_and_none(self):
        os.environ["REDLINES_REASONING"] = "low"
        self.assertEqual(llm.reasoning_for("anthropic/claude-fable-5"), "low")
        os.environ["REDLINES_REASONING"] = "none"
        self.assertIsNone(llm.reasoning_for("anthropic/claude-fable-5"))

    def test_every_rung_steps_down_to_something(self):
        for r in set(llm.REASONING.values()) | {llm.REASONING_DEFAULT}:
            self.assertIn(r, llm.REASONING_STEP_DOWN)


class TestCallToolsLoop(unittest.TestCase):
    # These tests assert the tools degrade without a key; a developer's
    # exported TAVILY_API_KEY must not turn them into live calls.
    def setUp(self):
        self._saved_key = os.environ.pop("TAVILY_API_KEY", None)

    def tearDown(self):
        if self._saved_key is not None:
            os.environ["TAVILY_API_KEY"] = self._saved_key

    FINAL = {"name": "submit", "description": "submit",
             "parameters": {"type": "object"}}

    def test_tool_call_then_submission(self):
        turns = []

        def fake(model, messages, *, tools_=None, **kw):
            turns.append(list(messages))
            if len(turns) == 1:
                return {"content": "searching",
                        "tool_calls": [{"id": "c1", "name": "web_search",
                                        "arguments": '{"query": "ai risk"}'}]}
            return {"content": "", "tool_calls": [{"id": "c2", "name": "submit",
                                                   "arguments": '{"p": 0.07}'}]}

        def backend(model, messages, **kw):
            return fake(model, messages, **kw)

        ans, ev = llm.call_tools("fake/model", "forecast", tools.FORECAST_TOOLS,
                                 self.FINAL, complete=backend)
        self.assertEqual(ans, {"p": 0.07})
        self.assertEqual([e["tool"] for e in ev], ["web_search"])
        # no TAVILY_API_KEY in the test env -> the tool degrades to an {error}
        # result rather than raising, and the loop carries on ungrounded
        self.assertIn("error", ev[0]["result"])
        # the tool reply must be preceded by an assistant turn carrying tool_calls,
        # or the provider rejects the message list
        second = turns[1]
        self.assertEqual(second[-1]["role"], "tool")
        self.assertTrue(second[-2].get("tool_calls"))

    def test_prose_answer_is_nudged_back_to_the_tool(self):
        replies = [{"content": "I think about 7%.", "tool_calls": []},
                   {"content": "", "tool_calls": [{"id": "c1", "name": "submit",
                                                   "arguments": '{"p": 0.07}'}]}]
        seen = []

        def backend(model, messages, **kw):
            seen.append(list(messages))
            return replies[len(seen) - 1]

        ans, ev = llm.call_tools("fake/model", "forecast", [], self.FINAL,
                                 complete=backend)
        self.assertEqual(ans, {"p": 0.07})
        self.assertEqual(ev, [])
        self.assertIn("Now call submit", seen[1][-1]["content"])

    def test_last_turn_forces_submission(self):
        choices = []

        def backend(model, messages, *, tool_choice=None, **kw):
            choices.append(tool_choice)
            if len(choices) < 3:
                return {"content": "thinking", "tool_calls": []}
            return {"content": "", "tool_calls": [{"id": "c1", "name": "submit",
                                                   "arguments": "{}"}]}

        llm.call_tools("fake/model", "forecast", [], self.FINAL, max_iters=3,
                       complete=backend)
        self.assertEqual(choices[:2], ["auto", "auto"])
        self.assertEqual(choices[2],
                         {"type": "function", "function": {"name": "submit"}})

    def test_research_floor_withholds_submit_until_met(self):
        """With min_evidence=2 the final tool is not in the offered specs until two
        tool calls have returned, a premature submit is refused with a count,
        and the loop returns the answer once the floor is met."""
        offered, n = [], [0]

        def backend(model, messages, *, tools=None, **kw):
            n[0] += 1
            offered.append("submit" in [t["function"]["name"] for t in tools])
            if n[0] == 1:   # tries to submit at once -- refused
                return {"content": "", "tool_calls": [{"id": "s0", "name": "submit", "arguments": '{"p": 0.1}'}]}
            if n[0] == 2:   # two searches in one turn -> floor met
                return {"content": "", "tool_calls": [
                    {"id": "c1", "name": "web_search", "arguments": '{"query": "a"}'},
                    {"id": "c2", "name": "web_search", "arguments": '{"query": "b"}'}]}
            return {"content": "", "tool_calls": [{"id": "s1", "name": "submit", "arguments": '{"p": 0.2}'}]}

        ans, ev = llm.call_tools("fake/model", "forecast", tools.FORECAST_TOOLS, self.FINAL,
                                 complete=backend, min_evidence=2, max_iters=6)
        self.assertEqual(ans, {"p": 0.2})
        self.assertEqual([e["args"]["query"] for e in ev], ["a", "b"])
        self.assertEqual(offered, [False, False, True])

    def test_coverage_withholds_submit_until_every_group_has_a_recent_search(self):
        """With coverage=["ai", "bio"] the final tool stays withheld after the
        floor is met until each group has a recent_days search tagged with it;
        a premature submit is refused naming only the groups still missing,
        and a search without a window (or without a tag) does not count."""
        offered, refusals, n = [], [], [0]

        def backend(model, messages, *, tools=None, **kw):
            n[0] += 1
            offered.append("submit" in [t["function"]["name"] for t in tools])
            if n[0] == 1:   # floor met (2 calls); ai covered; bio searched with no window
                return {"content": "", "tool_calls": [
                    {"id": "c1", "name": "web_search",
                     "arguments": '{"query": "a", "cause": "ai", "recent_days": 30}'},
                    {"id": "c2", "name": "web_search", "arguments": '{"query": "b", "cause": "bio"}'}]}
            if n[0] == 2:   # tries to submit -- refused
                return {"content": "", "tool_calls": [{"id": "s0", "name": "submit", "arguments": '{"p": 0.1}'}]}
            if n[0] == 3:   # sees the refusal, covers bio
                refusals.append(messages[-1]["content"])
                return {"content": "", "tool_calls": [
                    {"id": "c3", "name": "web_search",
                     "arguments": '{"query": "c", "cause": "bio", "recent_days": 30}'}]}
            return {"content": "", "tool_calls": [{"id": "s1", "name": "submit", "arguments": '{"p": 0.2}'}]}

        ans, ev = llm.call_tools("fake/model", "forecast", tools.FORECAST_TOOLS, self.FINAL,
                                 complete=backend, min_evidence=2, max_iters=8,
                                 coverage=["ai", "bio"])
        self.assertEqual(ans, {"p": 0.2})
        self.assertEqual(offered, [False, False, False, True])
        self.assertEqual(len(refusals), 1)
        self.assertIn("bio", refusals[0])
        self.assertNotIn("ai", refusals[0].split("needed for:")[1])
        self.assertNotIn("more research call", refusals[0])   # the floor was met
        self.assertEqual(llm.research_coverage(ev), {"ai": 1, "bio": 1})

    def test_coverage_prose_nudge_names_the_missing_groups(self):
        seen = []

        def backend(model, messages, *, tools=None, **kw):
            seen.append(messages[-1]["content"])
            if len(seen) == 1:
                return {"content": "thinking out loud", "tool_calls": []}
            return {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": "{}"}]}

        llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                       min_evidence=0, max_iters=2, coverage=["cyber"])
        self.assertIn("recent_days on each of: cyber", seen[1])

    def test_coverage_still_forces_submission_on_the_last_turn(self):
        """The turn guard wins over the coverage rule, and the log says what
        went uncovered."""
        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            if "submit" in [t["function"]["name"] for t in tools]:
                return {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": "{}"}]}
            return {"content": "hm", "tool_calls": []}

        with contextlib.redirect_stderr(io.StringIO()) as err:
            ans, ev = llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                                     min_evidence=0, max_iters=3, coverage=["ai", "bio"])
        self.assertEqual(ans, {})
        self.assertIn("WARN", err.getvalue())
        self.assertIn("ai, bio", err.getvalue())

    def test_web_search_echoes_cause_and_never_sends_it(self):
        self.assertNotIn("cause", tools.search_body("q", recent_days=7))
        out = tools.web_search("q", recent_days=7, cause="bio")   # no key: an {error} result
        self.assertEqual(out["cause"], "bio")
        self.assertIn("error", out)
        self.assertNotIn("cause", tools.web_search("q"))

    def test_fable_submission_guard_keeps_context_without_forced_tool_choice(self):
        seen = []
        usage = {}

        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            seen.append((list(messages), tools, tool_choice))
            if len(seen) == 1:
                return {"content": "", "tool_calls": [{"id": "r", "name": "research",
                                                        "arguments": "{}"}]}
            self.assertEqual(tool_choice, "auto")
            self.assertEqual([t["function"]["name"] for t in tools], ["submit"])
            return {"content": "", "tool_calls": [{"id": "s", "name": "submit",
                                                    "arguments": '{"p": 0.2}'}]}

        ans, evidence = llm.call_tools(
            "anthropic/claude-fable-5-1", "forecast",
            [{"name": "research", "parameters": {"type": "object"},
              "fn": lambda: {"fact": "retained"}}], self.FINAL,
            complete=backend, max_iters=2, usage=usage)
        self.assertEqual(ans, {"p": 0.2})
        self.assertEqual(evidence[0]["result"], {"fact": "retained"})
        self.assertEqual(seen[-1][0][-2]["role"], "tool")
        self.assertIn("Now call submit", seen[-1][0][-1]["content"])
        self.assertEqual(usage["submission_guard"], "auto-final-tool-only")

    def test_the_claude_5_5_models_never_get_a_forced_tool_choice(self):
        """Probed 2026-10-01: Opus 5.5 and Sonnet 5.5 refuse it, Opus 5 does not."""
        for m in ("anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5",
                  "anthropic/claude-fable-5-1"):
            self.assertTrue(llm.refuses_forced_tool_choice(m), m)
        self.assertFalse(llm.refuses_forced_tool_choice("anthropic/claude-opus-5"))

    def test_an_unknown_refusal_is_learned_and_the_call_still_submits(self):
        """A model nobody probed refuses the forced turn: the loop redoes that
        turn the Fable 5.1 way (final tool only, asked in words) instead of
        raising, WARNs, and remembers the model for the process."""
        model = "anthropic/claude-test-refuses-force"
        llm._NO_FORCE_LEARNED.discard(model)
        seen = []

        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            seen.append(tool_choice)
            if isinstance(tool_choice, dict):
                raise RuntimeError('AnthropicException - tool_choice: type "tool" and "any" '
                                   'are not supported for this model.')
            if any(isinstance(c, dict) for c in seen):   # only after the refused forced turn
                self.assertEqual([t["function"]["name"] for t in tools], ["submit"])
                return {"content": "", "tool_calls": [{"id": "s", "name": "submit",
                                                        "arguments": '{"p": 0.3}'}]}
            return {"content": "still reading", "tool_calls": []}

        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                ans, _ = llm.call_tools(model, "forecast", [], self.FINAL, complete=backend,
                                        min_evidence=0, max_iters=2)
            self.assertEqual(ans, {"p": 0.3})
            self.assertIn("refuses a forced tool_choice", err.getvalue())
            self.assertTrue(llm.refuses_forced_tool_choice(model))
            self.assertEqual(seen[-1], "auto")
        finally:
            llm._NO_FORCE_LEARNED.discard(model)

    def test_any_other_error_on_the_forced_turn_still_raises(self):
        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            raise RuntimeError("overloaded")
        with self.assertRaises(RuntimeError):
            llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                           min_evidence=0, max_iters=1)
        self.assertFalse(llm.refuses_forced_tool_choice("fake/model"))

    DEBRIEF = {"name": "submit_debrief", "description": "debrief",
               "parameters": {"type": "object"}}

    def test_debrief_turn_follows_the_accepted_submission(self):
        seen, usage = [], {}

        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            seen.append((list(messages), [t["function"]["name"] for t in tools], tool_choice))
            if len(seen) == 1:
                return {"content": "", "usage": {"cost_usd": 1.0},
                        "tool_calls": [{"id": "s", "name": "submit", "arguments": '{"p": 0.2}'}]}
            return {"content": "", "usage": {"cost_usd": 0.5},
                    "tool_calls": [{"id": "d", "name": "submit_debrief",
                                    "arguments": '{"ai": {"pathway": "x"}}'}]}

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.",
                 "validate": lambda args: [] if "ai" in args else ["ai: missing"]}
        ans, ev = llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                                 usage=usage, debrief=state)
        self.assertEqual(ans, {"p": 0.2})
        self.assertEqual(state["result"], {"ai": {"pathway": "x"}})
        self.assertTrue(state["complete"])
        self.assertEqual(state["attempts"], 1)
        # the debrief request: only the debrief tool, forced; preceded by the
        # submission's tool result and the debrief prompt
        msgs, names, choice = seen[1]
        self.assertEqual(names, ["submit_debrief"])
        self.assertEqual(choice["function"]["name"], "submit_debrief")
        self.assertEqual(msgs[-1], {"role": "user", "content": "Now the debrief."})
        self.assertEqual(msgs[-2]["role"], "tool")
        self.assertIn("accepted", msgs[-2]["content"])
        # its cost is part of the call's
        self.assertEqual(usage["cost_usd"], 1.5)
        self.assertEqual(usage["turns"], 2)

    def test_debrief_problems_are_returned_and_retried_once(self):
        replies = [
            {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": '{"p": 0.2}'}]},
            {"content": "", "tool_calls": [{"id": "d1", "name": "submit_debrief", "arguments": '{}'}]},
            {"content": "", "tool_calls": [{"id": "d2", "name": "submit_debrief",
                                            "arguments": '{"ai": {"pathway": "x"}}'}]},
        ]
        seen = []

        def backend(model, messages, **kw):
            seen.append(list(messages))
            return replies[len(seen) - 1]

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.",
                 "validate": lambda args: [] if "ai" in args else ["ai: missing"]}
        ans, ev = llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                                 debrief=state)
        self.assertEqual(ans, {"p": 0.2})
        self.assertTrue(state["complete"])
        self.assertEqual(state["attempts"], 2)
        self.assertEqual(state["problems"], [])
        # the retry saw the problems as the tool result, then a user nudge
        third = seen[2]
        self.assertEqual(third[-2]["role"], "tool")
        self.assertIn("ai: missing", third[-2]["content"])
        self.assertIn("fixing: ai: missing", third[-1]["content"])

    def test_debrief_that_keeps_failing_is_recorded_not_raised(self):
        replies = [
            {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": '{"p": 0.2}'}]},
            {"content": "", "tool_calls": [{"id": "d1", "name": "submit_debrief", "arguments": '{}'}]},
            {"content": "", "tool_calls": [{"id": "d2", "name": "submit_debrief", "arguments": '{}'}]},
        ]
        n = [0]

        def backend(model, messages, **kw):
            n[0] += 1
            return replies[n[0] - 1]

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.",
                 "validate": lambda args: ["ai: missing"]}
        ans, ev = llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                                 debrief=state)
        self.assertEqual(ans, {"p": 0.2})
        self.assertFalse(state["complete"])
        self.assertEqual(state["attempts"], 2)
        self.assertEqual(state["result"], {})
        self.assertEqual(state["problems"], ["ai: missing"])
        self.assertEqual(n[0], 3)

    def test_debrief_backend_error_never_loses_the_forecast(self):
        def backend(model, messages, *, tools=None, **kw):
            if [t["function"]["name"] for t in tools] == ["submit_debrief"]:
                raise RuntimeError("provider down")
            return {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": '{"p": 0.2}'}]}

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief."}
        ans, ev = llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                                 debrief=state)
        self.assertEqual(ans, {"p": 0.2})
        self.assertFalse(state["complete"])
        self.assertIn("provider down", state["error"])

    def test_fable_debrief_is_offered_not_forced(self):
        choices = []

        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            choices.append(tool_choice)
            if len(choices) == 1:
                return {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": '{"p": 0.2}'}]}
            return {"content": "", "tool_calls": [{"id": "d", "name": "submit_debrief", "arguments": '{"ai": {}}'}]}

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief."}
        llm.call_tools("anthropic/claude-fable-5-1", "forecast", [], self.FINAL,
                       complete=backend, max_iters=1, debrief=state)
        self.assertEqual(choices[-1], "auto")
        self.assertTrue(state["complete"])

    def test_submission_failure_retains_diagnostic_usage_and_conversation(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REDLINES_TRACE_DIR": directory}):
            def backend(*args, **kw):
                return {"content": "unfinished", "tool_calls": [],
                        "usage": {"cost_usd": 0.25, "output_tokens": 10}}
            with self.assertRaises(RuntimeError):
                llm.call_tools("anthropic/claude-fable-5-1", "forecast", [],
                               self.FINAL, complete=backend, max_iters=1, usage={})
            paths = list(Path(directory).glob('*.json'))
            self.assertEqual(len(paths), 1)
            state = json.loads(paths[0].read_text())
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['usage']['cost_usd'], 0.75)
            self.assertEqual(state['usage']['turns'], 3)
            self.assertEqual(sum(m['role'] == 'assistant' for m in state['messages']), 3)
            self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)

    def test_research_floor_still_forces_submission_on_the_last_turn(self):
        choices = []

        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            choices.append((tool_choice, "submit" in [t["function"]["name"] for t in tools]))
            if len(choices) < 3:
                return {"content": "hm", "tool_calls": []}
            return {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": "{}"}]}

        llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend,
                       min_evidence=99, max_iters=3)
        self.assertEqual([o for _, o in choices], [False, False, True])
        self.assertEqual(choices[-1][0], {"type": "function", "function": {"name": "submit"}})

    def test_thinking_blocks_ride_on_the_assistant_turn(self):
        """Anthropic requires the signed thinking block back on the assistant turn
        that a tool result follows; the loop carries whatever the backend
        returned, and nothing when there is none."""
        seen = []

        def backend(model, messages, **kw):
            seen.append(list(messages))
            if len(seen) == 1:
                return {"content": "", "thinking_blocks": [{"type": "thinking", "thinking": "t", "signature": "s"}],
                        "tool_calls": [{"id": "c1", "name": "web_search", "arguments": '{"query": "q"}'}]}
            return {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": "{}"}]}

        llm.call_tools("fake/model", "forecast", tools.FORECAST_TOOLS, self.FINAL, complete=backend)
        asst = [m for m in seen[1] if m["role"] == "assistant"][0]
        self.assertEqual(asst["thinking_blocks"][0]["signature"], "s")

    def test_usage_is_tallied_across_turns_and_retries(self):
        """The caller's dict accumulates every turn's tokens and price; an
        unpriced turn is counted, not silently zero."""
        n = [0]

        def backend(model, messages, **kw):
            n[0] += 1
            usage = {"input_tokens": 100, "output_tokens": 10, "cost_usd": 0.01 if n[0] == 1 else None}
            if n[0] == 1:
                return {"content": "", "usage": usage,
                        "tool_calls": [{"id": "c1", "name": "web_search", "arguments": '{"query": "q"}'}]}
            return {"content": "", "usage": usage,
                    "tool_calls": [{"id": "s", "name": "submit", "arguments": "{}"}]}

        total = {}
        llm.call_tools("fake/model", "forecast", tools.FORECAST_TOOLS, self.FINAL,
                       complete=backend, usage=total)
        llm.call_tools("fake/model", "forecast", tools.FORECAST_TOOLS, self.FINAL,
                       complete=backend, usage=total)   # a retry keeps counting
        # call 1: search (priced) + submit (unpriced); call 2: submit (unpriced)
        self.assertEqual(total["turns"], 3)
        self.assertEqual(total["input_tokens"], 300)
        self.assertEqual(total["cost_usd"], 0.01)
        self.assertEqual(total["unpriced_turns"], 2)

    def test_never_submitting_raises(self):
        def backend(model, messages, **kw):
            return {"content": "no", "tool_calls": []}

        with self.assertRaises(RuntimeError):
            llm.call_tools("fake/model", "forecast", [], self.FINAL, max_iters=2,
                           complete=backend)


if __name__ == "__main__":
    unittest.main()


class TestPiecewiseDelivery(unittest.TestCase):
    """call_tools partial_tool (2026-09-02 evening): the answer may arrive in
    pieces through a tool that is offered with the final one, served by the
    caller's fn, and never counted as research."""

    def _tools(self):
        seen = []
        research = [{"name": "web_search", "description": "", "parameters": {"type": "object"},
                     "fn": lambda **a: {"results": [1]}}]
        pieces = []
        partial = {"name": "submit_cells", "description": "", "parameters": {"type": "object"},
                   "fn": lambda forecasts=None, **_: (pieces.append(forecasts) or {"received": len(pieces)})}
        final = {"name": "submit_forecast", "description": "", "parameters": {"type": "object"}}
        return research, partial, final, pieces, seen

    def test_pieces_are_kept_not_counted_and_offered_with_the_final(self):
        research, partial, final, pieces, seen = self._tools()
        turns = iter([
            # turn 1: research (floor 1)
            {"content": "", "tool_calls": [{"id": "a", "name": "web_search", "arguments": "{}"}]},
            # turn 2: two pieces
            {"content": "", "tool_calls": [{"id": "b", "name": "submit_cells", "arguments": '{"forecasts": [1, 2]}'},
                                           {"id": "c", "name": "submit_cells", "arguments": '{"forecasts": [3]}'}]},
            # turn 3: the final
            {"content": "", "tool_calls": [{"id": "d", "name": "submit_forecast", "arguments": '{"rationale": "r"}'}]},
        ])

        def complete(model, messages, tools=None, tool_choice=None, **kw):
            seen.append([t["function"]["name"] for t in tools])
            return next(turns)

        answer, evidence = llm.call_tools("m", "p", research, final, complete=complete,
                                          max_iters=6, min_evidence=1, partial_tool=partial)
        self.assertEqual(answer, {"rationale": "r"})
        self.assertEqual(pieces, [[1, 2], [3]])
        self.assertEqual([e["tool"] for e in evidence], ["web_search"])   # pieces are not evidence
        self.assertEqual(seen[0], ["web_search"])                          # under the floor: research only
        self.assertEqual(seen[1], ["web_search", "submit_cells", "submit_forecast"])

    def test_a_piece_under_the_floor_is_refused(self):
        research, partial, final, pieces, seen = self._tools()
        turns = iter([
            {"content": "", "tool_calls": [{"id": "a", "name": "submit_cells", "arguments": '{"forecasts": [1]}'}]},
            {"content": "", "tool_calls": [{"id": "b", "name": "web_search", "arguments": "{}"}]},
            {"content": "", "tool_calls": [{"id": "c", "name": "submit_forecast", "arguments": '{"rationale": "r"}'}]},
        ])
        replies = []

        def complete(model, messages, tools=None, tool_choice=None, **kw):
            replies.append([m for m in messages if m.get("role") == "tool"])
            return next(turns)

        llm.call_tools("m", "p", research, final, complete=complete, max_iters=6, min_evidence=1,
                       partial_tool=partial)
        self.assertEqual(pieces, [])
        self.assertIn("not offered yet", replies[1][0]["content"])


class TestThinkingBudget(unittest.TestCase):
    def test_no_explicit_budget_by_default_max_is_adaptive(self):
        # Probed 2026-09-02: for the Claude 5 family litellm sends
        # reasoning_effort="max" as adaptive thinking + output_config.effort
        # "max" -- Anthropic's own top setting -- so no budget is sent unless
        # an experiment asks for one.
        os.environ.pop("REDLINES_THINKING_BUDGET", None)
        os.environ.pop("REDLINES_REASONING", None)
        self.assertEqual(llm.THINKING_BUDGET, {})
        self.assertIsNone(llm.thinking_budget_for("anthropic/claude-fable-5", 64000))
        self.assertIsNone(llm.thinking_budget_for("openai/gpt-5.6-sol", 64000))
        self.assertEqual(llm.reasoning_for("anthropic/claude-fable-5"), "max")

    def test_explicit_budget_is_an_opt_in_kept_under_the_cap(self):
        os.environ.pop("REDLINES_REASONING", None)
        os.environ["REDLINES_THINKING_BUDGET"] = "48000"
        try:
            self.assertEqual(llm.thinking_budget_for("anthropic/claude-fable-5", 64000), 48000)
            self.assertEqual(llm.thinking_budget_for("anthropic/claude-fable-5", 32000), 16000)   # cap - headroom
            os.environ["REDLINES_REASONING"] = "none"
            self.assertIsNone(llm.thinking_budget_for("anthropic/claude-fable-5", 64000))
        finally:
            del os.environ["REDLINES_THINKING_BUDGET"]
            os.environ.pop("REDLINES_REASONING", None)


class TestPromptCache(unittest.TestCase):
    """Claude calls mark the last message for Anthropic's prompt cache
    (2026-10-06); the conversation itself is never edited, and a turn's
    cache writes are recorded beside its reads."""

    def setUp(self):
        self._saved = os.environ.pop("REDLINES_PROMPT_CACHE", None)

    def tearDown(self):
        os.environ.pop("REDLINES_PROMPT_CACHE", None)
        if self._saved is not None:
            os.environ["REDLINES_PROMPT_CACHE"] = self._saved

    def test_anthropic_only_five_minutes_by_default(self):
        self.assertEqual(llm.prompt_cache_for("anthropic/claude-sonnet-5-5"),
                         {"type": "ephemeral", "ttl": "5m"})
        self.assertIsNone(llm.prompt_cache_for("openai/responses/gpt-6-astra"))
        self.assertIsNone(llm.prompt_cache_for("openrouter/anthropic/claude-opus-5-5"))

    def test_override_and_off(self):
        os.environ["REDLINES_PROMPT_CACHE"] = "1h"
        self.assertEqual(llm.prompt_cache_for("anthropic/claude-opus-5-5")["ttl"], "1h")
        os.environ["REDLINES_PROMPT_CACHE"] = "off"
        self.assertIsNone(llm.prompt_cache_for("anthropic/claude-opus-5-5"))
        os.environ["REDLINES_PROMPT_CACHE"] = "10m"
        with self.assertRaises(ValueError):
            llm.prompt_cache_for("anthropic/claude-opus-5-5")

    def _complete(self, model, messages):
        """_litellm_complete against a stand-in litellm; returns (sent kwargs, result)."""
        from types import SimpleNamespace as NS
        from unittest import mock
        sent = []

        def completion(**kw):
            sent.append(kw)
            usage = NS(prompt_tokens=320100, completion_tokens=1000,
                       completion_tokens_details=None,
                       prompt_tokens_details=NS(cached_tokens=300000),
                       cache_creation_input_tokens=20000)
            msg = NS(content="ok", tool_calls=None)
            return NS(choices=[NS(message=msg)], usage=usage)

        fake = NS(BadRequestError=type("BadRequestError", (Exception,), {}),
                  APIConnectionError=type("APIConnectionError", (Exception,), {}),
                  completion=completion, completion_cost=lambda completion_response: 0.12)
        with mock.patch.dict(sys.modules, {"litellm": fake}):
            out = llm._litellm_complete(model, messages)
        return sent[-1], out

    def test_claude_requests_mark_the_last_message_and_leave_history_alone(self):
        messages = [{"role": "user", "content": "forecast"},
                    {"role": "tool", "tool_call_id": "c1", "content": "{}"}]
        before = json.dumps(messages)
        kw, out = self._complete("anthropic/claude-sonnet-5-5", messages)
        self.assertEqual(kw["cache_control_injection_points"],
                         [{"location": "message", "index": -1,
                           "control": {"type": "ephemeral", "ttl": "5m"}}])
        self.assertEqual(json.dumps(messages), before)
        self.assertEqual(out["usage"]["cached_tokens"], 300000)
        self.assertEqual(out["usage"]["cache_write_tokens"], 20000)
        kw, _ = self._complete("openai/responses/gpt-6-astra", messages)
        self.assertNotIn("cache_control_injection_points", kw)

    def test_cache_writes_are_tallied(self):
        total = {}
        for _ in range(2):
            llm.tally_usage(total, {"input_tokens": 10, "cached_tokens": 6,
                                    "cache_write_tokens": 3, "cost_usd": 0.01})
        self.assertEqual((total["cached_tokens"], total["cache_write_tokens"]), (12, 6))


class DebriefTurn2026_09_16(unittest.TestCase):
    """The debrief turn since 2026-09-16: deliveries merge across attempts, a
    stringified entry is parsed, an empty reply gets one text-only ask, and
    the debrief may set its own output cap."""
    FINAL = {"name": "submit", "description": "final", "parameters": {"type": "object"}}
    DEBRIEF = {"name": "submit_debrief", "description": "debrief", "parameters": {"type": "object"}}
    SUBMIT = {"content": "", "tool_calls": [{"id": "s", "name": "submit", "arguments": '{"p": 0.2}'}]}

    @staticmethod
    def _validate(args):
        return [f"{k}: missing" for k in ("q1", "q2") if not isinstance(args.get(k), dict)]

    def test_deliveries_merge_across_attempts(self):
        replies = [self.SUBMIT,
                   {"content": "", "tool_calls": [{"id": "d1", "name": "submit_debrief",
                                                   "arguments": '{"q1": {"rationale": "a"}}'}]},
                   {"content": "", "tool_calls": [{"id": "d2", "name": "submit_debrief",
                                                   "arguments": '{"q2": {"rationale": "b"}}'}]}]
        seen = []

        def backend(model, messages, **kw):
            seen.append((list(messages), kw))
            return replies[len(seen) - 1]

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.", "validate": self._validate,
                 "retries": 2, "max_tokens": 48000}
        llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend, debrief=state)
        self.assertTrue(state["complete"])
        self.assertEqual(state["result"], {"q1": {"rationale": "a"}, "q2": {"rationale": "b"}})
        self.assertEqual(state["attempts"], 2)
        # the retry named what was missing and promised to keep what arrived
        self.assertIn("q2: missing", seen[2][0][-1]["content"])
        self.assertIn("already sent are kept", seen[2][0][-1]["content"])
        # the debrief's own cap reached the backend
        self.assertEqual(seen[1][1]["max_tokens"], 48000)

    def test_two_calls_in_one_turn_both_count(self):
        replies = [self.SUBMIT,
                   {"content": "", "tool_calls": [
                       {"id": "d1", "name": "submit_debrief", "arguments": '{"q1": {"rationale": "a"}}'},
                       {"id": "d2", "name": "submit_debrief", "arguments": '{"q2": {"rationale": "b"}}'}]}]
        n = [0]

        def backend(model, messages, **kw):
            n[0] += 1
            return replies[n[0] - 1]

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.", "validate": self._validate}
        llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend, debrief=state)
        self.assertTrue(state["complete"])
        self.assertEqual(sorted(state["result"]), ["q1", "q2"])

    def test_stringified_entries_are_parsed(self):
        replies = [self.SUBMIT,
                   {"content": "", "tool_calls": [{"id": "d1", "name": "submit_debrief",
                                                   "arguments": json.dumps({"q1": '{"rationale": "a"}',
                                                                            "q2": {"rationale": "b"}})}]}]
        n = [0]

        def backend(model, messages, **kw):
            n[0] += 1
            return replies[n[0] - 1]

        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.", "validate": self._validate}
        llm.call_tools("fake/model", "forecast", [], self.FINAL, complete=backend, debrief=state)
        self.assertTrue(state["complete"])
        self.assertEqual(state["result"]["q1"], {"rationale": "a"})

    def test_empty_reply_gets_one_text_ask(self):
        replies = [self.SUBMIT,
                   {"content": "", "tool_calls": [], "usage": {"cost_usd": 1.0, "output_tokens": 0}},
                   {"content": 'Here it is:\n```json\n{"q1": {"rationale": "a"}, "q2": {"rationale": "b"}}\n```',
                    "usage": {"cost_usd": 0.5}}]
        seen = []

        def backend(model, messages, *, tools=None, tool_choice=None, **kw):
            seen.append((list(messages), tools))
            return replies[len(seen) - 1]

        usage = {}
        state = {"tool": self.DEBRIEF, "prompt": "Now the debrief.", "validate": self._validate}
        llm.call_tools("anthropic/claude-fable-5-1", "forecast", [], self.FINAL, complete=backend,
                       max_iters=1, usage=usage, debrief=state)
        self.assertTrue(state["complete"])
        self.assertEqual(state["delivery"], "text")
        self.assertEqual(state["result"]["q2"], {"rationale": "b"})
        # the text ask carried no tools and its cost is counted
        self.assertIsNone(seen[2][1])
        self.assertIn("nothing else", seen[2][0][-1]["content"])
        self.assertEqual(usage["cost_usd"], 1.5)

    def test_json_object_in_text(self):
        self.assertEqual(llm._json_object_in('x {"a": 1} y'), {"a": 1})
        self.assertIsNone(llm._json_object_in("no object here"))
        self.assertIsNone(llm._json_object_in("[1, 2]"))
        self.assertEqual(llm._parse_stringified({"a": '{"b": 1}', "c": "text", "d": 2}),
                         {"a": {"b": 1}, "c": "text", "d": 2})
