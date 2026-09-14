"""Authenticated Docker bridge relay for the local VS Code Copilot server."""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_REQUEST_BYTES = 64 * 1024 * 1024
UPSTREAM_TIMEOUT_SEC = 620


def validated_copilot_proxy_base_url(value: str) -> str:
    """Return a normalized loopback-only upstream URL."""
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("COPILOT_PROXY_BASE_URL has an invalid port") from exc

    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or port is None
        or parsed.path != "/v1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "COPILOT_PROXY_BASE_URL must be an HTTP loopback URL ending "
            "exactly in /v1, for example http://127.0.0.1:3141/v1"
        )
    return base_url


def validated_relay_host(value: str, variable_name: str) -> str:
    """Require an explicit private IPv4 address for relay binding/routing."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise RuntimeError(f"{variable_name} must be an IPv4 address") from exc
    if (
        address.version != 4
        or address.is_unspecified
        or address.is_multicast
        or not (address.is_private or address.is_loopback)
    ):
        raise RuntimeError(
            f"{variable_name} must be a private or loopback IPv4 address"
        )
    return str(address)


class _RelayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    upstream_base_url: str
    bearer_token: str
    expected_model: str
    expected_reasoning_effort: str


class _RelayHandler(BaseHTTPRequestHandler):
    server: _RelayHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "HandbookCopilotRelay/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path != "/v1/models":
            self._write_json(404, {"error": {"message": "Not found"}})
            return
        try:
            status, body, content_type = self._upstream_request("GET", "/models")
            if status == 200:
                self._require_expected_model(body)
            self._write_raw(status, body, content_type)
        except Exception as exc:
            self._write_upstream_error(exc)

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if self.path != "/v1/chat/completions":
            self._write_json(404, {"error": {"message": "Not found"}})
            return

        try:
            body = self._read_body()
            request = json.loads(body)
            if not isinstance(request, dict):
                raise ValueError("request body must be a JSON object")
            self._validate_completion_request(request)

            models_status, models_body, _ = self._upstream_request(
                "GET", "/models"
            )
            if models_status != 200:
                raise RuntimeError(
                    f"model-list preflight returned HTTP {models_status}"
                )
            self._require_expected_model(models_body)

            status, response_body, content_type = self._upstream_request(
                "POST", "/chat/completions", body
            )
            if status == 200:
                self._validate_completion_response(response_body)
            self._write_raw(status, response_body, content_type)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._write_json(400, {"error": {"message": str(exc)}})
        except Exception as exc:
            self._write_upstream_error(exc)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.bearer_token}"
        if hmac.compare_digest(supplied, expected):
            return True
        self._write_json(401, {"error": {"message": "Unauthorized"}})
        return False

    def _read_body(self) -> bytes:
        value = self.headers.get("Content-Length")
        if value is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(value)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError(
                f"request body must be between 0 and {MAX_REQUEST_BYTES} bytes"
            )
        return self.rfile.read(length)

    def _validate_completion_request(self, request: dict[str, Any]) -> None:
        observed_model = request.get("model")
        if observed_model != self.server.expected_model:
            raise ValueError(
                "model mismatch: "
                f"expected {self.server.expected_model!r}, "
                f"received {observed_model!r}"
            )
        if request.get("stream") is True:
            raise ValueError("the VS Code Copilot proxy does not support streaming")

        reasoning = request.get("reasoning")
        observed_effort = (
            reasoning.get("effort") if isinstance(reasoning, dict) else None
        )
        if observed_effort != self.server.expected_reasoning_effort:
            raise ValueError(
                "reasoning effort mismatch: "
                f"expected {self.server.expected_reasoning_effort!r}, "
                f"received {observed_effort!r}"
            )

    def _require_expected_model(self, body: bytes) -> None:
        payload = json.loads(body)
        models = payload.get("data") if isinstance(payload, dict) else None
        identifiers = {
            item.get("id")
            for item in models or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if self.server.expected_model not in identifiers:
            raise RuntimeError(
                f"Copilot does not advertise requested model "
                f"{self.server.expected_model!r}"
            )

    def _validate_completion_response(self, body: bytes) -> None:
        payload = json.loads(body)
        observed_model = payload.get("model") if isinstance(payload, dict) else None
        if observed_model != self.server.expected_model:
            raise RuntimeError(
                "Copilot substituted a different model: "
                f"expected {self.server.expected_model!r}, "
                f"received {observed_model!r}"
            )

    def _upstream_request(
        self, method: str, path: str, body: bytes | None = None
    ) -> tuple[int, bytes, str]:
        request = Request(
            f"{self.server.upstream_base_url}{path}",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=UPSTREAM_TIMEOUT_SEC) as response:
                return (
                    response.status,
                    response.read(),
                    response.headers.get("Content-Type", "application/json"),
                )
        except HTTPError as exc:
            return (
                exc.code,
                exc.read(),
                exc.headers.get("Content-Type", "application/json"),
            )
        except (OSError, URLError) as exc:
            raise RuntimeError(f"could not reach the VS Code Copilot server: {exc}") from exc

    def _write_upstream_error(self, exc: Exception) -> None:
        self._write_json(
            502,
            {"error": {"message": str(exc), "type": "copilot_proxy_error"}},
        )

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        self._write_raw(
            status,
            json.dumps(payload).encode(),
            "application/json",
        )

    def _write_raw(self, status: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


class CopilotProxyRelay:
    """Expose a loopback Copilot server to one trial through an authenticated port."""

    def __init__(
        self,
        *,
        upstream_base_url: str,
        bind_host: str,
        container_host: str,
        expected_model: str,
        expected_reasoning_effort: str,
    ) -> None:
        if not expected_model or "/" in expected_model:
            raise RuntimeError(
                "the Copilot model must be a non-empty exact model ID"
            )
        if not expected_reasoning_effort:
            raise RuntimeError("a Copilot reasoning effort is required")

        self.upstream_base_url = validated_copilot_proxy_base_url(
            upstream_base_url
        )
        self.bind_host = validated_relay_host(
            bind_host, "COPILOT_PROXY_RELAY_BIND_HOST"
        )
        self.container_host = validated_relay_host(
            container_host, "COPILOT_PROXY_CONTAINER_HOST"
        )
        self.expected_model = expected_model
        self.expected_reasoning_effort = expected_reasoning_effort
        self.bearer_token = secrets.token_urlsafe(32)
        self._server: _RelayHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def container_base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Copilot relay has not been started")
        port = self._server.server_address[1]
        return f"http://{self.container_host}:{port}/v1"

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Copilot relay is already running")
        server = _RelayHTTPServer((self.bind_host, 0), _RelayHandler)
        server.upstream_base_url = self.upstream_base_url
        server.bearer_token = self.bearer_token
        server.expected_model = self.expected_model
        server.expected_reasoning_effort = self.expected_reasoning_effort
        thread = threading.Thread(
            target=server.serve_forever,
            name=f"copilot-relay-{server.server_address[1]}",
            daemon=True,
        )
        thread.start()
        self._server = server
        self._thread = thread

    def close(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("Copilot relay did not stop cleanly")
