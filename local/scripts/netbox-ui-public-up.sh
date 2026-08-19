#!/usr/bin/env bash
# Apply NetBox public NLB + SG using exported session creds (Windows SSO safe).
set -euo pipefail

WIN_LAB=/mnt/c/Users/mesve/projects/network-o11y-demo/terraform/colocated-network-lab
WSL_ROOT=/home/mnetterfield/network-o11y-demo
LAB="$WSL_ROOT/terraform/colocated-network-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"

if command -v aws.exe >/dev/null 2>&1; then AWS=aws.exe; else AWS=aws; fi

echo "==> syncing terraform lab Windows -> WSL ext4"
sudo rm -rf "$LAB"
sudo mkdir -p "$(dirname "$LAB")"
sudo cp -a "$WIN_LAB" "$LAB"
sudo chown -R "$(id -u):$(id -g)" "$LAB"
# ensure new files present
cp -f "$WIN_LAB"/*.tf "$LAB/" 2>/dev/null || true
cp -f "$WIN_LAB/terraform.tfvars" "$LAB/" 2>/dev/null || true

echo "==> exporting AWS session creds (profile=$PROFILE)"
eval "$($AWS --profile "$PROFILE" configure export-credentials --format env)"
export AWS_REGION="$REGION"
export AWS_PROFILE=""
export AWS_SDK_LOAD_CONFIG=0

run_tf() {
  docker run --rm \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    -e AWS_REGION \
    -e AWS_DEFAULT_REGION="$REGION" \
    -e AWS_PROFILE= \
    -e AWS_SDK_LOAD_CONFIG=0 \
    -v "${WSL_ROOT}:/repo" \
    -w /repo/terraform/colocated-network-lab \
    hashicorp/terraform:1.9 \
    "$@"
}

run_tf init -input=false
run_tf apply -auto-approve -input=false \
  -var=aws_profile= \
  -var=lab_enabled=true \
  -target=data.aws_vpc.selected \
  -target=aws_security_group.lab_host \
  -target=aws_lb.netbox_ui \
  -target=aws_lb_target_group.netbox_ui \
  -target=aws_lb_target_group_attachment.netbox_ui \
  -target=aws_lb_listener.netbox_ui

# sync state back to Windows workspace
cp -a "$LAB/terraform.tfstate" "$WIN_LAB/terraform.tfstate" 2>/dev/null || true
cp -a "$LAB/.terraform.lock.hcl" "$WIN_LAB/" 2>/dev/null || true

echo ""
echo "NetBox UI URL:"
run_tf output -raw netbox_ui_url
echo
