#!/usr/bin/env bash
# Run alloy-scale-bench.py from the Windows tree via WSL (/mnt/c is OK — no clab).
set -euo pipefail
SRC="/mnt/c/Users/mesve/projects/network-o11y-demo/local"
DST="/tmp/alloy-scale-src"
mkdir -p "$DST/scripts" "$DST/fixtures/alloy-snmp/modules/_general"
cp -f "$SRC/scripts/alloy-scale-bench.py" "$DST/scripts/"
cp -f "$SRC/fixtures/alloy-snmp/modules/_general/device_base.yml" "$DST/fixtures/alloy-snmp/modules/_general/"
cp -f "$SRC/fixtures/alloy-snmp/modules/_general/if_mib.yml" "$DST/fixtures/alloy-snmp/modules/_general/"
cp -f "$SRC/fixtures/alloy-snmp/modules/_general/if_mib_meta.yml" "$DST/fixtures/alloy-snmp/modules/_general/"
sed -i 's/\r$//' "$DST/scripts/alloy-scale-bench.py"
export ALLOY_IMAGE="${ALLOY_IMAGE:-srl-local/alloy:network-dev}"
python3 "$DST/scripts/alloy-scale-bench.py" "$@"
WIN="$SRC/fixtures/alloy-scale-bench"
mkdir -p "$WIN"
cp -f /tmp/alloy-scale-bench/report.json /tmp/alloy-scale-bench/report.md "$WIN/" 2>/dev/null || true
echo "copied report to $WIN"
