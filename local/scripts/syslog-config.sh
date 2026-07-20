#!/usr/bin/env bash
# syslog-config.sh — point SR Linux remote syslog at ktranslate_syslog:1514/udp

set -euo pipefail

CLAB_NET="${CLAB_NETWORK:-clab}"
DEVICES=(spine1 leaf1 leaf2)
PORT=1514

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

syslog_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" ktranslate_syslog 2>/dev/null || true)"
[[ -n "$syslog_ip" && "$syslog_ip" != "<no value>" ]] || die "ktranslate_syslog not on network ${CLAB_NET} — is compose up?"

info "Syslog destination: ${syslog_ip}:${PORT}/udp"

for d in "${DEVICES[@]}"; do
  docker inspect "$d" >/dev/null 2>&1 || die "container ${d} not found"
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
