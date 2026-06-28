#!/usr/bin/env bash
# WorldBase POSIX starter — equivalent of start.ps1 for Linux/macOS.
# Kills stale processes, starts backend + frontend, optionally runs smoke test.
#
# Usage:
#   ./scripts/start.sh             # full start with smoke test
#   ./scripts/start.sh --skip-smoke  # skip smoke test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_URL="http://127.0.0.1:8002"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
SKIP_SMOKE=0

for arg in "$@"; do
  case "$arg" in
    --skip-smoke) SKIP_SMOKE=1 ;;
    -h|--help)
      echo "Usage: $0 [--skip-smoke]"
      exit 0
      ;;
  esac
done

echo ""
echo "====================================="
echo "  WORLDBASE"
echo "====================================="
echo ""

# --- [0/4] Kill stale processes ---
echo "[0/4] Cleaning up..."
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "vite.*5176" 2>/dev/null || true
sleep 2

# --- [1/4] Backend ---
echo "[1/4] Backend..."
VENV_PY="$BACKEND_DIR/venv/bin/python"

if [ ! -f "$VENV_PY" ]; then
  echo "  venv not found. Creating one..."
  python3 -m venv "$BACKEND_DIR/venv"
  VENV_PY="$BACKEND_DIR/venv/bin/python"
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r "$BACKEND_DIR/requirements.txt"
fi

# Init DB if missing
if [ ! -f "$BACKEND_DIR/worldbase.db" ]; then
  echo "  Init DB..."
  (cd "$BACKEND_DIR" && "$VENV_PY" -c 'from main import init_db; init_db()')
fi

# Read bind host from .env (default 127.0.0.1)
BIND_HOST="127.0.0.1"
ENV_FILE="$BACKEND_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*WORLDBASE_BIND_HOST[[:space:]]*=[[:space:]]*(.+)$ ]]; then
      BIND_HOST="${BASH_REMATCH[1]}"
      BIND_HOST="${BIND_HOST//\"/}"
      BIND_HOST="${BIND_HOST//\'/}"
      BIND_HOST="${BIND_HOST//[[:space:]]/}"
    fi
  done < "$ENV_FILE"
fi

# Start backend in background
cd "$BACKEND_DIR"
"$VENV_PY" -m uvicorn main:app \
  --host "$BIND_HOST" \
  --port 8002 \
  --reload \
  --reload-exclude worldbase.db \
  --reload-exclude worldbase.db-wal \
  --reload-exclude worldbase.db-shm \
  --reload-exclude data/entities.duckdb \
  --reload-exclude data/entities.duckdb.wal \
  --reload-exclude data/ais_trajectory.db \
  --reload-exclude data/ais_trajectory.db-wal \
  --reload-exclude data/ais_trajectory.db-shm \
  --reload-exclude data/intel_subgraph_latest.json \
  --reload-exclude data/tle/active.tle \
  &
BACKEND_PID=$!
echo "  Started backend (PID $BACKEND_PID)"

# Wait for backend health
echo "  Waiting for backend ($BACKEND_URL/api/health/ping)..."
BACKEND_READY=0
for i in $(seq 1 30); do
  if curl -sf "$BACKEND_URL/api/health/ping" >/dev/null 2>&1; then
    echo "  Backend ready (${i}s)."
    BACKEND_READY=1
    break
  fi
  sleep 2
done

if [ "$BACKEND_READY" -eq 0 ]; then
  echo "  Backend not ready — check stderr for errors."
fi

# --- [2/4] Frontend ---
echo "[2/4] Frontend..."
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "  npm install..."
  (cd "$FRONTEND_DIR" && npm install)
fi

(cd "$FRONTEND_DIR" && npm run dev -- --port 5176) &
FRONTEND_PID=$!
echo "  Started frontend (PID $FRONTEND_PID)"
sleep 3

# --- [3/4] Smoke test ---
if [ "$SKIP_SMOKE" -eq 1 ]; then
  echo "[3/4] Smoke test skipped (--skip-smoke)"
elif [ "$BACKEND_READY" -eq 1 ]; then
  echo "[3/4] Smoke test..."
  # Re-check backend if it wasn't ready earlier
  if [ "$BACKEND_READY" -eq 0 ]; then
    for i in $(seq 1 5); do
      if curl -sf "$BACKEND_URL/api/health/ping" >/dev/null 2>&1; then
        BACKEND_READY=1
        break
      fi
      sleep 2
    done
  fi
  if [ -f "$ROOT/scripts/smoke-test.sh" ]; then
    bash "$ROOT/scripts/smoke-test.sh" || echo "  Smoke test failed — stack is running; fix before release."
  else
    echo "  smoke-test.sh not found — skipping (PowerShell-only on Windows)"
  fi
else
  echo "[3/4] Backend not ready — skip smoke"
fi

# --- [4/4] Browser ---
echo "[4/4] Browser..."
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:5176" 2>/dev/null || true
elif command -v open >/dev/null 2>&1; then
  open "http://localhost:5176" 2>/dev/null || true
fi

echo ""
echo "====================================="
echo "  RUNNING"
echo "====================================="
echo "  http://localhost:5176"
echo "  http://localhost:8002/docs"
echo ""
echo "  Backend bind: $BIND_HOST"
echo "  Backend PID:  $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo "  Tip: if Vite shows proxy ECONNREFUSED, backend is still starting or reloading."
echo ""
echo "  Stop with: kill $BACKEND_PID $FRONTEND_PID"
echo ""
