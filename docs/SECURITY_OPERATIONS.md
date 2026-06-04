# Security Operations — WorldBase + Off-Grid Pi

> Rolle: Zentrale Checkliste für Lenovo Legion (PC) und Raspberry Pi 4 (OGN).  
> Stand: 2026-06-04 | Positive Intelligence: Schutz, keine Angriffs-Tools.

**Live status (2026-06-04):** PC token set; Pi push/pull **Ingest OK**; Pi UFW hardened; Borg on `/mnt/sdcard/borg-repo`; `/mnt/usb` gone. Portal basic auth on Pi still optional.

---

## Architektur (zwei Knoten)

| Knoten | Rolle | Hauptrisiko |
|--------|-------|-------------|
| **Legion i9** | WorldBase, Flowsint (Docker), Ollama, LLM-Keys | API `:8002` offen im LAN, Node-Steuerung, Docker |
| **Pi 4** | Edge: Portal, Mesh, Pi-hole, LLM, MQTT | Portal ohne Login, LLM direkt, Hotspot-PSK |

**Prinzip:** Öffentliche Daten anzeigen — **keine** Steuerung fremder Infrastruktur, **kein** Massen-Tracking.

---

## Sofort (einmalig, ~30 Min)

### PC (Legion)

```powershell
Set-Location -LiteralPath 'D:\MCP Mods\worldbase'
.\scripts\setup-node-security.ps1    # Token + backend/.env + pi-node-token.conf
.\scripts\pc-security-audit.ps1      # Report
.\start.ps1                          # Backend mit Bind aus .env
```

**Windows SSH to Pi** (if `ssh` not on PATH):

```powershell
& "$env:WINDIR\System32\OpenSSH\ssh.exe" -i "$env:USERPROFILE\.ssh\offgrid-pi" user0@192.168.1.121
```

| Schritt | Warum |
|---------|--------|
| `NODE_INGEST_TOKEN` setzen | Pi-Push/Pull + Befehls-Queue nicht für jeden im WLAN |
| `WORLDBASE_BIND_HOST=0.0.0.0` nur mit Token | Pi erreicht PC; ohne Token → `127.0.0.1` |
| Windows-Firewall | Blockiere eingehend `8002` von außerhalb vertrauenswürdigem LAN |
| Flowsint Docker | Ports 5001/5173/7474 nur localhost oder LAN — nicht ins Internet forwarden |
| `backend/.env` nie committen | Enthält API-Keys |

### Pi (SSH)

```bash
sudo offgrid security-harden
offgrid ufw-verify-gui
sudo offgrid mqtt-harden
```

| Schritt | Warum |
|---------|--------|
| Portal-Auth | `/etc/offgrid/portal.env`: `PORTAL_USER`, `PORTAL_PASS`, `PORTAL_REQUIRE_AUTH=1` |
| Pi-Token | `pi-node-token.conf` von PC → systemd override für `worldbase_push` / `worldbase_pull` |
| Hotspot-PSK | Kein Default mehr im Repo — liegt in `/etc/offgrid/wifi-ap.env` |
| LLM | `llama-server` nur `127.0.0.1:8081`; LAN nutzt **HAK_GAL :8084** |
| SSH | Key-only: `sudo bash offgrid/bin/offgrid-apply-security-fixes.sh` |

```bash
# Auf dem Pi (nach setup-node-security.ps1 auf dem PC):
sudo mkdir -p /etc/systemd/system/worldbase_{push,pull}.service.d
sudo cp ~/…/pi-node-token.conf /etc/systemd/system/worldbase_push.service.d/override.conf
sudo cp ~/…/pi-node-token.conf /etc/systemd/system/worldbase_pull.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart worldbase_push worldbase_pull
```

---

## API-Schutz WorldBase (neu)

| Endpoint | Schutz wenn `NODE_INGEST_TOKEN` gesetzt |
|----------|----------------------------------------|
| `POST /api/node/ingest` | HMAC-SHA256 des JSON-Body → Header `X-Node-Token` |
| `GET /api/node/pull` | Header `X-Node-Token` = Token (Klartext) |
| `GET /api/node/{id}/commands` | Pi: `X-Node-Token` |
| `POST /api/node/{id}/command` | PC: `X-Admin-Token` (= `NODE_ADMIN_TOKEN` oder gleicher Token) |

Ohne Token: Backend loggt `[SECURITY] … open` beim Start.

---

## Pi — Port-Matrix (nach Hardening)

| Port | Dienst | Erreichbar |
|------|--------|------------|
| 22 | SSH | Global (Fail2ban) |
| 53 | Pi-hole DNS | LAN / Passepartout-IF |
| 8080–8093 | Kiwix, Maps, Portal, **HAK_GAL 8084** | Nur LAN (+ Gast-Modus separat) |
| 8081 | llama | **Nur localhost** |
| 8085 | Pi-hole Admin | LAN |
| 1883 | MQTT | LAN, mit Passwort |
| 51820/udp | WireGuard | Optional WAN-Forward |

**Entfernt:** globale UFW-Regel `allow from 10.42.0.0/16` (Passepartout) — stattdessen `offgrid security-harden guest`.

---

## Wiederkehrend

| Intervall | Aktion |
|-----------|--------|
| Wöchentlich | `.\scripts\pc-security-audit.ps1` |
| Nach Setup-Änderung | Pi: `offgrid security-audit` |
| Nach Git-Pull | `offgrid security-harden` + Portal-Auth prüfen |
| Bei Hotspot-Nutzung | `PORTAL_REQUIRE_AUTH=1`, starkes WLAN-PSK |

---

## Was wir bewusst nicht tun

- SCADA / Ampel-Steuerung
- Personen-Tracking über ADS-B/Mobilfunk-Fusion
- Verkauf oder exklusive Datenpartnerschaften
- `StrictHostKeyChecking=no` in Produktions-SSH (PC-Skripte nach und nach härten)

---

## Referenzen

- Pi sync: `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`
- Pi: `offgrid-raspi/offgrid/docs/security.md`
- Pi storage/Borg: `offgrid-raspi/docs/pi-storage-layout.md`
- Audit 2026-05-25: `offgrid-raspi/offgrid/docs/security-audit-2026-05-25.md`
- Flowsint: `docs/FLOWSINT_INTEGRATION.md`
- Vision: `docs/POSITIVE_PALANTIR_VISION.md` (Layer 5 Ethik)
- Handoff: `LLM_HANDOFF.md`
