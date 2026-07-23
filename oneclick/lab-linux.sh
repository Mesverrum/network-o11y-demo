#!/usr/bin/env bash
# Lab bring-up / teardown that runs INSIDE a Linux environment — WSL2 (Windows),
# native Linux, or an OrbStack VM. Platform bootstrappers (deploy.ps1 for Windows,
# deploy.sh for macOS) install the Linux env and then invoke this.
#
#   bash oneclick/lab-linux.sh deploy
#   bash oneclick/lab-linux.sh decommission
#
# uid-aware: ktranslate containers run as uid 1000. On WSL the login user IS 1000
# (discovery runs as the user); on OrbStack the user is 501 (discovery via sudo).
# Roadblocks print remediation and exit 2 so the caller can stop and re-run.
set -uo pipefail
ACTION="${1:-deploy}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LDIR="$REPO_ROOT/local"

if [[ -t 1 ]]; then B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; Z=$'\033[0m'; else B=; D=; G=; Y=; Z=; fi
step(){ printf '%s▶ %s%s\n' "$B" "$*" "$Z"; }
ok(){   printf '  %s✓%s %s\n' "$G" "$Z" "$*"; }
skip(){ printf '  %s•%s %s %s(already done)%s\n' "$D" "$Z" "$*" "$D" "$Z"; }
warn(){ printf '  %s! %s%s\n' "$Y" "$*" "$Z"; }
roadblock(){ local t="$1"; shift; printf '\n%s┌─ ROADBLOCK: %s\n' "$Y" "$t"; local i=1
  for l in "$@"; do printf '│  %2d. %s\n' "$i" "$l"; i=$((i+1)); done
  printf '│  Then re-run the deploy from Windows/macOS (it resumes here).\n└─%s\n' "$Z"; exit 2; }

UID_N="$(id -u)"

# --- creds check on the ACTIVE GC_OTLP_* lines only (ignore .env.example comments)
creds_present(){ cd "$LDIR" && grep -qE '^GC_OTLP_KEY=glc_' .env 2>/dev/null && \
  ! grep -E '^GC_OTLP_(URL|ACCOUNT|KEY)=' .env | grep -qE 'REPLACE_ME|YOUR-REGION|glc_REPLACE_ME'; }

install_toolchain(){
  step "Toolchain"
  local pkgs=""
  command -v docker      >/dev/null || pkgs+=" docker.io"
  docker compose version >/dev/null 2>&1 || pkgs+=" docker-compose-v2"
  command -v make        >/dev/null || pkgs+=" make"
  command -v envsubst    >/dev/null || pkgs+=" gettext-base"
  command -v curl        >/dev/null || pkgs+=" curl"
  command -v git         >/dev/null || pkgs+=" git"
  command -v go          >/dev/null || pkgs+=" golang-go"
  if [[ -n "$pkgs" ]]; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs >/dev/null 2>&1 \
      || roadblock "apt install failed" "Run inside Linux: sudo apt-get update && sudo apt-get install -y$pkgs"
    ok "installed:$pkgs"
  else skip "apt packages"; fi

  # docker engine (WSL needs systemd enabled to run dockerd via systemctl)
  if ! sudo docker info >/dev/null 2>&1; then
    if command -v systemctl >/dev/null && systemctl list-units >/dev/null 2>&1; then
      sudo systemctl enable --now docker >/dev/null 2>&1 || true
    fi
    if ! sudo docker info >/dev/null 2>&1; then
      roadblock "Docker engine is not running in this Linux environment" \
        "Easiest on Windows: install Docker Desktop and enable WSL integration for this distro (Settings → Resources → WSL integration)." \
        "OR enable systemd in WSL: add to /etc/wsl.conf →  [boot]\\n systemd=true" \
        "Then from Windows PowerShell run:  wsl --shutdown   (closes WSL; next command restarts it)" \
        "Verify:  sudo systemctl enable --now docker && docker info"
    fi
  fi
  sudo usermod -aG docker "$USER" >/dev/null 2>&1 || true
  ok "Docker engine available"

  command -v containerlab >/dev/null && skip "containerlab" || {
    step "Installing containerlab"; bash -c "$(curl -sL https://get.containerlab.dev)" >/dev/null 2>&1 \
      && ok "containerlab" || roadblock "containerlab install failed" 'Run: bash -c "$(curl -sL https://get.containerlab.dev)"'; }
  if yq --version 2>&1 | grep -q mikefarah; then skip "yq (mikefarah)"; else
    step "Installing mikefarah yq"
    sudo curl -sL -o /usr/local/bin/yq "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_$(dpkg --print-architecture)" \
      && sudo chmod +x /usr/local/bin/yq && ok "yq" || roadblock "yq install failed" "Install mikefarah yq from github.com/mikefarah/yq/releases into /usr/local/bin/yq"; fi
}

