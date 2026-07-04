# webmock — atrapy popularnych serwisów w wirtualnym internecie

Jeden serwer, wiele atrap markowych stron, routowanych po nagłówku **Host**.
Zamiast osobnego kontenera na każdą markę, `app.py` czyta `brands.json` i renderuje
wiarygodną, markową stronę dla każdej domeny (formularz logowania dla sociali,
wyszukiwarka dla Google, kartę produktu dla sklepu…). Każde wejście i akcja to
zdarzenie **`web://<domena>/...`** na szynie — dokładnie jak atrapy banku/gov, więc
automatyzacje da się raportować i odtwarzać.

Nazwy domen są **prawdziwe** (np. `facebook.com`), a ważny HTTPS pochodzi z lokalnego
CA przez proxy Caddy — spójnie z resztą bliźniaka (`mbank.pl`). Cały ruch zostaje
w sieci `netpl`; nic nie wychodzi do prawdziwego internetu. To świadomie mocniejszy
wariant niż `*.localhost` z Traefikiem (patrz `TODO/`): daje realny HTTPS i realne
nazwy domen, których potrzebują testy przeglądarkowe.

## Zawarte atrapy (31)

| Adres | Marka | Typ UI |
| --- | --- | --- |
| `https://facebook.com` | Facebook | social |
| `https://instagram.com` | Instagram | social |
| `https://x.com` | X | social |
| `https://linkedin.com` | LinkedIn | social |
| `https://reddit.com` | Reddit | social |
| `https://tiktok.com` | TikTok | video |
| `https://youtube.com` | YouTube | video |
| `https://netflix.com` | Netflix | video |
| `https://spotify.com` | Spotify | video |
| `https://google.com` | Google | search |
| `https://gmail.com` | Gmail | mail |
| `https://wikipedia.org` | Wikipedia | wiki |
| `https://github.com` | GitHub | dev |
| `https://stackoverflow.com` | Stack Overflow | dev |
| `https://amazon.pl` | Amazon | shop |
| `https://allegro.pl` | Allegro | shop |
| `https://olx.pl` | OLX | shop |
| `https://wp.pl` | WP | portal |
| `https://onet.pl` | Onet | portal |
| `https://discord.com` | Discord | social |
| `https://whatsapp.com` | WhatsApp | social |
| `https://telegram.org` | Telegram | social |
| `https://airbnb.com` | Airbnb | shop |
| `https://booking.com` | Booking.com | shop |
| `https://pekao.pl` | Bank Pekao | social |
| `https://ing.pl` | ING | social |
| `https://santander.pl` | Santander | social |
| `https://pkobp.pl` | PKO BP | social |
| `https://ceneo.pl` | Ceneo | shop |
| `https://empik.com` | Empik | shop |
| `https://x-kom.pl` | x-kom | shop |

Typy UI (`kind`): `social` (login+feed), `video`, `search`, `mail`, `shop`,
`wiki`, `dev`, `portal`.

## Uruchomienie (część `net-user-pl`)

```bash
cd net-user-pl
python3 sites/webmock/build.py        # z brands.json → certy/Caddy/aliasy (idempotentne)
bash ca/gen.sh                        # wystaw certy liście domen (w tym atrap)
docker network create netpl           # idempotentne
docker compose -f compose.net.yml up -d --build
```

Test (wewnątrz sieci netpl, z lokalnym CA):

```bash
docker run --rm --network netpl -v $PWD/ca/out:/ca:ro curlimages/curl   -s --cacert /ca/rootCA.pem https://facebook.com/ | head
curl -s 'http://127.0.0.1:28800/events?scheme=web' | python3 -m json.tool   # zdarzenia web://
```

Z pulpitu bliźniaka (pc-user-pl) po prostu otwórz `https://facebook.com`,
`https://youtube.com`, `https://allegro.pl` — Chromium ufa lokalnemu CA.

## Jak dodać kolejną atrapę

1. dopisz wpis do `brands.json` (`domain`, `name`, `kind`, `color`, `tagline`);
2. `python3 sites/webmock/build.py` (regeneruje certy-listę, bloki Caddy, aliasy);
3. wklej wypisane aliasy pod usługą `proxy` w `compose.net.yml` (sekcja „webmock brands");
4. `bash ca/gen.sh && docker compose -f compose.net.yml up -d --build`.

Aby podmienić atrapę na pełny klon (Node/Next/Django z GitHuba), dodaj osobną usługę
w compose i skieruj blok Caddy `reverse_proxy` na jej port zamiast na `webmock:9860`.

## Skąd wziąć bogatsze mocki (rozbudowa)

Katalogi i generatory z GitHuba do zasilenia atrap prawdziwym UI (patrz `TODO/`):

- **gorvgoyl/clone-wars** — 100+ open-source klonów popularnych serwisów (Instagram,
  Netflix, TikTok, Spotify, WhatsApp, YouTube, Facebook, Reddit…). Główne źródło kandydatów.
- **fraxxio/MockSocial** — generator realistycznych zrzutów postów (Twitter/IG/FB/Discord).
- **ashishguleria04/MockSocial** — generator mockupów czatów (WhatsApp, iMessage, Signal,
  Slack, Discord, Telegram, Messenger, IG, Teams, X).
- **arvinsroom/mocksocialmediawebsite** — badawcza atrapa feedu social media.

Każdy klon przed wpięciem sprawdź: README z instrukcją, Dockerfile, baza danych,
wymagane klucze API, czy się buduje — i dopiero wtedy dodaj jako osobną usługę.
