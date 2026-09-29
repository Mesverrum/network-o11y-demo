#!/usr/bin/env bash
set -euo pipefail
cd "${HOME}/ktranslate-pr939"
git diff -- pkg/util/rule/rule.go pkg/kt/device_types.go pkg/kt/snmp.go
