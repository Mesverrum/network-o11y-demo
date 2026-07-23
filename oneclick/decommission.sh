#!/usr/bin/env bash
# One-click decommission for network-o11y-demo (macOS / native Linux).
#   ./oneclick/decommission.sh          (or: make teardown)
# Thin bootstrapper: runs the shared oneclick/lab-linux.sh 'decommission' inside
# the Linux env (OrbStack VM on macOS, host on native Linux) - which also does the
# Grafana teardown (dashboards + plugins-we-installed) - then handles the host-side
# extra (delete VM). Idempotent; prompts before destructive steps; roadblocks exit 2.
set -uo pipefail
SELF="./oneclick/decommission.sh"; ACTION=decommission
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# Ask the yes/no teardown questions HERE (on the host) so prompts are clean and
# ordered; lab-linux.sh then runs non-interactively in the Linux env.
gather_teardown_answers() {
  RM_DASHBOARDS=0; RM_PLUGINS=""
  confirm "Remove the network-lab dashboards + folder from Grafana Cloud?" && RM_DASHBOARDS=1
  local plist p
  if [[ "$(uname -s)" == "Darwin" ]]; then
    plist="$(orb -m "$VM_NAME" bash -lc 'cat ~/.network-o11y-demo-oneclick/plugins-installed 2>/dev/null' 2>/dev/null)"
  else
    plist="$(cat "$HOME/.network-o11y-demo-oneclick/plugins-installed" 2>/dev/null)"
  fi
  for p in $plist; do
    confirm "Remove panel plugin '$p' that THIS deploy installed? (it may be used by other dashboards now)" && RM_PLUGINS+="$p "
  done
}

# Run lab-linux.sh decommission non-interactively; pipe through 'cat -s' so the
# output prints as one contiguous, de-blanked, correctly-ordered block.
run_teardown() {
  local envs="RM_DASHBOARDS=${RM_DASHBOARDS:-0} RM_PLUGINS='${RM_PLUGINS:-}'"
  if [[ "$(uname -s)" != "Darwin" ]]; then
    RM_DASHBOARDS="${RM_DASHBOARDS:-0}" RM_PLUGINS="${RM_PLUGINS:-}" bash "$REPO_ROOT/oneclick/lab-linux.sh" decommission 2>&1 | cat -s
    return "${PIPESTATUS[0]}"
  fi
  tr -d '\r' < "$REPO_ROOT/oneclick/lab-linux.sh" | orb -m "$VM_NAME" bash -lc "mkdir -p ~/$VM_REPO/oneclick && cat > ~/$VM_REPO/oneclick/lab-linux.sh" >/dev/null 2>&1 || true
  orb -m "$VM_NAME" bash -lc "set -o pipefail; $envs bash ~/$VM_REPO/oneclick/lab-linux.sh decommission 2>&1 | cat -s"
}

decom_local() {
  hdr "Tear down local lab"
  if [[ "$(uname -s)" != "Darwin" ]]; then
    gather_teardown_answers
    step "Tearing down (lab + Grafana) via lab-linux.sh"; run_teardown; local rc=$?
    [[ $rc -eq 2 ]] && { final_report "resolve the roadblock above, then re-run $SELF"; exit 2; }
    [[ $rc -eq 0 ]] || warn "teardown exited $rc"
    return
  fi
  if ! have orb; then skip "OrbStack not installed - nothing local to remove"; return; fi
  if ! orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM_NAME"; then skip "VM '$VM_NAME' not present"
  else
    if vm_q "test -d ~/$VM_REPO/local"; then
      gather_teardown_answers
      step "Tearing down (lab + Grafana) via lab-linux.sh in the VM"; run_teardown; local rc=$?
      [[ $rc -eq 2 ]] && { final_report "resolve the roadblock above, then re-run $SELF"; exit 2; }
      [[ $rc -eq 0 ]] || warn "teardown exited $rc"
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
  hdr "network-o11y-demo - one-click DECOMMISSION"
  state_init
  TARGET="$(state_get TARGET)"; [[ -z "$TARGET" ]] && choose_target
  say "Target: ${C_B}$TARGET${C_RESET}"
  case "$TARGET" in local) decom_local ;; aws) decom_aws ;; *) err "unknown target"; exit 1 ;; esac
  final_report "Decommission complete."
}
main "$@"
