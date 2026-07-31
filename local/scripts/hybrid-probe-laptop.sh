#!/usr/bin/env bash
# Start hybrid probe agent on laptop (listens for AWS callbacks on :18080).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m pip install -q -r hybrid-probe/requirements.txt --ignore-scripts 2>/dev/null || \
  pip install -q -r hybrid-probe/requirements.txt --ignore-scripts
exec python3 hybrid-probe/agent.py \
  --config hybrid-probe/targets-laptop.yaml \
  --listen "${HYBRID_PROBE_LISTEN_PORT:-18080}"
