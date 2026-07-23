#!/bin/sh
# Flex-style gap-fill PoC: SSH to devices, parse CLI output, emit Prometheus text.
#
# nri-flex runs remote commands and parses in YAML (jq, split, regex). Telegraf
# inputs.exec expects the script to print valid exposition format — so this
# script owns SSH + parse; Telegraf ships the result over OTLP.
#
# Lab: ContainerLab SR Linux defaults (admin / NokiaSrl1!) on clab DNS names.

set -eu

USER="${SRL_SSH_USER:-admin}"
PASS="${SRL_SSH_PASSWORD:-NokiaSrl1!}"
TESTER="${LAB_TESTER_ID:-network-lab}"
COLLECTOR="telegraf-flex-poc"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8"

ssh_run() {
  host=$1
  shift
  sshpass -p "$PASS" ssh $SSH_OPTS "${USER}@${host}" "$@"
}

echo "# HELP srl_flex_poc_ssh_up SSH session to device succeeded (Flex SSH PoC)"
echo "# TYPE srl_flex_poc_ssh_up gauge"
echo "# HELP srl_flex_poc_bgp_peers_up BGP peers in established state (parsed from SSH JSON)"
echo "# TYPE srl_flex_poc_bgp_peers_up gauge"

for dev in spine1 leaf1 leaf2; do
  json=""
  if json=$(ssh_run "$dev" 'show network-instance default protocols bgp neighbor | as json' 2>/dev/null); then
    ssh_up=1
    peers_up=$(printf '%s' "$json" | jq '[."neighbor summary"[0].state[]? | select(.State == "established")] | length' 2>/dev/null || echo 0)
    peers_up="${peers_up:-0}"
  else
    ssh_up=0
    peers_up=0
  fi
  echo "srl_flex_poc_ssh_up{device=\"$dev\",tester_id=\"$TESTER\",collector=\"$COLLECTOR\",transport=\"ssh\"} $ssh_up"
  echo "srl_flex_poc_bgp_peers_up{device=\"$dev\",tester_id=\"$TESTER\",collector=\"$COLLECTOR\",transport=\"ssh\",source=\"sr_cli_json\"} $peers_up"
done
