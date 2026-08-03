#!/usr/bin/env bash
# Continue EC2 bootstrap after userdata failed mid-flight (deps, .env, systemd).
# Requires: GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY; optional KTRANS_HOST, LAB_TESTER_ID.
set -euxo pipefail

REPO_ROOT=/opt/network-o11y-demo
LAB_ROOT="${REPO_ROOT}/local"
KTRANS_HOST="${KTRANS_HOST:-aws-colocated-lab}"
LAB_TESTER_ID="${LAB_TESTER_ID:-aws-colocated-lab}"

: "${GC_OTLP_URL:?GC_OTLP_URL required}"
: "${GC_OTLP_ACCOUNT:?GC_OTLP_ACCOUNT required}"
: "${GC_OTLP_KEY:?GC_OTLP_KEY required}"

if [[ -d "${REPO_ROOT}/.git" ]]; then
  git -C "$REPO_ROOT" fetch origin main --depth 1
  git -C "$REPO_ROOT" reset --hard origin/main
fi

bash "${LAB_ROOT}/scripts/colocated-host-deps.sh"

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

bash "${LAB_ROOT}/scripts/ensure-snmp-groups.sh"

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

systemctl daemon-reload
systemctl enable --now network-o11y-fabric.service
systemctl enable --now network-o11y-telemetry.service

echo "recover: fabric=$(systemctl is-active network-o11y-fabric) telemetry=$(systemctl is-active network-o11y-telemetry)"
