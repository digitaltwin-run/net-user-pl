"""Shared twin helpers: emit URI events, and standardized error:// / log:// data.

Errors and logs follow the urirun conventions so any process, service or runtime
on the bus can consume them uniformly:

  error://<target>/<code>/query/info   code = E-sha1(scheme|type|message)[:8]
  log://<target>/<stream>/command/write

Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

EVENTBUS = os.environ.get("EVENTBUS_URL", "http://eventbus:9800")
DOCS_BASE = "https://docs.ifuri.com/errors.html"

# minimal gRPC-style categorization mirroring urirun_runtime.errors.classify
_RULES = (
    ("UNIMPLEMENTED", ("not implemented", "no checkout", "unavailable path", "no executor")),
    ("NOT_FOUND", ("no such", "not found", "missing", "brak")),
    ("ALREADY_EXISTS", ("already exists", "duplicate")),
    ("PERMISSION_DENIED", ("default deny", "not allowed", "denied", "forbidden", "bledny")),
    ("FAILED_PRECONDITION", ("precondition", "requires", "blocked", "cannot proceed", "wymaga")),
    ("UNAVAILABLE", ("connection refused", "unreachable", "unavailable", "refused")),
    ("DEADLINE_EXCEEDED", ("timed out", "timeout")),
    ("INVALID_ARGUMENT", ("invalid", "malformed", "schema", "niepoprawn")),
)
_CATEGORY_STATUS = {
    "NOT_FOUND": 404, "PERMISSION_DENIED": 403, "FAILED_PRECONDITION": 412,
    "UNAVAILABLE": 503, "DEADLINE_EXCEEDED": 504, "INVALID_ARGUMENT": 400,
    "ALREADY_EXISTS": 409, "UNIMPLEMENTED": 501, "UNKNOWN": 500,
}


class TwinRequestHandler(BaseHTTPRequestHandler):
    """Common HTTP mechanics for the small services in the virtual internet."""

    def log_message(self, *_args) -> None:
        return

    def send_bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_bytes(code, body, "application/json; charset=utf-8")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode())
        return {key: items[0] for key, items in values.items()}

    def redirect(self, location: str, *, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()


def _post(uri: str, actor: str, payload: dict) -> None:
    body = json.dumps({"uri": uri, "actor": actor, "payload": payload}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{EVENTBUS}/emit", data=body,
            headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


def emit(uri: str, actor: str = "system", **payload) -> None:
    """Record a generic URI event."""
    _post(uri, actor, payload)


def classify(error_type: str, message: str) -> str:
    low = (message or "").lower()
    for category, needles in _RULES:
        if any(n in low for n in needles):
            return category
    return "UNKNOWN"


def error_code(error_type: str, message: str, scheme: str = "") -> str:
    norm = re.sub(r"\d+", "N", (message or "").strip().lower())
    basis = f"{scheme}|{error_type}|{norm}"
    return f"E-{hashlib.sha1(basis.encode()).hexdigest()[:8]}"


def emit_error(target: str, error_type: str, message: str, *, scheme: str = "",
               source_uri: str = "", severity: str = "error", actor: str = "system",
               category: str = "") -> str:
    """Record a standardized error:// address + record. Returns the error code."""
    category = category or classify(error_type, message)
    code = error_code(error_type, message, scheme)
    status = _CATEGORY_STATUS.get(category, 500)
    uri = f"error://{target}/{code}/query/info"
    _post(uri, actor, {
        "code": code, "ts": time.time(), "sourceUri": source_uri, "scheme": scheme,
        "type": error_type, "category": category, "severity": severity,
        "status": status, "message": message,
        "help": f"{DOCS_BASE}?code={code}&category={category}",
    })
    return code


def emit_log(target: str, stream: str, message: str, *, level: str = "info",
             actor: str = "system", **fields) -> None:
    """Record a standardized log:// line."""
    uri = f"log://{target}/{stream}/command/write"
    _post(uri, actor, {"ts": time.time(), "level": level, "message": message, **fields})
