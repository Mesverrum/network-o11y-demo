# Alloy scale bench (2026-09-09)

Image `srl-local/alloy:network-dev` · `GOMAXPROCS=1` · `--cpus=1` · localhost WSL Docker.

Re-run: `bash local/scripts/run-alloy-scale-bench.sh --devices 100 --snmp-settle 90`

## SNMP — 100 × 48-port stand-ins

Simulator answers IF-MIB + `device_base` (hot) and `if_mib_meta` (cold) on `127.0.0.1:16101+`. No SNMP timeout, no WAN.

| | Lab |
|--|--|
| Devices / interfaces | 100 / 4800 |
| Peak CPU (docker stats) | **0.12 core** (12%) |
| Average CPU over the window | 0.02 core |
| RSS | **101–264 MiB** (~2.6 MiB/device including ~200 MiB Alloy idle) |
| Implied at peak | **~800 devices / core** or **~39k interfaces / core** |
| Implied RAM | **~400 devices / GiB** after idle baseline |

Real gear that sits on `timeout_ms`, or a chassis with thousands of ifIndex rows, eats this faster. Planning numbers in the public guide are **half** of the lab peak.

## Events / second (one core, decode + local OTLP HTTP)

| Lane | Lab result |
|------|------------|
| Syslog (`otelcol.receiver.syslog`, `protocol=none`) | **3200/s** no loss; **6400/s** ~0.4% miss; **12800/s** ~5% miss, 0 refuse |
| SNMP traps | Counters did not move on a net-snmp `linkDown` replay — not a measured ceiling |
| NetFlow records | Harness not isolated this run |

Syslog is cheap UDP + a small parse. Use **2000 events/s per core** as the conservative syslog number (same order as upstream ktranslate ~2000/s). Traps and flow decode are heavier; until the next bench, plan **1000/s per core** each (ktranslate’s conservative column).
