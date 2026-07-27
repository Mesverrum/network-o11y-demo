#!/usr/bin/env bash
# apply-north-south-flows.sh — dual softflowd (eth0+eth1) + internet probes on running lab.
exec python3 "$(dirname "$0")/apply-north-south-flows.py" "$@"
