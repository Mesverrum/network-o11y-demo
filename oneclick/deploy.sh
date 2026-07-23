#!/usr/bin/env bash
# One-click deploy for network-o11y-demo.
#   ./oneclick/deploy.sh
# Idempotent + resumable: safe to re-run; each step checks real state and skips
# what's already done. On an unsurmountable roadblock it prints step-by-step
# remediation and exits 2 so you can fix it and re-run.
set -uo pipefail
SELF="./oneclick/deploy.sh"; ACTION=deploy
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# ===========================================================================
# LOCAL (OrbStack Linux VM)
# ===========================================================================
preflight_local() {
  hdr "Pre-flight — local (macOS + OrbStack)"
  [[ "$(uname -s)" == "Darwin" ]] || roadblock "This local path targets macOS + OrbStack" \
    "You are on $(uname -s). On native Linux you can run the lab directly:" \
    "cd local && make up   (ContainerLab runs natively; no VM needed)" \
    "This one-click VM flow is macOS-specific."
  have brew || roadblock "Homebrew is required" \
    "Install Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"" \
    "Follow its post-install 'Next steps' to add brew to your PATH."
  ok "Homebrew present"

  if ! have orb; then
    step "Installing OrbStack (brew cask)"; brew install --cask orbstack >/dev/null 2>&1 \
      && ok "OrbStack installed" || roadblock "OrbStack install failed" "Run: brew install --cask orbstack"
  else ok "OrbStack CLI present"; fi

  if ! orb status >/dev/null 2>&1 || [[ "$(orb status 2>/dev/null)" != "Running" ]]; then
    open -a OrbStack >/dev/null 2>&1 || true
    roadblock "OrbStack needs its one-time setup (GUI, admin approval)" \
      "The OrbStack app was opened for you. In it:" \
      "Click through the welcome and APPROVE the macOS admin password prompt (installs the network helper)." \
      "When asked what to use, enable 'Linux' (and 'Docker')." \
      "Wait until the menu-bar icon shows OrbStack is running (orb status == Running)."
  fi
  ok "OrbStack running"

  if ! orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM_NAME"; then
    step "Creating Linux VM '$VM_NAME'"; orb create ubuntu "$VM_NAME" >/dev/null 2>&1 \
      && ok "VM '$VM_NAME' created" || roadblock "Could not create the VM" "Run: orb create ubuntu $VM_NAME"
  else ok "VM '$VM_NAME' exists"; fi
  vm_q 'true' || roadblock "VM '$VM_NAME' not reachable" "Open OrbStack and start the '$VM_NAME' machine, or run: orb start $VM_NAME"
}

toolchain_local() {
  hdr "VM toolchain"
  local pkgs=""
  vm_q 'command -v docker'        || pkgs+=" docker.io"
  vm_q 'docker compose version'   || pkgs+=" docker-compose-v2"
  vm_q 'command -v make'          || pkgs+=" make"
  vm_q 'command -v envsubst'      || pkgs+=" gettext-base"
  vm_q 'command -v curl'          || pkgs+=" curl"
  vm_q 'command -v go'            || pkgs+=" golang-go"
  if [[ -n "$pkgs" ]]; then
    step "apt install:$pkgs"
    vm "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs" \
      >/dev/null 2>&1 || roadblock "apt install failed in the VM" "Open a VM shell: orb -m $VM_NAME" "Run: sudo apt-get update && sudo apt-get install -y$pkgs"
    ok "installed:$pkgs"
  else skip "apt packages"; fi

  vm_q 'systemctl is-active --quiet docker' || vm 'sudo systemctl enable --now docker' >/dev/null 2>&1
  vm_q 'groups | grep -q docker' || vm "sudo usermod -aG docker \$USER" >/dev/null 2>&1
  vm_q 'sudo docker info' && ok "Docker engine active" || roadblock "Docker engine not usable in the VM" "orb -m $VM_NAME then: sudo systemctl status docker"

  if vm_q 'command -v containerlab'; then skip "containerlab"; else
    step "Installing containerlab"; vm 'bash -c "$(curl -sL https://get.containerlab.dev)"' >/dev/null 2>&1 \
      && ok "containerlab installed" || roadblock "containerlab install failed" "orb -m $VM_NAME then: bash -c \"\$(curl -sL https://get.containerlab.dev)\""
  fi
  if vm_q 'yq --version 2>&1 | grep -q mikefarah'; then skip "yq (mikefarah)"; else
    step "Installing mikefarah yq"
    vm 'sudo curl -sL -o /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_$(dpkg --print-architecture) && sudo chmod +x /usr/local/bin/yq' >/dev/null 2>&1 \
      && ok "yq installed" || roadblock "yq install failed" "orb -m $VM_NAME then install mikefarah yq from github.com/mikefarah/yq/releases"
  fi
}

