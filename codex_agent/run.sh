#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/users /data/runs /data/snapshots /data/tmp

exec /sbin/tini -- /opt/codex-agent/bin/uvicorn \
  codex_agent.main:app \
  --host "${CODEX_AGENT_HOST:-0.0.0.0}" \
  --port "${CODEX_AGENT_PORT:-8099}" \
  --proxy-headers
