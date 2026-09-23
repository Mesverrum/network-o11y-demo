#!/usr/bin/env bash
# Discover VPC/subnet and apply terraform/kafka-plugin-lab (separate from the Clos host).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/kafka-plugin-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"

aws_bin() {
  if command -v aws >/dev/null 2>&1 && aws --version >/dev/null 2>&1; then
    command -v aws
    return
  fi
  echo "ERROR: aws CLI not found (run from Windows or WSL with working aws)" >&2
  exit 1
}

AWS="$(aws_bin)"
"$AWS" sts get-caller-identity --profile "$PROFILE" --region "$REGION" >/dev/null

PREFERRED_VPC="vpc-07905dc0ab6652b64"
if "$AWS" ec2 describe-vpcs --profile "$PROFILE" --region "$REGION" --vpc-ids "$PREFERRED_VPC" >/dev/null 2>&1; then
  VPC_ID="$PREFERRED_VPC"
else
  VPC_ID="$("$AWS" ec2 describe-nat-gateways --profile "$PROFILE" --region "$REGION" \
    --filter Name=state,Values=available --query 'NatGateways[0].VpcId' --output text)"
fi

SUBNET="$("$AWS" ec2 describe-subnets --profile "$PROFILE" --region "$REGION" \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=map-public-ip-on-launch,Values=false" \
  --query 'Subnets[0].SubnetId' --output text)"

cat >"${LAB}/terraform.tfvars" <<EOF
aws_region  = "${REGION}"
aws_profile = ""
lab_enabled = true
vpc_id = "${VPC_ID}"
private_subnet_id = "${SUBNET}"
instance_type = "t3.xlarge"
root_volume_gb = 40
plugin_repo   = "https://github.com/Mesverrum/grafana-kafka-datasource.git"
plugin_branch = "feat/enable-grafana-alerting"
EOF

echo "Wrote ${LAB}/terraform.tfvars vpc=${VPC_ID} subnet=${SUBNET}"
