#!/usr/bin/env bash
# Idempotent OS + toolchain install for colocated EC2 (fresh AL2023 or re-run).
set -euo pipefail

log() { echo "$(date -Is) [colocated-deps] $*"; }

if [[ "$(id -u)" -ne 0 ]]; then
  SUDO=sudo
else
  SUDO=
fi

log "installing base packages (dnf)"
# AL2023 ships curl-minimal; full curl package conflicts — do not install curl.
$SUDO dnf install -y \
  docker git make gettext tar gzip which rsync \
  python3 python3-pip jq iproute procps-ng

log "enabling docker"
$SUDO systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  log "installing docker compose plugin"
  $SUDO mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL https://github.com/docker/compose/releases/download/v2.29.2/docker-compose-linux-x86_64 \
    -o /tmp/docker-compose
  $SUDO install -m 0755 /tmp/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
  rm -f /tmp/docker-compose
fi

if ! command -v containerlab >/dev/null 2>&1; then
  log "installing containerlab"
  curl -sL https://get.containerlab.dev | bash
fi

if ! command -v yq >/dev/null 2>&1; then
  log "installing yq"
  curl -fsSL "https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64" \
    -o /tmp/yq
  $SUDO install -m 0755 /tmp/yq /usr/local/bin/yq
  rm -f /tmp/yq
fi

if ! command -v kubectl >/dev/null 2>&1; then
  log "installing k3s"
  curl -sfL https://get.k3s.io | $SUDO INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -
fi

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
log "waiting for k3s API"
for _ in $(seq 1 60); do
  if kubectl get nodes >/dev/null 2>&1; then
    log "k3s ready"
    break
  fi
  sleep 5
done
kubectl get nodes >/dev/null 2>&1 || {
  log "ERROR: k3s API not ready after 5m"
  exit 1
}

log "host dependencies OK"
