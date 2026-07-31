#!/usr/bin/env bash
# Bring up AWS dashboard lab (NLB + traffic hosts). Requires: aws sso login --profile mvr
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/aws-dashboard-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"
TF="$(dirname "$0")/aws-lab-terraform.sh"

aws_cmd() {
  if command -v aws >/dev/null 2>&1; then
    aws "$@"
    return
  fi
  local win_aws="/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe"
  if [[ -x "$win_aws" ]]; then
    "$win_aws" "$@"
    return
  fi
  echo "ERROR: aws CLI not found" >&2
  exit 1
}

aws_cmd sts get-caller-identity --profile "$PROFILE" --region "$REGION" >/dev/null

# OTLP creds for hybrid probe (optional; baked into traffic host userdata)
TF_EXTRA=()
ENV_FILE="${ROOT}/local/.env"
if [[ -f "$ENV_FILE" ]]; then
  # Strip Windows CRLF before sourcing (repo may live on /mnt/c).
  # shellcheck disable=SC1090
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
  fi
  if [[ -n "${HYBRID_LAPTOP_CALLBACK_URL:-}" ]]; then
    TF_EXTRA+=(-var="laptop_callback_url=${HYBRID_LAPTOP_CALLBACK_URL}")
  fi
fi

if [[ ! -f "${LAB}/terraform.tfvars" ]]; then
  bash "$(dirname "$0")/aws-lab-discover.sh"
fi

cd "$LAB"
bash "$TF" "$LAB" init -input=false
bash "$TF" "$LAB" apply -auto-approve -var="lab_enabled=true" "${TF_EXTRA[@]}"

echo ""
echo "Lab is up. NLB DNS: $(bash "$TF" "$LAB" output -raw nlb_dns_name 2>/dev/null || echo n/a)"
echo "Traffic hosts: $(bash "$TF" "$LAB" output -json traffic_private_ips 2>/dev/null || echo '{}')"
echo "Hybrid probe: baked into traffic host userdata when GC_OTLP_* set in local/.env"
echo "Laptop probe: make -C local hybrid-probe-laptop  (or hybrid-probe-once for one cycle)"
echo "Allow ~5-15m for CloudWatch → Grafana, then check Cloud Network dashboards."
echo "Tear down: make -C local aws-lab-down"