prep_config(){
  step "Config + credentials"
  cd "$LDIR" || exit 1
  [[ -f .env ]] || cp .env.example .env
  [[ -f groups/srl.env ]] || cp groups/srl.env.sample groups/srl.env
  sed -i 's/\r$//' .env groups/srl.env 2>/dev/null || true
  ok "config files present (CRLF stripped)"
  creds_present && ok "Grafana Cloud OTLP credentials set" || roadblock \
    "Grafana Cloud OTLP credentials required" \
    "Get them in Grafana Cloud → Connections → Add new connection → OpenTelemetry (OTLP)." \
    "Edit: $LDIR/.env" \
    "Set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY (glc_… token with metrics/logs/traces write)."
  # Alloy topology-health scrape + tester_id (until PR #5 merges)
  if grep -q topology_health alloy/config.alloy; then skip "Alloy topology-health scrape"; else
    step "Patching Alloy (topology-health scrape + tester_id)"
    sed -i 's/marcnetterfield-lab/network-lab/g' alloy/config.alloy
    cat >> alloy/config.alloy <<'A'

prometheus.scrape "topology_health" {
  targets         = [{ __address__ = "topology_exporter:9100", "job" = "network-topology-exporter" }]
  forward_to      = [otelcol.receiver.prometheus.topology_health.receiver]
  scrape_interval = "30s"
}
otelcol.receiver.prometheus "topology_health" {
  output { metrics = [otelcol.processor.transform.preprocessing.input] }
}
A
    ok "Alloy patched"; fi
}

bringup(){
  step "Bring up the lab"
  cd "$LDIR" || exit 1
  make generate >/dev/null 2>&1 && ok "make generate" || roadblock "make generate failed" "cd $LDIR && make generate  (read the error)"
  make check    >/dev/null 2>&1 && ok "make check" || warn "make check warnings (continuing)"
  docker image inspect srl-local/network-topology-exporter:v1.0.0 >/dev/null 2>&1 && skip "topology-exporter image" \
    || { step "Building topology-exporter image"; make topology-exporter-image >/dev/null 2>&1 && ok "image built" || warn "topology-exporter image build failed"; }

  local up; up="$(docker ps --format '{{.Names}}' | grep -cE 'spine1|leaf1|leaf2|client1|client2|alloy|gnmic|ktranslate|topology_exporter' || true)"
  if [[ "${up:-0}" -ge 12 ]]; then skip "12 lab containers up"
  elif docker inspect spine1 >/dev/null 2>&1; then
    step "make stabilize"; make stabilize >/dev/null 2>&1 && ok "stabilized" || roadblock "make stabilize failed" "cd $LDIR && make stabilize"
  else
    step "make up (cold: ~10 min native / longer under emulation)"; make up >/dev/null 2>&1 && ok "make up" \
      || { warn "make up incomplete → make stabilize"; make stabilize >/dev/null 2>&1 && ok "stabilized" || roadblock "bring-up failed" "cd $LDIR && make stabilize"; }
  fi

  # discovery: chown state to ktranslate's uid 1000; run as user if uid==1000 else via sudo
  if grep -q device_name state/devices-srl.yaml 2>/dev/null; then skip "SNMP discovery"
  else step "SNMP discovery"
    sudo chown -R 1000:1000 config state 2>/dev/null || true
    if [[ "$UID_N" -eq 1000 ]]; then make discover GROUP=srl >/dev/null 2>&1
    else sudo chown -R "$UID_N":"$UID_N" config 2>/dev/null; sudo make discover GROUP=srl >/dev/null 2>&1; fi
    grep -q device_name state/devices-srl.yaml 2>/dev/null && ok "discovered spine1/leaf1/leaf2" || warn "discovery found no devices (check SNMP)"; fi

  pgrep -f traffic.sh >/dev/null 2>&1 || docker exec client2 pgrep iperf3 >/dev/null 2>&1 && skip "traffic" \
    || { step "make traffic"; make traffic >/dev/null 2>&1 && ok "traffic started" || warn "traffic failed"; }
  if docker exec client1 pgrep -f join-app >/dev/null 2>&1; then skip "join-app"
  elif command -v go >/dev/null; then step "make join-app"; make join-app >/dev/null 2>&1 && ok "join-app deployed" || warn "join-app failed"
  else warn "go missing — skipping join-app"; fi
}

