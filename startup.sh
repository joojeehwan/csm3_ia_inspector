#!/usr/bin/env bash
set -euo pipefail

# Azure App Service sets PORT
: "${PORT:=8000}"
: "${HOST:=0.0.0.0}"

echo "Starting Chainlit on ${HOST}:${PORT} (LangGraph=${USE_LANGGRAPH:-false})"
exec chainlit run app.py --host "${HOST}" --port "${PORT}"
