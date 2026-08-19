#!/usr/bin/env bash
# Enroll lab Alloy in Grafana Fleet Management and (optionally) push SNMP scrape via pipeline.
#
# Prereqs:
#   GC_FM_URL  — from Collector app (or Connections → Fleet Management → API)
#                marcnetterfield1: https://fleet-management-prod-008.grafana.net
#   GC_FM_TOKEN — access policy with fleet-management:read (+ write to upsert).
#                 Defaults to GC_OTLP_KEY when unset (works on this stack).
#   LAB_ALLOY_FLEET=1
#   LAB_ALLOY_FLEET_SNMP=1       — move SNMP River to Fleet
#   LAB_ALLOY_FLEET_DISCOVERY=1  — discovery.snmp in Fleet (default; needs FROM_SOURCE image)
#   LAB_ALLOY_FLEET_DISCOVERY=0  — sidecar snmp_discovery + local.file targets
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' .env)
  set +a
fi

# Auto-detect Fleet URL from Collector app when missing.
if [[ -z "${GC_FM_URL:-}" && -n "${GRAFANA_URL:-}" && -n "${GRAFANA_TOKEN:-}" ]]; then
  detected="$(
    curl -s -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
      "${GRAFANA_URL}/api/plugins/grafana-collector-app/settings" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("jsonData") or {}).get("agmClusterUrl") or "")' \
      2>/dev/null || true
  )"
  if [[ -n "${detected}" ]]; then
    GC_FM_URL="${detected}"
    echo "==> detected GC_FM_URL=${GC_FM_URL}"
  fi
fi

export GC_FM_URL="${GC_FM_URL:?set GC_FM_URL (Fleet Management base URL)}"
export GC_FM_USER="${GC_FM_USER:-${GC_OTLP_ACCOUNT:?}}"
export GC_FM_TOKEN="${GC_FM_TOKEN:-${GC_OTLP_KEY:?}}"

# Persist non-secret URL into .env if missing (token stays as GC_OTLP_KEY fallback).
if ! grep -q '^GC_FM_URL=' .env 2>/dev/null; then
  echo "GC_FM_URL=${GC_FM_URL}" >> .env
  echo "==> appended GC_FM_URL to .env"
fi
if ! grep -q '^LAB_ALLOY_FLEET=' .env 2>/dev/null; then
  echo "LAB_ALLOY_FLEET=1" >> .env
fi

bash "${ROOT}/scripts/write-compose-host-env.sh" 2>/dev/null || true
# ensure KTRANS_HOST available before remotecfg id/attributes
if [[ -f compose-host.generated.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' compose-host.generated.env)
  set +a
fi

export LAB_ALLOY_FLEET=1
export LAB_ALLOY_SNMP="${LAB_ALLOY_SNMP:-1}"
# Prefer Fleet-owned SNMP; fall back to local River if upsert lacks write scope.
export LAB_ALLOY_FLEET_SNMP="${LAB_ALLOY_FLEET_SNMP:-1}"
# Default: in-process discovery.snmp (requires ALLOY_NETWORK_FROM_SOURCE image).
export LAB_ALLOY_FLEET_DISCOVERY="${LAB_ALLOY_FLEET_DISCOVERY:-1}"

bash "${ROOT}/scripts/render-alloy-remotecfg.sh"

if [[ "${LAB_ALLOY_FLEET_SNMP}" == "1" ]]; then
  if python3 "${ROOT}/scripts/fleet-upsert-snmp-pipeline.py"; then
    echo "==> Fleet owns SNMP River (discovery=${LAB_ALLOY_FLEET_DISCOVERY})"
  else
    echo "WARN: Fleet pipeline upsert failed (need fleet-management:write on GC_FM_TOKEN)." >&2
    echo "WARN: Falling back to local snmp-scrape.generated.alloy; remotecfg enrollment still proceeds." >&2
    echo "WARN: Create pipeline from fixtures/alloy-fleet/ in the UI, or add write scope." >&2
    export LAB_ALLOY_FLEET_SNMP=0
    sed -i '/^LAB_ALLOY_FLEET_SNMP=/d' .env 2>/dev/null || true
  fi
fi

LAB_ALLOY_FLEET_SNMP="${LAB_ALLOY_FLEET_SNMP}" bash "${ROOT}/scripts/render-alloy-snmp-scrape.sh"

# Refresh CIDR group file for discovery.snmp (and legacy sidecar).
export SNMP_DISCOVERY_UID="$(id -u)" SNMP_DISCOVERY_GID="$(id -g)"
LAB_FABRIC_PROFILE="${LAB_FABRIC_PROFILE:-snmp-min}" bash "${ROOT}/scripts/alloy-snmp-discover.sh" || true
# Ensure overrides file exists for the Alloy mount.
[[ -f "${ROOT}/alloy/snmp-overrides.yml" ]] || echo 'overrides: []' > "${ROOT}/alloy/snmp-overrides.yml"

compose=(docker compose --env-file .env)
[[ -f compose-host.generated.env ]] && compose+=(--env-file compose-host.generated.env)
compose+=(--profile alloy-snmp -f compose-base.yaml)
[[ -f compose-groups.generated.yaml ]] && compose+=(-f compose-groups.generated.yaml)
[[ -f compose-catalog.generated.yaml ]] && compose+=(-f compose-catalog.generated.yaml)
[[ -f compose-limits.generated.yaml ]] && compose+=(-f compose-limits.generated.yaml)

if [[ "${LAB_ALLOY_FLEET_DISCOVERY}" == "1" ]]; then
  echo "==> discovery.snmp in Alloy — stopping sidecar snmp_discovery (if any)"
  docker stop snmp_discovery >/dev/null 2>&1 || true
  docker rm snmp_discovery >/dev/null 2>&1 || true
  "${compose[@]}" up -d --no-deps --force-recreate alloy
else
  "${compose[@]}" up -d --no-deps --force-recreate alloy snmp_discovery
fi

echo "==> waiting for remotecfg poll…"
sleep 20
echo "==> remotecfg metrics"
curl -s http://127.0.0.1:12346/metrics | grep -E '^remotecfg_' | head -30 || true
echo "==> alloy remotecfg logs"
docker logs alloy --since 2m 2>&1 | grep -iE 'remotecfg|remote config|fleet' | tail -20 || true

echo "==> Fleet collectors (match lab=network-o11y-demo)"
python3 - <<'PY'
import json, os, urllib.request
base=os.environ["GC_FM_URL"].rstrip("/")
user=os.environ.get("GC_FM_USER") or os.environ["GC_OTLP_ACCOUNT"]
tok=os.environ.get("GC_FM_TOKEN") or os.environ["GC_OTLP_KEY"]
req=urllib.request.Request(
  base+"/collector.v1.CollectorService/ListCollectors",
  data=b"{}",
  method="POST",
  headers={"Authorization": f"Bearer {user}:{tok}", "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=30) as r:
  d=json.load(r)
for c in d.get("collectors") or []:
  attrs=c.get("attributes") or c.get("localAttributes") or {}
  if attrs.get("lab")=="network-o11y-demo" or "network-o11y" in (c.get("id") or ""):
    print(json.dumps({"id": c.get("id"), "attributes": attrs, "remoteConfigStatus": c.get("remoteConfigStatus")}, indent=2))
PY

echo "Done. UI: ${GRAFANA_URL}/a/grafana-collector-app/fleet-management"
