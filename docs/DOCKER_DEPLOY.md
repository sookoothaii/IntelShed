# WorldBase — Docker Deployment (PC + Pi as one secure organism)

WorldBase now ships a full containerized stack so the PC brain and the off-grid
Pi connect over **HTTPS** with **token-authenticated** sync — no more "Docker was
a problem" and no plaintext telemetry on the LAN.

```
                         ┌──────────────────────── Windows PC ────────────────────────┐
   Browser  ── https ──▶ │  caddy (web)  :80 / :443  ── internal CA TLS                │
                         │     │  /api/* ─▶ backend:8002  (FastAPI, non-root)           │
   Off-grid ── https ──▶ │     └─ SPA (built React/Cesium, /srv)                        │
   Pi (LAN)              │  backend ─ SQLite on named volume, Ollama via host gateway   │
                         └─────────────────────────────────────────────────────────────┘
```

| Container | Image | Ports | Role |
|-----------|-------|-------|------|
| `web`     | `worldbase-web:local` (Caddy 2) | `80`, `443` (LAN) | TLS termination, serves SPA, reverse-proxies `/api` |
| `backend` | `worldbase-backend:local` (py3.11) | `127.0.0.1:8002` only | FastAPI + SQLite, runs as uid 10001 |

Data lives in named volumes: `worldbase-db` (SQLite), `caddy-data` (TLS certs).

---

## Quick start

```powershell
Set-Location -LiteralPath 'D:\MCP Mods\worldbase'
.\scripts\start-docker.ps1
```

The helper:
1. ensures a `NODE_INGEST_TOKEN` exists (runs `setup-node-security.ps1` if not),
2. auto-detects the PC LAN IP so Caddy issues a TLS cert the Pi can reach,
3. reads `VITE_CESIUM_ION_TOKEN` from `frontend/.env` into the build,
4. writes the root `.env` and runs `docker compose up -d --build`.

Then open **https://localhost** (accept the internal-CA warning once).

Stop with `.\scripts\stop-docker.ps1` (add `-Volumes` to also wipe the DB).

### Manual

```powershell
copy .env.docker.example .env   # fill in VITE_CESIUM_ION_TOKEN, WORLDBASE_LAN
docker compose up -d --build
```

---

## Security model

- **Backend never touches the LAN directly** — it publishes only on
  `127.0.0.1:8002`. Everything from the LAN goes through Caddy on `:443`.
- **TLS everywhere on the wire** — Caddy uses its internal CA. The browser and
  the Pi talk HTTPS; node telemetry and tokens are no longer sent in cleartext.
- **Token-authenticated sync** — `/api/node/ingest` requires an HMAC-SHA256 of
  the body (`X-Node-Token`); `/api/node/pull` and command poll require the shared
  token; `/api/node/{id}/command` and `/api/briefing/generate` require the admin
  token. Verified: valid HMAC → `200`, wrong/missing token → `403`.
- **Secure-by-default** — `WORLDBASE_REQUIRE_NODE_TOKEN=1` makes the backend
  refuse to start when LAN-exposed without a token.
- **Hardening headers** — `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, and HSTS on HTTPS.
- **Least privilege** — backend runs as a non-root user; container healthcheck on
  `/api/health`.

Optional hard lockdown: uncomment the `remote_ip` block in `Caddyfile` to keep
the dashboard reachable only from the PC and the Pi subnet.

---

## Connecting the Pi over TLS

On the Pi, point the sync daemons at the PC over HTTPS (self-signed internal CA,
so verification is off by default on the trusted LAN):

```
# /etc/systemd/system/worldbase_push.service.d/override.conf  (and _pull)
[Service]
Environment=WORLDBASE_PC=192.168.1.111
Environment=WORLDBASE_SCHEME=https
Environment=WORLDBASE_VERIFY_TLS=0
Environment=NODE_INGEST_TOKEN=<same token as PC backend/.env>
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart worldbase_push worldbase_pull
journalctl -u worldbase_push -f
```

To **verify the TLS cert** instead of skipping it, export Caddy's root CA from the
`web` container and ship it to the Pi:

```powershell
docker compose cp web:/data/caddy/pki/authorities/local/root.crt .\caddy-root.crt
# scp caddy-root.crt to the Pi, then set on the Pi:
#   WORLDBASE_VERIFY_TLS=1
#   WORLDBASE_CA_BUNDLE=/etc/ssl/certs/worldbase-caddy-root.crt
```

(The Pi must then reach the PC by a hostname/IP present in the cert — set
`WORLDBASE_LAN` to that IP before starting the stack.)

---

## Ollama

The backend reaches the host's Ollama via `host.docker.internal:11434`
(`extra_hosts: host-gateway`). Keep Ollama running on the Windows host as before.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `backend` exits immediately, logs `WORLDBASE_REQUIRE_NODE_TOKEN ... refusing to start` | Set a token: `.\scripts\setup-node-security.ps1`, then restart |
| Browser cert warning | Expected (internal CA). Trust `caddy-root.crt` to remove it |
| Globe has no imagery | `VITE_CESIUM_ION_TOKEN` missing at build — set it in `frontend/.env` and `.\scripts\start-docker.ps1 -Rebuild` |
| Port 80/443/8002 in use | Stop the native `start.ps1` instance (it also uses 8002) |
| Pi can't reach `https://<ip>` | Set `WORLDBASE_LAN=<pc-ip>` and rebuild so the cert covers that IP |
| Windows `curl https://localhost` fails with schannel/LSA error | Client-side quirk; use the browser or test from a Linux client |

---

## Native (non-Docker) still works

`start.ps1` (venv + uvicorn + Vite) is unchanged for development. Don't run both
at once — they share port 8002.
