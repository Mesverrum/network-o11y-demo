#!/usr/bin/env bash
# syslog-config.sh — point SR Linux remote syslog at the syslog sink(s).
# ktranslate_syslog:1514. Alloy :1514 (cutover) or :1515 (parallel).
# Same-IP dual dest uses ALLOY_EVENTS_ALIAS_IP (default <prefix>.253).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=collector-runtime-ready.sh
source "${ROOT}/scripts/collector-runtime-ready.sh"
# shellcheck source=alloy-events-ports.sh
source "${ROOT}/scripts/alloy-events-ports.sh"

if [[ -f "${ROOT}/.env" ]]; then
  if [[ -z "${LAB_ALLOY_SYSLOG:-}" ]]; then
    LAB_ALLOY_SYSLOG="$(awk -F= '/^LAB_ALLOY_SYSLOG=/{gsub(/\r/,""); print $2; exit}' "${ROOT}/.env" || true)"
    export LAB_ALLOY_SYSLOG
  fi
  if [[ -z "${LAB_KTRANSLATE:-}" ]]; then
    LAB_KTRANSLATE="$(awk -F= '/^LAB_KTRANSLATE=/{gsub(/\r/,""); print $2; exit}' "${ROOT}/.env" || true)"
    export LAB_KTRANSLATE
  fi
fi
export_colocated_clab_host
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
CLAB_NET="${CLAB_NETWORK:-clab}"
DEVICES=("${SRL_NODES[@]}")
KT_PORT=1514

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

use_alloy=0
if lab_flag_on "${LAB_ALLOY_SYSLOG:-0}"; then
  use_alloy=1
fi
use_ktrans=0
if lab_ktranslate_on && collector_syslog_ready; then
  use_ktrans=1
fi
if [[ "${use_alloy}" != "1" && "${use_ktrans}" != "1" ]]; then
  if collector_syslog_ready; then
    use_ktrans=1
  elif collector_alloy_ready; then
    use_alloy=1
  else
    die "no syslog sink"
  fi
fi

kt_ip=""
if [[ "${use_ktrans}" == "1" ]]; then
  kt_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" syslog 2>/dev/null || true)"
  if [[ -z "$kt_ip" || "$kt_ip" == "<no value>" ]]; then
    kt_ip="${KTRANSLATE_CLAB_HOST:-}"
  fi
  [[ -n "$kt_ip" && "$kt_ip" != "<no value>" ]] || die "syslog collector not reachable on ${CLAB_NET}"
fi

alloy_ip=""
alloy_port="$(alloy_syslog_listen_port)"
if [[ "${use_alloy}" == "1" ]]; then
  alloy_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" alloy 2>/dev/null || true)"
  if [[ -z "$alloy_ip" || "$alloy_ip" == "<no value>" ]]; then
    alloy_ip="${KTRANSLATE_CLAB_HOST:-${kt_ip}}"
  fi
  [[ -n "$alloy_ip" && "$alloy_ip" != "<no value>" ]] || die "Alloy not on network ${CLAB_NET} — set LAB_ALLOY_SYSLOG=1"
  if [[ "${use_ktrans}" == "1" && "${alloy_ip}" == "${kt_ip}" ]]; then
    alloy_ip="$(ensure_alloy_events_alias_ip "${kt_ip}")"
    info "Syslog Alloy alias ${alloy_ip}:${alloy_port} (SRL remote-server is keyed by address)"
  fi
fi

apply_remote() {
  local ip="$1" port="$2"
  cat <<EOF
set / system logging remote-server ${ip} transport udp remote-port ${port}
set / system logging remote-server ${ip} facility local6 priority match-above informational
set / system logging remote-server ${ip} facility local7 priority match-above informational
set / system logging remote-server ${ip} subsystem aaa priority match-above informational
set / system logging remote-server ${ip} subsystem acl priority match-above informational
set / system logging remote-server ${ip} subsystem bgp priority match-above informational
set / system logging remote-server ${ip} subsystem chassis priority match-above informational
set / system logging remote-server ${ip} subsystem grpc priority match-above informational
set / system logging remote-server ${ip} subsystem lldp priority match-above informational
set / system logging remote-server ${ip} subsystem mgmt priority match-above informational
set / system logging remote-server ${ip} subsystem netinst priority match-above informational
set / system logging remote-server ${ip} subsystem platform priority match-above informational
EOF
}

extra=""
if [[ "${use_ktrans}" == "1" && "${use_alloy}" == "1" ]]; then
  info "Syslog sinks: ktranslate ${kt_ip}:${KT_PORT} + Alloy ${alloy_ip}:${alloy_port}"
  dest_ip="${kt_ip}"
  dest_port="${KT_PORT}"
  extra="$(apply_remote "${alloy_ip}" "${alloy_port}")"
elif [[ "${use_alloy}" == "1" ]]; then
  info "Syslog sink: Alloy ${alloy_ip}:${alloy_port}/udp (otelcol.receiver.syslog)"
  dest_ip="${alloy_ip}"
  dest_port="${alloy_port}"
else
  info "Syslog destination: ${kt_ip}:${KT_PORT}/udp"
  dest_ip="${kt_ip}"
  dest_port="${KT_PORT}"
fi

for d in "${DEVICES[@]}"; do
  if ! docker inspect "$d" >/dev/null 2>&1; then
    info "skip ${d} (container not running)"
    continue
  fi
  info "Configuring syslog on ${d}..."
  docker exec -i "$d" bash -c "sr_cli -ed" <<EOF
set / system logging network-instance mgmt
$(apply_remote "${dest_ip}" "${dest_port}")
${extra}
commit stay
EOF
done

info "Done."
