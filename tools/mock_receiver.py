"""A tiny webhook receiver for trying HookFlow on your own computer. Standard library only.

    set HOOKFLOW_SECRET=whsec_...      (Git Bash: export HOOKFLOW_SECRET=whsec_...)
    python tools/mock_receiver.py

Point an endpoint at one of these addresses (the part after the port picks the behaviour):

    http://127.0.0.1:9000/ok         answers 200
    http://127.0.0.1:9000/created    answers 201
    http://127.0.0.1:9000/fail500    answers 500   (HookFlow retries)
    http://127.0.0.1:9000/rate429    answers 429   (HookFlow retries)
    http://127.0.0.1:9000/bad400     answers 400   (HookFlow gives up at once)
    http://127.0.0.1:9000/redirect   answers 302   (HookFlow never follows redirects)
    http://127.0.0.1:9000/slow       waits 15 s    (HookFlow times out after 10 s and retries)
    http://127.0.0.1:9000/flaky      500 twice for each delivery, then 200

For the worker to accept http://127.0.0.1 you must set ALLOW_UNSAFE_WEBHOOK_URLS=true in .env.
This is for development only. A real receiver must use https.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9000
TOLERANCE_SECONDS = 300
SECRET = os.environ.get("HOOKFLOW_SECRET", "")
flaky_calls: dict[str, int] = {}


def check_signature(secret: str, timestamp: str, signature: str, raw_body: bytes) -> str:
    """Returns "valid" or the reason it is not. This is the check every real receiver should do."""
    if not secret:
        return "not checked (HOOKFLOW_SECRET is not set)"
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return "INVALID: bad timestamp header"
    if abs(time.time() - sent_at) > TOLERANCE_SECONDS:
        return "INVALID: timestamp too old or too far ahead (replay protection)"
    message = timestamp.encode() + b"." + raw_body
    expected = "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):  # constant-time compare
        return "INVALID: signature does not match"
    return "valid"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, code: int, **headers: str) -> None:
        self.send_response(code)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        verdict = check_signature(
            SECRET, self.headers.get("X-HookFlow-Timestamp", ""), self.headers.get("X-HookFlow-Signature", ""), raw
        )
        try:
            body = json.loads(raw)
            summary = f"{body.get('type')}  event={body.get('id')}"
        except ValueError:
            summary = "(body is not JSON)"
        delivery_id = self.headers.get("X-HookFlow-Delivery-ID", "?")
        path = self.path.split("?")[0]
        print(f"POST {path}  delivery={delivery_id}  {summary}  signature: {verdict}", flush=True)

        if path == "/ok":
            self.reply(200)
        elif path == "/created":
            self.reply(201)
        elif path == "/fail500":
            self.reply(500)
        elif path == "/rate429":
            self.reply(429)
        elif path == "/bad400":
            self.reply(400)
        elif path == "/redirect":
            self.reply(302, Location="/ok")
        elif path == "/slow":
            time.sleep(15)
            self.reply(200)
        elif path == "/flaky":
            flaky_calls[delivery_id] = flaky_calls.get(delivery_id, 0) + 1
            self.reply(500 if flaky_calls[delivery_id] <= 2 else 200)
        else:
            self.reply(404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"Mock receiver on http://127.0.0.1:{PORT}  (signature check: {'on' if SECRET else 'OFF, set HOOKFLOW_SECRET'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)