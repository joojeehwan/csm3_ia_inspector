#!/usr/bin/env bash
set -euo pipefail

# Move to repo root
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Activate venv if present
if [ -d ".venv" ]; then
  # Check OS and use appropriate activation script
  if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    # Windows (Git Bash/MSYS2/Cygwin)
    source .venv/Scripts/activate
  else
    # macOS/Linux
    source .venv/bin/activate
  fi
fi

# Quick env check
if [ -f .env ]; then
  # Export env vars for bash environments
  set -o allexport
  # shellcheck disable=SC2046
  source <(sed -n '/^[A-Za-z_][A-Za-z0-9_]*=.*/p' .env)
  set +o allexport
fi
python scripts/check_env.py

# Indicate web_qa availability
if [[ -n "${BING_SEARCH_KEY:-}" ]]; then
  echo "Web search: ENABLED (web_qa mode will be available)"
else
  echo "Web search: DISABLED (set BING_SEARCH_KEY in .env to enable web_qa)"
fi

# Optional reindex & ingest when --reindex passed
if [[ "${1:-}" == "--reindex" ]]; then
  python infra/create_index.py
  python ingest/build_chunks.py
fi

# Kill existing Chainlit on $PORT (or 8000 default)
PORT="${PORT:-8000}"

# Check OS and use appropriate port checking command
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
  # Windows - use netstat
  if netstat -ano | grep ":$PORT " >/dev/null 2>&1; then
    echo "Killing process on port $PORT"
    netstat -ano | grep ":$PORT " | awk '{print $5}' | xargs -r taskkill /F /PID 2>/dev/null || true
  fi
else
  # macOS/Linux - use lsof
  if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
    echo "Killing process on port $PORT"
    lsof -ti tcp:"$PORT" | xargs kill -9 || true
  fi
fi

echo "Starting Chainlit on port $PORT..."
exec python -m chainlit run app.py -w
