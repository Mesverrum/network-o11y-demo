# ktranslate customer demo — SE talk track

**Stack:** [networko11ydev.grafana.net](https://networko11ydev.grafana.net/)  
**Story:** network telemetry in Grafana Cloud *today*, before a first-party Network product.  
**Length:** 15 minutes. If the conversation goes deep (custom MIBs, NCM, a full migration plan), stop and pull in **Marc Netterfield** and **Colin**.

Stay on the links below. Do not wander the folder tree.

---

## Before you join

Open these in tabs. Time range **Last 3 hours**.

| Stop | Link |
|------|------|
| Architecture | https://networko11ydev.grafana.net/d/ktranslate-architecture |
| Device Summary | https://networko11ydev.grafana.net/d/ktranslate-device-summary |
| Device Details | https://networko11ydev.grafana.net/d/ktranslate-device-details |
| Flow Summary | https://networko11ydev.grafana.net/d/ktranslate-flow-summary |
| NetPath stand-in | https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294 |

Confirm Summary has devices and numbers. If a board is empty, you are on the wrong dashboard or the wrong time range.

---

## Open

Apps and the network still live in different tools. When checkout is slow, two teams open two consoles and argue. This demo puts device health, port traffic, routing, syslog, and “who talked to whom” in the **same Grafana Cloud stack** as traces and logs.

---

## Click path

### Architecture (~1 min)

Point at the picture.

Devices already speak SNMP (we ask for counters), NetFlow/sFlow (conversation receipts), and syslog/traps (the box pushes an event). **ktranslate** translates that to OTLP. Grafana Cloud stores it. Same backend as APM — no second NMS, no per-node licence tax.

First-party Network o11y is on the roadmap. This path stays valid because the contract is OTLP.

### Device Summary (~5 min) — the wallboard

Walk the tabs. Do not scroll at random.

| Tab | Line |
|-----|------|
| **Overview** | How many boxes, are we still polling them, what is already sick. |
| **Traffic** | Who is using bandwidth. |
| **Resources** | CPU and memory — same language as hosts, on the switch. |
| **Interfaces** | Every network ticket: a port is down or an error counter is climbing. |
| **Routing** | BGP = how routers stay neighbors. A down session is a path problem, not an app bug. |
| **Events** | The device yelled. Metrics are the trend; events are the moment. |

Click a device name. That drill-down is the demo.

### Device Details (~4 min)

Overview, then **Interfaces**. If Routing has rows, show one neighbor.

“Ticket says this box is sad. One board: CPU, ports, errors, events. Grafana already graphs, alerts, and drills. We did not invent a second UI.”

### Flow Summary (~3 min)

Conversations, then Sankey. Skip the world map if it is empty — internal IPs have no country. That is normal.

“SNMP is the box. Flow is the conversation. Together they end the app-vs-network argument.”

### Close

Same alerts, same Explore, same Assistant as the app stack. You page a switch the way you page a service.

---

## Words

| They say | You say |
|----------|---------|
| SNMP | We ask each device for counters — CPU, ports, BGP. |
| Trap / syslog | The device pushes an event: link down, neighbor lost, config change. |
| NetFlow / NTA | A receipt: who talked to whom, how many bytes. |
| Interface | A port on the box. |
| BGP | How routers stay neighbors. |
| NetPath | A repeating traceroute from a probe you place. That is Synthetic Monitoring. |
| NPM | Device and interface health — Summary + Details. |
| NMS | Their current network monitor (usually SolarWinds). |

---

## If they name a SolarWinds module

| They have | Show | One line |
|-----------|------|----------|
| **NPM** | Summary + Details | Device and port health in Grafana. |
| **NTA** | Flow Summary | Same UI, not a second licence. |
| **Log Analyzer / Kiwi / traps** | **Events** tab | Logs next to the metric, same time picker. |
| **NetPath / IP SLA ping** | [Synthetics traceroute](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294) | Hop path from Ohio and North Virginia to `grafana.com`. |
| **Advanced Alerts** | Grafana Alerting | Same rules language as the dashboard. IRM if they want on-call. |
| **PerfStack** | Explore or dashboard variables | Overlay whatever they click. |
| **IPAM / NCM / SAM / wireless** | Do not demo it | Separate workstream. Bring Marc and Colin. |

---

## Customer asks (keep it short)

**“Is this Kentik?”**  
ktranslate is open. Grafana Cloud is the backend. You are not selling a Kentik licence.

**“When is Grafana’s own network product?”**  
On the roadmap. Use this until then. You are not installing a dead-end collector.

**“Cisco / Arista / Fortinet / Palo?”**  
Yes. Each platform has an SNMP profile. This demo happens to be live switches, not screenshots. Odd or old gear may need a profile — that is implementation, not a new product.

**“UnDPs?”**  
Custom OIDs become a profile + a Grafana panel, once, for every box of that type.

**“We poll every 5 minutes. Can you go faster?”**  
Yes. These boards update about every minute. Going much faster can hurt the device. For “it just broke,” use traps/syslog (push), not a faster poll.

**“Interface util / errors / discards?”**  
Summary → Interfaces, then Details → Interfaces. Same counters they know, next to that device’s syslog.

**“Fans / PSU / temperature?”**  
Hardware tab when the vendor profile has those sensors. Missing on a given box means that MIB is not there — not that Grafana is broken.

**“BGP dropped at 14:32?”**  
Routing tab for session state. Events tab for the syslog in the same window.

**“Where is NetPath?”**  
Open the [traceroute check](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294). That is NetPath: a probe, hops, latency. Private probes in *their* sites are the equivalent of NetPath agents. Flow Sankey is NTA (who talked), not hops.

**“Top talkers?”**  
Flow → Conversations / Sankey.

**“Trap storms / parent-child alerts / unmanage?”**  
Traps are logs; alert on rate and inhibit children when the parent link is down. Silences cover maintenance. Grafana Alerting, not an Orion calendar clone.

**“Site / role / custom properties?”**  
Labels on the series (and later NetBox). Not a field typed into the NMS that goes stale.

**“We can’t turn NPM off.”**  
Don’t. Run in parallel. Add 10–20 devices, compare, then expand. Cut over module by module (flows and logs first). Frame it as adding capability.

**“How is this better? Our dashboards are already green.”**  
One pane with apps. Correlation without copying timestamps. Consumption pricing instead of per-interface elements. Skills that transfer off the NMS. Use **their** renewal quote with a Cloud AE — not blog ranges.

---

## When to call Marc and Colin

Anything past the click path: full SolarWinds replacement plan, NCM/IPAM, wireless/SD-WAN/voice, custom MIB farms, collector sizing, or “import our 400 Advanced Alerts.” Take the note, book the specialist, do not invent a demo.
