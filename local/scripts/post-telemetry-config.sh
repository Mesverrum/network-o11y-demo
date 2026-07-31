#!/usr/bin/env bash
# post-telemetry-config.sh — wire device exports → collectors and start demo workloads.
#
# Idempotent; safe to re-run after compose recreate or clab IP drift (with make stabilize).
# Called at end of make up / stabilize after SNMP discovery.
#
# Opt out via .env:
#   LAB_AUTO_TRAFFIC=0           skip client UDP/ICMP workloads (flows need traffic for volume)
#   LAB_AUTO_INTERNET_PROBES=0   skip occasional HTTPS to public sites (mgmt eth0)
#   LAB_AUTO_EVENTS=0            skip background traps + link-flap syslog loop

set -euo pipefail

export HOME="${HOME:-/root}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

warn() { echo "WARNING: $*" >&2; }
info() { echo "==> $*"; }

bash "${ROOT}/scripts/lab-topology-exporter.sh" post-config || true

bash "${ROOT}/scripts/refresh-flow-dns.sh" \
  || warn "flow-dns refresh failed — flow src_host/dst_host may stay empty"

info "Starting softflowd on clients → ktranslate_flow..."
bash "${ROOT}/scripts/softflowd.sh" \
  || warn "softflowd failed — check client eth1 / ktranslate_flow on clab"

info "Configuring sFlow → ktranslate_sflow..."
bash "${ROOT}/scripts/sflow-config.sh" \
  || warn "sflow config failed — check sr_cli syntax"

info "Configuring syslog → ktranslate_syslog..."
bash "${ROOT}/scripts/syslog-config.sh" \
  || warn "syslog config failed — check sr_cli syntax"

info "Configuring SNMP traps → ktranslate_snmp_srl..."
bash "${ROOT}/scripts/snmp-trap-config.sh" \
  || warn "snmp trap config failed — check sr_cli syntax"

info "Exporting SR Linux mgmt API catalog (live + mock)..."
bash "${ROOT}/scripts/mgmt-api-mock.sh" emit \
  || warn "mgmt-api-mock export failed — check go + alloy OTLP"

if [[ "${LAB_AUTO_TRAFFIC:-1}" == "1" ]]; then
  info "Starting traffic workloads (client1 ↔ client2)..."
  bash "${ROOT}/scripts/traffic.sh" start \
    || warn "traffic start failed — run: make traffic"
else
  info "Skipping traffic (LAB_AUTO_TRAFFIC=0)"
fi

if [[ "${LAB_AUTO_INTERNET_PROBES:-1}" == "1" ]]; then
  info "Starting internet probes (client mgmt → grafana.com / github.com / kentik.com)..."
  bash "${ROOT}/scripts/internet-probes.sh" start \
    || warn "internet-probes failed — run: make internet-probes"
else
  info "Skipping internet probes (LAB_AUTO_INTERNET_PROBES=0)"
fi

if [[ "${LAB_AUTO_EVENTS:-1}" == "1" ]]; then
  info "Starting events-loop (synthetic traps + link flaps for syslog/traps)..."
  bash "${ROOT}/scripts/events-loop.sh" start \
    || warn "events-loop failed — run: make events-loop"
else
  info "Skipping events-loop (LAB_AUTO_EVENTS=0)"
fi

info "Telemetry sidecars configured (flows, syslog, traps, sFlow, gNMI collectors should already be up)."
