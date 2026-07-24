#!/usr/bin/env bash
# Shared helpers for the one-click deploy / decommission scripts.
# Sourced by deploy.sh and decommission.sh. Not meant to be run directly.

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
ONECLICK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ONECLICK_DIR}/.." && pwd)"
REPO_URL="${REPO_URL:-https://github.com/Mesverrum/network-o11y-demo.git}"

VM_NAME="${VM_NAME:-ubuntu}"                       # OrbStack Linux machine name
VM_REPO="${VM_REPO:-network-o11y-demo}"            # clone dir inside the VM ($HOME/$VM_REPO)
GRAFANA_FOLDER="${GRAFANA_FOLDER:-network-lab}"

STATE_DIR="${STATE_DIR:-$HOME/.config/network-o11y-demo}"
STATE_FILE="${STATE_FILE:-$STATE_DIR/oneclick.state}"

GCX_BIN="$(command -v gcx 2>/dev/null || echo /opt/homebrew/bin/gcx)"

# report accumulators
declare -a REPORT_DONE=() REPORT_SKIP=() REPORT_FAIL=()

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RESET=$'\033[0m'; C_B=$'\033[1m'; C_DIM=$'\033[2m'
  C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_CYN=$'\033[36m'
else
  C_RESET=; C_B=; C_DIM=; C_GRN=; C_YEL=; C_RED=; C_CYN=
fi

say()   { printf '%s\n' "$*"; }
hdr()   { printf '\n%s== %s ==%s\n' "$C_B$C_CYN" "$*" "$C_RESET"; }
step()  { printf '%s> %s%s\n' "$C_B" "$*" "$C_RESET"; }
ok()    { printf '  %s[ok]%s %s\n' "$C_GRN" "$C_RESET" "$*"; REPORT_DONE+=("$*"); }
skip()  { printf '  %s-%s %s %s(already done)%s\n' "$C_DIM" "$C_RESET" "$*" "$C_DIM" "$C_RESET"; REPORT_SKIP+=("$*"); }
warn()  { printf '  %s! %s%s\n' "$C_YEL" "$*" "$C_RESET"; }
err()   { printf '  %s[x] %s%s\n' "$C_RED" "$*" "$C_RESET"; }

# ---------------------------------------------------------------------------
# State (idempotency is mostly condition-driven; this stores choices/flags)
# ---------------------------------------------------------------------------
state_init() { mkdir -p "$STATE_DIR"; touch "$STATE_FILE"; }
state_get()  { grep -E "^$1=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2-; }
state_set()  {
  state_init
  local k="$1" v="$2"
  grep -vE "^$k=" "$STATE_FILE" 2>/dev/null > "$STATE_FILE.tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$STATE_FILE.tmp"
  mv "$STATE_FILE.tmp" "$STATE_FILE"
}
state_clear() { rm -f "$STATE_FILE"; }

# ---------------------------------------------------------------------------
# Roadblock: print step-by-step remediation and exit so the user can re-run.
#   roadblock "Title" "step 1" "step 2" ...
# Exit code 2 == "fixable; re-run me after doing the steps".
# ---------------------------------------------------------------------------
SELF="${SELF:-$0}"
roadblock() {
  local title="$1"; shift
  printf '\n%s' "$C_YEL"
  printf '+- ROADBLOCK ---------------------------------------------------------+\n'
  printf '| %s%-67s%s|\n' "$C_B" "$title" "$C_RESET$C_YEL"
  printf '+---------------------------------------------------------------------+\n'
  printf '%s' "$C_RESET"
  local i=1
  for line in "$@"; do
    if [[ "$line" == "" ]]; then printf '\n'; else printf '   %s%2d.%s %s\n' "$C_B" "$i" "$C_RESET" "$line"; i=$((i+1)); fi
  done
  printf '\n   %sThen re-run:%s %s%s%s\n' "$C_B" "$C_RESET" "$C_CYN" "$SELF" "$C_RESET"
  printf '   %s(the script resumes from where it stopped)%s\n' "$C_DIM" "$C_RESET"
  printf '%s+---------------------------------------------------------------------+%s\n' "$C_YEL" "$C_RESET"
  REPORT_FAIL+=("$title")
  final_report "stopped at a roadblock"
  exit 2
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
have()   { command -v "$1" >/dev/null 2>&1; }
# </dev/null on every orb call: orb buffers/drains the caller's stdin, which would
# otherwise swallow input meant for the interactive confirm prompts (or piped answers).
vm()     { orb -m "$VM_NAME" bash -lc "$1" </dev/null; }   # run a command inside the VM
vm_q()   { orb -m "$VM_NAME" bash -lc "$1" </dev/null >/dev/null 2>&1; }
gcx_ok() { [[ -x "$GCX_BIN" ]] && "$GCX_BIN" config check >/dev/null 2>&1; }

confirm() { # confirm "question" -> returns 0 for yes
  local ans; read -r -p "  $1 [y/N] " ans; [[ "$ans" =~ ^[Yy] ]]; }

# ---------------------------------------------------------------------------
# Target selection (local | aws), remembered in state
# ---------------------------------------------------------------------------
choose_target() {
  local t; t="$(state_get TARGET)"
  if [[ -n "$t" ]]; then
    TARGET="$t"
    [[ -t 0 ]] || return                       # non-interactive (piped/resume): keep saved target silently
    hdr "Deployment target"
    say "  Saved target: ${C_B}$t${C_RESET}"
    local c; read -r -p "  Press Enter to keep, or type 'local' / 'aws' to change: " c
    case "${c:-}" in
      ""|"$t")  TARGET="$t" ;;
      local|1)  TARGET=local ;;
      aws|2)    TARGET=aws ;;
      *)        warn "unrecognized '$c' - keeping saved target '$t'"; TARGET="$t" ;;
    esac
    [[ "$TARGET" != "$t" ]] && state_set TARGET "$TARGET"
    return
  fi
  hdr "Choose deployment target"
  say "  ${C_B}1)${C_RESET} local  - OrbStack Linux VM on this Mac (ContainerLab + ktranslate -> Grafana Cloud)"
  say "  ${C_B}2)${C_RESET} aws    - EKS / Clabbernetes via OpenTofu + Ansible (repo's terraform + make all)"
  local c; read -r -p "  Select 1 or 2: " c
  case "$c" in
    1) TARGET=local ;;
    2) TARGET=aws ;;
    *) err "invalid selection"; exit 1 ;;
  esac
  state_set TARGET "$TARGET"
}

