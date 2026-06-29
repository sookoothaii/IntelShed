# WorldBase — Linux Migration Plan

> Goal: Move the entire WorldBase stack from Windows to Linux with zero data loss and minimal downtime.

---

## 1. Pre-Migration Inventory

### What runs on Windows today

| Component | Location | Linux-compatible? | Action |
|---|---|---|---|
| Docker stack (backend, web, redis, celery) | `docker-compose.yml` | Yes — already Linux-native | Copy as-is |
| Backend Python code | `backend/*.py` | Yes — zero Windows-specific code | Copy as-is |
| Frontend (React + Vite) | `frontend/` | Yes | Copy as-is |
| Caddy config | `Caddyfile` | Yes | Copy as-is |
| Dockerfile | `backend/Dockerfile` | Yes — `python:3.12-slim` (Debian) | Copy as-is |
| `requirements.txt` | `backend/requirements.txt` | Yes — all packages Linux-compatible | Copy as-is |
| `backend/.env` | API keys, feature flags | Yes | Copy as-is (update paths if needed) |
| `backend/worldbase.db` | SQLite database | Yes — portable format | Copy to Docker volume or mount |
| `backend/data/entities.duckdb` | DuckDB database | Yes — portable format | Copy to Docker volume or mount |
| `backend/data/` | Snapshots, models, subgraphs | Yes | Copy as-is |
| `data/pmtiles/` | PMTiles terrain tiles | Yes | Copy as-is |
| `tor/` | Tor binary + data | **No** — Windows `.exe` | Reinstall via `apt install tor` or remove if unused |
| `backend/venv/` | Python virtual env | **No** — Windows binaries | Recreate on Linux (`python -m venv venv`) |
| `scripts/*.ps1` | PowerShell helper scripts | **No** | Replace with `.sh` equivalents (optional) |
| `start.ps1` / `start.bat` | Windows launchers | **No** | Replace with `start.sh` (optional — Docker mode doesn't need them) |
| `offgrid-raspi/` | Pi subtree (separate repo) | Already Linux (Pi OS) | No change needed |

### What does NOT need migration

- `backend/venv/` — recreated automatically on Linux
- `tor/` — Windows binaries, reinstall on Linux if needed
- `*.ps1` scripts — replaced by `docker compose` commands or `.sh` equivalents
- `node_modules/` — recreated by `npm install`

---

## 2. Data Backup (on Windows, before migration)

```powershell
# 1. Stop the Docker stack
docker compose down

# 2. Backup Docker volumes (databases)
docker run --rm -v worldbase-db:/data -v ${PWD}:/backup alpine tar czf /backup/worldbase-db-backup.tar.gz -C /data .

# 3. Backup backend data directory (snapshots, models, subgraphs)
Copy-Item -Recurse backend\data backend\data-backup

# 4. Backup .env files
Copy-Item backend\.env backend\.env.backup
Copy-Item frontend\.env frontend\.env.backup

# 5. Backup PMTiles (if present)
Copy-Item -Recurse data\pmtiles data\pmtiles-backup

# 6. Git status — ensure all code is committed
git status
git add -A
git commit -m "Pre-migration snapshot"
```

---

## 3. Transfer to Linux

### Option A: Git-based (recommended for code)

```bash
# On Linux:
git clone <your-repo-url> worldbase
cd worldbase
```

### Option B: Full file copy (for data + code)

```bash
# On Linux, from the receiving machine:
rsync -avz --exclude='venv' --exclude='node_modules' --exclude='tor' \
  --exclude='*.ps1' --exclude='__pycache__' --exclude='.pytest_cache' \
  sooko@<windows-ip>:/d/MCP\ Mods/worldbase/ ~/worldbase/
```

### Restore Docker volume data

```bash
# Create the volume
docker volume create worldbase-db

# Restore backup
docker run --rm -v worldbase-db:/data -v $(pwd):/backup alpine \
  tar xzf /backup/worldbase-db-backup.tar.gz -C /data
```

---

## 4. Linux Environment Setup

### 4.1 Install Docker Engine + Compose

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect

# Verify
docker --version
docker compose version
```

### 4.2 Install Node.js (for frontend development, if needed)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### 4.3 Install Python + venv (for venv-mode development, if needed)

```bash
sudo apt install -y python3.12 python3.12-venv python3-pip
```

### 4.4 Install Tor (if darkweb features are used)

```bash
sudo apt install -y tor
# Tor runs as a system service on Linux — no manual binary needed
sudo systemctl enable --now tor
```

### 4.5 Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

---

## 5. Configuration Adjustments

### 5.1 `backend/.env` — update Ollama host

```bash
# Docker mode: Ollama runs on the host, container reaches it via host.docker.internal
OLLAMA_HOST=host.docker.internal:11434

# Venv mode (native Linux): Ollama on localhost
# OLLAMA_HOST=127.0.0.1:11434
```

### 5.2 `docker-compose.yml` — no changes needed

The compose file already uses:
- Relative paths (`./backend`, `./frontend`)
- `host.docker.internal:host-gateway` (works on Linux via `extra_hosts`)
- Linux-native images (`python:3.12-slim`, `redis:7-alpine`)

### 5.3 File permissions

```bash
# Ensure the repo is owned by your user
sudo chown -R $USER:$USER ~/worldbase

# Docker volume data must be writable by uid 10001 (Dockerfile non-root user)
# This is handled automatically by Docker named volumes
```

### 5.4 Firewall (if LAN-exposed)

```bash
# Open ports for Caddy (HTTP/HTTPS) and Pi sync
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8002/tcp  # only if venv mode + LAN access needed
```

---

## 6. Start the Stack on Linux

### 6.1 Docker mode (primary)

```bash
cd ~/worldbase
docker compose up -d --build
```

### 6.2 Verify

```bash
# Health check
curl -sk https://localhost/api/health/ping

# API docs
curl -sk https://localhost/api/docs

# Backend logs
docker compose logs -f backend

# Anomaly detection status
curl -sk https://localhost/api/anomalies/iso/status
```

### 6.3 Venv mode (alternative, for development)

```bash
cd ~/worldbase/backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # if exists

# Start backend
python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload

# In another terminal, start frontend
cd ~/worldbase/frontend
npm install
npm run dev -- --port 5176
```

---

## 7. Replace PowerShell Scripts with Shell Equivalents

### 7.1 `start.sh` (replaces `start.ps1` — venv mode only)

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

# Start backend
cd "$BACKEND"
source venv/bin/activate
python -m uvicorn main:app --host 127.0.0.1 --port 8002 --reload &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8002/api/health/ping >/dev/null 2>&1; then
    echo "Backend ready."
    break
  fi
  sleep 1
done

# Start frontend
cd "$FRONTEND"
npm run dev -- --port 5176 &
FRONTEND_PID=$!

echo "Backend PID: $BACKEND_PID, Frontend PID: $FRONTEND_PID"
wait
```

### 7.2 `smoke-test.sh` (replaces `smoke-test.ps1`)

```bash
#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://127.0.0.1:8002}"
PASS=0; FAIL=0

check() {
  local name="$1" url="$2" expect="$3"
  local resp
  resp=$(curl -sf "$url" 2>/dev/null || echo "FAIL")
  if echo "$resp" | grep -q "$expect"; then
    echo "PASS: $name"
    ((PASS++))
  else
    echo "FAIL: $name — got: ${resp:0:80}"
    ((FAIL++))
  fi
}

check "Health ping" "$BASE/api/health/ping" "ok"
check "Feeds" "$BASE/api/feeds" "feeds"
check "FTM stats" "$BASE/api/ftm/stats" "entities"
check "Briefing" "$BASE/api/briefing" "briefing"
check "Anomaly status" "$BASE/api/anomalies/iso/status" "enabled"

echo "---"
echo "PASS: $PASS  FAIL: $FAIL"
```

### 7.3 Docker start script (replaces `start-docker.ps1`)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Detect LAN IP
LAN_IP=$(hostname -I | awk '{print $1}')
export WORLDBASE_LAN="${WORLDBASE_LAN:-$LAN_IP}"

echo "Starting WorldBase Docker stack (LAN: $LAN_IP)..."
docker compose up -d --build

echo "Waiting for backend..."
for i in $(seq 1 60); do
  if curl -sf http://localhost/api/health/ping >/dev/null 2>&1; then
    echo "Backend ready at https://localhost"
    break
  fi
  sleep 2
done
```

---

## 8. Pi Node Adjustment

The Pi already runs Linux. Only update the target IP/URL if the PC's LAN IP changes:

```bash
# On the Pi, update the push service drop-in:
sudo nano /etc/systemd/system/worldbase_push.service.d/http-lan.conf
# Update WORLDBASE_HOST to the new Linux PC IP

sudo systemctl daemon-reload
sudo systemctl restart worldbase_push.service
```

---

## 9. Post-Migration Verification

| Check | Command | Expected |
|---|---|---|
| Docker containers running | `docker ps` | 6 containers (backend, web, redis, celery-worker, celery-beat, flower) |
| Health endpoint | `curl -sk https://localhost/api/health/ping` | `{"status": "ok", ...}` |
| Feeds live | `curl -sk https://localhost/api/feeds` | 20+ feeds, majority fresh |
| FtM graph intact | `curl -sk https://localhost/api/ftm/stats` | Entity count matches pre-migration |
| Briefing works | `curl -sk https://localhost/api/briefing` | Latest briefing JSON |
| Anomaly detection | `curl -sk https://localhost/api/anomalies/iso/status` | `{"enabled": true, ...}` |
| Pi sync | Check Pi heartbeat on `/api/node/pull` | Pi shows online |
| Ollama chat | `curl -sk https://localhost/api/chat` with message | LLM response |
| OpenAPI docs | `https://localhost/api/docs` | Swagger UI loads |
| Frontend | `https://localhost` in browser | Globe + HUD loads |

---

## 10. Rollback Plan

If migration fails, roll back to Windows:

```powershell
# On Windows:
# 1. Restore Docker volumes from backup
docker volume create worldbase-db
docker run --rm -v worldbase-db:/data -v %CD%:/backup alpine tar xzf /backup/worldbase-db-backup.tar.gz -C /data

# 2. Restore .env files
Copy-Item backend\.env.backup backend\.env

# 3. Start Docker stack
docker compose up -d --build
```

---

## 11. Estimated Timeline

| Step | Duration | Downtime |
|---|---|---|
| Backup data + code | 15 min | Yes (stack stopped) |
| Transfer to Linux | 10–30 min (depending on data size) | Yes |
| Install Docker + deps on Linux | 15 min | No |
| Configure + start stack | 10 min | No |
| Verify all endpoints | 15 min | No |
| Pi reconfiguration | 5 min | No |
| **Total** | **~60–90 min** | **~30 min** |

---

## 12. What You Can Delete After Migration

- `start.ps1`, `start.bat` — replaced by `start.sh` or `docker compose`
- `scripts/*.ps1` — replaced by `.sh` equivalents
- `tor/` directory — Windows binaries, use system `tor` package
- `backend/venv/` — Windows venv, recreate on Linux if needed
- `backend/Scripts/` — Windows venv scripts
- Any `__pycache__` directories

## 13. What You Must Keep

- All `backend/*.py` files — platform-neutral
- `docker-compose.yml` — already Linux-compatible
- `backend/Dockerfile` — already Linux-native
- `backend/.env` — API keys, feature flags
- `backend/data/` — snapshots, models, subgraphs
- `data/pmtiles/` — terrain tiles (portable)
- `frontend/` — React app (platform-neutral)
- `Caddyfile` — web server config
- `offgrid-raspi/` — Pi subtree (already Linux)
- All `docs/` — documentation
- All test files — platform-neutral
