"""In-container OpenHands agent runner.

Runs the OpenHands SDK agent loop *inside* the task container, talking to the
syntara MCP proxy at ``localhost:8000/mcp`` (reachable in-container on every
harbor environment, including Modal sandboxes where the host can't reach the
port).

Baked into the ``syntara`` image at build time (this
single file is staged to ``/app/openhands-runner/openhands_runner.py`` next to an
isolated venv holding ``openhands-sdk``). The host-side ``OpenHandsAgent`` uploads
a config JSON, execs this script, and downloads the trajectory it writes.

Contract:
- argv[1] = path to a config JSON: {instruction, systemPrompt, model, mcpUrl,
  maxToolCalls}.
- argv[2] = path to write the result/trajectory JSON to. This is a **dedicated
  file**, NOT stdout: the OpenHands SDK prints a human-readable transcript to
  stdout, so the machine-readable result must go to its own file for the host
  to parse it.
- The process exits 0 even when the agent loop errored — the error is recorded
  in the trajectory's ``stopped_reason``/``error_message`` so the host decides
  whether to fail the trial.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

MCP_TOOL_TIMEOUT = 300
WORKSPACE_DIR = "/tmp/openhands_workspace"
STATE_DIR = "/tmp/openhands_state"
LITELLM_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"
LITELLM_MODEL_COST_MAP_RESOURCE = "model_prices_and_context_window_backup.json"

# LiteLLM otherwise downloads mutable model capability metadata at import time.
os.environ[LITELLM_MODEL_COST_MAP_ENV] = "True"

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _litellm_model_cost_map_protocol() -> dict[str, Any]:
    from importlib.resources import files

    from litellm.litellm_core_utils.get_model_cost_map import (
        get_model_cost_map_source_info,
    )

    source = get_model_cost_map_source_info()
    if source.get("source") != "local" or source.get("is_env_forced") is not True:
        raise RuntimeError(
            "LiteLLM did not use its forced package-bundled model cost map"
        )
    contents = (
        files("litellm")
        .joinpath(LITELLM_MODEL_COST_MAP_RESOURCE)
        .read_bytes()
    )
    return {
        **source,
        "resource": LITELLM_MODEL_COST_MAP_RESOURCE,
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def _resolve_llm_kwargs(
    config: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None]:
    """Separate protocol controls from the OpenHands LLM constructor kwargs.

    ``reasoning_effort`` is applied post-construction. ``api_mode`` is checked
    against the SDK's actual request path before the first model call.
    """
    llm_kwargs = dict(config.get("llmKwargs") or {})

    effort = llm_kwargs.pop("reasoning_effort", None)
    if effort is not None:
        effort = str(effort).strip().lower() or None

    api_mode = llm_kwargs.pop("api_mode", None)
    if api_mode is not None:
        api_mode = str(api_mode).strip().lower() or None
        if api_mode not in {"chat_completions", "responses"}:
            raise ValueError(
                "api_mode must be 'chat_completions' or 'responses'; "
                f"got {api_mode!r}"
            )

    return llm_kwargs, effort, api_mode


def _request_protocol(
    llm: Any,
    expected_api_mode: str | None,
    expected_reasoning_effort: str | None,
) -> dict[str, Any]:
    """Return and validate the SDK's non-secret effective request settings."""
    api_mode = "responses" if llm.uses_responses_api() else "chat_completions"
    if expected_api_mode is not None and api_mode != expected_api_mode:
        raise RuntimeError(
            f"OpenHands selected {api_mode!r}, expected {expected_api_mode!r}; "
            "review the pinned SDK model capabilities before running"
        )

    if api_mode == "responses":
        selected = llm._finalize_responses_params(
            None, [], None, None, False, False, {}
        )[3]
        reasoning = selected.get("reasoning")
        top_level_effort = (
            reasoning.get("effort") if isinstance(reasoning, dict) else None
        )
        top_level_parameter = "reasoning.effort"
    else:
        selected = llm._finalize_completion_params([], None, False, {})[3]
        reasoning = None
        top_level_effort = selected.get("reasoning_effort")
        top_level_parameter = "reasoning_effort"

    extra_body = selected.get("extra_body")
    extra_body_reasoning = (
        extra_body.get("reasoning") if isinstance(extra_body, dict) else None
    )
    nested_effort = (
        extra_body_reasoning.get("effort")
        if isinstance(extra_body_reasoning, dict)
        else None
    )
    if (
        top_level_effort is not None
        and nested_effort is not None
        and top_level_effort != nested_effort
    ):
        raise RuntimeError(
            "OpenHands produced conflicting reasoning settings: "
            f"{top_level_parameter}={top_level_effort!r}, "
            f"extra_body.reasoning.effort={nested_effort!r}"
        )
    if nested_effort is not None:
        observed_effort = nested_effort
        reasoning_parameter = "extra_body.reasoning.effort"
    else:
        observed_effort = top_level_effort
        reasoning_parameter = top_level_parameter

    if (
        expected_reasoning_effort is not None
        and observed_effort != expected_reasoning_effort
    ):
        raise RuntimeError(
            "OpenHands did not preserve the requested reasoning effort: "
            f"expected {expected_reasoning_effort!r}, observed {observed_effort!r}"
        )

    tracked_parameters = (
        "temperature",
        "top_p",
        "seed",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "store",
        "include",
        "prompt_cache_retention",
        "tool_choice",
        "parallel_tool_calls",
    )
    return {
        "model": llm.model,
        "base_url": llm.base_url,
        "api_mode": api_mode,
        "reasoning_parameter": reasoning_parameter,
        "reasoning_effort": observed_effort,
        "reasoning_configuration": {
            "reasoning": reasoning,
            "reasoning_effort": selected.get("reasoning_effort"),
            "extra_body_reasoning": extra_body_reasoning,
            "thinking": selected.get("thinking"),
        },
        "sdk_controls": {
            "drop_params": getattr(llm, "drop_params", None),
            "modify_params": getattr(llm, "modify_params", None),
            "stream": getattr(llm, "stream", None),
            "native_tool_calling": getattr(llm, "native_tool_calling", None),
            "timeout": getattr(llm, "timeout", None),
            "num_retries": getattr(llm, "num_retries", None),
        },
        "parameters": {
            name: {"present": name in selected, "value": selected.get(name)}
            for name in tracked_parameters
        },
    }


