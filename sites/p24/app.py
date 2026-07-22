"""Virtual Przelewy24 (przelewy24.pl) — the payment gateway in the twin.

A merchant (the ifURI shop) registers a payment; the buyer enters a card, and
the gateway requires a 3-D Secure SMS code delivered to the buyer's phone via
the same virtual carrier the bank uses. On success it calls the merchant back
(server-to-server) and returns the buyer to the shop.

Test card accepted: 4111 1111 1111 1111 (any exp in the future, any 3-digit cvv).
Every step is a p24:// URI event; declines/failures are standardized error://.

Routes:
  POST /register    {orderId, amount, email, title, returnUrl, callbackUrl}
  GET  /pay?order=  -> card form
  POST /pay-card    {order, card, exp, cvv} -> 3DS SMS form
  POST /pay-3ds     {order, code} -> verify -> callback merchant -> return to shop
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/opt/twin")
from twinlib import TwinRequestHandler, emit, emit_error, emit_log  # noqa: E402

DOMAIN = os.environ.get("P24_DOMAIN", "przelewy24.pl")
SMS_URL = os.environ.get("SMS_URL", "http://sms-gateway:9810")
BUYER_MSISDN = os.environ.get("BUYER_MSISDN", "+48500100200")
TEST_CARD = "4111111111111111"

PAYMENTS: dict[str, dict] = {}

PAGE = """<!doctype html><html lang=pl><head><meta charset=utf-8><title>Przelewy24</title>
<style>body{{font-family:Arial,sans-serif;font-size:24px;margin:36px}}h1{{color:#c8102e}}
.box{{max-width:560px;border:1px solid #ddd;border-radius:12px;padding:22px}}
label{{display:block;margin:14px 0 6px}}input{{font-size:24px;padding:9px;width:320px}}
button{{font-size:24px;padding:12px 26px;background:#c8102e;color:#fff;border:0;border-radius:8px;margin-top:18px;cursor:pointer}}
.amt{{font-size:30px;font-weight:bold}}</style></head><body>{body}</body></html>"""


class PaymentGatewayHandler(TwinRequestHandler):
    def _page(self, code, body):
        p = PAGE.format(body=body).encode()
        self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(p))); self.end_headers(); self.wfile.write(p)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if path == "/pay":
            oid = parse_qs(urlparse(self.path).query).get("order", [""])[0]
            p = PAYMENTS.get(oid)
            if not p:
                emit_error(DOMAIN, "unknown_payment", f"no payment for {oid}", scheme="p24", actor=DOMAIN)
                return self._page(404, "<h1>Nieznana platnosc</h1>")
            emit(f"p24://{DOMAIN}/pay/query/form", actor=DOMAIN, orderId=oid, amount=p["amount"])
            return self._page(200, (
                f"<div class=box><h1>Przelewy24</h1>"
                f"<p>{p['title']}</p><p class=amt>{p['amount']/100:.2f} zl</p>"
                f"<form method=post action=/pay-card><input type=hidden name=order value={oid}>"
                f"<label>Numer karty</label><input name=card value='4111 1111 1111 1111'>"
                f"<label>Data waznosci</label><input name=exp value='12/28'>"
                f"<label>CVV</label><input name=cvv value='123'>"
                f"<button>Zaplac</button></form></div>"))
        self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/register":
            d = self.read_json()
            oid = d.get("orderId")
            PAYMENTS[oid] = {"amount": d["amount"], "email": d.get("email", ""),
                             "title": d.get("title", ""), "returnUrl": d.get("returnUrl", ""),
                             "callbackUrl": d.get("callbackUrl", ""), "status": "registered"}
            emit(f"p24://{DOMAIN}/payment/command/register", actor=DOMAIN, orderId=oid, amount=d["amount"])
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return
        if path == "/pay-card":
            f = self.read_form()
            oid = f.get("order")
            p = PAYMENTS.get(oid or "")
            if not p:
                return self._page(404, "<h1>Nieznana platnosc</h1>")
            card = f.get("card", "").replace(" ", "")
            if card != TEST_CARD:
                code = emit_error(DOMAIN, "card_declined", f"card declined for {oid}",
                                  scheme="p24", actor=DOMAIN, category="PERMISSION_DENIED")
                return self._page(402, f"<div class=box><h1>Karta odrzucona</h1><p>Kod: {code}</p></div>")
            # issue a 3-D Secure SMS code to the buyer's phone
            otp = f"{int(time.time()) % 900000 + 100000}"
            p["otp"] = otp
            emit(f"p24://{DOMAIN}/3ds/command/challenge", actor=DOMAIN, orderId=oid, msisdn=BUYER_MSISDN)
            try:
                body = json.dumps({"to": BUYER_MSISDN, "from": "Przelewy24",
                                   "text": f"Przelewy24: kod 3D-Secure {otp} do platnosci {p['amount']/100:.2f} zl."}).encode()
                urllib.request.urlopen(urllib.request.Request(
                    f"{SMS_URL}/send", data=body, headers={"Content-Type": "application/json"}), timeout=4).read()
            except Exception as e:
                emit_error(DOMAIN, "sms_unavailable", f"3ds sms failed: {e}", scheme="p24",
                           actor=DOMAIN, category="UNAVAILABLE")
            emit_log(DOMAIN, "payment", f"3DS challenge sent for {oid}", actor=DOMAIN, orderId=oid)
            return self._page(200, (
                f"<div class=box><h1>3-D Secure</h1><p>Wpisz kod SMS z telefonu.</p>"
                f"<form method=post action=/pay-3ds><input type=hidden name=order value={oid}>"
                f"<label>Kod 3D-Secure</label><input name=code autofocus>"
                f"<button>Potwierdz platnosc</button></form></div>"))
        if path == "/pay-3ds":
            f = self.read_form()
            oid = f.get("order")
            p = PAYMENTS.get(oid or "")
            if not p:
                return self._page(404, "<h1>Nieznana platnosc</h1>")
            if f.get("code", "").strip() != p.get("otp"):
                code = emit_error(DOMAIN, "threeds_failed", f"3ds code rejected for {oid}",
                                  scheme="p24", actor=DOMAIN, category="PERMISSION_DENIED")
                return self._page(401, f"<div class=box><h1>Bledny kod 3D-Secure</h1><p>{code}</p></div>")
            p["status"] = "success"
            emit(f"p24://{DOMAIN}/payment/command/success", actor=DOMAIN, orderId=oid, amount=p["amount"])
            emit_log(DOMAIN, "payment", f"payment {oid} SUCCESS", actor=DOMAIN, level="info")
            # notify the merchant server-to-server
            try:
                body = json.dumps({"orderId": oid, "status": "success", "token": f"p24-{oid}"}).encode()
                urllib.request.urlopen(urllib.request.Request(
                    p["callbackUrl"], data=body, headers={"Content-Type": "application/json"}), timeout=5).read()
            except Exception as e:
                emit_error(DOMAIN, "callback_failed", f"merchant callback failed: {e}",
                           scheme="p24", actor=DOMAIN, category="UNAVAILABLE")
            return self.redirect(p["returnUrl"])
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9860"))
    print(f"p24 {DOMAIN} on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), PaymentGatewayHandler).serve_forever()
