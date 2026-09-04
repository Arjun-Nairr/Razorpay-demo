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
unauthenticated public endpoint). Reading it is bounded by an ABSOLUTE
monotonic deadline (``BODY_READ_TIMEOUT_S`` from when the read starts), not a
per-recv inactivity timer - a sender that drips one byte just inside each
individual read's timeout can never extend the total time beyond the
deadline (408). A connection that closes before exactly ``Content-Length``
bytes arrive is a premature EOF, rejected (400) and never forwarded partial.
Logging never includes the raw path, query string, headers, body, or raw HTTP
method token - only a NORMALIZED method (one of a fixed allowlist, else
``"OTHER"``), a fixed route category ("webhook"/"rejected"), and the response
status.
"""

from __future__ import annotations

import argparse
import http.server
import socket
import time
import urllib.error
import urllib.request

ALLOWED_PATH = "/webhooks/razorpay-test"
_FORWARD_HEADERS = ("X-Razorpay-Signature", "X-Razorpay-Event-Id")
MAX_BODY_BYTES = 65_536  # 64 KiB - documented ceiling, see module docstring
BODY_READ_TIMEOUT_S = 10.0  # ABSOLUTE deadline for reading the whole body
_READ_CHUNK = 8192
_KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"})


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

    def _read_body(self, length: int) -> tuple[bytes | None, str | None]:
        """Bounded, incremental read against an ABSOLUTE monotonic deadline -
        never a per-``recv`` inactivity timer that a drip-fed sender could
        reset forever. Returns ``(body, None)`` on success, or ``(None,
        "timeout")`` if the deadline expires, or ``(None, "eof")`` if the
        connection closes before exactly ``length`` bytes arrive. Never
        returns a partial body.
        """
        if length == 0:
            return b"", None
        deadline = time.monotonic() + BODY_READ_TIMEOUT_S
        previous = self.connection.gettimeout()
        chunks: list[bytes] = []
        received = 0
        try:
            while received < length:
                remaining_s = deadline - time.monotonic()
                if remaining_s <= 0:
                    return None, "timeout"  # absolute deadline - no more reads attempted
                self.connection.settimeout(remaining_s)  # recalculated every iteration
                want = min(_READ_CHUNK, length - received)
                try:
                    # read1(), not read(): read() loops internally over
                    # MULTIPLE underlying recv() calls to fill `want`, each
                    # getting its OWN fresh socket timeout - exactly the
                    # inactivity-only bug this fix exists to close. read1()
                    # makes AT MOST ONE underlying read per call (draining
                    # any already-buffered bytes first), so the timeout set
                    # just above genuinely bounds THIS iteration only.
                    chunk = self.rfile.read1(want)
                except (TimeoutError, socket.timeout, OSError):
                    return None, "timeout"
                if not chunk:
                    return None, "eof"  # connection closed before Content-Length bytes arrived
                chunks.append(chunk)
                received += len(chunk)
            return b"".join(chunks), None
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
        raw, read_err = self._read_body(length)
        if read_err == "timeout":
            self._reject(408, "request timeout")
            return
        if read_err == "eof":
            self._reject(400, "connection closed before the declared body arrived")
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

    # -- sanitized logging only: normalized method + fixed route category +
    #    status - never the raw path, query string, headers, body, or the
    #    client's raw method token (an attacker can put anything there).

    def _route_category(self) -> str:
        return "webhook" if self.path == ALLOWED_PATH else "rejected"

    def _normalized_method(self) -> str:
        cmd = self.command
        return cmd if isinstance(cmd, str) and cmd in _KNOWN_METHODS else "OTHER"

    def log_request(self, code="-", size="-") -> None:  # noqa: D102 - override
        print(f"[relay] {self._normalized_method()} {self._route_category()} -> {code}")

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