def _protocol_aware_condenser_llm_class(llm_class: type) -> type:
    class ProtocolAwareCondenserLLM(llm_class):
        route_completion_via_responses: bool = False

        def completion(self, messages, tools=None, **kwargs):
            if self.route_completion_via_responses:
                return self.responses(messages=messages, tools=tools, **kwargs)
            return super().completion(messages=messages, tools=tools, **kwargs)

        async def acompletion(self, messages, tools=None, **kwargs):
            if self.route_completion_via_responses:
                return await self.aresponses(
                    messages=messages, tools=tools, **kwargs
                )
            return await super().acompletion(
                messages=messages, tools=tools, **kwargs
            )

    return ProtocolAwareCondenserLLM


def _resolve_llm_auth(model_name: str) -> tuple[str, str | None, str | None]:
    """Map harbor's ``provider/model`` id to a litellm (model, api_key, base_url).

    ``openrouter/anthropic/<model>`` is rewritten to ``anthropic/<model>`` (dots
    -> dashes) so Anthropic models route through the Anthropic provider, never
    OpenRouter. To send Anthropic traffic through an LLM proxy, point
    ``ANTHROPIC_BASE_URL`` at the proxy endpoint and set ``ANTHROPIC_API_KEY`` to
    the proxy token.
    """
    if "/" not in model_name:
        raise ValueError(
            f"model must be in 'provider/model' form; got {model_name!r}"
        )
    provider, model = model_name.split("/", 1)

    if provider == "openrouter" and model.startswith("anthropic/"):
        provider = "anthropic"
        model = model.split("/", 1)[1].replace(".", "-")

    if provider == "anthropic":
        litellm_model = f"anthropic/{model}"
        return (
            litellm_model,
            os.environ.get("ANTHROPIC_API_KEY"),
            os.environ.get("ANTHROPIC_BASE_URL"),
        )

    _provider_key_env = {
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "google": "GEMINI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    api_key = os.environ.get(_provider_key_env.get(provider, ""))
    base_url = os.environ.get("OPENAI_BASE_URL") if provider == "openai" else None
    return model_name, api_key, base_url


def _usage(*llms: Any) -> dict[str, int | float | None]:
    """Pull token/cost totals from one or more LLMs' metrics, tolerant of API drift.

    Sums across every LLM passed in (e.g. the agent loop plus the condenser) so
    the reported cost and cache usage reflect *all* model traffic for the trial,
    not just the main agent call. Each field stays ``None`` if no LLM exposed it,
    so a metrics-shape change degrades to null rather than crashing the trial.
    """
    input_tokens = output_tokens = cache_tokens = None
    cost: float | None = None

    def _accumulate(current: int | float | None, value: Any) -> int | float | None:
        if not isinstance(value, (int, float)):
            return current
        return value if current is None else current + value

    for llm in llms:
        metrics = getattr(llm, "metrics", None)
        if metrics is None:
            continue
        cost = _accumulate(cost, getattr(metrics, "accumulated_cost", None))
        token_usage = getattr(metrics, "accumulated_token_usage", None)
        if token_usage is None:
            continue
        input_tokens = _accumulate(input_tokens, getattr(token_usage, "prompt_tokens", None))
        output_tokens = _accumulate(output_tokens, getattr(token_usage, "completion_tokens", None))
        cache_tokens = _accumulate(cache_tokens, getattr(token_usage, "cache_read_tokens", None))

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_tokens": cache_tokens,
        # accumulated_cost is 0.0 when litellm has no pricing for the model
        # (e.g. an aliased model behind a proxy); treat that as "unknown" so
        # downstream cost reporting can fall back to provider dashboards.
        "cost_usd": cost if cost else None,
    }


