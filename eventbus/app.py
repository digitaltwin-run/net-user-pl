"""URI event bus — the single source of truth for the digital twin.

Every action anywhere in the virtual world (DNS resolve, TLS handshake, bank
login, SMS delivery, phone read, desktop navigation) is recorded here as a
URI-addressed event, so a whole real-life episode can be replayed and every
urirun feature exercised against a faithful causal log.

    POST /emit   {"uri": "...", "payload": {...}, "actor": "..."}
    GET  /events[?since=N][&scheme=bank]   -> JSON list, newest-appended last
    GET  /health

Stdlib only; no build step.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DATA = os.environ.get("EVENTBUS_DATA", "/data/events.jsonl")
LOCK = threading.Lock()
_SEQ = [0]


def _append(record: dict) -> dict:
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with LOCK:
        _SEQ[0] += 1
        record["seq"] = _SEQ[0]
        with open(DATA, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _read(since: int, scheme: str | None) -> list[dict]:
    if not os.path.exists(DATA):
        return []
    out = []
    with open(DATA, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("seq", 0) <= since:
                continue
            if scheme and not str(rec.get("uri", "")).startswith(scheme + "://"):
                continue
            out.append(rec)
    return out


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._json(200, {"ok": True, "count": _SEQ[0]})
        if parsed.path == "/events":
            q = parse_qs(parsed.query)
            since = int(q.get("since", ["0"])[0])
            scheme = q.get("scheme", [None])[0]
            return self._json(200, {"ok": True, "events": _read(since, scheme)})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/emit":
            return self._json(404, {"ok": False, "error": "not found"})
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"ok": False, "error": "bad json"})
        uri = data.get("uri")
        if not uri:
            return self._json(400, {"ok": False, "error": "uri required"})
        rec = _append({
            "uri": uri,
            "ts": time.time(),
            "actor": data.get("actor", "system"),
            "payload": data.get("payload", {}),
        })
        return self._json(200, {"ok": True, "seq": rec["seq"]})


if __name__ == "__main__":
    # restore sequence across restarts
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as fh:
            _SEQ[0] = sum(1 for _ in fh)
    port = int(os.environ.get("PORT", "9800"))
    print(f"eventbus on :{port} -> {DATA}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