dashboards(){
  if [[ "${LAB_SKIP_DASHBOARDS:-}" == "1" ]]; then skip "dashboards (handled by the host bootstrapper)"; return; fi
  step "Grafana Cloud dashboards (best-effort)"
  cd "$LDIR" || exit 1
  if ! command -v gcx >/dev/null; then warn "gcx not installed in Linux env — telemetry still queryable in Explore. Install gcx + 'gcx login … --oauth' to import curated dashboards."; return; fi
  gcx config check >/dev/null 2>&1 || roadblock "gcx is not authenticated" "gcx login mystack --server https://<your-stack>.grafana.net --oauth" "Verify: gcx config check"
  python3 scripts/build-topology-dashboards.py >/dev/null 2>&1 || true
  python3 scripts/build-network-join-demo.py   >/dev/null 2>&1 || true
  python3 scripts/retarget-dashboards-local.py >/dev/null 2>&1 || true
  gcx api /api/folders -d '{"uid":"network-lab","title":"network-lab"}' >/dev/null 2>&1 || true
  local n=0
  for f in dashboards/*.json .dash-payloads/topology/*.json .dash-payloads/network-join-demo.json; do
    [[ -f "$f" ]] || continue
    python3 - "$f" <<'PY' && n=$((n+1))
import json,subprocess,sys,tempfile,os
d=json.load(open(sys.argv[1])); d=d.get("dashboard",d); d.pop("id",None)
t=tempfile.NamedTemporaryFile("w",suffix=".json",delete=False)
json.dump({"dashboard":d,"folderUid":"network-lab","overwrite":True},t); t.close()
r=subprocess.run(["gcx","api","/api/dashboards/db","-d","@"+t.name,"-o","json"],capture_output=True,text=True)
os.unlink(t.name); sys.exit(0 if r.returncode==0 else 1)
PY
  done
  [[ "$n" -gt 0 ]] && ok "imported $n dashboards into folder network-lab" || warn "no dashboards imported"
  local miss=""
  for p in andrewbmchugh-flow-panel netsage-sankey-panel; do gcx api /api/plugins -o json 2>/dev/null | grep -q "\"$p\"" || miss+=" $p"; done
  [[ -n "$miss" ]] && warn "panel plugins not installed:$miss (Fabric Map / Sankey blank until installed via Administration → Plugins)" || ok "panel plugins installed"
}

teardown(){
  step "Tear down lab"; cd "$LDIR"
  make traffic-stop  >/dev/null 2>&1 || true
  make join-app-stop >/dev/null 2>&1 || true
  if docker ps -q | grep -q .; then make down >/dev/null 2>&1 && ok "lab torn down" || roadblock "make down failed" "cd $LDIR && make down" "Stuck containers: docker rm -f \$(docker ps -aq)"
  else skip "no lab containers running"; fi
}

case "$ACTION" in
  deploy)        install_toolchain; prep_config; bringup; dashboards; ok "lab-linux: deploy complete" ;;
  decommission)  teardown; ok "lab-linux: decommission complete" ;;
  *) echo "usage: lab-linux.sh deploy|decommission"; exit 1 ;;
esac
