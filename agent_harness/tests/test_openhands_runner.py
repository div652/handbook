import asyncio
import os
import unittest

from agent_harness.openhands_runner import (
    LITELLM_MODEL_COST_MAP_ENV,
    _litellm_model_cost_map_protocol,
    _protocol_aware_condenser_llm_class,
    _request_protocol,
    _resolve_llm_kwargs,
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


if __name__ == "__main__":
    unittest.main()
