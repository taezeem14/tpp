from __future__ import annotations

import json
import socketserver
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from importlib.resources import files
from typing import Any

from tpp.api.json_api import execute_json_request


@dataclass
class ApiServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787


class ThreadingHttpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TppApiHandler(BaseHTTPRequestHandler):
    server_version = "TppApiServer/1.0"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            html = files("tpp.api.webide").joinpath("index.html").read_text(encoding="utf-8")
            self._send_html(html)
            return

        if self.path == "/manifest":
            self._send_json(HTTPStatus.OK, {"name": "T++ API", "version": "1.0", "endpoints": ["POST /run"]})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/run":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Payload must be JSON object")
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid JSON payload: {exc}"})
            return

        result = execute_json_request(payload)
        status = HTTPStatus.OK if result.get("ok", False) else HTTPStatus.BAD_REQUEST
        self._send_json(status, result)

    def log_message(self, format: str, *args: Any) -> None:
        # Quiet default server logging for cleaner CLI output.
        return


def serve_api(config: ApiServerConfig) -> None:
    with ThreadingHttpServer((config.host, config.port), TppApiHandler) as httpd:
        print(f"T++ API server running at http://{config.host}:{config.port}")
        print("Web IDE: open the URL above in your browser")
        print("JSON endpoint: POST /run")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping T++ API server")