repo_local() {
  hdr "Repo + config (in VM)"
  if vm_q "test -d ~/$VM_REPO/.git"; then vm "cd ~/$VM_REPO && git pull -q || true" >/dev/null 2>&1; skip "repo cloned (pulled latest)"
  else step "Cloning repo into VM"; vm "git clone -q $REPO_URL ~/$VM_REPO" && ok "cloned ~/$VM_REPO" || roadblock "git clone failed in VM" "orb -m $VM_NAME then: git clone $REPO_URL ~/$VM_REPO"; fi

  vm "cd ~/$VM_REPO/local && { [ -f .env ] || cp .env.example .env; [ -f groups/srl.env ] || cp groups/srl.env.sample groups/srl.env; sed -i 's/\r\$//' .env groups/srl.env" >/dev/null 2>&1 && \
  vm "cd ~/$VM_REPO/local && true" ; ok "config files present (.env, groups/srl.env; CRLF stripped)"

  # credentials — only inspect the ACTIVE GC_OTLP_* lines (the .env.example
  # comments legitimately contain REPLACE_ME / YOUR-REGION and must be ignored).
  local creds_ok="grep -qE '^GC_OTLP_KEY=glc_' .env && ! grep -E '^GC_OTLP_(URL|ACCOUNT|KEY)=' .env | grep -qE 'REPLACE_ME|YOUR-REGION|glc_REPLACE_ME'"
  if vm_q "cd ~/$VM_REPO/local && { $creds_ok; }"; then
    skip "Grafana Cloud OTLP credentials"
  elif [[ -f "$REPO_ROOT/local/.env" ]] && ( cd "$REPO_ROOT/local" && eval "$creds_ok" ) 2>/dev/null; then
    step "Copying GC_OTLP_* from this Mac's local/.env into the VM"
    for k in GC_OTLP_URL GC_OTLP_ACCOUNT GC_OTLP_KEY LAB_TESTER_ID; do
      local v; v="$(grep -E "^$k=" "$REPO_ROOT/local/.env" | head -1 | cut -d= -f2- | tr -d '\r')"
      [[ -n "$v" ]] && vm "cd ~/$VM_REPO/local && grep -vE '^$k=' .env > .env.t && echo '$k=$v' >> .env.t && mv .env.t .env"
    done
    ok "credentials copied from Mac repo"
  else
    roadblock "Grafana Cloud OTLP credentials required" \
      "Get them in Grafana Cloud → Connections → Add new connection → OpenTelemetry (OTLP)." \
      "Open the VM's env file:  orb -m $VM_NAME" \
      "  nano ~/$VM_REPO/local/.env" \
      "Set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY (glc_… token with metrics/logs/traces write)." \
      "(Alternatively put the same values in this Mac's local/.env and the script copies them.)"
  fi

  # apply the Alloy topology-health scrape + tester_id fix if not present (PR #5)
  if vm_q "grep -q topology_health ~/$VM_REPO/local/alloy/config.alloy"; then
    skip "Alloy topology-health scrape"
  else
    step "Patching Alloy: topology-health scrape + tester_id"
    vm "cd ~/$VM_REPO/local && sed -i 's/marcnetterfield-lab/network-lab/g' alloy/config.alloy && cat >> alloy/config.alloy <<'A'

prometheus.scrape \"topology_health\" {
  targets         = [{ __address__ = \"topology_exporter:9100\", \"job\" = \"network-topology-exporter\" }]
  forward_to      = [otelcol.receiver.prometheus.topology_health.receiver]
  scrape_interval = \"30s\"
}
otelcol.receiver.prometheus \"topology_health\" {
  output { metrics = [otelcol.processor.transform.preprocessing.input] }
}
A" && ok "Alloy patched"
  fi
}

