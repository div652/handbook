import asyncio
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agent_harness.openhands_agent import (
    OpenHandsAgent,
    _copilot_model_id,
    _forwarded_env,
    _trapi_token,
    _validated_trapi_base_url,
)


class FakeEnvironment:
    def __init__(
        self,
        chmod_return_code: int = 0,
        upload_error: Exception | None = None,
    ) -> None:
        self.commands: list[str] = []
        self.local_path: Path | None = None
        self.local_mode: int | None = None
        self.uploaded_content: str | None = None
        self.chmod_return_code = chmod_return_code
        self.upload_error = upload_error

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        self.local_path = Path(local_path)
        self.local_mode = stat.S_IMODE(self.local_path.stat().st_mode)
        self.uploaded_content = self.local_path.read_text()
        if self.upload_error is not None:
            raise self.upload_error

    async def exec(self, command: str, timeout_sec: int) -> SimpleNamespace:
        self.commands.append(command)
        return_code = (
            self.chmod_return_code if command.startswith("chmod 600 ") else 0
        )
        return SimpleNamespace(return_code=return_code, stderr="test failure")


class TrapiTokenTransportTests(unittest.TestCase):
    def test_recognizes_only_exact_copilot_provider_models(self) -> None:
        self.assertEqual(
            _copilot_model_id("copilot/gpt-5.6-sol"),
            "gpt-5.6-sol",
        )
        self.assertIsNone(_copilot_model_id("openai/gpt-5.6-sol"))
        with self.assertRaisesRegex(RuntimeError, "exact form"):
            _copilot_model_id("copilot/team/gpt-5.6-sol")

    def test_azure_cli_token_request_has_timeout(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"TRAPI_AZURE_SCOPE": "api://trapi/.default"},
                clear=True,
            ),
            patch(
                "agent_harness.openhands_agent.subprocess.run",
                return_value=SimpleNamespace(stdout="test-token\n"),
            ) as run,
        ):
            self.assertEqual(_trapi_token(), "test-token")

        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_forwarded_env_omits_openai_key_for_trapi(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TRAPI_AZURE_SCOPE": "api://trapi/.default",
                "OPENAI_API_KEY": "must-not-be-forwarded",
                "OPENAI_BASE_URL": (
                    "https://trapi.research.microsoft.com/test/openai/v1"
                ),
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "OPENROUTER_API_KEY": "openrouter-secret",
                "GEMINI_API_KEY": "gemini-secret",
            },
            clear=True,
        ):
            forwarded = _forwarded_env()

        self.assertEqual(
            forwarded,
            {
                "OPENAI_BASE_URL": (
                    "https://trapi.research.microsoft.com/test/openai/v1"
                )
            },
        )

    def test_trapi_requires_validated_base_url_before_token_acquisition(self) -> None:
        for base_url in ("", "https://api.openai.com/v1"):
            with (
                self.subTest(base_url=base_url),
                patch.dict(
                    os.environ,
                    {
                        "TRAPI_AZURE_SCOPE": "api://trapi/.default",
                        "OPENAI_BASE_URL": base_url,
                    },
                    clear=True,
                ),
                patch(
                    "agent_harness.openhands_agent._trapi_token"
                ) as acquire_token,
            ):
                environment = FakeEnvironment()
                agent = OpenHandsAgent.__new__(OpenHandsAgent)
                with self.assertRaisesRegex(RuntimeError, "OPENAI_BASE_URL"):
                    asyncio.run(agent._stage_trapi_token(environment))
                acquire_token.assert_not_called()
                self.assertIsNone(environment.uploaded_content)

    def test_accepts_expected_trapi_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_BASE_URL": (
                    "https://trapi.research.microsoft.com/redmond/"
                    "interactive/openai/v1"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                _validated_trapi_base_url(),
                (
                    "https://trapi.research.microsoft.com/redmond/"
                    "interactive/openai/v1"
                ),
            )

    def test_forwarded_env_preserves_direct_provider_credentials(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-secret",
                "ANTHROPIC_API_KEY": "anthropic-secret",
            },
            clear=True,
        ):
            forwarded = _forwarded_env()

        self.assertEqual(
            forwarded,
            {
                "OPENAI_API_KEY": "openai-secret",
                "ANTHROPIC_API_KEY": "anthropic-secret",
            },
        )

    def test_stages_token_in_private_temporary_file(self) -> None:
        environment = FakeEnvironment()
        agent = OpenHandsAgent.__new__(OpenHandsAgent)

        with patch.dict(
            os.environ,
            {"TRAPI_AZURE_SCOPE": "api://trapi/.default"},
            clear=True,
        ), patch(
            "agent_harness.openhands_agent._trapi_token",
            return_value="test-secret-token",
        ), patch("agent_harness.openhands_agent._validated_trapi_base_url"):
            remote_path = asyncio.run(agent._stage_trapi_token(environment))

        self.assertEqual(environment.uploaded_content, "test-secret-token")
        self.assertEqual(environment.local_mode, 0o600)
        self.assertIsNotNone(environment.local_path)
        self.assertFalse(environment.local_path.exists())
        self.assertTrue(remote_path.startswith("/tmp/.handbook-trapi-token-"))
        self.assertTrue(
            all(
                "test-secret-token" not in command
                for command in environment.commands
            )
        )

    def test_removes_remote_token_when_upload_fails(self) -> None:
        environment = FakeEnvironment(upload_error=RuntimeError("upload failed"))
        agent = OpenHandsAgent.__new__(OpenHandsAgent)

        with patch.dict(
            os.environ,
            {"TRAPI_AZURE_SCOPE": "api://trapi/.default"},
            clear=True,
        ), patch(
            "agent_harness.openhands_agent._trapi_token",
            return_value="test-secret-token",
        ), patch("agent_harness.openhands_agent._validated_trapi_base_url"):
            with self.assertRaisesRegex(RuntimeError, "upload failed"):
                asyncio.run(agent._stage_trapi_token(environment))

        self.assertTrue(
            any(command.startswith("rm -f ") for command in environment.commands)
        )
        self.assertIsNotNone(environment.local_path)
        self.assertFalse(environment.local_path.exists())

    def test_removes_remote_token_when_permission_change_fails(self) -> None:
        environment = FakeEnvironment(chmod_return_code=1)
        agent = OpenHandsAgent.__new__(OpenHandsAgent)

        with patch.dict(
            os.environ,
            {"TRAPI_AZURE_SCOPE": "api://trapi/.default"},
            clear=True,
        ), patch(
            "agent_harness.openhands_agent._trapi_token",
            return_value="test-secret-token",
        ), patch("agent_harness.openhands_agent._validated_trapi_base_url"):
            with self.assertRaisesRegex(RuntimeError, "failed to protect"):
                asyncio.run(agent._stage_trapi_token(environment))

        self.assertTrue(
            any(command.startswith("rm -f ") for command in environment.commands)
        )
        self.assertIsNotNone(environment.local_path)
        self.assertFalse(environment.local_path.exists())

    def test_copilot_run_uses_isolated_authenticated_relay(self) -> None:
        environment = FakeEnvironment()
        agent = OpenHandsAgent.__new__(OpenHandsAgent)
        agent.llm_kwargs = {
            "api_mode": "chat_completions",
            "reasoning_effort": "medium",
        }
        relay = MagicMock()
        relay.bearer_token = "relay-token"
        relay.container_base_url = "http://172.17.0.1:32000/v1"

        with (
            patch.dict(
                os.environ,
                {
                    "COPILOT_PROXY_BASE_URL": (
                        "http://127.0.0.1:3141/v1"
                    )
                },
                clear=True,
            ),
            patch(
                "agent_harness.openhands_agent.CopilotProxyRelay",
                return_value=relay,
            ) as relay_class,
            patch.object(
                agent,
                "_stage_secret",
                AsyncMock(return_value="/tmp/private-relay-token"),
            ) as stage_secret,
            patch.object(
                agent,
                "_execute_runner",
                AsyncMock(return_value=SimpleNamespace(return_code=0)),
            ) as execute_runner,
        ):
            result = asyncio.run(
                agent._run_through_copilot_proxy(
                    environment,
                    "gpt-5.6-sol",
                )
            )

        self.assertEqual(result.return_code, 0)
        relay_class.assert_called_once_with(
            upstream_base_url="http://127.0.0.1:3141/v1",
            bind_host="172.17.0.1",
            container_host="172.17.0.1",
            expected_model="gpt-5.6-sol",
            expected_reasoning_effort="medium",
        )
        relay.start.assert_called_once_with()
        relay.close.assert_called_once_with()
        stage_secret.assert_awaited_once_with(
            environment,
            "relay-token",
            "copilot-proxy",
        )
        execute_runner.assert_awaited_once_with(
            environment,
            env={"OPENAI_BASE_URL": "http://172.17.0.1:32000/v1"},
            credential="/tmp/private-relay-token",
            credential_label="Copilot proxy",
        )

    def test_copilot_run_requires_locked_protocol(self) -> None:
        environment = FakeEnvironment()
        for llm_kwargs, error in (
            (
                {"reasoning_effort": "medium"},
                "api_mode='chat_completions'",
            ),
            (
                {"api_mode": "chat_completions"},
                "explicit reasoning_effort",
            ),
        ):
            with self.subTest(llm_kwargs=llm_kwargs):
                agent = OpenHandsAgent.__new__(OpenHandsAgent)
                agent.llm_kwargs = llm_kwargs
                with self.assertRaisesRegex(RuntimeError, error):
                    asyncio.run(
                        agent._run_through_copilot_proxy(
                            environment,
                            "gpt-5.6-sol",
                        )
                    )

    def test_rejects_retargeted_content_named_base_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment_dir = Path(temporary_directory)
            digest = "a" * 64
            (environment_dir / "Dockerfile").write_text(
                f"FROM handbook_base:{digest}\n"
            )
            environment = SimpleNamespace(environment_dir=environment_dir)
            agent = OpenHandsAgent.__new__(OpenHandsAgent)

            with patch(
                "agent_harness.openhands_agent.subprocess.run",
                return_value=SimpleNamespace(stdout=f"sha256:{'b' * 64}\n"),
            ):
                with self.assertRaisesRegex(RuntimeError, "resolves to"):
                    asyncio.run(
                        agent._verify_content_named_base_image(environment)
                    )

    def test_accepts_matching_content_named_base_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment_dir = Path(temporary_directory)
            digest = "a" * 64
            (environment_dir / "Dockerfile").write_text(
                f"FROM handbook_base:{digest}\n"
            )
            environment = SimpleNamespace(environment_dir=environment_dir)
            agent = OpenHandsAgent.__new__(OpenHandsAgent)

            with patch(
                "agent_harness.openhands_agent.subprocess.run",
                return_value=SimpleNamespace(stdout=f"sha256:{digest}\n"),
            ):
                asyncio.run(agent._verify_content_named_base_image(environment))


if __name__ == "__main__":
    unittest.main()
