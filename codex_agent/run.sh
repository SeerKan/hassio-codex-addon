#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/users /data/runs /data/snapshots /data/tmp

export PYTHONPATH="/app/src:${PYTHONPATH:-}"
cd /app/src

python3 - <<'PY'
import codex_agent
print(f"Starting Home Assistant Codex Agent {codex_agent.__version__}", flush=True)
PY

exec /opt/codex-agent/bin/uvicorn \
  codex_agent.main:app \
  --host "${CODEX_AGENT_HOST:-0.0.0.0}" \
  --port "${CODEX_AGENT_PORT:-8099}" \
  --proxy-headers
