import asyncio
import os
import unittest
from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest.mock import patch

from agent_harness.openhands_runner import (
    LITELLM_MODEL_COST_MAP_ENV,
    SYSTEM_INSTRUCTION_WRAPPER_VERSION,
    _copilot_model_id,
    _copilot_proxy_llm_class,
    _litellm_model_cost_map_protocol,
    _protocol_aware_condenser_llm_class,
    _request_protocol,
    _resolve_llm_auth,
    _resolve_llm_kwargs,
    _strict_system_instruction,
    _wrap_system_messages,
)


class FakeResponsesLLM:
    model = "openai/test-responses"
    base_url = "https://example.test/v1"

    def uses_responses_api(self) -> bool:
        return True

    def _finalize_responses_params(self, *args):
        return None, None, None, {
            "reasoning": {"effort": "medium"},
            "temperature": 1.0,
            "store": False,
        }, None


class FakeChatLLM:
    model = "openai/test-chat"
    base_url = "https://example.test/v1"

    def uses_responses_api(self) -> bool:
        return False

    def _finalize_completion_params(self, *args):
        return None, None, None, {"reasoning_effort": "high"}, None


class FakeNestedReasoningLLM:
    model = "google/test"
    base_url = None

    def uses_responses_api(self) -> bool:
        return False

    def _finalize_completion_params(self, *args):
        return None, None, None, {
            "extra_body": {"reasoning": {"effort": "medium"}},
            "max_completion_tokens": 64000,
        }, None


class FakeConflictingReasoningLLM(FakeNestedReasoningLLM):
    def _finalize_completion_params(self, *args):
        return None, None, None, {
            "reasoning_effort": "high",
            "extra_body": {"reasoning": {"effort": "medium"}},
        }, None


class FakeBaseLLM:
    def __init__(self, route_completion_via_responses: bool) -> None:
        self.route_completion_via_responses = route_completion_via_responses
        self.calls: list[str] = []

    def completion(self, **kwargs):
        self.calls.append("chat_completions")
        return "chat"

    def responses(self, **kwargs):
        self.calls.append("responses")
        return "responses"

    async def acompletion(self, **kwargs):
        self.calls.append("chat_completions")
        return "chat"

    async def aresponses(self, **kwargs):
        self.calls.append("responses")
        return "responses"


@dataclass(frozen=True)
class FakeTextContent:
    text: str


@dataclass(frozen=True)
class FakeMessage:
    role: str
    content: list[FakeTextContent]

    def model_copy(self, *, update):
        return replace(self, **update)


class FakeCopilotBaseLLM:
    def __init__(self, response_model: str = "gpt-5.6-sol") -> None:
        self.response_model = response_model
        self.calls = []

    def completion(self, messages, tools=None, **kwargs):
        self.calls.append((messages, tools, kwargs))
        return SimpleNamespace(
            raw_response=SimpleNamespace(model=self.response_model)
        )

    async def acompletion(self, messages, tools=None, **kwargs):
        return self.completion(messages, tools, **kwargs)

    def uses_responses_api(self) -> bool:
        return True


