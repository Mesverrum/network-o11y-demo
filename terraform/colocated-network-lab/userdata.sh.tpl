#!/bin/bash
# Colocated network lab bootstrap — ContainerLab fabric + k3s ktranslate-golden.
set -euxo pipefail
exec > >(tee /var/log/network-o11y-bootstrap.log) 2>&1

REPO_URL="${repo_url}"
REPO_BRANCH="${repo_branch}"

REPO_ROOT=/opt/network-o11y-demo
LAB_ROOT=/opt/network-o11y-demo/local

install -d -m 0755 /opt
# Fresh AL2023 has no git — install before clone; full toolchain after clone.
if ! command -v git >/dev/null 2>&1; then
  dnf install -y git
fi
if [[ ! -d "$${REPO_ROOT}/.git" ]]; then
  git clone --depth 1 -b "$REPO_BRANCH" "$REPO_URL" "$REPO_ROOT"
else
  git -C "$REPO_ROOT" fetch origin "$REPO_BRANCH" --depth 1
  git -C "$REPO_ROOT" checkout "$REPO_BRANCH"
  git -C "$REPO_ROOT" reset --hard "origin/$${REPO_BRANCH}"
fi

bash "$${LAB_ROOT}/scripts/colocated-host-deps.sh"

export GC_OTLP_URL=${gc_otlp_url}
export GC_OTLP_ACCOUNT=${gc_otlp_account}
export GC_OTLP_KEY=${gc_otlp_key}
export KTRANS_HOST=${ktrans_host}
export LAB_TESTER_ID=${lab_tester_id}

bash "$${LAB_ROOT}/scripts/colocated-ec2-bootstrap.sh"
