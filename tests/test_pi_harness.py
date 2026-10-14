"""code/run_unified.py --harness pi: the joint instrument through the FRI
Forecaster loop (forecastingresearch/agent-box), driven end to end through the
real pi by a scripted model on a local OpenAI-compatible server. No network,
no spend. Needs the fri_forecaster package, node and pi 0.99.2; skipped
without them (AIRO's core and CI never need them)."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from fri_forecaster import harness
except ImportError:
    harness = None


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_unified", REPO / "code" / "run_unified.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ru = _load_runner()

# Research without the network; the debrief validator runs as the real
# tool_cli runs it (AIRO's validate_debrief_ids, loaded from run_unified.py).
FAKE_TOOL_CLI = textwrap.dedent("""\
    import json, sys
    tool = sys.argv[1]
    if tool == "validate":
        from fri_forecaster.tool_cli import validate
        print(json.dumps(validate(**json.load(sys.stdin))))
    else:
        print(json.dumps({"results": [{"url": "https://example.org/a", "title": "t", "content": "c"}]}
                         if tool == "web_search" else {"url": "https://example.org/a", "text": "page"}))
    """)


class ScriptedModel:
    """An OpenAI chat-completions endpoint playing a script: one tool call per
    turn, then a closing text. Keeps every request."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        model = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                model.requests.append(body)
                n = len(model.requests)
                turn = model.script[n - 1] if n <= len(model.script) else "done"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                base = {"id": f"c{n}", "object": "chat.completion.chunk", "created": 0, "model": "scripted"}
                if isinstance(turn, str):
                    delta, finish = {"role": "assistant", "content": turn}, "stop"
                else:
                    delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{n}", "type": "function",
                             "function": {"name": turn[0], "arguments": json.dumps(turn[1])}}]}
                    finish = "tool_calls"
                for chunk in (dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
                              dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": finish}]),
                              dict(base, choices=[], usage={"prompt_tokens": 10, "completion_tokens": 5,
                                                            "total_tokens": 15})):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def tool_result(self, n):
        """The tool result the model saw at the start of request n (1-based)."""
        msg = [m for m in self.requests[n - 1]["messages"] if m.get("role") == "tool"][-1]
        c = msg["content"]
        return c if isinstance(c, str) else "".join(p.get("text", "") for p in c)

    def close(self):
        self.server.shutdown()


class TestPiModelIds(unittest.TestCase):
    def test_openai_responses_route_is_dropped(self):
        self.assertEqual(ru.pi_model("openai/responses/gpt-6-astra"), "openai/gpt-6-astra")
        self.assertEqual(ru.pi_model("anthropic/claude-opus-5-5"), "anthropic/claude-opus-5-5")

    def test_harness_choices(self):
        self.assertEqual(ru.DEFAULT_HARNESS, "litellm")
        self.assertIn("pi", ru.HARNESSES)


@unittest.skipUnless(harness and harness.DEFAULT_PI and shutil.which("node"),
                     "needs fri_forecaster, node and pi (agent-box: npm ci)")