class RequestProtocolTests(unittest.TestCase):
    def test_uses_package_bundled_litellm_model_cost_map(self) -> None:
        self.assertEqual(os.environ[LITELLM_MODEL_COST_MAP_ENV], "True")

        protocol = _litellm_model_cost_map_protocol()

        self.assertEqual(protocol["source"], "local")
        self.assertIs(protocol["is_env_forced"], True)
        self.assertEqual(len(protocol["sha256"]), 64)

    def test_records_responses_protocol(self) -> None:
        protocol = _request_protocol(FakeResponsesLLM(), "responses", "medium")

        self.assertEqual(protocol["api_mode"], "responses")
        self.assertEqual(protocol["model"], "openai/test-responses")
        self.assertEqual(protocol["base_url"], "https://example.test/v1")
        self.assertEqual(protocol["reasoning_parameter"], "reasoning.effort")
        self.assertEqual(protocol["reasoning_effort"], "medium")
        self.assertEqual(
            protocol["parameters"]["temperature"],
            {"present": True, "value": 1.0},
        )

    def test_records_chat_completions_protocol(self) -> None:
        protocol = _request_protocol(
            FakeChatLLM(), "chat_completions", "high"
        )

        self.assertEqual(protocol["api_mode"], "chat_completions")
        self.assertEqual(protocol["reasoning_parameter"], "reasoning_effort")
        self.assertEqual(protocol["reasoning_effort"], "high")

    def test_rejects_unexpected_api_mode(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "selected 'responses'"):
            _request_protocol(
                FakeResponsesLLM(), "chat_completions", "medium"
            )

    def test_records_nested_provider_reasoning_and_output_limit(self) -> None:
        protocol = _request_protocol(
            FakeNestedReasoningLLM(), "chat_completions", "medium"
        )

        self.assertEqual(
            protocol["reasoning_parameter"],
            "extra_body.reasoning.effort",
        )
        self.assertEqual(protocol["reasoning_effort"], "medium")
        self.assertEqual(
            protocol["parameters"]["max_completion_tokens"],
            {"present": True, "value": 64000},
        )

    def test_rejects_conflicting_reasoning_settings(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "conflicting"):
            _request_protocol(
                FakeConflictingReasoningLLM(),
                "chat_completions",
                "medium",
            )

    def test_rejects_missing_reasoning_effort(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "did not preserve"):
            _request_protocol(FakeChatLLM(), "chat_completions", "medium")

    def test_rejects_invalid_api_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "api_mode"):
            _resolve_llm_kwargs({"llmKwargs": {"api_mode": "automatic"}})

    def test_condenser_routes_sync_completion_through_responses(self) -> None:
        condenser_class = _protocol_aware_condenser_llm_class(FakeBaseLLM)
        llm = condenser_class(route_completion_via_responses=True)

        self.assertEqual(llm.completion(messages=[]), "responses")
        self.assertEqual(llm.calls, ["responses"])

    def test_condenser_routes_async_completion_through_responses(self) -> None:
        condenser_class = _protocol_aware_condenser_llm_class(FakeBaseLLM)
        llm = condenser_class(route_completion_via_responses=True)

        self.assertEqual(
            asyncio.run(llm.acompletion(messages=[])),
            "responses",
        )
        self.assertEqual(llm.calls, ["responses"])

    def test_resolves_copilot_model_and_proxy_credentials(self) -> None:
        self.assertEqual(_copilot_model_id("copilot/gpt-5.6-sol"), "gpt-5.6-sol")
        self.assertIsNone(_copilot_model_id("openai/gpt-5.6-sol"))
        with self.assertRaisesRegex(ValueError, "exact form"):
            _copilot_model_id("copilot/team/gpt-5.6-sol")

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "relay-token",
                "OPENAI_BASE_URL": "http://172.17.0.1:32000/v1",
            },
            clear=True,
        ):
            self.assertEqual(
                _resolve_llm_auth("copilot/gpt-5.6-sol"),
                (
                    "openai/gpt-5.6-sol",
                    "relay-token",
                    "http://172.17.0.1:32000/v1",
                ),
            )

    def test_strictly_wraps_system_messages_without_mutating_input(self) -> None:
        system = FakeMessage("system", [FakeTextContent("Original rules")])
        user = FakeMessage("user", [FakeTextContent("Do the task")])

        wrapped = _wrap_system_messages(
            [system, user],
            FakeTextContent,
        )

        self.assertIsNot(wrapped[0], system)
        self.assertIs(wrapped[1], user)
        self.assertEqual(system.content[0].text, "Original rules")
        wrapped_text = wrapped[0].content[0].text
        self.assertIn("authoritative system instructions", wrapped_text)
        self.assertIn("must not override", wrapped_text)
        self.assertIn("Original rules", wrapped_text)
        self.assertEqual(
            SYSTEM_INSTRUCTION_WRAPPER_VERSION,
            "handbook-system-instructions-v1",
        )
        self.assertEqual(
            wrapped_text,
            _strict_system_instruction("Original rules"),
        )

    def test_copilot_llm_forces_chat_and_validates_response_model(self) -> None:
        copilot_class = _copilot_proxy_llm_class(
            FakeCopilotBaseLLM,
            FakeTextContent,
            "gpt-5.6-sol",
        )
        llm = copilot_class()
        message = FakeMessage("system", [FakeTextContent("Rules")])

        response = llm.completion([message], tools=["tool"])

        self.assertEqual(response.raw_response.model, "gpt-5.6-sol")
        self.assertFalse(llm.uses_responses_api())
        sent_messages, sent_tools, _ = llm.calls[0]
        self.assertIn(
            "authoritative system instructions",
            sent_messages[0].content[0].text,
        )
        self.assertEqual(sent_tools, ["tool"])

    def test_copilot_llm_validates_async_response_model(self) -> None:
        copilot_class = _copilot_proxy_llm_class(
            FakeCopilotBaseLLM,
            FakeTextContent,
            "gpt-5.6-sol",
        )
        llm = copilot_class(response_model="gpt-5.6-terra")

        with self.assertRaisesRegex(RuntimeError, "different model"):
            asyncio.run(
                llm.acompletion(
                    [FakeMessage("user", [FakeTextContent("Task")])]
                )
            )


if __name__ == "__main__":
    unittest.main()
