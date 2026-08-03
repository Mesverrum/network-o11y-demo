#!/usr/bin/env bash
# Discover VPC + private subnet for colocated-network-lab; write terraform.tfvars
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/colocated-network-lab"
PROFILE="${AWS_PROFILE:-}"
REGION="${AWS_REGION:-us-east-1}"

# shellcheck source=aws-cmd.sh
source "$(cd "$(dirname "$0")" && pwd)/aws-cmd.sh"

pick_vpc() {
  local preferred="${PREFERRED_VPC_ID:-}"
  if [[ -n "$preferred" ]] && aws_cmd ec2 describe-vpcs --region "$REGION" --vpc-ids "$preferred" >/dev/null 2>&1; then
    echo "$preferred"
    return
  fi
  aws_cmd ec2 describe-nat-gateways --region "$REGION" \
    --filter Name=state,Values=available \
    --query 'NatGateways[0].VpcId' --output text
}

VPC_ID="$(pick_vpc | tr -d '\r')"
SUBNET_ID="$(
  aws_cmd ec2 describe-subnets --region "$REGION" \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=map-public-ip-on-launch,Values=false" \
    --query 'Subnets | sort_by(@, &AvailabilityZone)[0].SubnetId' --output text | tr -d '\r'
)"

if [[ -z "$SUBNET_ID" || "$SUBNET_ID" == "None" ]]; then
  echo "ERROR: no private subnet in ${VPC_ID}" >&2
  exit 1
fi

PROFILE_LINE=""
if [[ -n "$PROFILE" ]]; then
  PROFILE_LINE="aws_profile = \"${PROFILE}\""
fi

REPO_BRANCH="${COLOCATED_REPO_BRANCH:-main}"

cat >"${LAB}/terraform.tfvars" <<EOF
aws_region = "${REGION}"
${PROFILE_LINE}
lab_enabled = true

vpc_id            = "${VPC_ID}"
private_subnet_id = "${SUBNET_ID}"

instance_type  = "m5.4xlarge"
root_volume_gb = 120
repo_branch    = "${REPO_BRANCH}"
ktrans_host    = "aws-colocated-lab"
lab_tester_id  = "aws-colocated-lab"
EOF

echo "Wrote ${LAB}/terraform.tfvars (vpc=${VPC_ID}, subnet=${SUBNET_ID})"
