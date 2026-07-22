"""webmock — one server, many branded mock sites, routed by the Host header.

The virtual internet's stand-ins for popular social/global services. Instead of
25 separate containers, a single service reads brands.json and renders a
believable branded landing per domain (login form for socials, search box for
Google, a feed teaser, a shop card…). Every page view and form action is a
``web://<domain>/...`` URI event on the bus, so automations can be reported and
replayed exactly like the bank/gov sites. Real domain names + valid HTTPS come
from the Caddy proxy + local CA (see build.py / ca/gen.sh).

Stdlib only; same shape as sites/gov/app.py.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/opt/twin")
from twinlib import TwinRequestHandler, emit, emit_error  # noqa: E402

BRANDS_FILE = Path(os.environ.get("BRANDS_FILE", "/app/brands.json"))


def _load_brands() -> dict[str, dict]:
    data = json.loads(BRANDS_FILE.read_text(encoding="utf-8"))
    return {b["domain"]: b for b in data.get("brands", [])}


BRANDS = _load_brands()

_SHELL = """<!doctype html><html lang=pl><head><meta charset=utf-8>
<title>{name}</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{{--brand:{color}}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#f2f3f5;color:#111}}
header{{background:var(--brand);color:#fff;padding:14px 22px;font-size:24px;font-weight:700;display:flex;align-items:center;gap:12px}}
.badge{{margin-left:auto;font-size:12px;font-weight:600;background:rgba(255,255,255,.22);padding:4px 10px;border-radius:12px}}
main{{max-width:720px;margin:40px auto;padding:0 20px}}
.card{{background:#fff;border:1px solid #dfe1e5;border-radius:14px;padding:28px;margin:18px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
h1{{margin:0 0 6px;font-size:30px}}
p.tag{{color:#555;font-size:18px;margin:0 0 22px}}
input,textarea{{font-size:18px;padding:12px;width:100%;border:1px solid #ccc;border-radius:10px;margin:6px 0}}
button{{font-size:18px;font-weight:700;padding:12px 26px;background:var(--brand);color:#fff;border:0;border-radius:10px;cursor:pointer;margin-top:12px}}
.feed .post{{border-top:1px solid #eee;padding:14px 0}}
.small{{color:#888;font-size:13px}}
a{{color:var(--brand)}}
</style></head><body>
<header>{name}<span class=badge>atrapa · wirtualny internet</span></header>
<main>{body}</main>
<footer style="text-align:center;color:#aaa;font-size:12px;padding:24px">
{domain} — lokalna atrapa bliźniaka ifURI. Żaden ruch nie opuszcza sieci netpl.</footer>
</body></html>"""


def _login_form(action: str, label: str = "E-mail lub telefon", extra: str = "") -> str:
    return (f"<form method=post action='{action}'>"
            f"<label>{label}</label><input name=login autofocus autocomplete=off>"
            f"<label>Hasło</label><input name=haslo type=password>{extra}"
            f"<button>Zaloguj się</button></form>")


def _body_for(brand: dict) -> str:
    kind, name, tag = brand["kind"], brand["name"], brand["tagline"]
    head = f"<div class=card><h1>{name}</h1><p class=tag>{tag}</p>"
    if kind == "social":
        return head + _login_form("/auth") + "</div>" + (
            "<div class='card feed'><b>Na skróconej osi:</b>"
            "<div class=post>Kolega z pracy dodał zdjęcie z konferencji. <span class=small>2 godz.</span></div>"
            "<div class=post>Grupa „Automatyzacja PL” — nowy wątek. <span class=small>wczoraj</span></div></div>")
    if kind == "video":
        return head + ("<form method=post action='/play'><label>Szukaj filmu</label>"
                       "<input name=q placeholder='wpisz tytuł'><button>Odtwórz</button></form></div>"
                       "<div class='card feed'><div class=post>▶ Polecane: „Jak działa cyfrowy bliźniak” · 12:04</div>"
                       "<div class=post>▶ Na żywo: transmisja testowa</div></div>")
    if kind == "search":
        return head + ("<form method=post action='/search'><input name=q autofocus "
                       "placeholder='Szukaj w wirtualnym internecie'><button>Szukaj</button></form></div>")
    if kind == "mail":
        return head + _login_form("/auth", "Adres Gmail") + "</div>"
    if kind == "shop":
        return head + ("<div class=post><b>CyberMysz</b> — bliźniak pracownika · <b>555,00 zł</b></div>"
                       "<div class=post><b>Klawiatura biurowa</b> · 149,00 zł</div>"
                       "<form method=post action='/order'><label>E-mail do zamówienia</label>"
                       "<input name=email placeholder='biuro@firma.pl'><button>Kup i zapłać</button></form></div>")
    if kind == "wiki":
        return head + ("<form method=post action='/search'><input name=q autofocus "
                       "placeholder='Szukaj hasła'><button>Szukaj</button></form>"
                       "<p class=small>Wolna encyklopedia w wersji lokalnej.</p></div>")
    if kind == "dev":
        return head + ("<form method=post action='/search'><input name=q autofocus "
                       "placeholder='Szukaj repozytoriów / pytań'><button>Szukaj</button></form></div>")
    # portal (news)
    return head + ("<div class=post><b>Wiadomość dnia:</b> Bliźniak biurowy przechodzi testy end-to-end.</div>"
                   "<div class=post>Gospodarka · Technologie · Sport</div></div>")


class WebMockHandler(TwinRequestHandler):
    server_version = "webmock/1.0"

    def _brand(self) -> "dict | None":
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        host = host[4:] if host.startswith("www.") else host
        return BRANDS.get(host)

    def _html(self, code: int, brand: dict, body: str):
        page = _SHELL.format(name=brand["name"], color=brand["color"],
                             domain=brand["domain"], body=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers(); self.wfile.write(page)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        brand = self._brand()
        if not brand:
            host = (self.headers.get("Host") or "?").split(":")[0]
            emit_error(f"web://{host}", "not-found",
                       f"no mock brand for host {host}", scheme="web", actor="webmock")
            self.send_response(404); self.end_headers()
            self.wfile.write(f"brak atrapy dla {host}".encode()); return
        emit(f"web://{brand['domain']}/strona/query/view", actor=brand["domain"], kind=brand["kind"])
        self._html(200, brand, _body_for(brand))

    def do_POST(self):
        brand = self._brand()
        if not brand:
            self.send_response(404); self.end_headers(); return
        action = urlparse(self.path).path.lstrip("/") or "submit"
        length = int(self.headers.get("Content-Length", "0"))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        # actor = login/email when present, else the brand
        who = form.get("login") or form.get("email") or brand["domain"]
        emit(f"web://{brand['domain']}/{action}/command/submit", actor=who,
             **{k: v for k, v in form.items() if k != "haslo"})  # never log the password
        done = {
            "auth": f"<h1>Zalogowano</h1><p>Witaj, <b>{form.get('login','')}</b>.</p>",
            "search": f"<h1>Wyniki</h1><p>Zapytanie: <b>{form.get('q','')}</b> — 3 wyniki (atrapa).</p>",
            "play": f"<h1>Odtwarzanie</h1><p>▶ <b>{form.get('q','')}</b> (atrapa).</p>",
            "order": f"<h1>Zamówienie przyjęte</h1><p>Potwierdzenie na: <b>{form.get('email','')}</b>.</p>",
        }.get(action, "<h1>Przyjęto</h1>")
        self._html(200, brand, f"<div class=card>{done}</div>")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9860"))
    print(f"webmock on :{port} — {len(BRANDS)} atrap: {', '.join(sorted(BRANDS))}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), WebMockHandler).serve_forever()
