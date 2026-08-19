#!/usr/bin/env bash
# post-telemetry-config.sh — wire device exports → collectors and start demo workloads.
#
# Idempotent; safe to re-run after compose recreate or clab IP drift (with make stabilize).
# Called at end of make up / stabilize after SNMP discovery.
#
# Opt out via .env:
#   LAB_AUTO_TRAFFIC=0           skip client UDP/ICMP workloads (flows need traffic for volume)
#   LAB_AUTO_INTERNET_PROBES=0   skip occasional HTTPS to public sites (mgmt eth0)
#   LAB_AUTO_EVENTS=0            skip background link-flap emit-events loop
#   LAB_AUTO_SYNTHETIC_TRAPS=1     opt-in host snmptrap suite (default off; SRL sends real traps)

set -euo pipefail

export HOME="${HOME:-/root}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

warn() { echo "WARNING: $*" >&2; }
info() { echo "==> $*"; }

if [[ "${LAB_FABRIC_PROFILE}" == "snmp-min" ]]; then
  info "snmp-min profile — skipping traffic/flow/syslog/events (Alloy SNMP only)"
  exit 0
fi

bash "${ROOT}/scripts/lab-topology-exporter.sh" post-config || true

if bash "${ROOT}/scripts/lab-alloy-snmp.sh" enabled; then
  info "Rendering Alloy SNMP scrape overlay (LAB_ALLOY_SNMP=1)..."
  bash "${ROOT}/scripts/render-alloy-snmp-scrape.sh" \
    || warn "alloy SNMP scrape render failed"
  info "Alloy SNMP discovery (named auth + sysObjectID→module)..."
  bash "${ROOT}/scripts/alloy-snmp-discover.sh" \
    || warn "alloy-snmp-discover failed — run: make alloy-snmp-discover"
  if docker inspect alloy >/dev/null 2>&1; then
    info "Recreating alloy to pick up SNMP scrape overlay..."
    (cd "${ROOT}" && docker compose --env-file .env --env-file compose-host.generated.env \
      -f compose-base.yaml -f compose-groups.generated.yaml -f compose-catalog.generated.yaml \
      -f compose-limits.generated.yaml up -d --no-deps alloy) \
      || warn "alloy recreate failed — run: docker compose up -d --force-recreate alloy"
  fi
fi

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

info "Configuring SNMP traps → ktranslate poller or Alloy :1620..."
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
  info "Starting events-loop (link flaps for real SRL traps/syslog; synthetic traps off unless LAB_AUTO_SYNTHETIC_TRAPS=1)..."
  bash "${ROOT}/scripts/events-loop.sh" start \
    || warn "events-loop failed — run: make events-loop"
else
  info "Skipping events-loop (LAB_AUTO_EVENTS=0)"
fi

info "Telemetry sidecars configured (flows, syslog, traps, sFlow, gNMI collectors should already be up)."
