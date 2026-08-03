#!/usr/bin/env bash
# Finish colocated EC2 bootstrap: .env, site SNMP groups, systemd units, start lab.
# Called from terraform userdata.sh.tpl (after git clone + colocated-host-deps.sh).
# Manual recovery: export GC_OTLP_* (or source local/.env) then run this script.
set -euxo pipefail

REPO_ROOT="${REPO_ROOT:-/opt/network-o11y-demo}"
LAB_ROOT="${LAB_ROOT:-${REPO_ROOT}/local}"

log() { echo "$(date -Is) [colocated-ec2-bootstrap] $*"; }

install_systemd_units() {
  cat >/etc/systemd/system/network-o11y-fabric.service <<'UNIT'
[Unit]
Description=Network O11y ContainerLab fabric (no compose collectors)
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/network-o11y-demo/local
Environment=HOME=/root
Environment=LAB_FABRIC_PROFILE=colocated
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/bin/bash /opt/network-o11y-demo/local/scripts/colocated-fabric-bringup.sh
ExecStop=/bin/bash -lc 'cd /opt/network-o11y-demo/local && docker ps -q | xargs -r docker stop'
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
UNIT

  cat >/etc/systemd/system/network-o11y-telemetry.service <<'UNIT'
[Unit]
Description=Network O11y ktranslate-golden on k3s
After=network-o11y-fabric.service k3s.service docker.service
Wants=k3s.service
Requires=network-o11y-fabric.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/network-o11y-demo/local
Environment=HOME=/root
Environment=LAB_FABRIC_PROFILE=colocated
Environment=COLLECTOR_RUNTIME=k3s
Environment=KUBECONFIG=/etc/rancher/k3s/k3s.yaml
Environment=KTRANSLATE_OTEL_ENDPOINT=http://127.0.0.1:4317/
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/bin/bash /opt/network-o11y-demo/local/scripts/colocated-telemetry-bringup.sh
ExecStop=/bin/bash -lc 'kubectl delete -k /opt/network-o11y-demo/k8s/ktranslate-golden --ignore-not-found=true || true'
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
UNIT
}

# Load existing .env when terraform/user did not export OTLP vars.
if [[ -f "${LAB_ROOT}/.env" && -z "${GC_OTLP_URL:-}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "${LAB_ROOT}/.env")
  set +a
fi

KTRANS_HOST="${KTRANS_HOST:-aws-colocated-lab}"
LAB_TESTER_ID="${LAB_TESTER_ID:-aws-colocated-lab}"

: "${GC_OTLP_URL:?GC_OTLP_URL required}"
: "${GC_OTLP_ACCOUNT:?GC_OTLP_ACCOUNT required}"
: "${GC_OTLP_KEY:?GC_OTLP_KEY required}"

install -d -m 0755 "${LAB_ROOT}/groups" "${LAB_ROOT}/config" "${LAB_ROOT}/state"

cat >"${LAB_ROOT}/.env" <<ENV
GC_OTLP_URL=${GC_OTLP_URL}
GC_OTLP_ACCOUNT=${GC_OTLP_ACCOUNT}
GC_OTLP_KEY=${GC_OTLP_KEY}
KTRANS_HOST=${KTRANS_HOST}
LAB_TESTER_ID=${LAB_TESTER_ID}
LAB_FABRIC_PROFILE=colocated
CLAB_NETWORK=clab
COLLECTOR_RUNTIME=k3s
KTRANSLATE_OTEL_ENDPOINT=http://127.0.0.1:4317
KTRANSLATE_IMAGE=quay.io/kentik/ktranslate:latest
GNMIC_IMAGE=ghcr.io/openconfig/gnmic:latest
FLOW_DNS_UPSTREAM=169.254.169.253
LAB_AUTO_INTERNET_PROBES=0
LAB_AUTO_SYNTHETIC_TRAPS=0
ENV
chmod 0600 "${LAB_ROOT}/.env"

export LAB_FABRIC_PROFILE=colocated
export HOME="${HOME:-/root}"

log "installing site SNMP groups (srl-hq, srl-branch1, srl-branch2)"
bash "${LAB_ROOT}/scripts/colocated-snmp-groups.sh"

log "installing systemd units"
install_systemd_units
systemctl daemon-reload
systemctl enable network-o11y-fabric.service network-o11y-telemetry.service

log "starting fabric (ContainerLab — may take ~10 min)"
systemctl reset-failed network-o11y-fabric.service network-o11y-telemetry.service 2>/dev/null || true
systemctl start network-o11y-fabric.service

log "starting telemetry (k3s collectors)"
systemctl start network-o11y-telemetry.service

log "fabric=$(systemctl is-active network-o11y-fabric) telemetry=$(systemctl is-active network-o11y-telemetry)"
