#!/usr/bin/env bash
# Discover a lab VPC with NAT + private subnets; write terraform/aws-dashboard-lab/terraform.tfvars
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/aws-dashboard-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"

pick_vpc() {
  # Prefer eksctl-ai-o11y-mg VPC if present; else first VPC with NAT + 2+ private subnets.
  local preferred="vpc-07905dc0ab6652b64"
  if aws ec2 describe-vpcs --profile "$PROFILE" --region "$REGION" --vpc-ids "$preferred" >/dev/null 2>&1; then
    echo "$preferred"
    return
  fi
  aws ec2 describe-nat-gateways --profile "$PROFILE" --region "$REGION" \
    --filter Name=state,Values=available \
    --query 'NatGateways[0].VpcId' --output text
}

VPC_ID="$(pick_vpc)"
mapfile -t PRIVATE_SUBNETS < <(
  aws ec2 describe-subnets --profile "$PROFILE" --region "$REGION" \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=map-public-ip-on-launch,Values=false" \
    --query 'Subnets[*].SubnetId' --output text | tr '\t' '\n' | head -2
)

if [[ ${#PRIVATE_SUBNETS[@]} -lt 2 ]]; then
  echo "ERROR: need at least 2 private subnets in ${VPC_ID}" >&2
  exit 1
fi

cat >"${LAB}/terraform.tfvars" <<EOF
aws_region  = "${REGION}"
aws_profile = "${PROFILE}"
lab_enabled = true

vpc_id = "${VPC_ID}"
private_subnet_ids = [
  "${PRIVATE_SUBNETS[0]}",
  "${PRIVATE_SUBNETS[1]}",
]

instance_type        = "t3.micro"
traffic_interval_sec = 30
EOF

echo "Wrote ${LAB}/terraform.tfvars (vpc=${VPC_ID})"
