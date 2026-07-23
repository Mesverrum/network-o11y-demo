#!/usr/bin/env bash
# One-click deploy for network-o11y-demo (macOS / native Linux).
#   ./oneclick/deploy.sh          (or: make deploy)
# Thin bootstrapper: on macOS it sets up OrbStack + a Linux VM, then runs the
# shared oneclick/lab-linux.sh INSIDE that VM (the same routine the Windows
# PowerShell path runs inside WSL, and native Linux runs directly). Idempotent +
# resumable; on a roadblock it prints remediation and exits 2 so you fix + re-run.
set -uo pipefail
SELF="./oneclick/deploy.sh"; ACTION=deploy
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# ===========================================================================
# LOCAL — macOS bootstrap (OrbStack VM) + shared lab-linux.sh, OR native Linux
# ===========================================================================
preflight_local() {
  hdr "Pre-flight — local"
  if [[ "$(uname -s)" != "Darwin" ]]; then
    have docker || warn "docker not found; lab-linux.sh will install it"
    ok "native Linux detected (no VM needed)"; NATIVE_LINUX=1; return
  fi
  NATIVE_LINUX=0
  have brew || roadblock "Homebrew is required" \
    "Install Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"" \
    "Then follow its 'Next steps' to add brew to your PATH."
  ok "Homebrew present"
  if ! have orb; then
    step "Installing OrbStack (brew cask)"; brew install --cask orbstack >/dev/null 2>&1 \
      && ok "OrbStack installed" || roadblock "OrbStack install failed" "Run: brew install --cask orbstack"
  else ok "OrbStack CLI present"; fi
  if [[ "$(orb status 2>/dev/null)" != "Running" ]]; then
    open -a OrbStack >/dev/null 2>&1 || true
    roadblock "OrbStack needs its one-time setup (GUI + admin approval)" \
      "OrbStack was opened. Click through the welcome and APPROVE the macOS admin prompt (installs its network helper)." \
      "When asked what to use, enable 'Linux' (and 'Docker')." \
      "Wait until 'orb status' reports Running."
  fi
  ok "OrbStack running"
  if ! orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM_NAME"; then
    step "Creating Linux VM '$VM_NAME'"; orb create ubuntu "$VM_NAME" >/dev/null 2>&1 \
      && ok "VM created" || roadblock "Could not create the VM" "Run: orb create ubuntu $VM_NAME"
  else ok "VM '$VM_NAME' exists"; fi
  vm_q 'true' || roadblock "VM '$VM_NAME' not reachable" "Start it: orb start $VM_NAME"
}

ensure_repo() {
  hdr "Repo + shared routine"
  if [[ "${NATIVE_LINUX:-0}" == "1" ]]; then skip "using this checkout ($REPO_ROOT)"; return; fi
  if vm_q "test -d ~/$VM_REPO/.git"; then vm "cd ~/$VM_REPO && git pull -q || true" >/dev/null 2>&1; skip "repo cloned (pulled latest)"
  else step "Cloning repo into VM"; vm "git clone -q $REPO_URL ~/$VM_REPO" && ok "cloned ~/$VM_REPO" || roadblock "git clone failed in VM" "orb -m $VM_NAME then: git clone $REPO_URL ~/$VM_REPO"; fi
  # Inject THIS checkout's lab-linux.sh into the VM clone (works even before it's merged upstream).
  step "Syncing lab-linux.sh into the VM"
  tr -d '\r' < "$REPO_ROOT/oneclick/lab-linux.sh" | orb -m "$VM_NAME" bash -lc "mkdir -p ~/$VM_REPO/oneclick && cat > ~/$VM_REPO/oneclick/lab-linux.sh && chmod +x ~/$VM_REPO/oneclick/lab-linux.sh" \
    && ok "lab-linux.sh synced" || roadblock "could not sync lab-linux.sh into the VM" "Check: orb -m $VM_NAME"
}