class TestJointThroughPi(unittest.TestCase):
    """The combined instrument, one call, through the real pi."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        cli = os.path.join(d, "tool_cli.py")
        open(cli, "w").write(FAKE_TOOL_CLI)
        self.real_cli, harness.TOOL_CLI = harness.TOOL_CLI, cli
        self.real_workdir, ru.PI_WORKDIR = ru.PI_WORKDIR, os.path.join(d, "traces")
        self.env = {k: os.environ.get(k) for k in ("PI_CODING_AGENT_DIR", "PI_OFFLINE", "PI_TELEMETRY",
                                                     "PYTHONPATH")}
        os.environ.update(PI_CODING_AGENT_DIR=os.path.join(d, "agent"), PI_OFFLINE="1", PI_TELEMETRY="0",
                          PYTHONPATH=os.pathsep.join(filter(None, [os.path.dirname(os.path.dirname(
                              harness.__file__)), os.environ.get("PYTHONPATH")])))
        os.makedirs(os.environ["PI_CODING_AGENT_DIR"])

    def tearDown(self):
        harness.TOOL_CLI = self.real_cli
        ru.PI_WORKDIR = self.real_workdir
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _instrument(self):
        today = date(2026, 10, 14)
        policies = ru.resolve_set(ru.load_policies(ru.COMBINED), today)
        groups, by_group, horizons, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
        horizons = ru.set_horizons(policies, horizons)
        return today, policies, groups, by_group, horizons, spec

    def _script(self, groups, by_group, horizons, cond_ids):
        keys = [g["key"] for g in groups]
        cells = [{"question_id": q["id"], "horizon": h,
                  "probabilities": {k: 0.01 for k in [ru.UNCONDITIONAL_KEY] + cond_ids}}
                 for g in groups for q in by_group[g["key"]] for h in horizons if h in q["horizons"]]
        eci = {"p10": 168, "p25": 170, "p50": 172, "p75": 175, "p90": 178}
        debrief = {ru.debrief_key(q["id"]): {
            "rationale": "Base rates from the historical record, adjusted for current capabilities "
                         "and the incident reports read in this call.",
            "key_sources": [{"url": "https://example.org/a", "contribution": "base rate"}],
            "weakest_link": "That the historical base rate still applies."}
            for g in groups for q in by_group[g["key"]]}
        research = [("web_search", {"query": f"recent {k}", "cause": k, "recent_days": 30}) for k in keys]
        research += [("read_page", {"url": "https://example.org/a"})] * (ru.MIN_RESEARCH - len(keys))
        return research + [
            # The 2026-10-14 failure: a final answer with no cells. Refused once.
            ("submit_forecast", {"eci_forecast": eci, "rationale": "r"}),
            ("submit_cells", {"forecasts": cells[:100]}),
            ("submit_forecast", {"eci_forecast": eci, "rationale": "r", "key_sources": ["https://example.org/a"],
                                 "forecasts": cells[100:]}),
            ("submit_debrief", debrief),
        ], len(cells)

    def test_full_instrument(self):
        today, policies, groups, by_group, horizons, spec = self._instrument()
        conds = policies["conditions"]
        cond_ids = [c["id"] for c in conds]
        script, n_cells = self._script(groups, by_group, horizons, cond_ids)
        model = ScriptedModel(script)
        self.addCleanup(model.close)
        json.dump({"providers": {"fake": {"baseUrl": model.url, "api": "openai-completions", "apiKey": "x",
                                          "models": [{"id": "scripted"}]}}},
                  open(os.path.join(os.environ["PI_CODING_AGENT_DIR"], "models.json"), "w"))
        os.environ["REDLINES_REASONING"] = "none"
        try:
            rows = ru.run_one_joint("Scripted", "fake/scripted", groups, by_group, horizons, "2026-10-14T0000Z",
                                    0, spec, conds, policies, experiment="test", arm="joint#1",
                                    today=today, harness="pi")
        finally:
            os.environ.pop("REDLINES_REASONING", None)
        refused = model.tool_result(len(ru.research_tools(groups)[1]) + (ru.MIN_RESEARCH - len(groups)) + 2)
        self.assertIn("missing_keys", refused)
        first = rows[0]
        self.assertEqual(first["attempts"], 1)
        self.assertEqual(first["harness"]["name"], "pi")
        self.assertEqual(first["harness"]["pi"], harness.PINNED_PI_VERSION)
        self.assertEqual(first["usage"]["harness"], "pi")
        self.assertEqual(first["delivery"]["cells_in_pieces"], 100)
        self.assertEqual(first["delivery"]["cells_in_final"], n_cells - 100)
        answered = [r for r in rows if r["forecasts"]]
        self.assertEqual(len(answered), len(rows))
        self.assertEqual(len(rows), (len(cond_ids) + 1) * sum(len(v) for v in by_group.values()))
        self.assertTrue(first["debrief_status"]["complete"], first["debrief_status"])
        self.assertEqual(first["elicited"]["eci_forecast"]["p50"], 172)
        self.assertEqual(len([e for e in first["evidence"] if e["tool"] == "web_search"]), len(groups))
        self.assertTrue(os.path.exists(first["harness"]["trace"]))


class TestEmptyCallFails(unittest.TestCase):
    """A call with no forecasts after every attempt raises instead of writing
    rows of nulls that the runner logged as done (2026-10-14)."""

    def test_raises(self):
        orig = ru.call_tools
        ru.call_tools = lambda *a, **k: ({"rationale": "r", "eci_forecast": {
            "p10": 1, "p25": 2, "p50": 3, "p75": 4, "p90": 5}}, [])
        try:
            today = date(2026, 10, 14)
            policies = ru.resolve_set(ru.load_policies(ru.COMBINED), today)
            groups, by_group, horizons, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
            with self.assertRaisesRegex(RuntimeError, "no forecasts"):
                ru.run_one_joint("X", "anthropic/x", groups, by_group, ru.set_horizons(policies, horizons),
                                 "r", 0, spec, policies["conditions"], policies, today=today)
        finally:
            ru.call_tools = orig


if __name__ == "__main__":
    unittest.main()
