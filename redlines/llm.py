#!/usr/bin/env python3
"""The acquisition side's LLM plumbing: key loading + the agentic tool-use loop.

VENDORED on 2026-08-28 from xrisk-canaries' `forecast/cruxgen/_llm.py`, which
`code/run_unified.py` and `code/run_ladder_joint.py` used to import across a
`sys.path` insert into a sibling checkout. That made new elicitation depend on a
second private repo, so nobody outside it could re-run the pipeline that produced
the published forecasts. The loop below is that file's `call_tools` /
`_litellm_complete` / `_fn_spec` carried over unchanged, so a run before and
after the move issues the same calls.

TWO deliberate departures from the original:

  * `load_keys()` is REWRITTEN, not copied. Upstream read Anthropic from the
    xrisk-canaries `.env` and the rest from GCP Secret Manager via a project id
    at a hardcoded macOS path -- machinery that has been a no-op on the cron box
    since day one (see code/cron_run.sh, which sources the keys itself). Copying
    it would have vendored the reproducibility problem instead of fixing it, so
    this version reads an env file, which is what actually happens in production.
  * The Secret Manager path is gone, and with it `python-dotenv` and
    `google-cloud-secret-manager`. Parsing KEY=value needs no dependency. litellm
    is still required and is still imported INSIDE the call, so that importing
    this module -- which tests/ do, to load the runners -- stays stdlib-only and
    the `python3 -m redlines build` path keeps its no-third-party-deps promise.

Nothing here is reachable from `build`. This module is only imported by the
runners under code/, which need `pip install -e '.[acquire]'`.
"""
import json
import os
import sys
from pathlib import Path
import time

from .config import REPO_ROOT

# Every provider key the runners can use. TAVILY is the one that is load-bearing
# rather than optional: run_unified.py refuses to run without it rather than
# quietly publishing forecasts that the provenance line says were web-grounded
# but were not. It serves both grounding tools (web_search and read_page).
# METACULUS_API_KEY left the list on 2026-09-02 with the metaculus_lookup tool
# (redlines/tools.py says why); a value still in the env file is ignored.
PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "XAI_API_KEY", "TAVILY_API_KEY",
                 # code/observational/run_roster.py: the ECI roster runs
                 # through OpenRouter, one key for all 24 models.
                 "OPENROUTER_API_KEY")

# REDLINES_ENV_FILE is EXCLUSIVE: naming a file means read that file and no
# other, so a run can be pinned to a known key set (and so tests are hermetic on
# a machine that has real keys lying around). With it unset, both defaults are
# read in order and the FIRST value found wins for a given key. A variable
# already in the environment always beats every file, so
# `TAVILY_API_KEY=... python code/run_unified.py` works with no file at all --
# and so does cron_run.sh, which sources the env file before exec'ing us.
DEFAULT_ENV_FILES = ("~/.config/redlines/env",   # the cron box's location (mode 600)
                     "<repo>/.env")              # a local checkout's own file


def _env_paths():
    explicit = os.environ.get("REDLINES_ENV_FILE")
    if explicit:
        return [Path(explicit).expanduser()]
    return [Path.home() / ".config" / "redlines" / "env", REPO_ROOT / ".env"]


def _parse_env(path):
    """KEY=value lines -> dict. Tolerates `export ` prefixes, blank lines, #
    comments, and surrounding quotes -- the same shapes `set -a; . file` accepts,
    since the cron box sources the very same file with the shell."""
    out = {}
    try:
        text = path.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def load_keys():
    """Populate os.environ with provider API keys from the first env file that
    has them. Never overrides a variable that is already set.

    Best-effort by design: a missing file or a missing provider just means that
    provider stays unconfigured, and an Anthropic-only run still works. Callers
    that actually need a specific key check for it themselves after calling this
    (run_unified.py refuses to start without TAVILY_API_KEY). Returns the sorted
    names of the keys that ARE configured afterwards, for logging.
    """
    for path in _env_paths():
        values = _parse_env(path)
        for k in PROVIDER_KEYS:
            if values.get(k):
                os.environ.setdefault(k, values[k])
    return sorted(k for k in PROVIDER_KEYS if os.environ.get(k))


