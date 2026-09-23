#!/usr/bin/env bash
# Apply kafka-plugin-lab with exported SSO session creds (safe for Terraform-in-Docker on Windows).
set -euo pipefail

WIN_LAB="/mnt/c/Users/mesve/projects/network-o11y-demo/terraform/kafka-plugin-lab"
WSL_ROOT="${HOME}/network-o11y-demo"
LAB="${WSL_ROOT}/terraform/kafka-plugin-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"

if [[ ! -f "${WIN_LAB}/main.tf" ]]; then
  echo "ERROR: missing ${WIN_LAB}" >&2
  exit 1
fi

mkdir -p "${WSL_ROOT}/terraform"
rm -rf "$LAB"
cp -a "$WIN_LAB" "$LAB"

if [[ -z "${AWS_ACCESS_KEY_ID:-}" || -z "${AWS_SECRET_ACCESS_KEY:-}" || -z "${AWS_SESSION_TOKEN:-}" ]]; then
  if command -v aws >/dev/null 2>&1; then
    eval "$(aws --profile "$PROFILE" configure export-credentials --format env | tr -d '\r')"
  else
    echo "ERROR: export AWS session credentials first, or run kafka-plugin-lab-up.ps1 on Windows" >&2
    exit 1
  fi
fi
export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"
export AWS_PROFILE=""
export AWS_SDK_LOAD_CONFIG=0

run_tf() {
  docker run --rm \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    -e AWS_REGION \
    -e AWS_DEFAULT_REGION \
    -e AWS_PROFILE= \
    -e AWS_SDK_LOAD_CONFIG=0 \
    -v "${WSL_ROOT}:/repo" \
    -w /repo/terraform/kafka-plugin-lab \
    hashicorp/terraform:1.9 \
    "$@"
}

run_tf init -input=false
run_tf apply -auto-approve -input=false -var=aws_profile= -var=lab_enabled=true

echo "instance_id=$(run_tf output -raw instance_id)"
echo "private_ip=$(run_tf output -raw private_ip)"
echo "ssm: $(run_tf output -raw ssm_port_forward)"
