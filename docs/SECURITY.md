# WorldBase Security

Security implementation details for Pi↔PC synchronization and API protection.

## Overview

WorldBase implements defense-in-depth for edge-to-cloud communication:

1. **HMAC-SHA256** request signing (for Node Sync)
2. **API Key Authentication** (for Chat, Briefing, OSINT)
3. **Replay attack protection** via nonces
4. **Rate limiting** per endpoint
5. **Token expiration** with TTL
6. **Constant-time comparison** to prevent timing attacks

---

## API Key Authentication

Sensitive endpoints that are accessed by the frontend (such as AI Chat, Briefing Generation, and OSINT tools) are protected by a simple API Key mechanism.

### Configuration
Set the `WORLDBASE_API_KEY` in your `.env` file:
```env
WORLDBASE_API_KEY=your-super-secret-api-key
```

### Frontend Integration
The frontend automatically injects this key into the `X-API-Key` header for all requests using the centralized `fetchApi` wrapper in `frontend/src/lib/networkFetch.ts`. To use it in the browser, set the key in `localStorage`:
```javascript
localStorage.setItem('WORLDBASE_API_KEY', 'your-super-secret-api-key');
```

---

## HMAC Authentication (Node Sync)

### Signing Process (Pi Client)

```python
from auth.security import create_signed_request

payload = {
    "node_id": "offgrid-pi",
    "lat": 52.5200,
    "lon": 13.4050,
    "sensors": {"temp_c": 22.5, "humidity_pct": 65}
}

signed = create_signed_request(
    payload,
    secret=INGEST_TOKEN,
    include_timestamp=True,
    include_nonce=True
)

# signed = {
#     "payload": {...},        # With timestamp + nonce added
#     "headers": {
#         "X-Node-Token": "<hmac-sha256>",
#         "X-Request-Timestamp": "1234567890",
#         "X-Request-Nonce": "<uuid>"
#     }
# }
```

### Verification Process (PC Server)

```python
from auth.security import verify_request_auth

# In FastAPI endpoint:
auth_result = verify_request_auth(
    request,
    token_header="X-Node-Token",
    secret=INGEST_TOKEN
)

# Returns parsed payload or raises HTTPException(403)
```

---

## Replay Attack Protection

### Threat Model

Attacker captures valid request and retransmits it.

### Mitigation

```
Request must include:
├── Nonce (unique per request)
├── Timestamp (Unix epoch)
└── HMAC (covers nonce + timestamp)

Server validates:
├── HMAC signature valid
├── Timestamp within window (±5 min)
├── Nonce not seen before
└── Nonce age < max (10 min)
```

### Nonce Cache

- Thread-safe in-memory storage
- Automatic expiration (TTL)
- Periodic cleanup every 60 seconds

---

## Rate Limiting

### slowapi Implementation

```python
from middleware.rate_limit import rate_limit_node_ingest

@router.post("/node/ingest")
@rate_limit_node_ingest()  # 100 req/min
async def node_ingest(...):
    ...
```

### Default Limits

| Endpoint | Limit | Per |
|----------|-------|-----|
| `/api/node/ingest` | 100 | minute, per node |
| `/api/node/pull` | 20 | minute, per node |
| `/api/node/command` | 10 | minute, admin only |
| General API | 1000 | hour, per IP |

### Response (429 Too Many Requests)

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 45
Content-Type: application/json

{
  "error": "Rate limit exceeded",
  "limit": "100/minute",
  "retry_after": 45
}
```

---

## Token Management

### Environment Variables

```bash
# Required for production
NODE_INGEST_TOKEN=$(openssl rand -hex 32)

# Optional separate admin token
NODE_ADMIN_TOKEN=$(openssl rand -hex 32)

# Fail fast without token
WORLDBASE_REQUIRE_NODE_TOKEN=1
```

### Generation Script

```powershell
# scripts/setup-node-security.ps1 (existing)
$token = -join ((1..32) | ForEach-Object { Get-Random -Maximum 16 | ForEach-Object { "0123456789abcdef".Substring($_,1) } })
[System.Environment]::SetEnvironmentVariable("NODE_INGEST_TOKEN", $token, "User")
```

### Token Rotation

1. Generate new token
2. Update PC environment
3. Sync to Pi (via secure channel)
4. Restart both services

---

## Constant-Time Comparison

### Vulnerability

Standard string comparison exits early on mismatch:

```python
# VULNERABLE
if signature == expected:  # Early exit leaks timing info
    ...
```

### Mitigation

```python
# SECURE
import hmac
if hmac.compare_digest(signature, expected):  # Always same time
    ...
```

Always used in `auth.security.verify_hmac_signature()`.

---

## Security Headers

Implemented in `main.py` via `SecurityHeadersMiddleware`:

```http
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: strict-origin-when-cross-origin
X-Permitted-Cross-Domain-Policies: none
Permissions-Policy: geolocation=(self), microphone=(), camera=()
```

---

## Best Practices

### For Operators

1. **Always set NODE_INGEST_TOKEN in production**
   ```powershell
   $env:NODE_INGEST_TOKEN = (openssl rand -hex 32)
   ```

2. **Enable WORLDBASE_REQUIRE_NODE_TOKEN=1**
   - Fails startup if token not set
   - Prevents accidental insecure deployment

3. **Use HTTPS in production**
   - Docker stack includes Caddy TLS proxy
   - Self-signed certs acceptable for LAN Pi sync

4. **Separate Admin Token**
   - NODE_ADMIN_TOKEN for command endpoints
   - Different key than ingest token

### For Developers

1. **Never log tokens**
   ```python
   # Bad
   logger.info(f"Token: {token}")
   
   # Good
   logger.info(f"Token set: {bool(token)}")
   ```

2. **Always use verify_hmac_signature()**
   - Never implement own comparison
   - Never use `==` for signatures

3. **Validate all inputs**
   - Pydantic models enforce types
   - Additional validators for ranges

---

## Security Checklist

Deploying to production? Verify:

- [ ] NODE_INGEST_TOKEN is set and strong (≥256 bits)
- [ ] WORLDBASE_REQUIRE_NODE_TOKEN=1 is set
- [ ] HTTPS is enabled (Caddy/docker)
- [ ] Rate limiting is active (default: yes)
- [ ] Replay protection enabled (default: yes)
- [ ] Token expiration configured (default: 5 min)
- [ ] Logs don't contain tokens
- [ ] Pi has correct token synced
- [ ] Admin token different from ingest (optional)

---

## Penetration Testing

### Tools

```bash
# Timing attack detection
pip install timing-attack

# Rate limit testing
for i in {1..150}; do
    curl -X POST http://localhost:8002/api/node/ingest ...
done

# Replay attack attempt
curl -X POST ... -H "X-Node-Token: <captured>" -d '<same-body>'
# Should fail: nonce already used
```

---

## Incident Response

### Token Compromise

1. Generate new token immediately
2. Update PC environment
3. Revoke old token (restart service)
4. Sync new token to Pi
5. Review access logs

### Rate Limit Bypass

If attacker uses multiple IPs:
- Enable stricter limits
- Consider IP reputation filtering
- Add geographic filtering (if applicable)

---

## References

- [OWASP Cheat Sheet: Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [Timing Attacks on HMAC](https://codahale.com/a-lesson-in-timing-attacks/)
- [slowapi documentation](https://slowapi.readthedocs.io/)
