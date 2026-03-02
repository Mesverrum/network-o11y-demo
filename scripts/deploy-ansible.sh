#!/usr/bin/env bash
# deploy-ansible.sh — Deploy the Ansible config-management layer (Blog Post 6).
#
# Deploys (into the network-tools namespace):
#   - ansible-playbooks ConfigMap   playbook and inventory definitions
#   - ansible-runner Deployment     interactive pod for running playbooks
#   - ansible-backup CronJob        daily automated config backup
#   - ansible-backups PVC           persistent storage for backup files
#
# After deployment, exec into the runner pod to run playbooks interactively:
#
#   kubectl exec -it -n network-tools deployment/ansible-runner -- bash
#   ansible-inventory --graph
#   ansible-playbook playbooks/drift-detection.yml
#   ansible-playbook playbooks/configure-bgp-neighbors.yml --check --diff
#   ansible-playbook playbooks/backup-configs.yml
#
# Prerequisites:
#   1. kubectl configured and pointing at the demo cluster.
#   2. NetBox deployed and populate job complete (deploy-netbox.sh done).
#   3. netbox-credentials Secret present in network-tools namespace.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ANSIBLE_K8S_DIR="$REPO_ROOT/k8s/ansible"
NAMESPACE="network-tools"

info()  { echo "==> $*"; }
warn()  { echo "WARN: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# ─── Preflight ────────────────────────────────────────────────────────────────

info "Checking prerequisites..."

kubectl cluster-info >/dev/null 2>&1 \
  || fatal "kubectl is not configured. Run: aws eks update-kubeconfig ..."

kubectl get secret netbox-credentials -n "$NAMESPACE" >/dev/null 2>&1 \
  || fatal "netbox-credentials Secret not found in namespace $NAMESPACE.
  Run scripts/deploy-netbox.sh first."

# ─── Deploy ───────────────────────────────────────────────────────────────────

info "Deploying Ansible runner and backup CronJob..."
kubectl apply -f "$ANSIBLE_K8S_DIR/runner.yaml"
kubectl apply -f "$ANSIBLE_K8S_DIR/backup-cronjob.yaml"

# ─── Wait for runner ──────────────────────────────────────────────────────────

info "Waiting for ansible-runner pod to start (init container installs Ansible — may take 2–3 min)..."
kubectl rollout status deployment/ansible-runner -n "$NAMESPACE" --timeout=300s

# ─── Verify inventory ─────────────────────────────────────────────────────────

info "Verifying Ansible can reach NetBox inventory..."
kubectl exec -n "$NAMESPACE" deployment/ansible-runner -- \
  bash -c 'cd /ansible && ansible-inventory --graph 2>&1 | head -40' \
  || warn "Inventory check failed — check runner logs: kubectl logs -n $NAMESPACE deployment/ansible-runner"

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Ansible config management layer deployed (Blog Post 6)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo " Interactive runner:"
echo "   kubectl exec -it -n $NAMESPACE deployment/ansible-runner -- bash"
echo ""
echo " Once inside the runner:"
echo ""
echo "   # List devices discovered from NetBox:"
echo "   ansible-inventory --graph"
echo ""
echo "   # Drift detection (check mode — no changes applied):"
echo "   ansible-playbook playbooks/drift-detection.yml"
echo ""
echo "   # Dry run BGP config push (see what would change):"
echo "   ansible-playbook playbooks/configure-bgp-neighbors.yml --check --diff"
echo ""
echo "   # Apply BGP configuration:"
echo "   ansible-playbook playbooks/configure-bgp-neighbors.yml"
echo ""
echo "   # Back up all device configs:"
echo "   ansible-playbook playbooks/backup-configs.yml"
echo ""
echo "   # Remediate an idle BGP session:"
echo "   ansible-playbook playbooks/remediate-bgp.yml --limit leaf2"
echo ""
echo " Automated daily backup (02:00 UTC):"
echo "   kubectl get cronjob ansible-backup -n $NAMESPACE"
echo "   kubectl create job backup-now -n $NAMESPACE --from=cronjob/ansible-backup"
echo ""
echo " Full playbook source in: ansible/playbooks/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
