#!/usr/bin/env bash
# Port + dest helpers for Alloy trap/syslog next to ktranslate.
# Same host cannot bind :1620/:1514 twice. Dual-write uses :11620/:1515
# (not :1621 — that is ktranslate srl-branch1 TRAP_PORT).
# shellcheck shell=bash

lab_flag_on() {
  case "${1:-0}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

lab_ktranslate_on() {
  lab_flag_on "${LAB_KTRANSLATE:-1}"
}

alloy_trap_listen_port() {
  if [[ -n "${LAB_ALLOY_SNMPTRAP_PORT:-}" ]]; then
    echo "${LAB_ALLOY_SNMPTRAP_PORT}"
    return
  fi
  if lab_ktranslate_on; then
    echo 11620
  else
    echo 1620
  fi
}

alloy_syslog_listen_port() {
  if [[ -n "${LAB_ALLOY_SYSLOG_PORT:-}" ]]; then
    echo "${LAB_ALLOY_SYSLOG_PORT}"
    return
  fi
  if lab_ktranslate_on; then
    echo 1515
  else
    echo 1514
  fi
}

# SRL remote-server is keyed by address. Same IP + two ports will collide, so
# colocated hostNetwork gets a second address on the clab bridge.
ensure_alloy_events_alias_ip() {
  local primary="${1:-}"
  local alias="${ALLOY_EVENTS_ALIAS_IP:-}"
  local dev=""
  if [[ -z "${alias}" && -n "${primary}" ]]; then
    alias="${primary%.*}.253"
  fi
  alias="${alias:-172.20.20.253}"
  export ALLOY_EVENTS_ALIAS_IP="${alias}"
  if [[ -n "${primary}" ]]; then
    dev="$(ip -o addr show 2>/dev/null | awk -v ip="${primary}" '$0 ~ ("inet " ip "/") {print $2; exit}')"
  fi
  if [[ -n "${dev}" ]] && ! ip -o addr show dev "${dev}" 2>/dev/null | grep -q "inet ${alias}/"; then
    ip addr add "${alias}/24" dev "${dev}" 2>/dev/null || true
  fi
  echo "${alias}"
}