def _fn_spec(tool):
    """A {name, description, parameters} tool -> the OpenAI/litellm function spec."""
    return {"type": "function", "function": {
        "name": tool["name"], "description": tool.get("description", ""),
        "parameters": tool["parameters"]}}


# Per-request timeout, seconds. litellm's default is 600, which the combined
# instrument (2,520 probabilities in one tool call) overran on GPT-5.5 Pro in
# the 2026-08-28 pilot: "Connection timed out after 600.0 seconds", a lost
# call. A slow model on a long instrument needs longer; set it per run.
def request_timeout():
    return float(os.environ.get("REDLINES_LLM_TIMEOUT", "600"))


# Reasoning level, per provider family. Project lead, 2026-09-02: reasoning
# should be at its maximum. litellm's `reasoning_effort` is the one knob across
# providers; the top rung is spelled differently per family, and a rung a
# model does not offer comes back as a 400, so the map is by model prefix and
# `_litellm_complete` steps down one rung on that error before giving up on
# reasoning altogether. Probed 2026-09-02 on the box, tools attached:
# Fable 5 / Opus 5 take "max"; GPT-5.5 Pro and GPT-5.6 Sol take "xhigh"
# (Sol rejects tools ONLY under litellm's default effort -- an explicit level
# is fine). Anthropic's effort also governs how many tool calls the model
# makes, which is the point. REDLINES_REASONING overrides for an experiment
# ("none" sends no reasoning parameter at all).
REASONING = {"anthropic": "max", "openai": "xhigh"}
REASONING_DEFAULT = "high"
# The rungs the panel is configured for. A model configured at one of these
# is never run without reasoning: if every rung is rejected the call fails.
TOP_RUNGS = {"max", "xhigh"}
# The oldest litellm known to map "max" to Anthropic's adaptive thinking and
# "xhigh" to OpenAI's reasoning.effort (verified on the cron box, 2026-09-10).
LITELLM_MIN = "1.96"
REASONING_STEP_DOWN = {"max": "high", "xhigh": "high", "high": "medium", "medium": "low",
                       "low": "minimal"}


def reasoning_for(model):
    """The reasoning_effort to send for `model`, or None for none."""
    override = os.environ.get("REDLINES_REASONING")
    if override:
        return None if override.lower() == "none" else override
    return REASONING.get(model.split("/", 1)[0], REASONING_DEFAULT)


# An EXPLICIT Anthropic thinking budget, tokens per turn -- off by default.
# Probed on the box 2026-09-02 evening (AnthropicConfig.map_openai_params):
# for the Claude 5 family litellm treats reasoning_effort="max" as ADAPTIVE
# thinking with output_config.effort="max" -- Anthropic's own top setting,
# the model deciding how much to think per turn. The fixed
# budget_tokens=16,384 alias exists only for models without adaptive
# thinking. So "max" IS max here, and an explicit budget would be a
# downgrade (a fixed cap in place of adaptive effort). The knob stays for
# experiments: REDLINES_THINKING_BUDGET=<tokens> sends
# thinking={enabled, budget_tokens} instead, kept THINKING_HEADROOM under
# max_tokens (Anthropic requires max_tokens > budget_tokens).
THINKING_BUDGET = {}
THINKING_HEADROOM = 16000


def thinking_budget_for(model, max_tokens):
    """The `thinking.budget_tokens` to send for `model` under `max_tokens`, or
    None (no explicit budget: reasoning_effort, or nothing, applies)."""
    if reasoning_for(model) is None:
        return None
    override = os.environ.get("REDLINES_THINKING_BUDGET")
    budget = int(override) if override else THINKING_BUDGET.get(model.split("/", 1)[0])
    if not budget:
        return None
    return max(1024, min(budget, max_tokens - THINKING_HEADROOM))


# {model: (effort, temperature, budget)} that the provider accepted, per
# process, so the step-down ladder runs once per model rather than per turn.
_ACCEPTED = {}


