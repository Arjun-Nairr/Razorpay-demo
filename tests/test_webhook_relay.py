"""Offline tests for scripts/webhook_relay.py - the loopback-only relay that
is the ONLY thing a public tunnel should ever point at. No live network, no
Neon, no engine: a local stub stands in for the upstream main app.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "webhook_relay.py"
_spec = importlib.util.spec_from_file_location("webhook_relay", _MODULE_PATH)
relay_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relay_mod)  # noqa: S102 - loading our own script by path


# --- a stub "upstream" standing in for the main app's one verified route ---


class _UpstreamStub(http.server.BaseHTTPRequestHandler):
    seen: list[dict] = []  # class-level: each request the stub actually received

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        _UpstreamStub.seen.append({
            "path": self.path,
            "body": raw,
            "signature": self.headers.get("X-Razorpay-Signature"),
            "event_id": self.headers.get("X-Razorpay-Event-Id"),
        })
        body = b'{"detail":"invalid signature"}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def upstream():
    _UpstreamStub.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _UpstreamStub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def relay(upstream):
    relay_mod.RelayHandler.upstream = f"http://127.0.0.1:{upstream.server_address[1]}"
    srv = http.server.HTTPServer(("127.0.0.1", 0), relay_mod.RelayHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _url(srv, path: str) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}{path}"


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(url: str, body: bytes = b"{}", headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# --- binding -------------------------------------------------------------


def test_binds_to_loopback_only(relay):
    assert relay.server_address[0] == "127.0.0.1"


# --- only POST /webhooks/razorpay-test is served --------------------------


def test_get_on_allowed_path_is_rejected_not_forwarded(relay, upstream):
    status, _ = _get(_url(relay, "/webhooks/razorpay-test"))
    assert status == 405
    assert _UpstreamStub.seen == []  # never reached the upstream


@pytest.mark.parametrize("path", ["/", "/demo/case", "/cases/case-1", "/docs", "/health"])
def test_unrelated_paths_are_rejected_not_forwarded(relay, upstream, path):
    status, _ = _get(_url(relay, path))
    assert status == 404
    assert _UpstreamStub.seen == []


def test_post_to_an_unrelated_path_is_rejected_not_forwarded(relay, upstream):
    status, _ = _post(_url(relay, "/demo/step"))
    assert status == 404
    assert _UpstreamStub.seen == []


# --- forwarding: raw body + required headers, unchanged --------------------


def test_forwards_raw_body_and_required_headers_unchanged(relay, upstream):
    raw_body = b'{"event":"payment_link.paid","payload":{"weird": "\\u00e9 bytes"}}'
    status, resp_body = _post(
        _url(relay, "/webhooks/razorpay-test"), body=raw_body,
        headers={
            "X-Razorpay-Signature": "deadbeef" * 8,
            "X-Razorpay-Event-Id": "evt_test_1",
            "Content-Type": "application/json",
        },
    )
    assert status == 401  # the stub's fixed response, relayed back verbatim
    assert resp_body == b'{"detail":"invalid signature"}'
    assert len(_UpstreamStub.seen) == 1
    seen = _UpstreamStub.seen[0]
    assert seen["path"] == "/webhooks/razorpay-test"
    assert seen["body"] == raw_body  # byte-for-byte, untouched
    assert seen["signature"] == "deadbeef" * 8
    assert seen["event_id"] == "evt_test_1"


def test_forwards_a_post_with_no_optional_headers(relay, upstream):
    status, _ = _post(_url(relay, "/webhooks/razorpay-test"), body=b"{}")
    assert status == 401
    assert len(_UpstreamStub.seen) == 1
    assert _UpstreamStub.seen[0]["signature"] is None
    assert _UpstreamStub.seen[0]["event_id"] is None


def test_upstream_unavailable_returns_502_not_a_crash():
    relay_mod.RelayHandler.upstream = "http://127.0.0.1:1"  # nothing listens here
    srv = http.server.HTTPServer(("127.0.0.1", 0), relay_mod.RelayHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, _ = _post(_url(srv, "/webhooks/razorpay-test"))
        assert status == 502
    finally:
        srv.shutdown()


# --- the relay module itself carries no engine/DB/credentials -------------


def test_relay_module_has_no_engine_db_or_credential_references():
    source = _MODULE_PATH.read_text(encoding="utf-8")
    forbidden = ("psycopg", "RecoveryEngine", "DATABASE_URL", "RAZORPAY_KEY",
                "GEMINI_API_KEY", "PgLedger", "RazorpayTestModeAdapter")
    for term in forbidden:
        assert term not in source, f"webhook_relay.py must not reference {term!r}"


# --- Content-Length hardening: missing/malformed/negative/oversized -------


def _raw_request(port: int, request_bytes: bytes, timeout: float = 5.0) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(request_bytes)
        s.settimeout(timeout)
        chunks = []
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except (TimeoutError, socket.timeout):
            pass
        return b"".join(chunks)


def _status_of(response: bytes) -> int:
    return int(response.split(b"\r\n", 1)[0].split(b" ")[1])


def test_missing_content_length_is_rejected(relay, upstream):
    port = relay.server_address[1]
    req = (b"POST /webhooks/razorpay-test HTTP/1.1\r\n"
           b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n")
    assert _status_of(_raw_request(port, req)) == 411
    assert _UpstreamStub.seen == []


def test_malformed_content_length_is_rejected(relay, upstream):
    port = relay.server_address[1]
    req = (b"POST /webhooks/razorpay-test HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           b"Content-Length: not-a-number\r\nConnection: close\r\n\r\n")
    assert _status_of(_raw_request(port, req)) == 400
    assert _UpstreamStub.seen == []


def test_negative_content_length_is_rejected(relay, upstream):
    port = relay.server_address[1]
    req = (b"POST /webhooks/razorpay-test HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           b"Content-Length: -5\r\nConnection: close\r\n\r\n")
    assert _status_of(_raw_request(port, req)) == 400
    assert _UpstreamStub.seen == []


def test_oversized_content_length_is_rejected(relay, upstream):
    port = relay.server_address[1]
    too_big = relay_mod.MAX_BODY_BYTES + 1
    req = (f"POST /webhooks/razorpay-test HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           f"Content-Length: {too_big}\r\nConnection: close\r\n\r\n").encode()
    assert _status_of(_raw_request(port, req)) == 413
    assert _UpstreamStub.seen == []


def test_content_length_at_the_limit_is_accepted(relay, upstream):
    """The ceiling itself, not just past it, must still forward normally."""
    port = relay.server_address[1]
    body = b"x" * relay_mod.MAX_BODY_BYTES
    req = (f"POST /webhooks/razorpay-test HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body
    assert _status_of(_raw_request(port, req)) == 401  # the stub's fixed reply
    assert len(_UpstreamStub.seen) == 1
    assert _UpstreamStub.seen[0]["body"] == body


# --- bounded body-read deadline --------------------------------------------


def test_slow_body_read_times_out(monkeypatch, relay, upstream):
    monkeypatch.setattr(relay_mod, "BODY_READ_TIMEOUT_S", 0.3)
    port = relay.server_address[1]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(
            b"POST /webhooks/razorpay-test HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Length: 20\r\nConnection: close\r\n\r\n"
            b"12345"  # only 5 of the declared 20 bytes - never completes
        )
        s.settimeout(5)
        chunks = []
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except (TimeoutError, socket.timeout):
            pass
    assert _status_of(b"".join(chunks)) == 408
    assert _UpstreamStub.seen == []  # never forwarded a partial body


# --- sanitized logging: no raw path, query string, headers, or body -------


def test_query_string_is_never_logged(relay, upstream, capsys):
    status, _ = _get(_url(relay, "/webhooks/razorpay-test?secret=SUPERSECRETVALUE"))
    assert status == 404  # exact-path match only
    time.sleep(0.05)  # let the background handler thread's print land
    out = capsys.readouterr().out
    assert "SUPERSECRETVALUE" not in out
    assert "secret=" not in out
    assert "?" not in out


def test_signature_header_is_never_logged(relay, upstream, capsys):
    _post(_url(relay, "/webhooks/razorpay-test"), body=b"{}",
          headers={"X-Razorpay-Signature": "deadbeef" * 8})
    time.sleep(0.05)
    out = capsys.readouterr().out
    assert "deadbeef" not in out


def test_log_output_is_method_status_and_fixed_category_only(relay, upstream, capsys):
    _post(_url(relay, "/webhooks/razorpay-test"), body=b"{}")
    time.sleep(0.05)
    out = capsys.readouterr().out
    assert "webhook" in out and "401" in out and "POST" in out
    assert "{" not in out  # never the body
