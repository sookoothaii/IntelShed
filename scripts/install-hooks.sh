#!/usr/bin/env bash
# Install pre-commit git hooks on Linux/macOS.
# Equivalent to the Windows path where pre-commit is installed via pip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT/backend/venv/bin/python"

if [ ! -f "$VENV_PY" ]; then
  echo "venv not found at backend/venv. Run scripts/start.sh first to create it."
  exit 1
fi

echo "Installing pre-commit into venv..."
"$VENV_PY" -m pip install pre-commit

echo "Installing git hooks..."
cd "$ROOT"
"$VENV_PY" -m pre_commit install

echo ""
echo "Pre-commit hooks installed."
echo "  - ruff (lint + format) on backend/"
echo "  - tsc --noEmit on frontend/"
echo ""
echo "Run manually: $VENV_PY -m pre_commit run --all-files"
