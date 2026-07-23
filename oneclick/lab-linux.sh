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

grafana(){
  # Token-based (no OAuth, no gcx dependency), identical on all platforms:
  #   dashboards  -> in-stack Grafana API with a service-account token (glsa_)
  #   plugins     -> grafana.com Cloud API with a stack-plugins:write CAP token (glc_)
  step "Grafana Cloud — dashboards + panel plugins (token auth)"
  cd "$LDIR" || exit 1
  set -a; [ -f .env ] && . ./.env; set +a
  [[ -n "${GRAFANA_URL:-}" && "${GRAFANA_TOKEN:-}" == glsa_* ]] || roadblock \
    "A Grafana service-account token is required for dashboard import" \
    "Grafana → Administration → Users and access → Service accounts → add a token (Editor or Admin)." \
    "Put in $LDIR/.env:  GRAFANA_URL=https://<stack>.grafana.net   and   GRAFANA_TOKEN=glsa_…"
  python3 scripts/build-topology-dashboards.py >/dev/null 2>&1 || true
  python3 scripts/build-network-join-demo.py   >/dev/null 2>&1 || true
  python3 scripts/retarget-dashboards-local.py >/dev/null 2>&1 || true
  GRAFANA_URL="$GRAFANA_URL" GRAFANA_TOKEN="$GRAFANA_TOKEN" \
  GC_PLUGINS_TOKEN="${GC_STACK_TOKEN:-${GC_OTLP_KEY:-}}" \
  python3 - <<'PY'
import json, os, sys, glob, urllib.request, urllib.error, re
base=os.environ["GRAFANA_URL"].rstrip("/"); tok=os.environ["GRAFANA_TOKEN"]
ptok=os.environ.get("GC_PLUGINS_TOKEN",""); slug=re.sub(r"^https?://([^.]+)\..*",r"\1",base)
PLUGINS=["andrewbmchugh-flow-panel","netsage-sankey-panel"]
FILES=sorted(glob.glob("dashboards/*.json")+glob.glob(".dash-payloads/topology/*.json")+glob.glob(".dash-payloads/network-join-demo.json"))
def req(url,tok_,body=None,method="POST"):
    data=None if body is None else json.dumps(body).encode()
    r=urllib.request.Request(url,data=data,method=method,
        headers={"Authorization":"Bearer "+tok_,"Content-Type":"application/json","Accept":"application/json"})
    try:
        with urllib.request.urlopen(r) as resp: return resp.status,resp.read()
    except urllib.error.HTTPError as e: return e.code,e.read()
    except Exception as e: return 0,str(e).encode()
# folder
req(base+"/api/folders",tok,{"uid":"network-lab","title":"network-lab"})
# dashboards
n=0
for f in FILES:
    d=json.load(open(f)); d=d.get("dashboard",d); d.pop("id",None)
    c,_=req(base+"/api/dashboards/db",tok,{"dashboard":d,"folderUid":"network-lab","overwrite":True})
    if 200<=c<300: n+=1
    else: print(f"  ! dashboard {os.path.basename(f)}: HTTP {c}")
print(f"  imported {n}/{len(FILES)} dashboards into folder network-lab")
# plugins (Cloud API)
if not ptok: print("PLUGIN_SCOPE_MISSING"); sys.exit(3)
need_scope=False
for p in PLUGINS:
    c,b=req(f"https://grafana.com/api/instances/{slug}/plugins",ptok,{"plugin":p})
    if 200<=c<300 or c==409: print(f"  plugin {p}: ok")
    elif c in (401,403): print(f"  plugin {p}: HTTP {c} (token lacks stack-plugins:write)"); need_scope=True
    else: print(f"  plugin {p}: HTTP {c} {b[:120].decode(errors='replace')}")
sys.exit(3 if need_scope else 0)
PY
  local rc=$?
  if [[ $rc -eq 3 ]]; then roadblock \
    "Panel-plugin install needs a Grafana Cloud token with 'stack-plugins:write'" \
    "Grafana Cloud portal → Access Policies → create a policy with scope 'stack-plugins:write' → create a token." \
    "Put in $LDIR/.env:  GC_STACK_TOKEN=glc_…   (or add the stack-plugins:write scope to your existing OTLP access policy)"
  elif [[ $rc -ne 0 ]]; then warn "dashboard/plugin step returned $rc (see lines above)"; else ok "dashboards imported + plugins installed"; fi
}

teardown(){
  step "Tear down lab"; cd "$LDIR"
  make traffic-stop  >/dev/null 2>&1 || true
  make join-app-stop >/dev/null 2>&1 || true
  if docker ps -q | grep -q .; then make down >/dev/null 2>&1 && ok "lab torn down" || roadblock "make down failed" "cd $LDIR && make down" "Stuck containers: docker rm -f \$(docker ps -aq)"
  else skip "no lab containers running"; fi
}

case "$ACTION" in
  deploy)        install_toolchain; prep_config; bringup; grafana; ok "lab-linux: deploy complete" ;;
  decommission)  teardown; ok "lab-linux: decommission complete" ;;
  *) echo "usage: lab-linux.sh deploy|decommission"; exit 1 ;;
esac
