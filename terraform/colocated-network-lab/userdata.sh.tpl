#!/bin/bash
# Colocated network lab bootstrap — ContainerLab fabric + k3s ktranslate-golden.
set -euxo pipefail
exec > >(tee /var/log/network-o11y-bootstrap.log) 2>&1

REPO_URL="${repo_url}"
REPO_BRANCH="${repo_branch}"
KTRANS_HOST="${ktrans_host}"
LAB_TESTER_ID="${lab_tester_id}"

dnf install -y docker git make gettext tar gzip which >/dev/null
systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL https://github.com/docker/compose/releases/download/v2.29.2/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

if ! command -v containerlab >/dev/null 2>&1; then
  curl -sL https://get.containerlab.dev | bash
fi

if ! command -v yq >/dev/null 2>&1; then
  curl -sL "https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64" -o /usr/local/bin/yq
  chmod +x /usr/local/bin/yq
fi

if ! command -v kubectl >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

install -d -m 0755 /opt
if [[ ! -d /opt/network-o11y-demo/.git ]]; then
  git clone --depth 1 -b "$REPO_BRANCH" "$REPO_URL" /opt/network-o11y-demo
fi

LAB_ROOT=/opt/network-o11y-demo/local
install -d -m 0755 "$LAB_ROOT/groups" "$LAB_ROOT/config" "$LAB_ROOT/state"

cat >"$LAB_ROOT/.env" <<ENV
GC_OTLP_URL=${gc_otlp_url}
GC_OTLP_ACCOUNT=${gc_otlp_account}
GC_OTLP_KEY=${gc_otlp_key}
KTRANS_HOST=$KTRANS_HOST
LAB_TESTER_ID=$LAB_TESTER_ID
CLAB_NETWORK=clab
COLLECTOR_RUNTIME=k3s
KTRANSLATE_OTEL_ENDPOINT=http://127.0.0.1:4317
KTRANSLATE_IMAGE=quay.io/kentik/ktranslate:latest
GNMIC_IMAGE=ghcr.io/openconfig/gnmic:latest
ENV
chmod 0600 "$LAB_ROOT/.env"

if [[ ! -f "$LAB_ROOT/groups/srl.env" ]]; then
  cp "$LAB_ROOT/groups/srl.env.sample" "$LAB_ROOT/groups/srl.env"
fi

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
Environment=KUBECONFIG=/etc/rancher/k3s/k3s.yaml
ExecStart=/bin/bash /opt/network-o11y-demo/local/scripts/colocated-telemetry-bringup.sh
ExecStop=/bin/bash -lc 'kubectl delete -k /opt/network-o11y-demo/k8s/ktranslate-golden --ignore-not-found=true || true'
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now network-o11y-fabric.service
systemctl enable --now network-o11y-telemetry.service
