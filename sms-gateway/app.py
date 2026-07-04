"""Virtual SMS network — the carrier that moves one-time codes.

A bank (or any service) POSTs a message; the gateway stores it in the
recipient's inbox and records it as a URI event. The virtual phone reads the
same inbox. This is what lets an automat obtain an OTP that a human would
normally read off their handset.

    POST /send        {"to": "+48...", "from": "mBank", "text": "..."}
    GET  /inbox/<msisdn>[?since_id=N]
    GET  /health
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/opt/twin")
from twinlib import emit  # noqa: E402

STORE: dict[str, list] = {}
LOCK = threading.Lock()
_ID = [0]


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._json(200, {"ok": True})
        if parsed.path.startswith("/inbox/"):
            msisdn = parsed.path[len("/inbox/"):]
            since = int(parse_qs(parsed.query).get("since_id", ["0"])[0])
            with LOCK:
                msgs = [m for m in STORE.get(msisdn, []) if m["id"] > since]
            return self._json(200, {"ok": True, "msisdn": msisdn, "messages": msgs})
        return self._json(404, {"ok": False})

    def do_POST(self):
        if urlparse(self.path).path != "/send":
            return self._json(404, {"ok": False})
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        to = data.get("to")
        if not to:
            return self._json(400, {"ok": False, "error": "to required"})
        with LOCK:
            _ID[0] += 1
            msg = {"id": _ID[0], "to": to, "from": data.get("from", "INFO"),
                   "text": data.get("text", ""), "ts": time.time()}
            STORE.setdefault(to, []).append(msg)
        emit(f"sms://{to}/inbox/command/deliver", actor="sms-gateway",
             sender=msg["from"], text=msg["text"], id=msg["id"])
        return self._json(200, {"ok": True, "id": msg["id"]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9810"))
    print(f"sms-gateway on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
