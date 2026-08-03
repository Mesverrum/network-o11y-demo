#!/usr/bin/env bash
# Continue EC2 bootstrap after userdata failed mid-flight.
# Usage (on instance): export GC_OTLP_URL=... GC_OTLP_ACCOUNT=... GC_OTLP_KEY=...
#   optional KTRANS_HOST, LAB_TESTER_ID — then run this script.
set -euxo pipefail

REPO_ROOT=/opt/network-o11y-demo
LAB_ROOT="${REPO_ROOT}/local"

if [[ -d "${REPO_ROOT}/.git" ]]; then
  git -C "$REPO_ROOT" fetch origin main --depth 1
  git -C "$REPO_ROOT" reset --hard origin/main
fi

bash "${LAB_ROOT}/scripts/colocated-host-deps.sh"
bash "${LAB_ROOT}/scripts/colocated-ec2-bootstrap.sh"