bringup_local() {
  hdr "Bring up the lab"
  vm "cd ~/$VM_REPO/local && make generate" >/dev/null 2>&1 && ok "make generate" || roadblock "make generate failed" "orb -m $VM_NAME then: cd ~/$VM_REPO/local && make generate"
  vm "cd ~/$VM_REPO/local && make check" >/dev/null 2>&1 && ok "make check" || warn "make check reported warnings (continuing)"

  vm_q "docker image inspect srl-local/network-topology-exporter:v1.0.0" && skip "topology-exporter image" || {
    step "Building topology-exporter image"; vm "cd ~/$VM_REPO/local && make topology-exporter-image" >/dev/null 2>&1 && ok "image built" || warn "topology-exporter image build failed (panel may be empty)"; }

  local up; up="$(vm 'docker ps --format "{{.Names}}" | grep -cE "spine1|leaf1|leaf2|client1|client2|alloy|gnmic|ktranslate|topology_exporter" || true')"
  if [[ "${up:-0}" -ge 12 ]]; then skip "12 lab containers already up"
  elif vm_q "docker inspect spine1"; then
    step "Fabric exists → make stabilize"; vm "cd ~/$VM_REPO/local && make stabilize" >/dev/null 2>&1 && ok "stabilized" || roadblock "make stabilize failed" "orb -m $VM_NAME then: cd ~/$VM_REPO/local && make stabilize"
  else
    step "make up (cold; ~10-15 min under emulation)"; vm "cd ~/$VM_REPO/local && make up" >/dev/null 2>&1 && ok "make up completed" || {
      warn "make up did not fully complete — running make stabilize"; vm "cd ~/$VM_REPO/local && make stabilize" >/dev/null 2>&1 && ok "stabilized" || roadblock "bring-up failed" "orb -m $VM_NAME then: cd ~/$VM_REPO/local && make stabilize"; }
  fi

  # discovery (uid 501↔1000: run as root)
  if vm_q "grep -q device_name ~/$VM_REPO/local/state/devices-srl.yaml 2>/dev/null"; then skip "SNMP discovery (devices present)"
  else step "SNMP discovery (sudo)"; vm "cd ~/$VM_REPO/local && sudo chown -R 501:501 config 2>/dev/null; sudo make discover GROUP=srl" >/dev/null 2>&1
    vm_q "grep -q device_name ~/$VM_REPO/local/state/devices-srl.yaml" && ok "discovered spine1/leaf1/leaf2" || warn "discovery returned no devices (check SNMP)"; fi

  vm_q "pgrep -f traffic.sh || docker exec client2 pgrep iperf3" && skip "traffic workloads" || { step "make traffic"; vm "cd ~/$VM_REPO/local && make traffic" >/dev/null 2>&1 && ok "traffic started" || warn "traffic start failed"; }

  if vm_q "docker exec client1 pgrep -f join-app"; then skip "join-app"
  elif vm_q 'command -v go'; then step "make join-app"; vm "cd ~/$VM_REPO/local && make join-app" >/dev/null 2>&1 && ok "join-app deployed" || warn "join-app failed (Go build / EVPN)";
  else warn "go not installed — skipping join-app"; fi
}

dashboards_local() {
  hdr "Grafana Cloud dashboards (best-effort)"
  if ! [[ -x "$GCX_BIN" ]]; then
    warn "gcx not installed — telemetry is still queryable in Explore. To get the curated dashboards:"
    say "     brew install grafana/grafana/gcx   (or see repo) then: gcx login <name> --server https://<stack>.grafana.net --oauth"
    REPORT_FAIL+=("Grafana dashboards (gcx not installed)"); return; fi
  if ! gcx_ok; then
    roadblock "gcx is not authenticated to your Grafana stack" \
      "Log in (opens a browser to approve):" \
      "  gcx login mystack --server https://<your-stack>.grafana.net --oauth" \
      "Verify:  gcx config check"
  fi
  ok "gcx authenticated ($("$GCX_BIN" config current 2>/dev/null || echo context set))"

  # plugins required by two panels
  local missing=""
  for p in andrewbmchugh-flow-panel netsage-sankey-panel; do
    "$GCX_BIN" api /api/plugins -o json 2>/dev/null | grep -q "\"$p\"" || missing+=" $p"
  done
  if [[ -n "$missing" ]]; then
    warn "panel plugins not installed:$missing (Fabric Map / Sankey will be blank until installed)"
    say "     Install via UI: Administration → Plugins → search each id → Install"
    say "     or a Cloud Access Policy token with 'stack-plugins:write':"
    say "       curl -s -XPOST https://grafana.com/api/instances/<stack-slug>/plugins -H 'Authorization: Bearer glc_…' -H 'Content-Type: application/json' -d '{\"plugin\":\"<id>\"}'"
  else ok "panel plugins installed"; fi

  step "Building + importing dashboards into folder '$GRAFANA_FOLDER'"
  vm "cd ~/$VM_REPO/local && python3 scripts/build-topology-dashboards.py >/dev/null 2>&1; python3 scripts/build-network-join-demo.py >/dev/null 2>&1; python3 scripts/retarget-dashboards-local.py >/dev/null 2>&1" || true
  local tmp; tmp="$(mktemp -d)"
  orb -m "$VM_NAME" bash -lc "cd ~/$VM_REPO/local && tar cf - dashboards/*.json .dash-payloads/topology/*.json .dash-payloads/network-join-demo.json 2>/dev/null" | tar -C "$tmp" -xf - 2>/dev/null || true
  "$GCX_BIN" api /api/folders -d "{\"uid\":\"$GRAFANA_FOLDER\",\"title\":\"$GRAFANA_FOLDER\"}" >/dev/null 2>&1 || true
  local n=0
  while IFS= read -r f; do
    python3 - "$f" "$GRAFANA_FOLDER" "$GCX_BIN" <<'PY' && n=$((n+1))
import json,subprocess,sys,tempfile,os
f,folder,gcx=sys.argv[1:4]
d=json.load(open(f)); d=d.get("dashboard",d); d.pop("id",None)
p={"dashboard":d,"folderUid":folder,"overwrite":True}
t=tempfile.NamedTemporaryFile("w",suffix=".json",delete=False); json.dump(p,t); t.close()
r=subprocess.run([gcx,"api","/api/dashboards/db","-d","@"+t.name,"-o","json"],capture_output=True,text=True)
os.unlink(t.name); sys.exit(0 if r.returncode==0 else 1)
PY
  done < <(find "$tmp" -name '*.json')
  rm -rf "$tmp"
  [[ "$n" -gt 0 ]] && ok "imported $n dashboards" || warn "no dashboards imported"

  # verify data
  if "$GCX_BIN" metrics query 'count(kentik_snmp_CPU)' -d grafanacloud-prom -o json 2>/dev/null | grep -q '"value"'; then
    ok "verified: SNMP metrics present in Grafana Cloud"; else warn "no kentik_snmp_CPU yet (give it ~60s, then check Explore)"; fi
}

