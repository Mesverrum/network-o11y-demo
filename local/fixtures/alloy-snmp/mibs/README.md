# Curated MIBs for `loki.source.snmptrap`

Small IETF set only (SNMPv2-SMI/TC/MIB + IF-MIB). **Do not** dump distro or Cisco mega-trees here — gosmi can hang.

Populate with:

```bash
bash local/scripts/stage-alloy-mibs.sh
```

Compose mounts this directory at `/etc/alloy/mibs`. Trap receive works with an empty dir (numeric OIDs).
