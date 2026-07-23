#!/usr/bin/env bash
# One-click decommission for network-o11y-demo (macOS / native Linux).
#   ./oneclick/decommission.sh          (or: make teardown)
# Thin bootstrapper: runs the shared oneclick/lab-linux.sh 'decommission' inside
# the Linux env (OrbStack VM on macOS, host on native Linux), then handles the
# host-side extras (delete VM, remove Grafana dashboards). Idempotent; prompts
# before destructive extras; roadblocks exit 2 so you fix + re-run.
set -uo pipefail
SELF="./oneclick/decommission.sh"; ACTION=decommission
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

run_teardown() { # runs lab-linux.sh decommission in the right Linux env
  if [[ "$(uname -s)" != "Darwin" ]]; then
    bash "$REPO_ROOT/oneclick/lab-linux.sh" decommission; return $?
  fi
  tr -d '\r' < "$REPO_ROOT/oneclick/lab-linux.sh" | orb -m "$VM_NAME" bash -lc "mkdir -p ~/$VM_REPO/oneclick && cat > ~/$VM_REPO/oneclick/lab-linux.sh" 2>/dev/null || true
  orb -m "$VM_NAME" bash -lc "bash ~/$VM_REPO/oneclick/lab-linux.sh decommission"
}

remove_dashboards() { # host-side gcx (macOS) — remove the network-lab folder if asked
  if [[ -x "$GCX_BIN" ]] && gcx_ok; then
    if confirm "Remove the '$GRAFANA_FOLDER' dashboards from Grafana Cloud?"; then
      step "Deleting dashboards + folder"
      for uid in net-o11y-topology net-o11y-bgp-status net-o11y-device-details net-o11y-iface-health \
                 net-o11y-traffic-flows net-o11y-traffic-sankey lab-topology-graph lab-topology-health lab-network-join-demo; do
        "$GCX_BIN" api "/api/dashboards/uid/$uid" -X DELETE >/dev/null 2>&1 || true
      done
      "$GCX_BIN" api "/api/folders/$GRAFANA_FOLDER" -X DELETE >/dev/null 2>&1 || true
      ok "dashboards/folder removed (installed panel plugins left in place)"
    else skip "dashboards kept in Grafana Cloud"; fi
  else warn "gcx not authenticated — left Grafana Cloud dashboards untouched (remove manually if desired)"; fi
  warn "Metrics already ingested are retained per your stack's retention; nothing is deleted from the TSDB."
}

decom_local() {
  hdr "Tear down local lab"
  if [[ "$(uname -s)" != "Darwin" ]]; then
    step "Running lab-linux.sh decommission (native Linux)"; run_teardown; local rc=$?
    [[ $rc -eq 2 ]] && { final_report "resolve the roadblock above, then re-run $SELF"; exit 2; }
    [[ $rc -eq 0 ]] && ok "lab torn down" || warn "teardown exited $rc"
    remove_dashboards; return
  fi
  if ! have orb; then skip "OrbStack not installed — nothing local to remove"; return; fi
  if ! orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM_NAME"; then skip "VM '$VM_NAME' not present"
  else
    if vm_q "test -d ~/$VM_REPO/local"; then
      step "Running lab-linux.sh decommission in the VM"; run_teardown; local rc=$?
      if [[ $rc -eq 2 ]]; then final_report "resolve the roadblock above, then re-run $SELF"; exit 2
      elif [[ $rc -eq 0 ]]; then ok "lab torn down"; else warn "teardown exited $rc"; fi
    else skip "repo not present in VM"; fi
    if confirm "Also DELETE the OrbStack VM '$VM_NAME' (removes repo, images, tools)?"; then
      step "Deleting VM '$VM_NAME'"; orb delete "$VM_NAME" >/dev/null 2>&1 && ok "VM deleted" || warn "could not delete VM (orb delete $VM_NAME)"
    else skip "VM kept (re-deploy will be fast)"; fi
  fi
  remove_dashboards
}

decom_aws() {
  hdr "Tear down AWS / EKS"
  { have aws && aws sts get-caller-identity >/dev/null 2>&1; } || roadblock "AWS credentials not working" "Run: aws configure" "Verify: aws sts get-caller-identity"
  { have tofu || have terraform; } || roadblock "OpenTofu/Terraform required to destroy" "Install: brew install opentofu"
  say "  ${C_RED}${C_B}This destroys ALL AWS infrastructure (EKS, VPC, bastion).${C_RESET}"
  confirm "Proceed with 'make destroy'?" || { warn "aborted by user"; return; }
  step "make destroy (OpenTofu destroy)"
  make -C "$REPO_ROOT" destroy || roadblock "make destroy failed" "cd $REPO_ROOT/terraform && tofu destroy" "Resolve dependency/ordering errors, then re-run."
  ok "AWS infrastructure destroyed"
}

main() {
  hdr "network-o11y-demo — one-click DECOMMISSION"
  state_init
  TARGET="$(state_get TARGET)"; [[ -z "$TARGET" ]] && choose_target
  say "Target: ${C_B}$TARGET${C_RESET}"
  case "$TARGET" in local) decom_local ;; aws) decom_aws ;; *) err "unknown target"; exit 1 ;; esac
  final_report "Decommission complete."
}
main "$@"
