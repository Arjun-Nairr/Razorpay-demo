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
"""

from __future__ import annotations

import argparse
import http.server
import urllib.error
import urllib.request

ALLOWED_PATH = "/webhooks/razorpay-test"
_FORWARD_HEADERS = ("X-Razorpay-Signature", "X-Razorpay-Event-Id")


class RelayHandler(http.server.BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:8000"  # set on the class before serving

    def _reject(self, code: int, detail: str) -> None:
        body = f'{{"detail":"{detail}"}}'.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method: str) -> None:
        if self.path != ALLOWED_PATH:
            self._reject(404, "not found")
            return
        if method != "POST":
            self._reject(405, "method not allowed")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
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

    def log_message(self, fmt: str, *args: object) -> None:
        # Sanitized: BaseHTTPRequestHandler's default log line is just
        # "<client> - - [<time>] <request-line> <status>" - method, path,
        # protocol version, and status code. Never headers, body, or secrets.
        print(f"[relay] {self.address_string()} {fmt % args}")


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
