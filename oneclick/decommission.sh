#!/usr/bin/env bash
# One-click decommission for network-o11y-demo.
#   ./oneclick/decommission.sh
# Tears down what deploy.sh created. Idempotent (skips what's already gone),
# prompts before destructive extras (deleting the VM, removing dashboards),
# and on a roadblock prints remediation + exits 2 so you can fix and re-run.
set -uo pipefail
SELF="./oneclick/decommission.sh"; ACTION=decommission
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# ===========================================================================
# LOCAL
# ===========================================================================
decom_local() {
  hdr "Tear down local lab"
  if ! have orb; then skip "OrbStack not installed — nothing local to remove"; return; fi
  if ! orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM_NAME"; then skip "VM '$VM_NAME' not present"; else
    if vm_q "test -d ~/$VM_REPO/local"; then
      step "Stopping workloads (traffic, join-app)"
      vm "cd ~/$VM_REPO/local && make traffic-stop >/dev/null 2>&1; make join-app-stop >/dev/null 2>&1; true" ; ok "workloads stopped"
      if vm_q "docker ps -q | grep -q ."; then
        step "make down (ContainerLab + collectors)"
        vm "cd ~/$VM_REPO/local && make down" >/dev/null 2>&1 && ok "lab torn down" \
          || roadblock "make down failed" "orb -m $VM_NAME then: cd ~/$VM_REPO/local && make down" "If containers are stuck: docker rm -f \$(docker ps -aq)"
      else skip "no lab containers running"; fi
    else skip "repo not present in VM"; fi

    # optional: delete the VM entirely
    if confirm "Also DELETE the OrbStack VM '$VM_NAME' (removes repo, images, tools)?"; then
      step "Deleting VM '$VM_NAME'"; orb delete "$VM_NAME" >/dev/null 2>&1 && ok "VM deleted" || warn "could not delete VM (orb delete $VM_NAME)"
    else skip "VM kept (re-deploy will be fast)"; fi
  fi

  # optional: remove dashboards from Grafana Cloud
  if [[ -x "$GCX_BIN" ]] && gcx_ok; then
    if confirm "Remove the '$GRAFANA_FOLDER' dashboards from Grafana Cloud?"; then
      step "Deleting dashboards + folder"
      for uid in net-o11y-topology net-o11y-bgp-status net-o11y-device-details net-o11y-iface-health \
                 net-o11y-traffic-flows net-o11y-traffic-sankey lab-topology-graph lab-topology-health lab-network-join-demo; do
        "$GCX_BIN" api "/api/dashboards/uid/$uid" -X DELETE >/dev/null 2>&1 || true
      done
      "$GCX_BIN" api "/api/folders/$GRAFANA_FOLDER" -X DELETE >/dev/null 2>&1 || true
      ok "dashboards/folder removed"
      warn "Telemetry may keep arriving until the VM/lab is fully stopped; installed panel plugins are left in place."
    else skip "dashboards kept in Grafana Cloud"; fi
  else warn "gcx not authenticated — left Grafana Cloud dashboards untouched (remove manually if desired)"; fi
  warn "Grafana Cloud metrics already ingested are retained per your stack's retention; nothing is deleted from TSDB."
}

# ===========================================================================
# AWS
# ===========================================================================
decom_aws() {
  hdr "Tear down AWS / EKS"
  have aws && aws sts get-caller-identity >/dev/null 2>&1 || roadblock "AWS credentials not working" "Run: aws configure" "Verify: aws sts get-caller-identity"
  { have tofu || have terraform; } || roadblock "OpenTofu/Terraform required to destroy" "Install: brew install opentofu"
  say "  ${C_RED}${C_B}This destroys ALL AWS infrastructure (EKS, VPC, bastion).${C_RESET}"
  confirm "Proceed with 'make destroy'?" || { warn "aborted by user"; return; }
  step "make destroy (OpenTofu destroy)"
  make -C "$REPO_ROOT" destroy || roadblock "make destroy failed" "cd $REPO_ROOT/terraform && tofu destroy" "Resolve dependency/ordering errors, then re-run."
  ok "AWS infrastructure destroyed"
}

# ===========================================================================
main() {
  hdr "network-o11y-demo — one-click DECOMMISSION"
  state_init
  TARGET="$(state_get TARGET)"
  if [[ -z "$TARGET" ]]; then choose_target; fi
  say "Target: ${C_B}$TARGET${C_RESET}"
  case "$TARGET" in
    local) decom_local ;;
    aws)   decom_aws ;;
    *)     err "unknown target"; exit 1 ;;
  esac
  # clear remembered target if the environment is fully gone
  final_report "Decommission complete."
}
main "$@"
