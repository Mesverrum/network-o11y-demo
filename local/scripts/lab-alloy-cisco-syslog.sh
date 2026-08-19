#!/usr/bin/env bash
# Lab: does Alloy loki.source.syslog accept Cisco-style / non-RFC syslogs?
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)" # local/
DIR="${ROOT}/fixtures/alloy-cisco-syslog"
CAPTURE="${DIR}/capture.jsonl"
METRICS_FILE="${DIR}/metrics.txt"
REPORT="${DIR}/report.md"
METRICS_URL="http://127.0.0.1:19191/metrics"
SINK_PORT=3100

mkdir -p "${DIR}"
: >"${CAPTURE}"
: >"${METRICS_FILE}"

cleanup() {
  [[ -n "${SINK_PID:-}" ]] && kill "${SINK_PID}" 2>/dev/null || true
  docker rm -f alloy-cisco-syslog-test >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Loki push sink :${SINK_PORT}"
python3 "${DIR}/loki_sink.py" "${CAPTURE}" "${SINK_PORT}" &
SINK_PID=$!
sleep 1

echo "==> Alloy (experimental) — 4 UDP syslog listeners"
docker rm -f alloy-cisco-syslog-test >/dev/null 2>&1 || true
docker run -d --name alloy-cisco-syslog-test --network host \
  -v "${DIR}/config.alloy:/etc/alloy/config.alloy:ro" \
  grafana/alloy:latest \
  run /etc/alloy/config.alloy \
  --server.http.listen-addr=0.0.0.0:19191 \
  --stability.level=experimental \
  >/dev/null

for _ in $(seq 1 40); do
  if curl -sf "${METRICS_URL}" | grep -q loki_source_syslog; then
    break
  fi
  sleep 1
done
if ! curl -sf "${METRICS_URL}" | grep -q loki_source_syslog; then
  echo "FAIL: Alloy metrics not ready"
  docker logs alloy-cisco-syslog-test 2>&1 | tail -60
  exit 1
fi
echo "Alloy ready: $(docker inspect -f '{{.Config.Image}}' alloy-cisco-syslog-test)"

send_udp() {
  local port="$1"
  local msg="$2"
  printf '%s' "${msg}" >/dev/udp/127.0.0.1/"${port}" 2>/dev/null \
    || printf '%s' "${msg}" | nc -u -w1 127.0.0.1 "${port}" || true
}

SAMPLES=(
  '<34>Oct 11 22:14:15 switch1 LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up'
  '<187>Apr  8 10:15:22: %SYS-5-CONFIG_I: Configured from console by vty0 (10.1.1.50)'
  '<189>Apr  8 10:15:22 router1: %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/0, changed state to down'
  '<189>92: *Apr  8 10:15:22.483: %SYS-5-CONFIG_I: Configured from console by console'
  '<189>12345: 67890: core-sw1: *Apr  8 10:15:22.483 UTC: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/1, changed state to up'
  'CEF:0|Cisco|ASA|9.0|302013|Teardown TCP|6|src=10.0.0.1 dst=10.0.0.2'
  '<165>1 2026-04-08T10:15:22.483Z web01 nginx - - - login failed for user admin'
)

echo "==> sending ${#SAMPLES[@]} samples × 4 modes"
for msg in "${SAMPLES[@]}"; do
  for port in 15140 15141 15142 15143; do
    send_udp "${port}" "${msg}"
  done
  sleep 0.2
done
sleep 3

curl -sf "${METRICS_URL}" >"${METRICS_FILE}"
echo "==> capture lines=$(wc -l <"${CAPTURE}")"
python3 "${DIR}/score_results.py" "${CAPTURE}" "${REPORT}" "${METRICS_FILE}"
echo "DONE report=${REPORT}"
