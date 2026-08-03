#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
find . \( -name '*.sh' -o -name '*.env' -o -name '*.env.sample' -o -name 'Makefile' -o -name '*.tmpl' \) \
  -print0 | xargs -0 sed -i 's/\r$//'
bash scripts/ensure-snmp-groups.sh
bash scripts/generate-groups.sh
PRIMARY="$(bash -c 'source scripts/snmp-group-utils.sh; primary_snmp_group .')"
echo "--- compose-groups head ---"
head -50 compose-groups.generated.yaml
echo "--- poller ---"
head -25 "config/poller-${PRIMARY}.yaml"
echo "--- discovery ---"
head -30 "config/discovery-${PRIMARY}.yaml"
