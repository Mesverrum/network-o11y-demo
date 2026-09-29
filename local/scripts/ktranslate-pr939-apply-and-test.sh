#!/usr/bin/env bash
set -euo pipefail
WIN="/mnt/c/Users/mesve/projects/network-o11y-demo/local/scripts"
python3 "$WIN/ktranslate-pr939-apply-guards.py"
sed 's/\r$//' "$WIN/ktranslate-pr939-user_device_rule_test.go" > "${HOME}/ktranslate-pr939/pkg/util/rule/user_device_rule_test.go"
cd "${HOME}/ktranslate-pr939"
go test ./pkg/util/rule/ ./pkg/kt/ ./pkg/inputs/snmp/metadata/ -count=1