# Tool observations larger than this (in chars) are kept intact. The OpenHands
# SDK otherwise hard-truncates every tool result at DEFAULT_TEXT_CONTENT_LIMIT
# (50_000) — see openhands/sdk/utils/truncate.py — which silently drops the tail
# of large reads (a 24-page SOP PDF is ~56 KB, big spreadsheet dumps similar).
# The worldbench baseline feeds tool outputs to the model untruncated (it only
# shortens them when building compaction summaries), so an aggressive per-call
# cap is a parity gap that costs OpenHands rubric points on SOP-heavy tasks.
# 1 MB clears every realistic task read with headroom while still guarding
# against a pathological multi-MB blob blowing the context window.
TOOL_OBSERVATION_CHAR_LIMIT = 1_000_000


def _raise_tool_observation_limit() -> None:
    """Lift the SDK's hardcoded 50K tool-observation truncation cap.

    The limit is a module-level constant (the per-message ``enable_truncation``
    field is deprecated), and ``message.py`` binds it at import time, so both the
    source module and that imported reference must be patched.
    """
    import openhands.sdk.llm.message as _message
    import openhands.sdk.utils.truncate as _truncate

    _truncate.DEFAULT_TEXT_CONTENT_LIMIT = TOOL_OBSERVATION_CHAR_LIMIT
    _message.DEFAULT_TEXT_CONTENT_LIMIT = TOOL_OBSERVATION_CHAR_LIMIT


