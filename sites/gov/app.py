"""Virtual login.gov.pl — a Profil Zaufany style identity stub.

Human-in-the-loop by design: it authenticates a citizen for downstream
services but performs no legally-binding action on its own. Every step is a
gov:// URI event.
"""
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/opt/twin")
from twinlib import emit  # noqa: E402

PAGE = """<!doctype html><html lang=pl><head><meta charset=utf-8><title>Profil Zaufany</title>
<style>body{{font-family:Arial;font-size:26px;margin:40px}}h1{{color:#003}}input{{font-size:26px;padding:10px;width:340px}}
button{{font-size:26px;padding:12px 28px;margin-top:20px;background:#003;color:#fff;border:0}}</style></head>
<body><h1>PROFIL ZAUFANY</h1>{body}</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def _html(self, code, body):
        page = PAGE.format(body=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers(); self.wfile.write(page)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        emit("gov://login.gov.pl/auth/query/form", actor="login.gov.pl")
        self._html(200, "<form method=post action=/auth><label>Login PZ</label><br>"
                   "<input name=login autofocus><br><button>Zaloguj przez PZ</button></form>")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        emit("gov://login.gov.pl/auth/command/assert", actor=form.get("login", "?"))
        self._html(200, f"<h1>ZALOGOWANO</h1><p>Tozsamosc potwierdzona: <b>{form.get('login','')}</b></p>")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9840"))
    print(f"gov on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
