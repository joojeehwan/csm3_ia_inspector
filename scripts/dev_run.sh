#!/usr/bin/env bash
set -euo pipefail

# Move to repo root
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Activate venv if present
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Quick env check
python scripts/check_env.py

# Optional reindex & ingest when --reindex passed
if [[ "${1:-}" == "--reindex" ]]; then
  python infra/create_index.py
  python ingest/build_chunks.py
fi

# Kill existing Chainlit on $PORT (or 8000 default)
PORT="${PORT:-8000}"
if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
  echo "Killing process on port $PORT"
  lsof -ti tcp:"$PORT" | xargs kill -9 || true
fi

echo "Starting Chainlit on port $PORT..."
exec chainlit run app.py -w