# Models that refuse a forced tool_choice under thinking (Anthropic 400:
# 'tool_choice: type "tool" and "any" are not supported for this model').
# call_tools then offers only the final tool and asks for it in words, and
# the debrief turn runs on "auto". Probed: Fable 5.1 (2026-09-15), Opus 5.5
# and Sonnet 5.5 (2026-10-01; Opus 5 still accepts it). A model missing from
# this list is caught at its first forced turn and learned for the process
# (_NO_FORCE_LEARNED), with a WARN to add it here.
NO_FORCED_TOOL_CHOICE = ("anthropic/claude-fable-5-1", "anthropic/claude-mythos",
                         "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5")
_NO_FORCE_LEARNED = set()


def refuses_forced_tool_choice(model):
    return model.startswith(NO_FORCED_TOOL_CHOICE) or model in _NO_FORCE_LEARNED


def _is_forced_choice_refusal(exc):
    msg = str(exc).lower()
    return "tool_choice" in msg and "not supported" in msg


def _litellm_complete(model, messages, *, tools=None, tool_choice=None,
                      max_tokens=8000, temperature=0.0):
    """One litellm completion, normalized to {content, tool_calls:[{id,name,arguments}],
    thinking_blocks?}. `thinking_blocks` is Anthropic's signed reasoning; the
    loop puts it back on the assistant turn, which the API requires when a
    tool result follows a thinking turn."""
    import litellm
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    kw = dict(model=model, messages=messages, max_tokens=max_tokens, num_retries=2,
              timeout=request_timeout())
    if tools:
        kw["tools"] = tools
    if tool_choice:
        kw["tool_choice"] = tool_choice
    effort = reasoning_for(model)
    budget = thinking_budget_for(model, max_tokens)

    def attempt(effort, temp, budget=None):
        extra = {}
        if budget:
            extra["thinking"] = {"type": "enabled", "budget_tokens": budget}
        elif effort:
            if model.startswith("openai/responses/"):
                # litellm maps reasoning_effort only for models in its own
                # model map and DROPS it silently for the rest (drop_params):
                # GPT-6 Astra's requests went out with no effort at all
                # (verified 2026-09-10 by capturing the request body). The
                # Responses API's native field passes through for any model.
                extra["reasoning"] = {"effort": effort}
            else:
                extra["reasoning_effort"] = effort
                if model.startswith("openai/"):
                    # Same drop on the chat route for an unmapped model; this
                    # forces the parameter through (litellm's allow-list).
                    extra["allowed_openai_params"] = ["reasoning_effort"]
        if temp is not None:
            extra["temperature"] = temp
        return litellm.completion(**kw, **extra)

    # Two error families carry a rejected request parameter: the provider's
    # 400 (litellm.BadRequestError: "`temperature` is deprecated", "thinking
    # .type.enabled is not supported") and litellm's own mapping failure before
    # any request is made (litellm.APIConnectionError, "Unmapped reasoning
    # effort: max" on a litellm build that predates the rung). A model can
    # reject several in a row -- Opus 4.8 on litellm 1.7x: temperature, then
    # "max", then every fixed-budget rung -- so this walks a ladder: drop the
    # temperature, drop an explicit thinking budget, step the effort down one
    # rung at a time to none (the model's own default), and only then give up.
    # Each step is logged, so the run log says what effort a call actually ran.
    rejected = (litellm.BadRequestError, litellm.APIConnectionError)
    temp = temperature
    # Start from what this model accepted earlier in the process: a model
    # that rejects `temperature` (the OpenAI reasoning models) would otherwise
    # pay one refused request per turn of every call.
    known = _ACCEPTED.get(model)
    if known:
        effort, temp, budget = known
    for _ in range(12):
        before = (effort, temp, budget)
        try:
            r = attempt(effort, temp, budget)
            _ACCEPTED[model] = (effort, temp, budget)
            break
        except rejected as e:
            msg = str(e).lower()
            # litellm itself could not map the rung: the installed litellm
            # predates it (1.81 has no "max"; the cron box's 1.96 maps it to
            # Anthropic's adaptive thinking). That is a setup fault, not a
            # model limit -- refuse rather than run a top-rung model at a
            # lower effort without anyone noticing.
            if "unmapped reasoning effort" in msg:
                raise RuntimeError(
                    f"{model}: litellm cannot map reasoning_effort={effort!r} "
                    f"({str(e)[:80]}); install litellm>={LITELLM_MIN} (pip install -e '.[acquire]')") from e
            if temp is not None and "temperature" in msg:
                temp = None
            elif budget and ("thinking" in msg or "budget" in msg):
                budget = None
            elif effort and ("reasoning" in msg or "effort" in msg or "thinking" in msg):
                lower = REASONING_STEP_DOWN.get(effort)
                if lower is None and effort in TOP_RUNGS:
                    # The provider rejected every rung of a model configured
                    # for the top one. Running it with no reasoning at all
                    # would be a different experiment; stop instead.
                    raise RuntimeError(
                        f"{model}: every reasoning rung was rejected ({str(e)[:100]}); "
                        f"not falling back to no reasoning for a model configured "
                        f"for {reasoning_for(model)!r}. Check the litellm version "
                        f"(>={LITELLM_MIN}) and the model id.") from e
                effort = lower
            else:
                raise
            if (effort, temp, budget) == before:
                raise
            print(f"  note  {model}: request rejected ({str(e)[:90]}...); retrying with "
                  f"effort={effort or 'none'} temperature={temp} budget={budget}",
                  file=sys.stderr)
    else:
        raise RuntimeError(f"{model}: no accepted request configuration after stepping down")
    requested = reasoning_for(model)
    if effort != requested:
        print(f"WARN: {model} ran with reasoning_effort={effort or 'none'}, not the configured "
              f"{requested or 'none'} (see the notes above); the row's usage records both",
              file=sys.stderr)
    msg = r.choices[0].message
    calls = [{"id": tc.id, "name": tc.function.name,
              "arguments": tc.function.arguments or "{}"}
             for tc in (getattr(msg, "tool_calls", None) or [])]
    out = {"content": msg.content, "tool_calls": calls, "usage": _usage_of(r),
           # What this turn actually ran with, so a row can show it (tally_usage).
           "reasoning_effort": effort, "reasoning_requested": requested}
    # OpenAI reports reasoning tokens separately; a reasoning-effort request
    # that comes back with none on a substantial turn is the parameter having
    # been dropped somewhere (a one-word reply may legitimately use none).
    if effort and model.startswith("openai") and out["usage"] is not None \
            and out["usage"].get("output_tokens", 0) >= 500 \
            and not out["usage"].get("reasoning_tokens"):
        print(f"WARN: {model} was asked for reasoning_effort={effort} but reported no "
              "reasoning tokens; check that the effort reached the provider", file=sys.stderr)
    blocks = getattr(msg, "thinking_blocks", None)
    if blocks:
        out["thinking_blocks"] = blocks
    return out


