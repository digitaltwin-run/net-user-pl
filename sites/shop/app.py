"""Virtual ifURI shop (sklep.ifuri.com) — the CyberMysz sales funnel.

Closes the purchase path the buyer persona found missing: a pricing page, a
product page, a checkout form, and a hand-off to the Przelewy24 payment gateway.
On successful payment (confirmed by p24's server-to-server callback) the order
is marked paid and a license is issued — which the customer persona then uses.

Every step is a shop:// URI event; failures are standardized error://.

Routes:
  GET  /               -> product (CyberMysz)
  GET  /cennik         -> pricing (BASIC / PRO / PrePaid)
  POST /checkout       {plan, email} -> create order, redirect to p24
  GET  /order?id=      -> order status (+ license when paid)
  POST /p24-callback   {orderId, status, token} -> mark paid (from p24)
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/opt/twin")
from twinlib import TwinRequestHandler, emit, emit_error, emit_log  # noqa: E402

DOMAIN = os.environ.get("SHOP_DOMAIN", "sklep.ifuri.com")
P24 = os.environ.get("P24_URL", "https://przelewy24.pl")
P24_INTERNAL = os.environ.get("P24_INTERNAL", "http://p24:9860")

PLANS = {
    "BASIC": {"name": "CyberMysz + BASIC Cloud", "gross": 55500, "actions": 1000,
              "desc": "Urzadzenie CyberMysz. BASIC Cloud w cenie przez 24 miesiace, 1000 akcji/mies."},
    "PRO": {"name": "PRO Cloud", "gross": 10000, "actions": 10000,
            "desc": "Dla firm z wieksza liczba procesow."},
    "PREPAID": {"name": "PrePaid 10 000 akcji", "gross": 10000, "actions": 10000,
                "desc": "Dodatkowy pakiet, wazny 12 miesiecy."},
}
ORDERS: dict[str, dict] = {}
LICENSES: dict[str, dict] = {}   # license -> order (with remaining quota)
_OID = [70000]

PAGE = """<!doctype html><html lang=pl><head><meta charset=utf-8><title>{title}</title>
<style>body{{font-family:Arial,sans-serif;font-size:24px;margin:36px;color:#111}}
h1{{color:#5b2ea6;font-size:38px}} .card{{border:1px solid #ddd;border-radius:12px;padding:20px;margin:14px 0;max-width:680px}}
.price{{font-size:30px;font-weight:bold}} a.btn,button{{display:inline-block;font-size:24px;padding:12px 26px;background:#5b2ea6;color:#fff;border:0;text-decoration:none;border-radius:8px;cursor:pointer}}
label{{display:block;margin:14px 0 6px}} input,select{{font-size:24px;padding:9px;width:340px}}</style></head>
<body>{body}</body></html>"""


class ShopHandler(TwinRequestHandler):
    def _page(self, code, title, body):
        p = PAGE.format(title=title, body=body).encode()
        self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(p))); self.end_headers(); self.wfile.write(p)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if path == "/":
            emit(f"shop://{DOMAIN}/product/query/view", actor=DOMAIN, product="CyberMysz")
            b = ("<h1>CyberMysz</h1>"
                 "<div class=card><p>Cyfrowy blizniak pracownika biurowego. Widzi ekran, klika i wpisuje "
                 "dane wedlug przygotowanych regul.</p>"
                 "<p class=price>555,00 zl brutto</p><p>451,22 zl netto + VAT 23%</p>"
                 "<ul><li>BASIC Cloud w cenie przez 24 miesiace</li><li>1000 akcji miesiecznie</li>"
                 "<li>Status zamowienia i instrukcja uruchomienia</li></ul>"
                 "<a class=btn href=/cennik>Zamow CyberMysz</a></div>")
            return self._page(200, "CyberMysz", b)
        if path == "/cennik":
            emit(f"shop://{DOMAIN}/pricing/query/view", actor=DOMAIN)
            cards = ""
            for key, p in PLANS.items():
                cards += (f"<div class=card><h2>{key} — {html.escape(p['name'])}</h2>"
                          f"<p>{html.escape(p['desc'])}</p><p class=price>{p['gross']/100:.2f} zl</p>"
                          f"<form method=post action=/checkout><input type=hidden name=plan value={key}>"
                          f"<label>E-mail</label><input name=email value='marek@firma.pl'>"
                          f"<button>Kup i zaplac</button></form></div>")
            return self._page(200, "Cennik", "<h1>Cennik</h1>" + cards)
        if path == "/order":
            oid = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            o = ORDERS.get(oid)
            if not o:
                emit_error(f"{DOMAIN}", "order_not_found", f"no such order {oid}", scheme="shop", actor=DOMAIN)
                return self._page(404, "Zamowienie", "<h1>Nie znaleziono zamowienia</h1>")
            emit(f"shop://{DOMAIN}/order/query/status", actor=DOMAIN, orderId=oid, status=o["status"])
            lic = f"<p>Licencja: <b>{o.get('license','')}</b></p>" if o["status"] == "paid" else ""
            return self._page(200, "Zamowienie", (
                f"<h1>Zamowienie {oid}</h1><p class=price>Status: {o['status'].upper()}</p>"
                f"<p>{o['plan']} — {PLANS[o['plan']]['actions']} akcji/mies.</p>{lic}"))
        self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/checkout":
            f = self.read_form()
            plan = f.get("plan", "BASIC")
            if plan not in PLANS:
                emit_error(DOMAIN, "invalid_plan", f"unknown plan {plan}", scheme="shop", actor=DOMAIN)
                return self._page(400, "Blad", "<h1>Nieznany plan</h1>")
            _OID[0] += 1
            oid = f"ORD-{_OID[0]}"
            ORDERS[oid] = {"plan": plan, "email": f.get("email", ""), "status": "pending",
                           "gross": PLANS[plan]["gross"], "ts": time.time()}
            emit(f"shop://{DOMAIN}/order/command/create", actor=DOMAIN, orderId=oid, plan=plan,
                 gross=PLANS[plan]["gross"])
            emit_log(DOMAIN, "checkout", f"order {oid} created for {plan}", actor=DOMAIN, orderId=oid)
            # register the payment with Przelewy24, then send the buyer there
            try:
                body = json.dumps({"orderId": oid, "amount": PLANS[plan]["gross"],
                                   "email": f.get("email", ""), "title": PLANS[plan]["name"],
                                   "returnUrl": f"https://{DOMAIN}/order?id={oid}",
                                   "callbackUrl": f"http://shop:9850/p24-callback"}).encode()
                urllib.request.urlopen(urllib.request.Request(
                    f"{P24_INTERNAL}/register", data=body,
                    headers={"Content-Type": "application/json"}), timeout=5).read()
            except Exception as e:
                emit_error(DOMAIN, "p24_unreachable", f"cannot register payment: {e}",
                           scheme="shop", actor=DOMAIN, category="UNAVAILABLE")
                return self._page(502, "Blad", "<h1>Bramka platnosci niedostepna</h1>")
            return self.redirect(f"{P24}/pay?order={oid}")
        if path == "/use":
            # CyberMysz consumes one action against a paid license
            n = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(n) or b"{}")
            lic = data.get("license", "")
            o = LICENSES.get(lic)
            if not o:
                emit_error(DOMAIN, "license_invalid", f"unknown license {lic}", scheme="shop", actor=DOMAIN)
                self.send_response(403); self.end_headers(); self.wfile.write(b'{"ok":false}'); return
            if o.get("quota", 0) <= 0:
                code = emit_error(DOMAIN, "quota_exhausted", f"no actions left on {lic}",
                                  scheme="shop", actor=DOMAIN, category="RESOURCE_EXHAUSTED")
                self.send_response(402); self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": code}).encode()); return
            o["quota"] -= 1
            action = data.get("action", "action")
            emit(f"shop://{DOMAIN}/cybermysz/command/use", actor=lic, action=action, remaining=o["quota"])
            emit_log(DOMAIN, "usage", f"{lic} used '{action}', remaining {o['quota']}", actor=DOMAIN)
            body = json.dumps({"ok": True, "remaining": o["quota"], "used": action}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if path == "/p24-callback":
            n = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(n) or b"{}")
            oid = data.get("orderId")
            o = ORDERS.get(oid or "")
            if not o:
                return (self.send_response(404), self.end_headers())
            if data.get("status") == "success":
                o["status"] = "paid"
                o["license"] = f"CM-{oid[-5:]}-{PLANS[o['plan']]['actions']}"
                o["quota"] = PLANS[o["plan"]]["actions"]
                LICENSES[o["license"]] = o
                emit(f"shop://{DOMAIN}/order/command/paid", actor=DOMAIN, orderId=oid, license=o["license"])
                emit_log(DOMAIN, "checkout", f"order {oid} PAID; license {o['license']}", actor=DOMAIN, level="info")
            else:
                emit_error(DOMAIN, "payment_failed", f"payment failed for {oid}", scheme="shop", actor=DOMAIN)
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9850"))
    print(f"shop {DOMAIN} on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), ShopHandler).serve_forever()
