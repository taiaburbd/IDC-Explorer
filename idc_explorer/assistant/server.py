"""Local portal page for the IDC assistant. No account.

The page and the stdio tool loop both call tools.py.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import tools

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.address_string()}] {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = (HERE / "static" / "index.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
            return
        if path == "/mcp/tools":
            self._json(200, {"tools": tools.TOOLS})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": "expected JSON"})
            return
        try:
            if path == "/ask":
                answer = tools.ask(payload.get("question", ""), bool(payload.get("confirm_large")))
                self._json(200, answer)
                return
            if path == "/notebook":
                answer = payload.get("answer")
                if not answer:
                    answer = tools.ask(payload.get("question", ""), bool(payload.get("confirm_large")))
                body = tools.notebook_bytes(answer)
                self._send(200, body, "application/json", "idc_cohort.ipynb")
                return
            if path == "/mcp/call":
                result = tools.call_tool(payload["name"], payload.get("arguments") or {})
                self._json(200, {"result": result})
                return
        except Exception as exc:  # surface query errors to the page
            self._json(400, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"IDC assistant at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
