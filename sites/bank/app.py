"""Virtual bank (mbank.pl in the twin) with SMS one-time-code login.

Flow, each step recorded as a bank:// URI event:
  GET  /            login form (login + password)
  POST /login       validate -> generate OTP -> send via SMS gateway -> /otp
  GET  /otp         one-time code entry form
  POST /otp         verify code -> dashboard
  GET  /dashboard   account overview

The bank knows the customer's phone number, so the OTP is delivered to the
virtual handset — exactly the real-world second factor.
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/opt/twin")
from twinlib import emit  # noqa: E402

SMS_URL = os.environ.get("SMS_URL", "http://sms-gateway:9810")
DOMAIN = os.environ.get("BANK_DOMAIN", "mbank.pl")
CUSTOMER = {"login": "jan.kowalski", "password": "Haslo123", "msisdn": "+48500100200",
            "name": "Jan Kowalski", "iban": "PL61109010140000071219812874", "balance": "4 812,37 PLN"}
SESSIONS: dict[str, dict] = {}
_SID = [1000]

PAGE = """<!doctype html><html lang=pl><head><meta charset=utf-8><title>{title}</title>
<style>body{{font-family:Arial,sans-serif;font-size:26px;margin:40px;color:#111}}
h1{{color:#0a4;font-size:40px}} .box{{max-width:640px}} label{{display:block;margin:18px 0 6px}}
input{{font-size:26px;padding:10px;width:360px}} button{{font-size:26px;padding:12px 28px;margin-top:24px;
background:#0a4;color:#fff;border:0;cursor:pointer}} .muted{{color:#666;font-size:20px}}</style></head>
<body><div class=box><h1>{bank}</h1>{body}</div></body></html>"""


def _sid_from(handler) -> str | None:
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    return cookie["sid"].value if "sid" in cookie else None


class Handler(BaseHTTPRequestHandler):
    def _html(self, code, title, body, set_sid=None):
        page = PAGE.format(title=title, bank=DOMAIN.upper(), body=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if set_sid:
            self.send_header("Set-Cookie", f"sid={set_sid}; Path=/")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _redirect(self, to, set_sid=None):
        self.send_response(303)
        self.send_header("Location", to)
        if set_sid:
            self.send_header("Set-Cookie", f"sid={set_sid}; Path=/")
        self.end_headers()

    def log_message(self, *a):
        return

    def _form(self):
        length = int(self.headers.get("Content-Length", "0"))
        return {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if path in ("/", "/login"):
            emit(f"bank://{DOMAIN}/login/query/form", actor=DOMAIN)
            return self._html(200, "Logowanie", (
                "<form method=post action=/login>"
                "<label>Login</label><input name=login autofocus>"
                "<label>Haslo</label><input name=password type=password>"
                "<button>Zaloguj</button></form>"))
        if path == "/otp":
            return self._html(200, "Kod SMS", (
                "<p>Wpisz jednorazowy kod SMS wyslany na Twoj telefon.</p>"
                "<form method=post action=/otp>"
                "<label>Kod SMS</label><input name=code autofocus>"
                "<button>Potwierdz</button></form>"))
        if path == "/dashboard":
            sid = _sid_from(self)
            sess = SESSIONS.get(sid or "")
            if not sess or not sess.get("authed"):
                return self._redirect("/")
            emit(f"bank://{DOMAIN}/dashboard/query/view", actor=CUSTOMER["login"])
            return self._html(200, "Pulpit", (
                f"<h1 style='color:#0a4'>PULPIT BANKOWY</h1>"
                f"<p>Zalogowano: <b>{html.escape(CUSTOMER['name'])}</b></p>"
                f"<p>Numer konta: {CUSTOMER['iban']}</p>"
                f"<p style='font-size:34px'>Saldo: <b>{CUSTOMER['balance']}</b></p>"
                f"<p class=muted>Sesja: {sid}</p>"))
        self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        form = self._form()
        if path == "/login":
            if form.get("login") == CUSTOMER["login"] and form.get("password") == CUSTOMER["password"]:
                _SID[0] += 1
                sid = f"s{_SID[0]}"
                otp = f"{int(time.time()) % 900000 + 100000}"
                SESSIONS[sid] = {"authed": False, "otp": otp, "login": CUSTOMER["login"]}
                emit(f"bank://{DOMAIN}/otp/command/request", actor=DOMAIN, msisdn=CUSTOMER["msisdn"])
                try:
                    body = json.dumps({"to": CUSTOMER["msisdn"], "from": "mBank",
                                       "text": f"mBank: kod jednorazowy {otp}. Nie podawaj go nikomu."}).encode()
                    urllib.request.urlopen(urllib.request.Request(
                        f"{SMS_URL}/send", data=body,
                        headers={"Content-Type": "application/json"}), timeout=4).read()
                except Exception as exc:
                    print("sms send failed:", exc, flush=True)
                return self._redirect("/otp", set_sid=sid)
            emit(f"bank://{DOMAIN}/login/command/reject", actor=DOMAIN, login=form.get("login"))
            return self._html(401, "Logowanie", "<p style='color:#c00'>Bledny login lub haslo.</p>"
                              "<p><a href=/>Sprobuj ponownie</a></p>")
        if path == "/otp":
            sid = _sid_from(self)
            sess = SESSIONS.get(sid or "")
            if sess and form.get("code", "").strip() == sess.get("otp"):
                sess["authed"] = True
                emit(f"bank://{DOMAIN}/session/command/login-success", actor=CUSTOMER["login"], sid=sid)
                return self._redirect("/dashboard", set_sid=sid)
            emit(f"bank://{DOMAIN}/otp/command/reject", actor=DOMAIN, sid=sid)
            return self._html(401, "Kod SMS", "<p style='color:#c00'>Bledny kod SMS.</p>"
                              "<p><a href=/otp>Sprobuj ponownie</a></p>")
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9820"))
    print(f"bank {DOMAIN} on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
