# End recap: NetBox × Grafana Cloud (live PoC)

**Audience:** Logan / Raj  
**Context:** Live PoC on colocated lab + Device Details enrichment boards — not a doc-only review.

## Bottom line

NetBox integration **closes a real Grafana Cloud gap**: inventory / source-of-truth context next to live device telemetry. It does **not** make network observability “done.” Most of what Device Details needs for *health* still has to come from a collector — and **today’s Alloy SNMP path does not cover that well**. NetBox makes that hole more visible, not smaller.

## What we proved (product-relevant)

We stood up NetBox (discovery in → CMDB), joined **live** NetBox REST (Infinity `netbox-api`) into Device Details next to SNMP — not a Grafana-side inventory history store:

- **Overview** — site, role, status, manufacturer/platform, tags, NetBox ID next to device identity
- **Interfaces** — planned type / enabled / description / IP count / cable id on the **same rows** as live oper & traffic
- Deep links into NetBox UI

**Demo point:** SoT + live in one table is the money shot. Customers will ask for that join the moment NetBox is connected.

Dashboard (lab): [25. Device Details + NetBox SoT](https://marcnetterfield1.grafana.net/d/ktranslate-device-details-netbox)  
Tab order: Overview → … → Telemetry → **NetBox SoT** (talk-track last).

## Gaps NetBox closes for Grafana Cloud users

What they **do not** get from Alloy SNMP scrape alone:


| Closed by NetBox            | Example                                                |
| --------------------------- | ------------------------------------------------------ |
| Canonical CMDB identity     | Site, role, lifecycle status, manufacturer, tags       |
| Planned interface inventory | Type, description, enabled, IPAM count, cable intent   |
| Intent vs observation       | “Should be WAN to leaf1” vs “oper up / bps”            |
| Operator deep links         | Jump to device / interfaces / IPAM in NetBox           |
| Discovery → SoT pipeline    | Automated inventory reconcile (vs spreadsheet targets) |


**One-liner:** NetBox answers *what is this / where does it live / how should it be wired*. Scraped SNMP answers *is it healthy / how busy* — only if the collector actually produces that health data.

## Gaps users still own (NetBox will not solve)


| Still on the customer (or on us in product)                  | Why it matters                                                                                                   |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| Continuous SNMP **health** metrics                           | CPU, memory, iface counters/errors, sensors, BGP/neighbor state — Device Summary/Details stay dark without these |
| **Traps + syslog**                                           | Event path for flaps/faults; not a NetBox problem                                                                |
| **Flow** (conversation / top talkers as used in flow boards) | Edge PCAP/DNS analytics ≠ flow rollups for traffic boards                                                        |
| Streaming **gNMI**-class telemetry (optional but common)     | Change-driven CMDB sync ≠ streaming BGP/LLDP metrics                                                             |
| Name hygiene for joins                                       | `device` / iface names must match SoT or enrichment is empty                                                     |
| Cable/circuit depth                                          | Only as good as what they model in NetBox                                                                        |




## What we need in Alloy (the ask — lead with this)

Framed as if there is no third-party collector in the story: a Grafana-native network path is Alloy + OTEL + dashboards + (now) NetBox. After this PoC, the missing Alloy investments are obvious:

1. **SNMP health depth** — multi-vendor coverage beyond basic IF-MIB; profiles that light a decent Device Details dashboard (CPU/mem/sensors/control-plane), not just scrapable counters
2. **Traps (+ syslog story)** — first-class event ingest aligned with the same device identity NetBox joins on
3. **Flow model for traffic boards** — conversation-oriented metrics (or a clear supported substitute), not only edge analytics
4. **NetBox → Alloy target sync** — SoT-driven scrape inventory (devices/IPs/credentials references) so NetBox isn’t only a dashboard enrichment
5. **Stable join labels** — `device_name` / interface name (and optional `netbox_id`) consistent across SNMP, events, and SoT so the Overview/Interfaces join pattern is productizable

NetBox without (1)–(3) = pretty CMDB next to empty or thin health panels.  
Alloy without NetBox = live numbers with no intent/CMDB.  
**Both** are required for the story we showed.

## Partner pieces (keep short)

- **Orb / discovery → NetBox** — strong for inventory SoT (this PoC).
- **pktvisor** — edge PCAP/DNS analytics; complementary, not a substitute for SNMP health or flow boards.
- Neither replaces a full network health + events + traffic collector stack inside Grafana Cloud.



## Optional gap-closer (end only)

Until Alloy covers the health/events/flow gaps above, teams can bridge with an external SNMP/flow/syslog collector (e.g. **ktranslate**) exporting OTLP into Alloy, and keep NetBox as the SoT join — which is what this lab used to prove the **dashboard pattern**. That is a **workaround**, not the desired end state; the product investment is closing those gaps **in Alloy** (and first-class NetBox sync), so customers are not told to assemble a side collector to make Device Details real.

## Ask of Raj

1. Treat NetBox as **standard enrichment + discovery SoT**, green-lit.
2. Fund Alloy work on **SNMP depth, traps/syslog, flow-for-boards, NetBox target sync, join labels** — this PoC is the customer-visible proof of what’s missing.
3. Do not position “NetBox connected” as network o11y complete.



## Related lab notes

- Enrichment map / join details: `[local/docs/device-details-netbox-enrichment.md](../local/docs/device-details-netbox-enrichment.md)`
- NetBox colocated bring-up: `[local/netbox/README.md](../local/netbox/README.md)`
- Orb: `[local/orb/README.md](../local/orb/README.md)`

