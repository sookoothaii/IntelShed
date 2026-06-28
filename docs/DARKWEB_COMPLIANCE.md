# Darkweb OSINT — Compliance & OPSEC

> Scope: `backend/darkweb_bridge.py`, `backend/darkweb_tor.py`, `backend/ransomware_tracker.py`.
> Audience: the single operator running WorldBase. This document records the
> hard rules the darkweb modules follow and the OPSEC controls available.

---

## 1. Operating principles

WorldBase's darkweb capability is a **passive OSINT collector**. It exists to
correlate publicly visible darkweb mentions with the FtM entity graph for
situational awareness. It is **not** an offensive or intrusion tool.

The following rules are enforced in code and must never be relaxed:

- **Passive metadata only.** The collector reads public search-engine result
  pages, public victim lists, and public page text. It extracts only public
  identifiers (crypto wallets, PGP keys, emails, IOCs, `.onion` links).
- **No credential stuffing.** No login attempts, no password reuse, no
  authentication against any third-party service.
- **No leaked-file download.** Ransomware/leak-site intelligence is limited to
  public victim-list metadata (name, date, group, claimed data size). Leaked
  files, dumps, and stolen documents are never downloaded or stored.
- **No marketplace interaction.** No purchases, no orders, no contact with
  vendors. Illegal-marketplace content is out of scope.
- **Opt-in only.** The entire darkweb subsystem is off by default
  (`WORLDBASE_DARKWEB=0`). Tor-proxy engines require an explicit proxy.

---

## 2. Clearnet-first default

By default, only clearnet search engines (Ahmia, DarkSearch — both currently
deprecated upstream) are queried over normal HTTPS. Tor-only engines are
**opt-in** and require `WORLDBASE_DARKWEB_TOR_PROXY` to be set. No Tor relay or
hidden service is run by WorldBase.

Search routing modes:

- **`clear`** — clearnet engines only; Tor engines skipped.
- **`auto`** (default) — clearnet over clearnet, Tor engines over the proxy.
- **`tor`** — all engines routed through the Tor SOCKS5 proxy.

---

## 3. OPSEC — Tor identity rotation (Phase 3.2)

`backend/darkweb_tor.py` isolates all Tor **control-port** logic. When enabled,
it sends `SIGNAL NEWNYM` to the Tor control port to regenerate circuits (new
exit node) before each Tor-engine batch.

| Control | Behaviour |
|---|---|
| **NEWNYM rate-limit** | Tor enforces a 10-second minimum between NEWNYM signals. The rotator enforces the same limit across all callers (`NEWNYM_MIN_INTERVAL_SEC = 10.0`). |
| **Circuit isolation** | A fresh `httpx.AsyncClient` is used per Tor request (already in `darkweb_bridge.py`), so concurrent requests do not share an exit node. |
| **Exit jurisdiction blocklist** | After rotation, the resolved exit-node country is checked against `WORLDBASE_DARKWEB_EXIT_BLOCKLIST` (default `CN,RU,IR`). If blocked, the rotator signals NEWNYM again, up to `max_attempts`. Best-effort: skipped silently if Tor GeoIP is unavailable. |
| **Fail-soft** | Disabled flag, missing `stem` library, or an unreachable control port all return a status dict and never raise into the search path. |

### Configuration

```bash
WORLDBASE_DARKWEB_TOR_ROTATE_IDENTITY=0          # default off, opt-in
WORLDBASE_DARKWEB_TOR_CONTROL_HOST=127.0.0.1:9051
WORLDBASE_DARKWEB_TOR_CONTROL_PASSWORD=          # optional control auth
WORLDBASE_DARKWEB_EXIT_BLOCKLIST=CN,RU,IR        # ISO country codes
```

Requires the `stem` library and a Tor control port. To enable the control port,
add to your `torrc`:

```
ControlPort 9051
# Recommended: authenticate the control port.
HashedControlPassword 16:<your-hash>   # generate with: tor --hash-password <pw>
```

`stem` is listed as an optional dependency in `backend/requirements.txt`. When
it is not installed, rotation is a no-op and the rest of the darkweb subsystem
continues to work over clearnet.

### Status

`GET /api/darkweb/status` exposes the rotation configuration (no secrets):

```json
"tor_rotation": {
  "enabled": false,
  "stem_available": false,
  "control_host": "127.0.0.1:9051",
  "control_password_set": false,
  "exit_blocklist": ["CN", "IR", "RU"],
  "newnym_min_interval_sec": 10.0
}
```

Each search response that touches Tor engines includes a `tor_rotation` field
reporting whether rotation occurred, the exit country (when resolvable), and
whether a blocklisted jurisdiction was hit.

---

## 4. Jurisdiction considerations

OSINT collection laws vary by jurisdiction. The operator is responsible for
ensuring use is lawful in their location. The exit-node blocklist is an OPSEC
aid (avoid routing through hostile jurisdictions), **not** legal advice or a
guarantee. Treat all collected data as sensitive and store it only within the
operator's controlled environment.

---

## 5. Audit

When RBAC/audit is enabled (`WORLDBASE_AUTH_AUDIT=1`, Phase 2.1), MCP darkweb
tool calls are recorded in the `auth_audit` table. Ingestion of darkweb results
as FtM `Mention` entities is gated behind `WORLDBASE_MCP_WRITE=1`.
