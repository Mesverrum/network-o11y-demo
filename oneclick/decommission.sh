#!/usr/bin/env bash
# One-click decommission for network-o11y-demo (macOS / native Linux).
#   ./oneclick/decommission.sh          (or: make teardown)
# Thin bootstrapper: runs the shared oneclick/lab-linux.sh 'decommission' inside
# the Linux env (OrbStack VM on macOS, host on native Linux) — which also does the
# Grafana teardown (dashboards + plugins-we-installed) — then handles the host-side
# extra (delete VM). Idempotent; prompts before destructive steps; roadblocks exit 2.
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

decom_local() {
  hdr "Tear down local lab"
  # lab-linux.sh 'decommission' also runs the Grafana teardown: it asks about the
  # network-lab dashboards, and (only for plugins THIS deploy installed) asks
  # before removing each — plugins that pre-existed the deploy are never touched.
  if [[ "$(uname -s)" != "Darwin" ]]; then
    step "Running lab-linux.sh decommission (native Linux)"; run_teardown; local rc=$?
    [[ $rc -eq 2 ]] && { final_report "resolve the roadblock above, then re-run $SELF"; exit 2; }
    [[ $rc -eq 0 ]] && ok "lab torn down" || warn "teardown exited $rc"
    return
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
