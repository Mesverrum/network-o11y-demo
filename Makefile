# Makefile — Network Observability Demo
#
# Targets are organized to match the blog post series:
#   "Network Observability Without the Lock-in"
#
# Each post-## target deploys the functionality introduced in that post.
# Run them in order for a full end-to-end deployment.
#
# Quick start:
#   make help
#   make post-03   # Lab: SR Linux fabric + telemetry pipeline
#   make post-04   # NetBox: inventory source of truth
#   make post-05   # Grafana: dashboards
#   make post-06   # Ansible: config management

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Detect kubectl context
KUBE_CONTEXT := $(shell kubectl config current-context 2>/dev/null || echo "none")

# ─── Help ─────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help
	@echo ""
	@echo "Network Observability Demo — Deployment Targets"
	@echo "================================================"
	@echo ""
	@echo "Blog post alignment:"
	@printf "  %-28s %s\n" "make post-03" "Post 3: Lab — SR Linux fabric + telemetry pipeline"
	@printf "  %-28s %s\n" "make post-04" "Post 4: NetBox — inventory source of truth"
	@printf "  %-28s %s\n" "make post-05" "Post 5: Grafana — dashboards"
	@printf "  %-28s %s\n" "make post-06" "Post 6: Ansible — config management"
	@printf "  %-28s %s\n" "make all"     "Deploy everything (posts 3–6)"
	@echo ""
	@echo "Infrastructure:"
	@printf "  %-28s %s\n" "make infra"    "Provision AWS infrastructure (EKS, bastion) via OpenTofu"
	@printf "  %-28s %s\n" "make destroy"  "Tear down all AWS infrastructure"
	@echo ""
	@echo "Utilities:"
	@printf "  %-28s %s\n" "make status"     "Show pod and deployment status across all namespaces"
	@printf "  %-28s %s\n" "make access"     "Open SSH tunnels to cluster services"
	@printf "  %-28s %s\n" "make traffic"    "Start traffic generation on client nodes"
	@printf "  %-28s %s\n" "make check"      "Run Ansible drift detection (requires post-06)"
	@printf "  %-28s %s\n" "make backup"     "Run Ansible config backup now (requires post-06)"
	@echo ""
	@echo "Local lab (WSL + ContainerLab — see local/README.md):"
	@printf "  %-28s %s\n" "make local-help" "Show local lab targets"
	@printf "  %-28s %s\n" "make local-up"   "Bring up reduced Clos + ktranslate/Alloy"
	@printf "  %-28s %s\n" "make local-down" "Tear down local lab"
	@echo ""
	@echo "Current kubectl context: $(KUBE_CONTEXT)"
	@echo ""

# ─── Full deployment ──────────────────────────────────────────────────────────

.PHONY: all
all: post-03 post-04 post-05 post-06 ## Deploy everything end-to-end (Posts 3–6)

# ─── Post 3: Building the Lab ─────────────────────────────────────────────────
# Covers: SR Linux Clos fabric on Kubernetes, Alloy SNMP + gNMI + syslog,
#         ktranslate NetFlow, network reconciler for Clabbernetes quirks.
#
# Blog post: "Building the Lab: SR Linux on Kubernetes"

.PHONY: post-03
post-03: check-kubectl ## Post 3: Lab — SR Linux fabric + telemetry pipeline
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo " Post 3: Building the Lab"
	@echo " SR Linux fabric + four telemetry streams"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	$(MAKE) deploy-topology
	$(MAKE) deploy-networking
	$(MAKE) deploy-telemetry

.PHONY: deploy-topology
deploy-topology: check-kubectl ## Deploy Clabbernetes + SR Linux topology
	@echo "==> Deploying SR Linux Clos topology (2 spines, 3 leaves, 3 clients)..."
	kubectl apply -f k8s/topology/manifests.yaml
	@echo "==> Waiting for all topology pods to be Running (up to 5 min)..."
	kubectl wait pod \
	  --for=condition=Ready \
	  --selector='clabernetes/topologyNode' \
	  --namespace=network-lab \
	  --timeout=300s \
	  || true
	kubectl get pods -n network-lab

.PHONY: deploy-networking
deploy-networking: check-kubectl ## Apply Clabbernetes networking fixes + reconciler
	@echo "==> Applying networking fixes (VxLAN, ARP, MTU, DNAT)..."
	bash scripts/fix-networking.sh
	@echo "==> Deploying network reconciler (re-applies fixes after pod restarts)..."
	kubectl apply -f k8s/network-reconciler.yaml
	kubectl rollout status deployment/network-reconciler -n network-lab --timeout=60s

.PHONY: deploy-telemetry
deploy-telemetry: check-kubectl ## Deploy Alloy, gnmic, ktranslate telemetry stack
	bash scripts/deploy-telemetry.sh

