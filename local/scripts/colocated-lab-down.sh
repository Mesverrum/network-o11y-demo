#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/colocated-network-lab"
TF="$(cd "$(dirname "$0")" && pwd)/aws-lab-terraform.sh"

bash "$TF" "$LAB" destroy -auto-approve -var="lab_enabled=true"
echo "Colocated network lab destroyed."