deploy_local() { preflight_local; toolchain_local; repo_local; bringup_local; dashboards_local; }

# ===========================================================================
# AWS (EKS / Clabbernetes) — drives the repo's existing automation
# ===========================================================================
deploy_aws() {
  hdr "Pre-flight — AWS / EKS"
  warn "The AWS path uses the repo's terraform + 'make all' automation (not validated in this session)."
  have aws       || roadblock "AWS CLI required"      "Install: brew install awscli" "Configure: aws configure  (or export AWS_PROFILE)"
  aws sts get-caller-identity >/dev/null 2>&1 || roadblock "AWS credentials not working" "Run: aws configure  (or set AWS_PROFILE / AWS_ACCESS_KEY_ID)" "Verify: aws sts get-caller-identity"
  { have tofu || have terraform; } || roadblock "OpenTofu (or Terraform) required" "Install: brew install opentofu"
  have kubectl   || roadblock "kubectl required"      "Install: brew install kubectl"
  ok "aws + IaC + kubectl present"
  [[ -f "$REPO_ROOT/terraform/terraform.tfvars" ]] || roadblock "terraform.tfvars missing" \
    "cd $REPO_ROOT/terraform && cp terraform.tfvars.example terraform.tfvars" \
    "Edit terraform.tfvars: region, cluster name, SSH key, allowed CIDRs, etc."
  [[ -f "$REPO_ROOT/k8s/telemetry/grafana-cloud-secret.yaml" ]] || warn "k8s/telemetry/grafana-cloud-secret.yaml not found — Post-3 telemetry will need Grafana Cloud creds (see scripts/setup-env.sh)"

  hdr "Provision + deploy (long-running)"
  step "make infra  (OpenTofu apply: VPC, EKS, bastion)"
  make -C "$REPO_ROOT" infra || roadblock "make infra failed" "Inspect: cd $REPO_ROOT/terraform && tofu plan" "Fix the reported issue (quota, creds, tfvars) and re-run."
  ok "AWS infra provisioned"
  step "make all  (Post 3-6: lab, NetBox, dashboards, Ansible)"
  make -C "$REPO_ROOT" all || roadblock "make all failed" "Check pod status: make -C $REPO_ROOT status" "Re-run after resolving (the make targets are re-entrant)."
  ok "EKS lab + telemetry + dashboards deployed"
}

# ===========================================================================
main() {
  hdr "network-o11y-demo — one-click DEPLOY"
  state_init; choose_target
  say "Target: ${C_B}$TARGET${C_RESET}"
  case "$TARGET" in
    local) deploy_local ;;
    aws)   deploy_aws ;;
  esac
  final_report "Deploy complete."
}
main "$@"
