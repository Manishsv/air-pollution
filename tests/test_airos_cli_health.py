from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_health_local_exits_0_and_mentions_read_only() -> None:
    res = _run_cli("health")
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "") + (res.stderr or "")
    assert "airos health" in out.lower()
    assert "read-only" in out.lower()
    assert "manifest" in out.lower()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health/live":
            body = {"status": "ok", "service": "airos-core", "check": "live"}
        elif self.path == "/health/ready":
            body = {
                "status": "ready",
                "service": "airos-core",
                "check": "ready",
                "checks": [{"name": "manifest", "status": "ok", "detail": "manifest loaded"}],
            }
        else:
            self.send_response(404)
            self.end_headers()
            return

        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # keep test output clean
        return


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def test_cli_health_api_mode_exits_0_when_ready() -> None:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        res = _run_cli("health", "--api-base-url", f"http://127.0.0.1:{port}")
        assert res.returncode == 0, res.stderr
        out = (res.stdout or "") + (res.stderr or "")
        assert "/health/live" not in out  # avoid echoing URLs
        assert "live:" in out.lower()
        assert "ready:" in out.lower()
    finally:
        server.shutdown()


def test_cli_health_api_unavailable_exits_nonzero() -> None:
    port = _free_port()
    # do not start server on this port
    res = _run_cli("health", "--api-base-url", f"http://127.0.0.1:{port}")
    assert res.returncode != 0

