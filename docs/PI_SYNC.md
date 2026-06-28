# Pi Sync Protocol — PC ↔ Off-Grid Edge Node

> WorldBase operator digest sync to the off-grid Raspberry Pi.
> Default: single-operator, single-Pi setup. The Pi is a **dumb consumer** with a
> local cache; it can also record local edits that the operator may need to merge.

---

## 1. Overview

The PC generates the 24-hour security briefing via `POST /api/briefing/generate`
or the autopilot. The Pi periodically pulls the latest state from the PC with
`GET /api/node/pull` and stores it locally for offline display on the off-grid
portal.

Two optional layers make this robust:

- **Delta sync** (`?since=<ISO-8601>`) — reduces payload size by sending only the
  briefing diff + intel added since the last pull.
- **Conflict detection** (`X-Client-Version` / `X-Client-Data-Hash`) — protects
  unsynced Pi work from being silently overwritten by the PC (Phase 3.1).

---

## 2. Pull request

```bash
curl -H "X-Node-Token: $NODE_INGEST_TOKEN" \
     -H "X-Client-Version: 7" \
     -H "X-Client-Data-Hash: sha256-of-local-briefing" \
     "http://127.0.0.1:8002/api/node/pull?since=2026-06-28T08:00:00Z"
```

### Headers

| Header | Required | Meaning |
|---|---|---|
| `X-Node-Token` | if `NODE_INGEST_TOKEN` set | Shared node secret (plain token, HMAC optional in legacy clients). |
| `X-Client-Version` | no | Highest PC briefing version the Pi has seen (monotonic integer, not wall-clock). |
| `X-Client-Data-Hash` | recommended | SHA-256 of the Pi's current local briefing text. |
| `X-Briefing-Hash` | no | SHA-256 of the briefing the Pi already has; triggers a delta-only response if unchanged. |

### Query parameters

| Param | Meaning |
|---|---|
| `?since=<ISO-8601>` | Request delta sync (intel/edges added after this timestamp). |
| `?force=1` | Bypass conflict detection and accept the server version. |
| `?mesh=1` | Return a <230-byte compressed payload for Meshtastic/LoRa relay. |

---

## 3. Conflict detection (Phase 3.1)

The Pi is **not a co-editor** — it normally overwrites its local cache with the
PC version. If the Pi went offline and generated a local briefing, or edited an
existing one, the PC must detect that before overwriting.

### Version model

- **Server version:** `MAX(briefings.id)` — the autoincrement primary key of the
  PC's briefing table. This is a **monotonic counter** (not wall-clock), making it
  immune to clock skew between the PC and the Pi.
- **Client version:** The last `server_version` the Pi successfully pulled and
  applied, stored locally on the Pi.
- **Client data hash:** SHA-256 of the Pi's current briefing text.

### Conflict rules

| Condition | HTTP | Reason |
|---|---|---|
| `client_version > server_version` | `409` | `client_ahead` — Pi has newer local work the PC would clobber. |
| `client_version == server_version` and `client_hash != server_hash` | `409` | `diverged` — concurrent edit at the same version. |
| otherwise | `200` | Normal forward sync. |

### 409 response body

```json
{
  "conflict": true,
  "reason": "client_ahead",
  "detail": "Pi version 7 is ahead of server version 5. The Pi has local work the server would overwrite.",
  "server_version": 5,
  "client_version": 7,
  "server_briefing_hash": "abc123...",
  "client_data_hash": "def456...",
  "server_briefing_at": "2026-06-28T08:23:45Z",
  "server_briefing_preview": "24h security digest preview...",
  "resolve": "POST /api/node/push with your local state for operator merge, or retry GET /api/node/pull?force=1 to accept the server version."
}
```

The operator can either:

1. **Merge the Pi's state manually** — the Pi uploads its local briefing via
   `POST /api/node/push`, then the operator resolves the merge.
2. **Force the PC version** — the Pi calls `GET /api/node/pull?force=1`, accepting
   that the PC version overwrites its local work.

---

## 4. Push — Pi uploads local state for merge

```bash
curl -H "X-Node-Token: $NODE_INGEST_TOKEN" \
     -H "Content-Type: application/json" \
     -X POST http://127.0.0.1:8002/api/node/push \
     -d '{
       "node_id": "offgrid-pi",
       "briefing": "<Pi local briefing text>",
       "client_version": 7,
       "client_data_hash": "sha256-of-local-briefing",
       "reason": "local generation while PC was offline"
     }'
```

Response:

```json
{
  "ok": true,
  "merge_id": 3,
  "status": "pending_merge",
  "node_id": "offgrid-pi",
  "client_version": 7,
  "server_version": 5,
  "created_at": "2026-06-28T14:45:00Z"
}
```

The PC does **not** auto-merge. It stores the pushed state in `node_push_log`
with status `pending` and waits for the operator to decide.

### Operator endpoints

- `GET /api/node/push/pending` — list pending merge requests.
- `POST /api/node/push/{merge_id}/resolve` — resolve with
  `{"resolution": "accept_server" | "accept_client" | "reject", "note": "..."}`.

The actual data action (regenerate briefing, overwrite, etc.) is performed by the
operator out-of-band. The resolution record is an audit trail, not a CRDT merge.

---

## 5. Configuration

```bash
# Pi sync conflict detection
WORLDBASE_NODE_CONFLICT_CHECK=1          # default on, backward-compatible
WORLDBASE_NODE_PULL_DELTA=1              # delta sync (default on)
NODE_INGEST_TOKEN=...                    # node auth (shared secret)
NODE_ADMIN_TOKEN=...                     # optional admin gate for resolve
```

`WORLDBASE_NODE_CONFLICT_CHECK=1` only activates when the Pi sends
`X-Client-Version`. Legacy clients that omit the header continue to work exactly
as before.

---

## 6. Best practices

- Always store the **last pulled server version** on the Pi, not wall-clock time.
- Keep the **local briefing hash** in the Pi cache and refresh it when the local
  file is edited.
- Use `?force=1` sparingly — it intentionally bypasses the safety check.
- Treat pushed briefings as audit logs; never let the PC auto-merge from the Pi
  without operator review in a single-operator security research setup.
