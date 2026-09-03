from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import threading
from typing import Any
from urllib.parse import urlsplit

from .controller import BenchmarkController


MAX_BODY_BYTES = 512 * 1024


def _valid_extension_origin(origin: str) -> bool:
    if not origin.startswith("chrome-extension://"):
        return False
    extension_id = origin.removeprefix("chrome-extension://").strip("/")
    return bool(extension_id) and extension_id.isalnum() and len(extension_id) <= 64


class CollectorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], controller: BenchmarkController):
        self.controller = controller
        super().__init__(address, CollectorRequestHandler)


class CollectorRequestHandler(BaseHTTPRequestHandler):
    server: CollectorHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _origin(self) -> str:
        return str(self.headers.get("Origin") or "")

    def _request_allowed(self) -> bool:
        origin = self._origin()
        if _valid_extension_origin(origin):
            return True
        # Facilita o autoteste/diagnóstico local sem liberar páginas web: um
        # browser normal não consegue enviar este header sem preflight, que é
        # recusado quando Origin não é chrome-extension://.
        return not origin and self.headers.get("X-SubNexus-Benchmark") == "1"

    def _cors_headers(self) -> None:
        origin = self._origin()
        if _valid_extension_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-SubNexus-Benchmark, X-SubNexus-Session",
        )
        self.send_header("Access-Control-Max-Age", "600")
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            data = self.rfile.read(length)
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def do_OPTIONS(self) -> None:
        if not _valid_extension_origin(self._origin()):
            self._send_json(403, {"ok": False, "error": "origin_not_allowed"})
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "subnexus-benchmark-passivo",
                    "session_id": self.server.controller.session_id,
                    "trial_active": self.server.controller.trial_active,
                },
            )
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if not self._request_allowed():
            self._send_json(403, {"ok": False, "error": "origin_not_allowed"})
            return

        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        path = urlsplit(self.path).path
        if path == "/api/v1/hello":
            origin = self._origin()
            origin_id = origin.removeprefix("chrome-extension://").strip("/")
            extension_id = origin_id or str(payload.get("extension_id") or "local-test")
            response = self.server.controller.hello(
                extension_id=extension_id,
                extension_version=str(payload.get("extension_version") or "unknown"),
            )
            self._send_json(200 if response.get("ok") else 403, response)
            return

        if path == "/api/v1/events":
            token = str(self.headers.get("X-SubNexus-Session") or "")
            if not hmac.compare_digest(token, self.server.controller.session_token):
                self._send_json(401, {"ok": False, "error": "invalid_session"})
                return
            events = payload.get("events")
            if not isinstance(events, list):
                self._send_json(400, {"ok": False, "error": "events_must_be_array"})
                return
            origin = self._origin()
            extension_id = (
                origin.removeprefix("chrome-extension://").strip("/")
                or str(payload.get("extension_id") or "local-test")
            )
            accepted = self.server.controller.ingest_batch(events, extension_id)
            self._send_json(
                200,
                {
                    "ok": True,
                    "accepted_sequences": accepted,
                    "trial_active": self.server.controller.trial_active,
                },
            )
            return

        self._send_json(404, {"ok": False, "error": "not_found"})


def start_server(
    host: str,
    port: int,
    controller: BenchmarkController,
) -> tuple[CollectorHTTPServer, threading.Thread]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("O coletor deve ficar restrito ao loopback.")
    server = CollectorHTTPServer((host, port), controller)
    thread = threading.Thread(
        target=server.serve_forever,
        name="BenchmarkCollectorHTTP",
        daemon=True,
    )
    thread.start()
    return server, thread
