#!/usr/bin/env bash
# Copy a small curated MIB set into fixtures/alloy-snmp/mibs for otelcol.receiver.snmptrap.
# Prefer distro net-snmp files; never dump the whole tree (gosmi hangs on mega-sets).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${ROOT}/fixtures/alloy-snmp/mibs"
mkdir -p "${DEST}"

# IETF / IF-MIB — enough to name coldStart/linkDown and ifIndex varbinds.
WANTED=(
  SNMPv2-SMI
  SNMPv2-TC
  SNMPv2-CONF
  SNMPv2-MIB
  IANAifType-MIB
  IF-MIB
)

SRC_DIRS=(
  /usr/share/snmp/mibs
  /usr/share/mibs/ietf
  /usr/share/mibs/iana
  /var/lib/snmp/mibs/ietf
)

copied=0
for name in "${WANTED[@]}"; do
  [[ -f "${DEST}/${name}" || -f "${DEST}/${name}.txt" ]] && continue
  for dir in "${SRC_DIRS[@]}"; do
    [[ -d "${dir}" ]] || continue
    for cand in "${dir}/${name}" "${dir}/${name}.txt" "${dir}/${name}.mib"; do
      if [[ -f "${cand}" ]]; then
        cp -f "${cand}" "${DEST}/${name}"
        copied=$((copied + 1))
        break 2
      fi
    done
  done
done

n="$(find "${DEST}" -type f ! -name 'README.md' ! -name '.gitkeep' | wc -l | tr -d ' ')"
echo "==> alloy mibs in ${DEST} (files=${n} newly_copied=${copied})"