def run(config: dict[str, Any]) -> dict[str, Any]:
    os.environ[LITELLM_MODEL_COST_MAP_ENV] = "True"

    from pydantic import SecretStr

    from openhands.sdk import (
        LLM,
        Agent,
        Conversation,
        ConversationExecutionStatus,
        Event,
        LLMSummarizingCondenser,
        MessageEvent,
    )
    from openhands.sdk.event import ActionEvent, AgentErrorEvent
    from openhands.sdk.llm.message import content_to_str

    _raise_tool_observation_limit()

    model_name = config["model"]
    litellm_model, api_key, base_url = _resolve_llm_auth(model_name)
    llm_kwargs, reasoning_effort, api_mode = _resolve_llm_kwargs(config)

    # Opt-in per-call request logging (--ak log_completions=true). Point the
    # folder at the trajectory's log dir so it's downloaded with the trial. Each
    # Logged payloads record the SDK request kwargs passed to LiteLLM, providing
    # a verifiable record of the requested reasoning and sampling settings.
    if llm_kwargs.pop("log_completions", False):
        log_root = config.get("logDir") or WORKSPACE_DIR
        llm_kwargs["log_completions"] = True
        llm_kwargs["log_completions_folder"] = os.path.join(log_root, "completions")
        _log(f"completion logging enabled -> {llm_kwargs['log_completions_folder']}")

    _log(
        f"Running OpenHands loop (model={litellm_model}, "
        f"base_url={base_url or 'default'})"
    )

    # timeout=600 matches worldbench's ~10-min per-call ceiling (anthropic-sdk.ts
    # uses `timeout: 600000 - 1`). The OpenHands LLM default is 300s, and
    # litellm.Timeout isn't in its retryable set, so a slow proxy call surfaces as
    # a fatal RuntimeError and drops the trial — doubling the ceiling matches the
    # baseline and cuts those spurious exclusions.
    llm = LLM(
        usage_id="agent",
        model=litellm_model,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
        timeout=600,
        **llm_kwargs,
    )

    # Context compaction, for parity with worldbench (which summarizes old turns
    # to stay within the window). We use the SDK defaults (event-count trigger at
    # max_size=240, keep_first=2): for these tasks neither harness's compaction
    # actually fires, but this gives the *reactive* recovery path — on a real
    # context-window overflow the SDK emits a CondensationRequest and retries with
    # a summarized history instead of hard-erroring the trial. The summarizer runs
    # on the same model/proxy as the agent (worldbench summarizes with its agent
    # model too); a separate LLM instance just keeps its metrics distinct.
    condenser_llm_class = _protocol_aware_condenser_llm_class(LLM)
    condenser_llm = condenser_llm_class(
        usage_id="condenser",
        model=litellm_model,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
        timeout=600,
        route_completion_via_responses=llm.uses_responses_api(),
        **llm_kwargs,
    )

    if reasoning_effort is not None:
        if litellm_model.startswith(("anthropic/", "openai/")):
            llm.reasoning_effort = reasoning_effort
            condenser_llm.reasoning_effort = reasoning_effort
        else:
            llm.reasoning_effort = None
            condenser_llm.reasoning_effort = None
            rb = {"reasoning": {"effort": reasoning_effort}}
            llm.litellm_extra_body = {**llm.litellm_extra_body, **rb}
            condenser_llm.litellm_extra_body = {**condenser_llm.litellm_extra_body, **rb}

    request_protocol = _request_protocol(llm, api_mode, reasoning_effort)
    condenser_protocol = _request_protocol(
        condenser_llm, api_mode, reasoning_effort
    )
    request_protocol["condenser_api_mode"] = condenser_protocol["api_mode"]
    request_protocol["condenser_reasoning_parameter"] = condenser_protocol[
        "reasoning_parameter"
    ]
    request_protocol["condenser_completion_adapter"] = (
        condenser_llm.route_completion_via_responses
    )
    request_protocol["litellm_model_cost_map"] = (
        _litellm_model_cost_map_protocol()
    )
    protocol_path = os.path.join(
        config.get("logDir") or WORKSPACE_DIR, "request_protocol.json"
    )
    os.makedirs(os.path.dirname(protocol_path), exist_ok=True)
    with open(protocol_path, "w") as protocol_file:
        json.dump(request_protocol, protocol_file, indent=2)
    _log(
        "validated request protocol "
        f"(api_mode={request_protocol['api_mode']}, "
        f"reasoning_parameter={request_protocol['reasoning_parameter']}, "
        f"reasoning_effort={request_protocol['reasoning_effort']})"
    )

    # Pass the office-assistant prompt as `system_prompt` (verbatim full
    # replacement) rather than an AgentContext suffix — otherwise OpenHands'
    # default SWE-coding system prompt dominates and diverges from worldbench,
    # which uses the office-assistant prompt as *the* system message.
    agent = Agent(
        llm=llm,
        tools=[],
        mcp_config={
            "mcpServers": {
                "syntara": {
                    "url": config["mcpUrl"],
                    "timeout": MCP_TOOL_TIMEOUT,
                }
            }
        },
        system_prompt=config["systemPrompt"],
        condenser=LLMSummarizingCondenser(llm=condenser_llm),
    )

    n_tool_calls = 0
    n_agent_errors = 0
    final_output = ""
    error_message: str | None = None

    def callback(event: Event) -> None:
        nonlocal n_tool_calls, n_agent_errors, final_output, error_message
        if isinstance(event, ActionEvent):
            n_tool_calls += 1
        elif isinstance(event, AgentErrorEvent):
            n_agent_errors += 1
            error_message = getattr(event, "error", None) or str(event)
        elif isinstance(event, MessageEvent) and event.source == "agent":
            text = "".join(content_to_str(event.to_llm_message().content))
            if text:
                final_output = text

    conversation = Conversation(
        agent=agent,
        callbacks=[callback],
        workspace=WORKSPACE_DIR,
        persistence_dir=STATE_DIR,
        max_iteration_per_run=int(config["maxToolCalls"]),
    )

    saw_error = False
    try:
        conversation.send_message(config["instruction"])
        conversation.run()
    except Exception as e:  # provider/transport/loop failure
        saw_error = True
        error_message = error_message or str(e)
        _log(f"OpenHands conversation.run() raised: {e}")

    status = getattr(conversation.state, "execution_status", None)
    status_val = getattr(status, "value", status)
    infra_failure = saw_error or status_val == ConversationExecutionStatus.ERROR.value
    did_work = n_tool_calls > 0 or bool(final_output)
    if saw_error:
        # conversation.run() raised (e.g. litellm.Timeout / provider error): the
        # loop was cut short and never completed, so this is a transport/infra
        # failure even if the agent had already made tool calls.
        stopped_reason = "error"
    elif infra_failure and not did_work:
        # ERROR status with nothing produced — genuine failure.
        stopped_reason = "error"
    elif status_val == ConversationExecutionStatus.STUCK.value:
        stopped_reason = "stuck"
    elif status_val == ConversationExecutionStatus.FINISHED.value:
        stopped_reason = "end_turn"
    else:
        stopped_reason = "max_tool_calls"

    usage = _usage(llm, condenser_llm)

    return {
        "agent_id": "openhands_sdk",
        "model": litellm_model,
        "final_output": final_output,
        "n_tool_calls": n_tool_calls,
        "n_agent_errors": n_agent_errors,
        "stopped_reason": stopped_reason,
        "error_message": error_message,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_tokens": usage["cache_tokens"],
        "cost_usd": usage["cost_usd"],
        "request_protocol": request_protocol,
    }


def main() -> None:
    if len(sys.argv) != 3:
        _log("usage: openhands_runner.py <config.json> <output.json>")
        sys.exit(2)

    config_path, output_path = sys.argv[1], sys.argv[2]
    config = json.loads(open(config_path).read())
    try:
        result = run(config)
    except Exception as e:
        # Hard failure before/around the loop — still emit a trajectory so the
        # host can surface it as an errored (excluded) trial rather than a crash.
        result = {
            "agent_id": "openhands_sdk",
            "model": config.get("model"),
            "final_output": "",
            "n_tool_calls": 0,
            "stopped_reason": "error",
            "error_message": str(e),
            "input_tokens": None,
            "output_tokens": None,
            "cache_tokens": None,
            "cost_usd": None,
        }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    _log(
        f"wrote trajectory to {output_path} "
        f"(stopped_reason={result.get('stopped_reason')}, "
        f"n_tool_calls={result.get('n_tool_calls')})"
    )


if __name__ == "__main__":
    main()
