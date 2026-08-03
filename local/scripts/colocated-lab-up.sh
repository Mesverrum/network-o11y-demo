#!/usr/bin/env bash
# Bring up colocated ContainerLab + k3s ktranslate-golden in AWS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/colocated-network-lab"
PROFILE="${AWS_PROFILE:-mvr}"
export AWS_PROFILE="$PROFILE"
REGION="${AWS_REGION:-us-east-1}"
TF="$(cd "$(dirname "$0")" && pwd)/aws-lab-terraform.sh"
# shellcheck source=aws-cmd.sh
source "$(cd "$(dirname "$0")" && pwd)/aws-cmd.sh"

if aws_cmd sts get-caller-identity --region "$REGION" >/dev/null 2>&1; then
  : # creds OK
elif ! command -v terraform >/dev/null 2>&1; then
  echo "==> AWS STS preflight skipped (Docker terraform uses mounted ~/.aws)" >&2
else
  echo "ERROR: AWS credentials check failed — set AWS_PROFILE and ~/.aws" >&2
  exit 1
fi

TF_EXTRA=()
ENV_FILE="${ROOT}/local/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "$ENV_FILE")
  set +a
  if [[ -n "${GC_OTLP_URL:-}" && -n "${GC_OTLP_ACCOUNT:-}" && -n "${GC_OTLP_KEY:-}" ]]; then
    TF_EXTRA+=(
      -var="gc_otlp_url=${GC_OTLP_URL}"
      -var="gc_otlp_account=${GC_OTLP_ACCOUNT}"
      -var="gc_otlp_key=${GC_OTLP_KEY}"
    )
  else
    echo "ERROR: set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY in local/.env" >&2
    exit 1
  fi
  if [[ -n "${LAB_TESTER_ID:-}" ]]; then
    TF_EXTRA+=(-var="lab_tester_id=${LAB_TESTER_ID}")
  fi
  if [[ -n "${KTRANS_HOST:-}" ]]; then
    TF_EXTRA+=(-var="ktrans_host=${KTRANS_HOST}")
  fi
else
  echo "ERROR: missing local/.env" >&2
  exit 1
fi

if [[ ! -f "${LAB}/terraform.tfvars" ]]; then
  bash "$(cd "$(dirname "$0")" && pwd)/colocated-lab-discover.sh"
fi

bash "$TF" "$LAB" init -input=false
bash "$TF" "$LAB" apply -auto-approve -var="lab_enabled=true" "${TF_EXTRA[@]}"

echo ""
echo "Account: $(bash "$TF" "$LAB" output -raw account_id 2>/dev/null || echo n/a)"
echo "Instance: $(bash "$TF" "$LAB" output -raw instance_id 2>/dev/null || echo n/a)"
echo "Private IP: $(bash "$TF" "$LAB" output -raw private_ip 2>/dev/null || echo n/a)"
echo ""
echo "Bootstrap (~15 min). Monitor:"
echo "  $(bash "$TF" "$LAB" output -raw ssm_connect_command 2>/dev/null || echo 'aws ssm start-session --target <id>')"
echo "  sudo journalctl -u network-o11y-telemetry -f"
echo ""
bash "$TF" "$LAB" output -raw grafana_checks 2>/dev/null || true