# ─── Post 4: NetBox ───────────────────────────────────────────────────────────
# Covers: NetBox deployment, netbox-sd HTTP SD adapter, populate job,
#         Alloy enrichment with NetBox inventory labels.
#
# Blog post: "NetBox as Your Source of Truth"

.PHONY: post-04
post-04: check-kubectl ## Post 4: NetBox — inventory source of truth
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo " Post 4: NetBox as Your Source of Truth"
	@echo " Inventory + Prometheus HTTP SD enrichment"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	bash scripts/deploy-netbox.sh

# ─── Post 5: Grafana Dashboards ───────────────────────────────────────────────
# Covers: Grafana Cloud dashboard deployment — topology, interface health,
#         BGP status, NetFlow, device inventory, device details.
#
# Blog post: "Observability with Grafana"

.PHONY: post-05
post-05: ## Post 5: Grafana — deploy dashboards to Grafana Cloud
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo " Post 5: Observability with Grafana"
	@echo " Dashboards: topology, interfaces, BGP, flows, inventory"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	bash scripts/deploy-dashboards.sh

# ─── Post 6: Ansible Config Management ───────────────────────────────────────
# Covers: Ansible runner deployment, NetBox as inventory source,
#         BGP config push, config backup, drift detection, remediation.
#
# Blog post: "Network Config Management with Ansible"

.PHONY: post-06
post-06: check-kubectl ## Post 6: Ansible — config management layer
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo " Post 6: Network Config Management with Ansible"
	@echo " Runner pod, daily backup CronJob, drift detection"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	bash scripts/deploy-ansible.sh

# ─── Ansible operations ───────────────────────────────────────────────────────

.PHONY: check
check: check-kubectl ## Run Ansible drift detection against all leaf nodes
	@echo "==> Running BGP configuration drift detection..."
	kubectl exec -n network-tools deployment/ansible-runner -- \
	  bash -c 'cd /ansible && ansible-playbook playbooks/drift-detection.yml'

.PHONY: backup
backup: check-kubectl ## Trigger immediate Ansible config backup
	@echo "==> Triggering config backup job..."
	kubectl create job -n network-tools "backup-$$(date +%Y%m%d-%H%M%S)" \
	  --from=cronjob/ansible-backup
	@echo "==> Watch progress:"
	@echo "    kubectl logs -n network-tools -l app=ansible-backup -f"

.PHONY: ansible-shell
ansible-shell: check-kubectl ## Open an interactive shell in the Ansible runner pod
	kubectl exec -it -n network-tools deployment/ansible-runner -- bash

# ─── Infrastructure ───────────────────────────────────────────────────────────

.PHONY: infra
infra: ## Provision AWS infrastructure (EKS, bastion, VPC) with OpenTofu
	@echo "==> Provisioning infrastructure with OpenTofu..."
	@echo "    Ensure terraform/terraform.tfvars exists with your allowed_ssh_cidr."
	cd terraform && tofu init && tofu apply

.PHONY: destroy
destroy: ## Tear down all AWS infrastructure
	@echo "WARNING: This will destroy the EKS cluster and all data in it."
	@read -p "Are you sure? Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ] || exit 1
	cd terraform && tofu destroy

# ─── Utilities ────────────────────────────────────────────────────────────────

.PHONY: status
status: check-kubectl ## Show status of all pods across demo namespaces
	@echo ""
	@echo "── network-lab (SR Linux fabric + telemetry) ──"
	kubectl get pods -n network-lab -o wide
	@echo ""
	@echo "── network-tools (NetBox + Ansible) ──"
	kubectl get pods -n network-tools -o wide
	@echo ""
	@echo "── c9s (Clabbernetes manager) ──"
	kubectl get pods -n c9s -o wide

.PHONY: access
access: ## Open SSH tunnels to cluster services (NetBox UI, Alloy UI)
	bash scripts/access.sh

.PHONY: traffic
traffic: check-kubectl ## Start traffic generation on client nodes
	bash scripts/traffic.sh start

.PHONY: traffic-stop
traffic-stop: check-kubectl ## Stop traffic generation
	bash scripts/traffic.sh stop

# ─── Local lab (WSL / ContainerLab / Docker Compose) ──────────────────────────
# Parallel path — does not require AWS/EKS. See local/README.md.

.PHONY: local-help
local-help: ## Show local lab Makefile help
	$(MAKE) -C local help

.PHONY: local-up
local-up: ## Deploy local Clos + ktranslate/Alloy → Grafana Cloud
	$(MAKE) -C local up

.PHONY: local-down
local-down: ## Tear down local lab
	$(MAKE) -C local down

.PHONY: local-status
local-status: ## Status of local lab
	$(MAKE) -C local status

# ─── Guards ───────────────────────────────────────────────────────────────────

.PHONY: check-kubectl
check-kubectl:
	@kubectl cluster-info >/dev/null 2>&1 \
	  || (echo "ERROR: kubectl is not configured. Run: aws eks update-kubeconfig ..." && exit 1)
