"""Loopback-only relay: the ONLY thing a public tunnel should ever point at.

Understands exactly ``POST /webhooks/razorpay-test`` - every other path or
method is rejected immediately (404/405), before the request ever reaches the
main app. Forwards the raw request body and the two required headers
(``X-Razorpay-Signature``, ``X-Razorpay-Event-Id``) UNCHANGED via a local HTTP
call to the main app's already-verified route. This relay holds no engine, no
database connection, and no payment logic of its own - it is a pure reverse
proxy for one route, so tunneling it can never expose ``/demo/*``, ``/cases/*``,
or the docs, even with an unrestricted port-forwarding tunnel.

    python scripts/webhook_relay.py --port 8100 --upstream http://127.0.0.1:8000

Binds to 127.0.0.1 only - never 0.0.0.0. Public exposure is the tunnel's job.

Hardening: the body must declare a valid ``Content-Length`` no larger than
``MAX_BODY_BYTES`` (64 KiB - comfortably larger than any real
``payment_link.paid`` envelope, small enough to bound memory/time for an
unauthenticated public endpoint); reading it is bounded by
``BODY_READ_TIMEOUT_S`` so a slow/stalled sender is rejected rather than
holding the connection open. Logging never includes the raw path, query
string, headers, or body - only the request method, a fixed normalized route
category ("webhook" for the one allowed route, "rejected" for everything
else), and the response status.
"""

from __future__ import annotations

import argparse
import http.server
import socket
import urllib.error
import urllib.request

ALLOWED_PATH = "/webhooks/razorpay-test"
_FORWARD_HEADERS = ("X-Razorpay-Signature", "X-Razorpay-Event-Id")
MAX_BODY_BYTES = 65_536  # 64 KiB - documented ceiling, see module docstring
BODY_READ_TIMEOUT_S = 10.0  # bounded client body read


class RelayHandler(http.server.BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:8000"  # set on the class before serving

    def _reject(self, code: int, detail: str) -> None:
        body = f'{{"detail":"{detail}"}}'.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _content_length_or_error(self) -> tuple[int | None, int | None]:
        """Returns ``(length, None)`` on a valid, in-bounds ``Content-Length``,
        or ``(None, status_code)`` for a missing/malformed/negative/oversized
        one - never guesses a length or reads an unbounded body."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            return None, 411  # Length Required
        try:
            length = int(raw)
        except ValueError:
            return None, 400  # malformed - not an integer
        if length < 0:
            return None, 400
        if length > MAX_BODY_BYTES:
            return None, 413  # Payload Too Large
        return length, None

    def _read_body(self, length: int) -> bytes | None:
        """Bounded read: ``None`` on a timeout (the client is rejected, not
        left connected indefinitely)."""
        if length == 0:
            return b""
        previous = self.connection.gettimeout()
        self.connection.settimeout(BODY_READ_TIMEOUT_S)
        try:
            return self.rfile.read(length)
        except (TimeoutError, socket.timeout, OSError):
            return None
        finally:
            try:
                self.connection.settimeout(previous)
            except OSError:  # pragma: no cover - connection already gone
                pass

    def _handle(self, method: str) -> None:
        if self.path != ALLOWED_PATH:
            self._reject(404, "not found")
            return
        if method != "POST":
            self._reject(405, "method not allowed")
            return
        length, err = self._content_length_or_error()
        if err is not None:
            self._reject(err, "invalid content-length")
            return
        raw = self._read_body(length)
        if raw is None:
            self._reject(408, "request timeout")
            return
        headers = {"Content-Type": "application/json"}
        for name in _FORWARD_HEADERS:
            value = self.headers.get(name)
            if value is not None:
                headers[name] = value
        req = urllib.request.Request(
            self.upstream + ALLOWED_PATH, data=raw, method="POST", headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
        except urllib.error.URLError:
            self._reject(502, "upstream unavailable")
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    # -- sanitized logging only: fixed method/status + a normalized route
    #    category - never the raw path, query string, headers, or body.

    def _route_category(self) -> str:
        return "webhook" if self.path == ALLOWED_PATH else "rejected"

    def log_request(self, code="-", size="-") -> None:  # noqa: D102 - override
        print(f"[relay] {self.command} {self._route_category()} -> {code}")

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        # Reached only for errors the base class logs before/without calling
        # log_request (e.g. a malformed request line at the HTTP parsing
        # layer) - those may carry raw client bytes, so this is a silent
        # no-op rather than an attempt to sanitize arbitrary text.
        pass

    def log_error(self, fmt: str, *args: object) -> None:  # noqa: D102
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--upstream", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    RelayHandler.upstream = args.upstream.rstrip("/")
    srv = http.server.HTTPServer(("127.0.0.1", args.port), RelayHandler)
    print(f"[relay] listening on 127.0.0.1:{args.port} -> "
          f"{RelayHandler.upstream}{ALLOWED_PATH} (only route served)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