def _usage_of(r):
    """One completion's tokens and price: {input_tokens, output_tokens,
    reasoning_tokens?, cached_tokens?, cost_usd} -- cost_usd is None when
    litellm has no price for the model, so an unpriced call is visible rather
    than free. None when the response carries no usage at all."""
    import litellm
    u = getattr(r, "usage", None)
    if u is None:
        return None
    out = {"input_tokens": getattr(u, "prompt_tokens", 0) or 0,
           "output_tokens": getattr(u, "completion_tokens", 0) or 0}
    ctd = getattr(u, "completion_tokens_details", None)
    rt = getattr(ctd, "reasoning_tokens", None) if ctd is not None else None
    if rt:
        out["reasoning_tokens"] = rt
    ptd = getattr(u, "prompt_tokens_details", None)
    ct = getattr(ptd, "cached_tokens", None) if ptd is not None else None
    if ct:
        out["cached_tokens"] = ct
    try:
        out["cost_usd"] = float(litellm.completion_cost(completion_response=r))
    except Exception:   # litellm raises its own family for an unknown model
        out["cost_usd"] = None
    return out


def tally_usage(total, one, effective=None):
    """Add one completion's usage into the running total for a call (in
    place): turns, tokens by kind, cost_usd, and unpriced_turns -- the turns
    litellm could not price, so a total with any of those is a floor.
    `effective` (the completion's {reasoning_effort, reasoning_requested})
    stamps the effort the call actually ran with, so a row records it."""
    if total is None:
        return
    total["turns"] = total.get("turns", 0) + 1
    if effective is not None:
        total["reasoning_effort"] = effective.get("reasoning_effort")
        total["reasoning_requested"] = effective.get("reasoning_requested")
    if not one or one.get("cost_usd") is None:
        total["unpriced_turns"] = total.get("unpriced_turns", 0) + 1
    else:
        total["cost_usd"] = round(total.get("cost_usd", 0.0) + one["cost_usd"], 6)
    for k in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"):
        if one and one.get(k):
            total[k] = total.get(k, 0) + one[k]


