# net-user-pl — a virtual internet for an average Polish citizen

An **isolated, offline digital twin of the internet**: local DNS, a local
certificate authority, a TLS reverse proxy, and citizen-facing sites (a bank, a
Profil-Zaufany-style identity portal), plus a virtual SMS carrier and a URI
**event bus** that records every action as a URI address. Built so `urirun`
automations run against something that behaves like production — real HTTPS,
real domains, real second factors — without touching the real internet.

Part of the trio: **net-user-pl** (the network) · [pc-user-pl](https://github.com/if-uri/pc-user-pl) (the computer) · [mobile-user-pl](https://github.com/if-uri/mobile-user-pl) (the phone). Orchestrated together by the `pc1` project.

## What runs (all on the `netpl` docker network)

| Service | Role | URI scheme |
| --- | --- | --- |
| `eventbus` | records every action as a URI event (source of truth) | — |
| `proxy` (Caddy) | TLS termination with the local CA; docker DNS aliases = the virtual internet's DNS | `net://` |
| `bank` | virtual mbank.pl with SMS one-time-code login | `bank://` |
| `gov` | virtual login.gov.pl (Profil Zaufany stub, human-in-the-loop) | `gov://` |
| `sms-gateway` | the virtual carrier: delivers OTPs to a handset inbox | `sms://` |
| `webmock` | 31 branded mocks of popular sites (facebook.com, youtube.com, allegro.pl…), host-routed from one server | `web://` |

Virtual domains (resolve to the proxy via docker embedded DNS):
`mbank.pl`, `login.gov.pl`, `phone.jan.pl` (served by mobile-user-pl), `poczta.jan.pl`,
plus the **webmock brands** — real names like `facebook.com`, `instagram.com`, `youtube.com`,
`google.com`, `gmail.com`, `wikipedia.org`, `github.com`, `amazon.pl`, `allegro.pl`, `olx.pl`,
`netflix.com`, `spotify.com`, `x.com`, `linkedin.com`, `reddit.com`, `tiktok.com`, `discord.com`,
`whatsapp.com`, `telegram.org`, `airbnb.com`, `booking.com`, `wp.pl`, `onet.pl`, `stackoverflow.com`
— each with valid HTTPS from the local CA. Full list + how to extend: [`sites/webmock/README.md`](sites/webmock/README.md).

## Run

```bash
bash ca/gen.sh                                  # generate the isolated root CA + leaf certs
docker network create netpl                     # idempotent shared network
docker compose -f compose.net.yml up -d
# read the whole URI event log:
curl -s http://127.0.0.1:28800/events | python3 -m json.tool
```

## Safety

`ca/out/rootCA.pem` can issue certificates for **real** domains (mbank.pl,
gov.pl). It is trusted **only inside the pc-user-pl desktop container**, never on
your host. Do not add it to your host trust store — it would let anyone MITM the
real sites. The keys are gitignored; regenerate with `ca/gen.sh`.

## Event model

Every real-life step is a URI on the bus, e.g. a bank SMS login produces:

```
bank://mbank.pl/login/query/form
bank://mbank.pl/otp/command/request
sms://+48500100200/inbox/command/deliver
phone://jan/sms/query/read
bank://mbank.pl/session/command/login-success
bank://mbank.pl/dashboard/query/view
```

so a whole episode is replayable and every urirun feature can be exercised
against a faithful causal log.
