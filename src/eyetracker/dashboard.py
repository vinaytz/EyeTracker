"""A small local web server for browsing the stats. It listens on this machine only."""

from __future__ import annotations

import json
import logging
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from eyetracker import guards
from eyetracker.config import Paths
from eyetracker.report import Report, read_status

log = logging.getLogger(__name__)

INDEX = Path(__file__).parent / "static" / "index.html"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'"


def payload(paths: Paths, day: date) -> dict:
    report = Report(paths.db)
    return {
        "today": date.today().isoformat(),
        "summary": report.summary(day),
        "timeline": report.timeline(day),
        "history": report.history(date.today()),
        "live": read_status(paths.status, guards.paused_until(paths.pause)),
    }


def make_handler(paths: Paths) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            if host not in ALLOWED_HOSTS:  # blocks DNS rebinding from other sites
                self._send(403, "text/plain", b"Forbidden")
                return
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, "text/html; charset=utf-8", INDEX.read_bytes())
            elif url.path == "/api/data":
                self._send_data(parse_qs(url.query))
            else:
                self._send(404, "text/plain", b"Not found")

        def _send_data(self, query: dict) -> None:
            try:
                day = date.fromisoformat(query["day"][0]) if "day" in query else date.today()
            except ValueError:
                self._send(400, "text/plain", b"day must look like 2026-11-03")
                return
            body = json.dumps(payload(paths, day)).encode()
            self._send(200, "application/json", body)

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            log.debug(format, *args)

    return Handler


def serve(paths: Paths, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(paths))