def research_coverage(evidence):
    """{cause: n} over recorded evidence: how many recent-window searches
    (args carrying `cause` and a truthy `recent_days`) each question group
    got, in first-seen order. What the coverage rule below counts."""
    out = {}
    for e in evidence or []:
        args = e.get("args")
        if isinstance(args, dict) and args.get("cause") is not None and args.get("recent_days"):
            out[args["cause"]] = out.get(args["cause"], 0) + 1
    return out


def call_tools(model, prompt, tools, final_tool, *, max_iters=6, system=None,
               max_tokens=8000, temperature=0.0, complete=None, min_evidence=0,
               usage=None, partial_tool=None, coverage=None, debrief=None):
    """Agentic loop: let the model call `tools` to gather evidence, then submit its
    answer via `final_tool`. Returns (answer_args, evidence).

    `partial_tool` (2026-09-02 evening): a tool the model may call any number
    of times to deliver its answer IN PIECES -- offered exactly when
    `final_tool` is, served by its `fn` (which keeps what it is given; the
    caller merges after the loop), never counted as research evidence. The
    final tool's call then carries the rest. This keeps a large structured
    answer clear of the per-turn output cap: the combined instrument's 2,520
    probabilities in one tool call were most of a 64k-token turn, shared with
    the thinking budget; in pieces, no turn is large, and the budget can be.

    `tools` are dicts {name, description, parameters, fn}; `final_tool` is the same
    minus fn (its args ARE the structured answer -- no regex parsing). On the last
    iteration the loop forces `final_tool` so the model can't stall. `evidence` is
    the ordered list of {tool, args, result} from the non-final tool calls.

    `min_evidence` is the RESEARCH FLOOR (2026-09-02): until that many tool
    calls have returned, `final_tool` is not offered at all -- the model can
    only research -- and a premature call to it is answered with how many
    calls remain. The floor is what makes "iterative multi-step search" a
    property of the harness rather than a hope about the prompt: asked
    nicely, Fable 5 searched four times and read nothing (the 2026-09-02
    smoke). The last iteration still forces submission, floor or no floor.

    `coverage` (2026-09-11) is a list of question-group keys: the COVERAGE
    RULE. Until every key has a returned research call whose args carry
    `cause` equal to it AND a truthy `recent_days` (a recent-window search on
    that group), `final_tool` is withheld exactly as under the floor, and a
    premature call is answered with the groups still uncovered. The floor
    counts calls; this says what they must span. Why: of three GPT-6 Astra
    draws of the combined instrument (2026-09-08, 09-10 and a 09-11 smoke),
    the 09-10 draw ran eight searches and none on misalignment, and put its
    loss-of-control forecasts at half the other two's, which had each read a
    loss-of-control incident report -- run-to-run spread that was a gap in
    the reading, not a change of mind. The prompt had asked for a recent
    check on each cause all along; the 09-10 draw skipped it anyway. The
    last iteration still forces submission, and a WARN in the log names
    what went uncovered.

    `usage`, if given, is a dict the loop fills in place with the call's
    tokens and price across every turn (tally_usage) -- pass the same dict
    through a retry and it keeps counting, so a call's cost includes the
    attempts that failed.

    `debrief` (2026-09-15): THE DEBRIEF TURN. A dict {tool, prompt, validate?,
    retries?} -- once `final_tool` has been accepted, the same conversation
    gets one more user turn (`prompt`) offering only `tool`, and the model's
    structured answer lands in debrief["result"], with debrief["complete"],
    ["attempts"], ["problems"] (what `validate(args)` returned on the last
    try, a list of strings) and ["error"] (an exception's text) beside it.
    `validate` failing gets the problems back as the tool result and one
    more try (`retries`, default 1). The numbers are already submitted when
    the debrief is asked for, so it cannot move them; and nothing here can
    lose them either -- a debrief that fails is logged and recorded, and the
    accepted answer is returned regardless. Why: the run recorded one 3-6
    sentence rationale per call, and the per-run brief for collaborators
    (project lead, 2026-09-15) needs, per question group, which sources mattered
    most, which arguments were most compelling and the most likely pathway
    to catastrophe -- in the model's own words, not inferred from its trail.

    `complete` is the completion backend (defaults to litellm); tests inject a fake
    one to drive the loop offline. Raises if the model never submits.
    """
    complete = complete or _litellm_complete
    by_name = {t["name"]: t for t in tools}
    research_specs = [_fn_spec(t) for t in tools]
    final_spec = _fn_spec(final_tool)
    partial_spec = _fn_spec(partial_tool) if partial_tool else None
    final_choice = {"type": "function", "function": {"name": final_tool["name"]}}
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": prompt})
    evidence = []
    trace_dir = os.environ.get("REDLINES_TRACE_DIR")
    trace_path = None
    if trace_dir:
        directory = Path(trace_dir)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        trace_path = directory / f"{model.replace('/', '_')}-{time.time_ns()}.json"

    def checkpoint(iteration, status, response=None, error=None):
        if trace_path is None:
            return
        state = {"model": model, "prompt": prompt, "system": system,
                 "iteration": iteration, "status": status, "messages": messages,
                 "evidence": evidence, "usage": usage, "response": response,
                 "error": error, "max_iters": max_iters, "max_tokens": max_tokens}
        temporary = trace_path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
        temporary.replace(trace_path)

    def uncovered():
        covered = research_coverage(evidence)
        return [k for k in (coverage or []) if k not in covered]

    def not_yet(name):
        """The tool result for a submission attempted before the floor and
        the coverage rule are both met: what remains, in the model's terms."""
        parts = []
        if len(evidence) < min_evidence:
            parts.append(f"{min_evidence - len(evidence)} more research call(s) must return "
                         f"first ({len(evidence)} of {min_evidence} so far)")
        missing = uncovered()
        if missing:
            parts.append("a web_search with recent_days set and cause=<group> is still "
                         f"needed for: {', '.join(missing)}")
        return {"error": f"{name} is not offered yet: " + "; ".join(parts)}

    cannot_force = refuses_forced_tool_choice(model)
    # Unsupported endpoints get two additional submission-only turns. These
    # retain the same conversation and accepted cells, never restart research.
    limit = max_iters + (2 if cannot_force else 0)
    warned_uncovered = []

    accepted = None
    i = -1
    while True:
        i += 1
        if i >= limit:   # a while, not range(limit): a refusal learned below raises the limit
            break
        force = i >= max_iters - 1
        offered = force or (len(evidence) >= min_evidence and not uncovered())
        if force and not warned_uncovered and uncovered():
            warned_uncovered.append(True)   # once per call, not per forced turn
            print(f"WARN: {model} reached the turn limit with no recent-window search on: "
                  f"{', '.join(uncovered())}; submission forced", file=sys.stderr)
        specs = research_specs + (([partial_spec] if partial_spec else []) + [final_spec] if offered else [])
        # Fable 5.1 rejects forced tool_choice at the API boundary. Keep its
        # reasoning setting and accumulated research, offer just the final
        # tool, and request submission explicitly on the termination turn.
        # https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/tool-use-concepts.md
        auto_submit = force and cannot_force
        if auto_submit:
            specs = [final_spec]
            messages.append({"role": "user", "content": (
                f"Now call {final_tool['name']} with your final answer. "
                "Include any remaining forecast cells and required summary fields; "
                "previously accepted cells are retained.")})
            if usage is not None:
                usage["submission_guard"] = "auto-final-tool-only"
        checkpoint(i, 'request')
        try:
            resp = complete(model, messages, tools=specs,
                            tool_choice=(final_choice if force and not auto_submit else "auto"),
                            max_tokens=max_tokens, temperature=temperature)
        except Exception as exc:
            if force and not auto_submit and _is_forced_choice_refusal(exc):
                # A model nobody has probed refuses the forced submission:
                # learn it for the process and redo this turn the way the
                # known ones submit, rather than lose the call (and the date).
                _NO_FORCE_LEARNED.add(model)
                cannot_force, limit = True, max_iters + 2
                print(f"WARN: {model} refuses a forced tool_choice ({str(exc)[:90]}); "
                      f"submitting by asking instead -- add it to NO_FORCED_TOOL_CHOICE "
                      f"in redlines/llm.py", file=sys.stderr)
                i -= 1
                continue
            checkpoint(i, 'failed', error=str(exc))
            raise
        tally_usage(usage, resp.get("usage"),
                    {k: resp.get(k) for k in ("reasoning_effort", "reasoning_requested")}
                    if "reasoning_effort" in resp else None)
        checkpoint(i, 'response', response=resp)
        calls = resp.get("tool_calls") or []
        if not calls:
            # answered in prose without submitting -- nudge it to use the tool
            asst = {"role": "assistant", "content": resp.get("content") or ""}
            if resp.get("thinking_blocks"):
                asst["thinking_blocks"] = resp["thinking_blocks"]
            messages.append(asst)
            missing = uncovered()
            messages.append({"role": "user", "content": (
                f"Now call {final_tool['name']} with your final answer." if offered else
                f"Keep researching with the tools: {final_tool['name']} is offered after "
                f"{min_evidence} tool calls have returned ({len(evidence)} so far)"
                + (f" and after a web_search with recent_days on each of: {', '.join(missing)}"
                   if missing else "") + ".")})
            continue
        # the assistant turn must carry tool_calls for the tool replies to validate
        asst = {"role": "assistant", "content": resp.get("content") or "",
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"],
                                             "arguments": c["arguments"]}}
                               for c in calls]}
        if resp.get("thinking_blocks"):
            asst["thinking_blocks"] = resp["thinking_blocks"]
        messages.append(asst)
        for c in calls:
            try:
                args = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if c["name"] == final_tool["name"]:
                if offered:
                    accepted = args
                    result = {"accepted": True}
                else:
                    result = not_yet(final_tool["name"])
            elif partial_tool and c["name"] == partial_tool["name"]:
                # A piece of the answer: kept by the caller's fn, not evidence.
                result = partial_tool["fn"](**args) if offered else not_yet(partial_tool["name"])
            else:
                spec = by_name.get(c["name"])
                result = spec["fn"](**args) if spec else {"error": f"unknown tool {c['name']}"}
                evidence.append({"tool": c["name"], "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result)[:8000]})
        if accepted is not None:
            checkpoint(i, 'complete', response=resp)
            if debrief:
                _debrief_turn(model, messages, debrief, complete, usage, max_tokens,
                              temperature, cannot_force, checkpoint)
            return accepted, evidence
    checkpoint(limit, 'failed', error='submission limit reached')
    raise RuntimeError(f"{final_tool['name']} not called within {limit} iterations; "
                       f"recorded usage={usage}; trace={trace_path}")


def _json_object_in(text):
    """The first JSON object in a text reply (fences and prose tolerated), or
    None. For a model that answers the debrief in words instead of a call."""
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```", 2)[1]
        t = t.split("\n", 1)[1] if t.startswith(("json", "JSON")) else t
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        obj = json.loads(t[a:b + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _parse_stringified(args):
    """A debrief whose entries arrived as JSON strings, parsed in place (Fable
    5.1, 2026-09-16: the whole `cells` object as one string). A string that
    is not JSON stays as it is."""
    if not isinstance(args, dict):
        return args
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and v.strip()[:1] == "{":
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        out[k] = v
    return out


def _debrief_turn(model, messages, debrief, complete, usage, max_tokens, temperature,
                  cannot_force, checkpoint):
    """The debrief turn of call_tools (see its docstring): ask, validate, retry,
    record in place. Never raises -- the forecast is already accepted.

    Since 2026-09-16 deliveries MERGE across attempts (a call that carries
    some entries is kept, and the retry asks for the rest), an entry that
    arrives as a JSON string is parsed, a reply with no call and no text gets
    one text-only ask for the object (Fable 5.1 returned zero output tokens
    to the tool-only turn), and the debrief may set its own `max_tokens`
    (a per-question debrief is a long call)."""
    tool = debrief["tool"]
    spec = _fn_spec(tool)
    choice = "auto" if cannot_force else {"type": "function", "function": {"name": tool["name"]}}
    validate = debrief.get("validate") or (lambda args: [])
    tries = 1 + int(debrief.get("retries", 1))
    max_tokens = int(debrief.get("max_tokens") or max_tokens)
    debrief.update(result=None, complete=False, attempts=0, problems=[], error=None)
    messages.append({"role": "user", "content": debrief["prompt"]})

    def merged(args):
        """Fold one delivery into the result; the merged whole is validated."""
        args = _parse_stringified(args)
        if isinstance(args, dict) and isinstance(debrief["result"], dict):
            debrief["result"] = {**debrief["result"], **args}
        else:
            debrief["result"] = args
        return debrief["result"]

    try:
        for attempt in range(1, tries + 1):
            debrief["attempts"] = attempt
            checkpoint(f"debrief-{attempt}", 'request')
            resp = complete(model, messages, tools=[spec], tool_choice=choice,
                            max_tokens=max_tokens, temperature=temperature)
            tally_usage(usage, resp.get("usage"),
                        {k: resp.get(k) for k in ("reasoning_effort", "reasoning_requested")}
                        if "reasoning_effort" in resp else None)
            checkpoint(f"debrief-{attempt}", 'response', response=resp)
            calls = resp.get("tool_calls") or []
            asst = {"role": "assistant", "content": resp.get("content") or ""}
            if calls:
                asst["tool_calls"] = [{"id": c["id"], "type": "function",
                                       "function": {"name": c["name"], "arguments": c["arguments"]}}
                                      for c in calls]
            if resp.get("thinking_blocks"):
                asst["thinking_blocks"] = resp["thinking_blocks"]
            messages.append(asst)
            hits = [c for c in calls if c["name"] == tool["name"]]
            if not hits:
                for c in calls:
                    messages.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": json.dumps({"error": f"only {tool['name']} is offered now"})})
                if not calls and not (resp.get("content") or "").strip():
                    # Nothing at all came back. Ask once for the object as text.
                    messages.append({"role": "user", "content": (
                        f"No call arrived. Reply with the JSON object you would pass to "
                        f"{tool['name']}, and nothing else.")})
                    resp = complete(model, messages, max_tokens=max_tokens, temperature=temperature)
                    tally_usage(usage, resp.get("usage"))
                    checkpoint(f"debrief-{attempt}", 'text', response=resp)
                    messages.append({"role": "assistant", "content": resp.get("content") or ""})
                    obj = _json_object_in(resp.get("content"))
                    if obj is not None:
                        result = merged(obj)
                        problems = [str(p) for p in (validate(result) or [])]
                        debrief["problems"] = problems
                        if not problems:
                            debrief["complete"] = True
                            debrief["delivery"] = "text"
                            checkpoint(f"debrief-{attempt}", 'complete', response=resp)
                            return
                        messages.append({"role": "user", "content": (
                            f"Call {tool['name']} with the rest, fixing: " + "; ".join(problems))})
                        continue
                debrief["problems"] = [f"{tool['name']} was not called"]
                messages.append({"role": "user", "content": f"Now call {tool['name']} with the debrief."})
                continue
            # Every delivery in this turn is folded in, in order.
            for c in hits:
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = merged(args)
            problems = [str(p) for p in (validate(result) or [])]
            debrief["problems"] = problems
            for c in calls:
                content = ({"accepted": not problems, "problems": problems} if c in hits
                           else {"error": f"only {tool['name']} is offered now"})
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "content": json.dumps(content)[:8000]})
            if not problems:
                debrief["complete"] = True
                checkpoint(f"debrief-{attempt}", 'complete', response=resp)
                return
            messages.append({"role": "user", "content": (
                f"Call {tool['name']} again with what is still missing or wrong (entries you "
                f"already sent are kept), fixing: " + "; ".join(problems)[:4000])})
        print(f"WARN: {model} debrief incomplete after {debrief['attempts']} attempt(s): "
              f"{'; '.join(debrief['problems'])[:300]}", file=sys.stderr)
    except Exception as exc:   # the forecast is accepted; the debrief must not undo that
        debrief["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        checkpoint('debrief', 'failed', error=debrief["error"])
        print(f"WARN: {model} debrief turn failed: {debrief['error']}", file=sys.stderr)
