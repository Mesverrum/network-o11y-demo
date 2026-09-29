#!/usr/bin/env bash
set -euo pipefail
cd "${HOME}/ktranslate-pr939"
go test ./pkg/util/rule/ -count=1 -v \
  -run 'TestLookup|TestEmpty|TestBlank|TestCIDR|TestIPv6|TestNumeric|TestNested|TestSnmp|TestWhitespace|TestDevice|TestGetUser'
go test ./pkg/util/rule/ -count=50 -run TestCIDRLongestPrefixWins
