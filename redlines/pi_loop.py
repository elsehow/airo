"""The same call as redlines.llm.call_tools, with pi as the loop: the
published loop since combined-v9 (2026-10-16), whose condition set names it
(`"harness": "pi"`; code/run_unified.py set_harness).

Under pi, run_unified swaps this in for call_tools and changes nothing else: the prompt, the tools and their schemas, the research floor, the
coverage rule, the turn limit, the debrief and its validator, the cell
cleaning and the rows are the instrument's own. The loop is FRI's agent-box
(github.com/forecastingresearch/agent-box, the `fri_forecaster` package):
pi drives the model, and its extension enforces the rules above with the
loop options that mirror call_tools (agent-box README, "How it works").

So the loop is the only difference between v8 and v9. A run through the loop
a set does not name (`--harness litellm` on v9, the cron's shadow) carries
protocol "<protocol>+<harness>" and may only be written as an experiment
(run_unified refuses otherwise): it never pools with the series.

Where the loops differ, by design of pi rather than of the instrument:
  * pi cannot force a tool choice, so the last turn ASKS for submit_forecast
    and offers nothing else, for every model -- the path call_tools takes
    for models that refuse a forced choice (Opus 5.5, Sonnet 5.5), not the
    forced one it takes for OpenAI's;
  * the output cap per turn is pi's for the model, not max_tokens;
  * the debrief's text-only fallback (a model that returns nothing to the
    tool-only turn) is not ported.

Needs `pip install -e '.[pi]'` (or agent-box itself) and pi 0.99.2:
FORECASTER_PI names its cli.js unless agent-box's own `npm ci` put it in place.
"""
import json
import os
import tempfile
import time

from .llm import reasoning_for

# A whole call, research and debrief included; REDLINES_LLM_TIMEOUT is per
# request on the litellm path, which has no single process to time out.
DEFAULT_TIMEOUT = 3 * 3600


def pi_model(model):
    """litellm's id -> pi's: litellm routes OpenAI's Responses API by a path
    segment; pi picks the API itself."""
    return model.replace("openai/responses/", "openai/", 1)


def call_tools(model, prompt, tools, final_tool, *, max_iters=6, system=None,
               max_tokens=8000, temperature=0.0, complete=None, min_evidence=0,
               usage=None, partial_tool=None, coverage=None, debrief=None,
               allowed_keys=None, run=None):
    """redlines.llm.call_tools's contract: -> (answer_args, evidence); fills
    `usage` and `debrief` in place, feeds `partial_tool["fn"]` every piece in
    order, raises if the model never submits. `allowed_keys` ("qid|horizon")
    are the cells the call asks for, which pi's tools check pieces against.
    `max_tokens`, `temperature` and `complete` are the litellm path's and do
    nothing here; `run` replaces fri_forecaster.harness.run (tests)."""
    if run is None:
        from fri_forecaster import harness
        run = harness.run
    names = {t["name"] for t in tools}
    specs = [*tools, *([partial_tool] if partial_tool else []), final_tool]
    cell_items = (partial_tool or final_tool)["parameters"]["properties"]["forecasts"]["items"]
    base = os.environ.get("REDLINES_PI_DIR") or os.path.join(tempfile.gettempdir(), "redlines-pi")
    workdir = os.path.join(base, f"{model.replace('/', '_')}-{time.time_ns()}")
    loop = dict(min_research=min_evidence, floor_counts="returned", coverage=list(coverage or []) or None,
                withhold_final=True, warn_missing_keys=False, max_turns=max_iters)
    if debrief:
        loop["debrief"] = {"tool": {k: debrief["tool"][k] for k in ("name", "description", "parameters")},
                           "prompt": debrief["prompt"], "retries": int(debrief.get("retries", 1)),
                           **({"validator": debrief["validator"]} if debrief.get("validator") else {})}
    thinking = reasoning_for(model) or "off"
    # pi writes its working directory into the system prompt; run from the
    # checkout, that line names the project (".../airo/...") to the model --
    # a pointer to AIRO's own published forecasts. pi runs from an empty
    # directory with a name that says nothing (2026-10-15).
    cwd = os.environ.get("REDLINES_PI_CWD") or os.path.join(tempfile.gettempdir(), "w")
    os.makedirs(cwd, exist_ok=True)
    res = run(model=pi_model(model), system=system or "", prompt=prompt, workdir=workdir, cwd=cwd,
              cell_schema=cell_items, key_fields=["question_id", "horizon"],
              allowed_keys=list(allowed_keys or []),
              tool_descriptions={t["name"]: t.get("description", "") for t in specs},
              tool_parameters={t["name"]: t["parameters"] for t in specs},
              research_tools=tuple(n for n in ("web_search", "read_page") if n in names),
              cells_tool=bool(partial_tool), thinking=thinking,
              timeout=int(os.environ.get("REDLINES_PI_TIMEOUT", DEFAULT_TIMEOUT)),
              env={"PI_CODING_AGENT_DIR": os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(base, "agent")},
              **loop)
    if usage is not None:
        u = res["usage"]
        for k in ("turns", "input_tokens", "output_tokens", "cached_tokens"):
            usage[k] = usage.get(k, 0) + (u.get(k) or 0)
        usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + (u.get("cost_usd") or 0.0), 6)
        usage.update(reasoning_effort=thinking, reasoning_requested=thinking,
                     harness={"name": "pi", "pi_model": pi_model(model), "forced": res["forced"],
                              "rc": res["rc"], "seconds": round(res["seconds"])})
    if partial_tool:
        pieces = os.path.join(res["workdir"], "pieces.jsonl")
        for line in (open(pieces) if os.path.exists(pieces) else []):
            if line.strip():
                partial_tool["fn"](forecasts=json.loads(line).get("forecasts"))
    if debrief is not None and res.get("debrief") is not None:
        debrief.update({k: res["debrief"].get(k) for k in ("result", "complete", "attempts", "problems", "error")})
    if not res["answer"]:
        raise RuntimeError(f"{final_tool['name']} not called within {max_iters + 2} turns (pi exit "
                           f"{res['rc']}); recorded usage={usage}; trace={res.get('trace')}")
    evidence = [{k: e.get(k) for k in ("tool", "args", "result")} for e in res["evidence"]]
    return res["answer"], evidence