seed_creds() {
  hdr "Grafana Cloud credentials"
  local creds_ok="grep -qE '^GC_OTLP_KEY=glc_' .env && ! grep -E '^GC_OTLP_(URL|ACCOUNT|KEY)=' .env | grep -qE 'REPLACE_ME|YOUR-REGION|glc_REPLACE_ME'"
  if [[ "${NATIVE_LINUX:-0}" == "1" ]]; then
    ( cd "$REPO_ROOT/local" && { [ -f .env ] || cp .env.example .env; sed -i 's/\r$//' .env 2>/dev/null || true; eval "$creds_ok"; } ) 2>/dev/null && skip "OTLP credentials present" \
      || roadblock "Grafana Cloud OTLP credentials required" "Edit $REPO_ROOT/local/.env" "Set GC_OTLP_URL / GC_OTLP_ACCOUNT / GC_OTLP_KEY (glc_… token)."
    return
  fi
  vm "cd ~/$VM_REPO/local && { [ -f .env ] || cp .env.example .env; sed -i 's/\r\$//' .env; }" >/dev/null 2>&1 || true
  if vm_q "cd ~/$VM_REPO/local && { $creds_ok; }"; then skip "OTLP credentials present in VM"; return; fi
  if [[ -f "$REPO_ROOT/local/.env" ]] && ( cd "$REPO_ROOT/local" && eval "$creds_ok" ) 2>/dev/null; then
    step "Copying Grafana Cloud creds/tokens from this Mac's local/.env into the VM"
    for k in GC_OTLP_URL GC_OTLP_ACCOUNT GC_OTLP_KEY LAB_TESTER_ID GRAFANA_URL GRAFANA_TOKEN GC_STACK_TOKEN; do
      local v; v="$(grep -E "^$k=" "$REPO_ROOT/local/.env" | head -1 | cut -d= -f2- | tr -d '\r')"
      [[ -n "$v" ]] && orb -m "$VM_NAME" bash -lc "cd ~/$VM_REPO/local && grep -v '^$k=' .env > .env.t && printf '%s\n' '$k=$v' >> .env.t && mv .env.t .env"
    done
    ok "credentials copied from Mac repo"
  else
    roadblock "Grafana Cloud OTLP credentials required" \
      "Grafana Cloud → Connections → Add new connection → OpenTelemetry (OTLP)." \
      "Either put GC_OTLP_URL/ACCOUNT/KEY in this Mac's local/.env and re-run," \
      "or edit the VM copy:  orb -m $VM_NAME  →  nano ~/$VM_REPO/local/.env"
  fi
}

run_lab() { # $1 = deploy
  hdr "Lab $1 — shared oneclick/lab-linux.sh"
  step "Running lab-linux.sh $1 (uid-aware toolchain + bring-up)"
  if [[ "${NATIVE_LINUX:-0}" == "1" ]]; then bash "$REPO_ROOT/oneclick/lab-linux.sh" "$1"
  else orb -m "$VM_NAME" bash -lc "bash ~/$VM_REPO/oneclick/lab-linux.sh $1"; fi
  local rc=$?
  if [[ $rc -eq 2 ]]; then REPORT_FAIL+=("lab $1 (roadblock above)"); final_report "resolve the roadblock above, then re-run $SELF"; exit 2
  elif [[ $rc -ne 0 ]]; then err "lab-linux.sh $1 exited $rc"; REPORT_FAIL+=("lab $1"); else ok "lab $1 complete"; fi
}

deploy_local() { preflight_local; ensure_repo; seed_creds; run_lab deploy; }

# ===========================================================================
# AWS — drives the repo's automation (not session-validated)
# ===========================================================================
deploy_aws() {
  hdr "Pre-flight — AWS / EKS"
  warn "The AWS path uses the repo's terraform + 'make all' (not validated in this session)."
  have aws || roadblock "AWS CLI required" "Install: brew install awscli" "Configure: aws configure"
  aws sts get-caller-identity >/dev/null 2>&1 || roadblock "AWS credentials not working" "Run: aws configure" "Verify: aws sts get-caller-identity"
  { have tofu || have terraform; } || roadblock "OpenTofu (or Terraform) required" "Install: brew install opentofu"
  have kubectl || roadblock "kubectl required" "Install: brew install kubectl"
  ok "aws + IaC + kubectl present"
  [[ -f "$REPO_ROOT/terraform/terraform.tfvars" ]] || roadblock "terraform.tfvars missing" \
    "cd $REPO_ROOT/terraform && cp terraform.tfvars.example terraform.tfvars" "Edit it (region, cluster, SSH key, CIDRs)."
  step "make infra (OpenTofu apply)"; make -C "$REPO_ROOT" infra || roadblock "make infra failed" "cd $REPO_ROOT/terraform && tofu plan"
  ok "AWS infra provisioned"
  step "make all (Posts 3-6)"; make -C "$REPO_ROOT" all || roadblock "make all failed" "make -C $REPO_ROOT status"
  ok "EKS lab + telemetry + dashboards deployed"
}

main() {
  hdr "network-o11y-demo — one-click DEPLOY"
  state_init; choose_target
  say "Target: ${C_B}$TARGET${C_RESET}"
  case "$TARGET" in local) deploy_local ;; aws) deploy_aws ;; esac
  final_report "Deploy complete."
}
main "$@"
