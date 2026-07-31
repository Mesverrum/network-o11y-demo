#!/usr/bin/env bash
# Tear down billable dashboard lab resources between sessions.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/aws-dashboard-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"
TF="$(dirname "$0")/aws-lab-terraform.sh"

aws_cmd() {
  if command -v aws >/dev/null 2>&1; then aws "$@"; return; fi
  local win_aws="/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe"
  [[ -x "$win_aws" ]] && "$win_aws" "$@" && return
  echo "ERROR: aws CLI not found" >&2; exit 1
}

if [[ ! -d "${LAB}/.terraform" ]]; then
  echo "Lab not initialized; nothing to destroy."
  exit 0
fi

cd "$LAB"
aws_cmd sts get-caller-identity --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1 || {
  echo "AWS SSO expired. Run: aws sso login --profile ${PROFILE}"
  exit 1
}

bash "$TF" "$LAB" destroy -auto-approve

echo "Dashboard lab destroyed."
