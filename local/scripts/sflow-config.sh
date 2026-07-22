#!/usr/bin/env bash
# sflow-config.sh — enable SR Linux sFlow on spine (and optional leaves) → ktranslate_sflow:6343
#
# Simulator note: containerized SR Linux often exports sFlow counter-samples (interface
# stats), not full flow-samples. Client softflowd (make softflowd) still provides L4 flows.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAB_NET="${CLAB_NETWORK:-clab}"
SFLOW_PORT="${SFLOW_PORT:-6343}"
# Space-separated list; default spine only.
SFLOW_DEVICES="${SFLOW_DEVICES:-spine1}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

sflow_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" ktranslate_sflow 2>/dev/null || true)"
[[ -n "$sflow_ip" && "$sflow_ip" != "<no value>" ]] || die "ktranslate_sflow not on network ${CLAB_NET} — run: docker compose up -d ktranslate_sflow"

info "sFlow collector: ${sflow_ip}:${SFLOW_PORT}/udp (network-instance mgmt)"

for d in ${SFLOW_DEVICES}; do
  docker inspect "$d" >/dev/null 2>&1 || die "container ${d} not found"
  src_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$d" 2>/dev/null || true)"
  [[ -n "$src_ip" && "$src_ip" != "<no value>" ]] || die "could not resolve mgmt IP for ${d} on ${CLAB_NET}"

  info "Configuring sFlow on ${d} (source ${src_ip})..."
  docker exec -i "$d" bash -c "sr_cli -ed" <<EOF
set / system sflow admin-state enable
set / system sflow sample-rate 10000
set / system sflow collector 1 collector-address ${sflow_ip}
set / system sflow collector 1 network-instance mgmt
set / system sflow collector 1 source-address ${src_ip}
set / system sflow collector 1 port ${SFLOW_PORT}
set / interface ethernet-1/1 sflow admin-state enable
set / interface ethernet-1/2 sflow admin-state enable
commit stay
EOF
done

info "Done. Check: docker logs ktranslate_sflow --tail 20"
