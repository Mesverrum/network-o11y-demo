#!/usr/bin/env bash
# syslog-config.sh — point SR Linux remote syslog at the syslog sink.
# Default: ktranslate_syslog:1514. LAB_ALLOY_SYSLOG=1 → Alloy :1514 on clab.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=collector-runtime-ready.sh
source "${ROOT}/scripts/collector-runtime-ready.sh"

if [[ -f "${ROOT}/.env" ]] && [[ -z "${LAB_ALLOY_SYSLOG:-}" ]]; then
  LAB_ALLOY_SYSLOG="$(awk -F= '/^LAB_ALLOY_SYSLOG=/{gsub(/\r/,""); print $2; exit}' "${ROOT}/.env" || true)"
  export LAB_ALLOY_SYSLOG
fi
export_colocated_clab_host
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
CLAB_NET="${CLAB_NETWORK:-clab}"
DEVICES=("${SRL_NODES[@]}")
PORT=1514

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

use_alloy=0
case "${LAB_ALLOY_SYSLOG:-0}" in
  1|true|TRUE|yes|YES|on|ON) use_alloy=1 ;;
esac

syslog_ip=""
if [[ "${use_alloy}" == "1" ]]; then
  syslog_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" alloy 2>/dev/null || true)"
  [[ -n "$syslog_ip" && "$syslog_ip" != "<no value>" ]] || die "Alloy not on network ${CLAB_NET} — recreate alloy with LAB_ALLOY_SYSLOG=1"
  info "Syslog sink: Alloy ${syslog_ip}:${PORT}/udp (loki.source.syslog)"
else
  syslog_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" syslog 2>/dev/null || true)"
  [[ -n "$syslog_ip" && "$syslog_ip" != "<no value>" ]] || die "syslog collector not reachable on ${CLAB_NET}"
fi

info "Syslog destination: ${syslog_ip}:${PORT}/udp"

for d in "${DEVICES[@]}"; do
  if ! docker inspect "$d" >/dev/null 2>&1; then
    info "skip ${d} (container not running)"
    continue
  fi
  info "Configuring syslog on ${d}..."
  # Non-interactive: pipe commands into sr_cli (heredoc + docker exec -i fails under some WSL paths)
  docker exec -i "$d" bash -c "sr_cli -ed" <<EOF
set / system logging network-instance mgmt
set / system logging remote-server ${syslog_ip} transport udp remote-port ${PORT}
set / system logging remote-server ${syslog_ip} facility local6 priority match-above informational
set / system logging remote-server ${syslog_ip} facility local7 priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem aaa priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem acl priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem bgp priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem chassis priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem grpc priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem lldp priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem mgmt priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem netinst priority match-above informational
set / system logging remote-server ${syslog_ip} subsystem platform priority match-above informational
commit stay
EOF
done

info "Done."
