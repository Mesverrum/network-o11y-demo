#!/usr/bin/env bash
# internet-probes.sh — occasional HTTPS probes from lab clients to the public internet.
#
# Clients reach the internet on eth0 (ContainerLab mgmt / clab bridge). Alpine softflowd
# 1.1.0 needs one process per interface — eth0 exports north-south probes, eth1 EVPN traffic.
#
# Targets: local/fixtures/internet-probe-targets.txt (host or host|pinned-ip for GeoIP variety).
# Override: INTERNET_PROBE_HOSTS=host1,host2  or  INTERNET_PROBE_TARGETS_FILE=/path
#
# Usage: ./scripts/internet-probes.sh [start|stop|status]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh" 2>/dev/null || true

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

WORKLOAD_TAG=lab-internet-probes
INTERNET_PROBE_INTERVAL_SEC="${INTERNET_PROBE_INTERVAL_SEC:-45}"
INTERNET_PROBE_TARGETS_FILE="${INTERNET_PROBE_TARGETS_FILE:-${ROOT}/fixtures/internet-probe-targets.txt}"
INTERNET_PROBE_HOSTS="${INTERNET_PROBE_HOSTS:-}"

ensure_clients() {
  for c in client1 client2; do
    docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found — deploy the lab first (make up)"
  done
}

stop_client_probes() {
  local c="$1"
  docker exec "$c" sh -c "
    pkill -f ${WORKLOAD_TAG} 2>/dev/null || true
  " >/dev/null 2>&1 || true
}

# Write probe target lines into client container (host or host|ip per line).
load_targets_into_client() {
  local c="$1"
  if [[ -n "${INTERNET_PROBE_HOSTS}" ]]; then
    docker exec "$c" sh -c ": > /tmp/${WORKLOAD_TAG}.targets"
    IFS=',' read -ra hosts <<< "${INTERNET_PROBE_HOSTS}"
    for h in "${hosts[@]}"; do
      h="${h// /}"
      [[ -n "$h" ]] || continue
      docker exec "$c" sh -c "echo '${h}' >> /tmp/${WORKLOAD_TAG}.targets"
    done
    return
  fi
  [[ -f "${INTERNET_PROBE_TARGETS_FILE}" ]] || die "missing ${INTERNET_PROBE_TARGETS_FILE}"
  docker exec -i "$c" sh -c ": > /tmp/${WORKLOAD_TAG}.targets && cat >> /tmp/${WORKLOAD_TAG}.targets" \
    < <(grep -v '^[[:space:]]*#' "${INTERNET_PROBE_TARGETS_FILE}" | grep -v '^[[:space:]]*$' || true)
}

start_on_client() {
  local c="$1"
  local offset="$2"
  load_targets_into_client "$c"
  docker exec "$c" sh -c "cat > /tmp/${WORKLOAD_TAG}.sh << 'SCRIPT'
#!/bin/sh
# ${WORKLOAD_TAG} — managed by local/scripts/internet-probes.sh
INTERVAL=${INTERNET_PROBE_INTERVAL_SEC}
OFFSET=${offset}
TARGETS=/tmp/${WORKLOAD_TAG}.targets

sleep \"\$OFFSET\"

probe_one() {
  line=\"\$1\"
  host=\"\${line%%|*}\"
  pin=\"\${line#*|}\"
  if [ \"\$pin\" = \"\$line\" ]; then
    pin=\"\"
  fi
  if [ -n \"\$pin\" ]; then
    wget -q -O /dev/null -T 20 --no-check-certificate \\
      --header=\"Host: \${host}\" \"https://\${pin}/\" >>/tmp/${WORKLOAD_TAG}.log 2>&1 || true
  else
    wget -q -O /dev/null -T 20 --no-check-certificate \\
      \"https://\${host}/\" >>/tmp/${WORKLOAD_TAG}.log 2>&1 || true
  fi
}

while true; do
  while IFS= read -r line || [ -n \"\$line\" ]; do
    line=\$(echo \"\$line\" | tr -d '\\r')
    [ -z \"\$line\" ] && continue
    probe_one \"\$line\"
    sleep \"\$INTERVAL\"
  done < \"\$TARGETS\"
done
SCRIPT
chmod +x /tmp/${WORKLOAD_TAG}.sh
: > /tmp/${WORKLOAD_TAG}.log
nohup /tmp/${WORKLOAD_TAG}.sh >/dev/null 2>&1 &
echo \"${c} internet probes started (PID \$!, offset \${offset}s, targets \$(wc -l < /tmp/${WORKLOAD_TAG}.targets))\"
"
}

start() {
  ensure_clients

  info "Stopping any previous internet probes..."
  stop_client_probes client1
  stop_client_probes client2
  sleep 1

  info "Starting HTTPS probes (mgmt eth0 -> public sites, GeoIP variety)..."
  start_on_client client1 0 | sed 's/^/  /'
  start_on_client client2 30 | sed 's/^/  /'

  if [[ -n "${INTERNET_PROBE_HOSTS}" ]]; then
    info "Targets (INTERNET_PROBE_HOSTS): ${INTERNET_PROBE_HOSTS}"
  else
    info "Targets file: ${INTERNET_PROBE_TARGETS_FILE}"
    grep -v '^[[:space:]]*#' "${INTERNET_PROBE_TARGETS_FILE}" | grep -v '^[[:space:]]*$' | sed 's/^/  /' || true
  fi
  info "Interval: ${INTERNET_PROBE_INTERVAL_SEC}s between targets (clients staggered 30s)"
  info "Stop: make internet-probes-stop   Status: make internet-probes-status"
}

stop() {
  ensure_clients
  info "Stopping internet probes..."
  for c in client1 client2; do
    stop_client_probes "$c"
    echo "  $c: stopped"
  done
  info "Internet probes stopped."
}

status() {
  ensure_clients
  info "Internet probe processes:"
  for c in client1 client2; do
    wl_n="$(docker exec "$c" sh -c "pgrep -cf ${WORKLOAD_TAG} 2>/dev/null || echo 0" 2>/dev/null || echo 0)"
    echo "  $c: workload=${wl_n}"
    docker exec "$c" sh -c "wc -l /tmp/${WORKLOAD_TAG}.targets 2>/dev/null || echo '0 targets'" | sed "s/^/    targets: /"
    docker exec "$c" sh -c "tail -n 3 /tmp/${WORKLOAD_TAG}.log 2>/dev/null || echo '  (no log yet)'" | sed "s/^/    /"
  done
  info "Quick reachability (client1 -> yandex pinned):"
  docker exec client1 wget -q -O /dev/null -T 8 --no-check-certificate \
    --header="Host: www.yandex.ru" https://77.88.55.242/ \
    && echo "  ok" || echo "  failed (check eth0 default route / edit fixtures/internet-probe-targets.txt)"
}

case "${1:-start}" in
  start)  start  ;;
  stop)   stop   ;;
  status) status ;;
  *)      echo "Usage: $0 [start|stop|status]"; exit 1 ;;
esac
