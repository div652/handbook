import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_harness.copilot_proxy import (
    CopilotProxyRelay,
    _RelayHandler,
    validated_copilot_proxy_base_url,
    validated_relay_host,
)


class FakeCopilotHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        self.server.state.model_requests += 1
        self._write(
            200,
            {
                "object": "list",
                "data": [
                    {"id": model, "object": "model"}
                    for model in self.server.state.models
                ],
            },
        )

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.server.state.completion_requests.append(
            {
                "body": request,
                "authorization": self.headers.get("Authorization"),
            }
        )
        self._write(
            200,
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": self.server.state.response_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            },
        )

    def _write(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CopilotProxyRelayTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            models=["gpt-5.6-sol"],
            response_model="gpt-5.6-sol",
            model_requests=0,
            completion_requests=[],
        )
        self.upstream = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            FakeCopilotHandler,
        )
        self.upstream.state = self.state
        self.upstream_thread = threading.Thread(
            target=self.upstream.serve_forever,
            daemon=True,
        )
        self.upstream_thread.start()
        self.relay = CopilotProxyRelay(
            upstream_base_url=(
                f"http://127.0.0.1:{self.upstream.server_address[1]}/v1"
            ),
            bind_host="127.0.0.1",
            container_host="127.0.0.1",
            expected_model="gpt-5.6-sol",
            expected_reasoning_effort="medium",
        )
        self.relay.start()

    def tearDown(self):
        self.relay.close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=5)

    def request(self, payload, token=None):
        request = Request(
            f"{self.relay.container_base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {token or self.relay.bearer_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def valid_request(self):
        return {
            "model": "gpt-5.6-sol",
            "messages": [{"role": "user", "content": "test"}],
            "reasoning": {"effort": "medium"},
            "stream": False,
        }

    def test_forwards_only_after_model_preflight(self):
        status, response = self.request(self.valid_request())

        self.assertEqual(status, 200)
        self.assertEqual(response["model"], "gpt-5.6-sol")
        self.assertEqual(self.state.model_requests, 1)
        self.assertEqual(len(self.state.completion_requests), 1)
        self.assertIsNone(
            self.state.completion_requests[0]["authorization"]
        )

        status, _ = self.request(self.valid_request())
        self.assertEqual(status, 200)
        self.assertEqual(self.state.model_requests, 2)

    def test_rejects_unauthorized_request(self):
        status, response = self.request(
            self.valid_request(),
            token="wrong-token",
        )

        self.assertEqual(status, 401)
        self.assertEqual(response["error"]["message"], "Unauthorized")
        self.assertEqual(self.state.model_requests, 0)
        self.assertEqual(self.state.completion_requests, [])

    def test_rejects_wrong_requested_model_before_forwarding(self):
        request = self.valid_request()
        request["model"] = "gpt-5.6-terra"

        status, response = self.request(request)

        self.assertEqual(status, 400)
        self.assertIn("model mismatch", response["error"]["message"])
        self.assertEqual(self.state.model_requests, 0)
        self.assertEqual(self.state.completion_requests, [])

    def test_rejects_unavailable_expected_model(self):
        self.state.models = ["gpt-5.6-terra"]

        status, response = self.request(self.valid_request())

        self.assertEqual(status, 502)
        self.assertIn(
            "does not advertise requested model",
            response["error"]["message"],
        )
        self.assertEqual(self.state.completion_requests, [])

    def test_rejects_substituted_response_model(self):
        self.state.response_model = "gpt-5.6-terra"

        status, response = self.request(self.valid_request())

        self.assertEqual(status, 502)
        self.assertIn(
            "substituted a different model",
            response["error"]["message"],
        )
        self.assertEqual(len(self.state.completion_requests), 1)

    def test_rejects_wrong_reasoning_effort(self):
        request = self.valid_request()
        request["reasoning"]["effort"] = "high"

        status, response = self.request(request)

        self.assertEqual(status, 400)
        self.assertIn(
            "reasoning effort mismatch",
            response["error"]["message"],
        )
        self.assertEqual(self.state.model_requests, 0)


class CopilotProxyConfigurationTests(unittest.TestCase):
    def test_client_disconnect_while_writing_is_cleanly_ignored(self):
        def disconnect(_body):
            raise BrokenPipeError

        handler = SimpleNamespace(
            send_response=lambda _status: None,
            send_header=lambda _name, _value: None,
            end_headers=lambda: None,
            wfile=SimpleNamespace(write=disconnect),
            close_connection=False,
        )

        _RelayHandler._write_raw(
            handler,
            502,
            b'{"error": "upstream timeout"}',
            "application/json",
        )

        self.assertTrue(handler.close_connection)

    def test_accepts_loopback_upstream(self):
        self.assertEqual(
            validated_copilot_proxy_base_url(
                "http://127.0.0.1:3141/v1/"
            ),
            "http://127.0.0.1:3141/v1",
        )

    def test_rejects_non_loopback_or_ambiguous_upstream(self):
        for value in (
            "http://172.17.0.1:3141/v1",
            "https://127.0.0.1:3141/v1",
            "http://127.0.0.1:3141/v1?target=other",
            "http://user@127.0.0.1:3141/v1",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "loopback URL",
                ):
                    validated_copilot_proxy_base_url(value)

    def test_relay_hosts_must_be_private_ipv4_addresses(self):
        self.assertEqual(
            validated_relay_host(
                "172.17.0.1",
                "COPILOT_PROXY_RELAY_BIND_HOST",
            ),
            "172.17.0.1",
        )
        for value in ("0.0.0.0", "8.8.8.8", "localhost", "::1"):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    validated_relay_host(
                        value,
                        "COPILOT_PROXY_RELAY_BIND_HOST",
                    )


if __name__ == "__main__":
    unittest.main()