# ---------------------------------------------------------------------------
# Access instructions - how to reach each component.
# ---------------------------------------------------------------------------
access_instructions() {
  hdr "How to access the components"
  if [[ "${TARGET:-}" == "aws" ]]; then
    cat <<EOF
  ${C_B}AWS / EKS${C_RESET}
    - Cluster:   aws eks update-kubeconfig --name <cluster>  (see terraform outputs: cd $REPO_ROOT/terraform && tofu output)
    - Pods:      make -C $REPO_ROOT status
    - Tunnels:   make -C $REPO_ROOT access   (opens NetBox UI + Alloy UI SSH tunnels)
    - Bastion:   ssh into the bastion host printed by 'tofu output' (key from terraform.tfvars)
  ${C_B}Grafana Cloud${C_RESET}
    - UI:        https://<your-stack>.grafana.net  -> Dashboards -> folder '${GRAFANA_FOLDER}'
    - Explore:   count by (device_name) (kentik_snmp_CPU)
EOF
  else
    cat <<EOF
  ${C_B}Local VM (OrbStack)${C_RESET}
    - Shell:     orb -m ${VM_NAME}
    - One cmd:   orb -m ${VM_NAME} docker ps
    - SSH:       ssh -p 32222 -i ~/.orbstack/ssh/id_ed25519 default@localhost
    - Lab dir:   ~/${VM_REPO}/local   (inside the VM)
    - Controls:  orb -m ${VM_NAME} bash -lc 'cd ~/${VM_REPO}/local && make status | traffic | stabilize'
  ${C_B}Grafana Cloud${C_RESET}
    - UI:        ${GRAFANA_URL:-https://<your-stack>.grafana.net}  -> Dashboards -> folder '${GRAFANA_FOLDER}'
    - Explore:   kentik_snmp_CPU | topk(20, network_io_by_flow_bytes) | network_topology_device_info
    - gcx query: gcx metrics query 'kentik_snmp_CPU' -d grafanacloud-prom
  ${C_B}AWS${C_RESET}
    - Not used in a local deployment.
EOF
  fi
}

# ---------------------------------------------------------------------------
# Final report (deploy or decommission). $1 = closing note.
# ---------------------------------------------------------------------------
final_report() {
  local note="${1:-}"
  hdr "Report - ${ACTION:-run} (${TARGET:-?})"
  if ((${#REPORT_DONE[@]})); then
    say "${C_GRN}${C_B}Completed:${C_RESET}"; printf '  [ok] %s\n' "${REPORT_DONE[@]}"
  fi
  if ((${#REPORT_SKIP[@]})); then
    say "${C_DIM}Already in place / skipped:${C_RESET}"; printf '  - %s\n' "${REPORT_SKIP[@]}"
  fi
  if ((${#REPORT_FAIL[@]})); then
    say "${C_RED}${C_B}Not completed:${C_RESET}"; printf '  [x] %s\n' "${REPORT_FAIL[@]}"
  fi
  [[ -n "$note" ]] && printf '\n%s%s%s\n' "$C_YEL" "$note" "$C_RESET"
  if [[ "${ACTION:-}" == "decommission" ]]; then
    hdr "Next steps"
    say "  Re-deploy any time:  ${C_CYN}./oneclick/deploy.sh${C_RESET}"
    say "  ${C_DIM}Forget the saved target choice:${C_RESET} rm -f $STATE_FILE"
  else
    access_instructions
  fi
}
