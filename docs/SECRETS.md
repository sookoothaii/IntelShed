# Secret Management (Phase 2.2)

WorldBase reads secrets in priority order: **env var → `.env` file → optional vault backend**.

## Architecture

### `backend/secrets_manager.py`

Thin abstraction over `os.getenv` with optional vault integration.

- **Default (`WORLDBASE_SECRET_BACKEND=env`)**: reads from process env, falls back to `backend/.env` file. Zero overhead — no extra imports, no I/O beyond a single file read.
- **Azure Key Vault** (`WORLDBASE_SECRET_BACKEND=azure_keyvault`): lazy-imports `azure.keyvault.secrets` + `azure.identity`. Requires `WORLDBASE_SECRET_VAULT_URL`.
- **AWS Secrets Manager** (`WORLDBASE_SECRET_BACKEND=aws_secretsmanager`): lazy-imports `boto3`. Uses default AWS credential chain.
- **HashiCorp Vault** (`WORLDBASE_SECRET_BACKEND=hashicorp_vault`): lazy-imports `hvac`. Requires `WORLDBASE_SECRET_VAULT_URL`.

All vault paths are **fail-soft**: if the SDK is not installed or the vault is unreachable, the env/`.env` value is returned. No secret is ever logged or exposed in error messages.

Thread-safe in-memory cache (5 min TTL, configurable via `WORLDBASE_SECRET_CACHE_SEC`).

### `backend/scripts/rotate_api_key.py`

Manual CLI tool for generating a new `WORLDBASE_API_KEY`.

```bash
# From backend/ with venv activated:
python scripts/rotate_api_key.py                    # print new key
python scripts/rotate_api_key.py --length 48        # longer key
python scripts/rotate_api_key.py --update-env       # auto-update backend/.env
```

The script uses `secrets.token_urlsafe` for cryptographic randomness. It reminds the operator to update `frontend/.env` and Pi node tokens.

### Cesium Ion Token — Backend Proxy

The Cesium Ion token is **no longer baked into the Vite bundle**. Instead:

1. Backend endpoint `GET /api/config/cesium` returns `{"token": "..."}` from env (`CESIUM_ION_TOKEN` or `VITE_CESIUM_ION_TOKEN` fallback).
2. Frontend `lib/cesiumToken.ts` fetches the token at runtime before Cesium Viewer initialization.
3. If the backend is unreachable, falls back to `import.meta.env.VITE_CESIUM_ION_TOKEN` (dev convenience).
4. 5-minute in-memory cache on the backend to avoid repeated env reads.

**Accepted risk (single-operator dev):** The token is exposed to the browser at runtime by design. For production deployments, create a Cesium token with:
- Minimal scopes (`assets:read` only)
- URL restrictions via Cesium's "Allowed URLs" feature
- Periodic rotation via the Cesium Tokens REST API

## Config

| Env var | Default | Description |
|---------|---------|-------------|
| `WORLDBASE_SECRETS_MANAGER` | `0` (off) | Enable secrets_manager integration in config |
| `WORLDBASE_SECRET_BACKEND` | `env` | Backend: `env`, `azure_keyvault`, `aws_secretsmanager`, `hashicorp_vault` |
| `WORLDBASE_SECRET_VAULT_URL` | (empty) | Vault URL for Azure/HVAC backends |
| `WORLDBASE_SECRET_CACHE_SEC` | `300` | Cache TTL in seconds |

## Files

- `backend/secrets_manager.py` — abstraction layer
- `backend/scripts/rotate_api_key.py` — key rotation CLI
- `backend/routes/config.py` — `/api/config/cesium` endpoint
- `frontend/src/lib/cesiumToken.ts` — runtime token fetch
- `backend/test_secrets_manager.py` — unit tests
