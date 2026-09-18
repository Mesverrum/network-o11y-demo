# ktranslate customer demo — SE talk track

**Audience:** Grafana SEs who are not network engineers, running a customer demo on [networko11ydev.grafana.net](https://networko11ydev.grafana.net/).

**Stack:** ktranslate → OTLP → Grafana Cloud. This is the path customers can run **today**, before a first-party Network Observability product ships.

**Duration:** 15–20 minutes for the click path. Use the Q&A below when a network team (usually a SolarWinds shop) starts asking operational questions.

**Related reading in this repo**

| Doc | Use when |
|-----|----------|
| [Network observability primer](network-observability-primer.md) | Vocabulary, signal types, why the silo hurts |
| [Blog series overview](../blog/blog-series-overview.md) | SolarWinds → open-stack narrative |
| [The case against SolarWinds](../blog/10_drafts/blog-post-01-the-case.md) | Cost, trust, “built for a different era” |
| [The open stack](../blog/10_drafts/blog-post-02-the-stack.md) | NPM / NTA / Log Analyzer / IPAM / NCM map |
| [Observability with Grafana](../blog/10_drafts/blog-post-05-grafana.md) | One UI vs four consoles |
| [TCO and migration](../blog/10_drafts/blog-post-07-migration.md) | Parallel run, cutover order, honest gaps |
| [ktranslate unified model](ktranslate-unified-model.md) | How collectors are actually deployed |

Do **not** open the [Alloy Network Fork](https://networko11ydev.grafana.net/dashboards/f/fb9d2s/alloy-network-fork) folder (`A0`–`A4`, `snmp_*` metrics). That is the in-progress first-party path. If a title starts with Alloy, go back.

---

## Before the call (2 minutes)

1. Open these four tabs. Time range **Last 3 hours** on each (not Last 5 minutes — SNMP polls every 60s).
2. Confirm Device Summary lists `spine1`, `leaf1`, `leaf2`. If it is empty, you are on the Alloy folder or the wrong range — fix that before they join.

| # | Dashboard | Link |
|---|-----------|------|
| 00 | Ktranslate Architecture | https://networko11ydev.grafana.net/d/ktranslate-architecture |
| 01 | Ktranslate Health | https://networko11ydev.grafana.net/d/ktranslate-health |
| 03 | Network Device Summary | https://networko11ydev.grafana.net/d/ktranslate-device-summary |
| 04 | Network Device Details | https://networko11ydev.grafana.net/d/ktranslate-device-details?var-instance=leaf1 |
| 02 | Network Flow Summary | https://networko11ydev.grafana.net/d/ktranslate-flow-summary |

Folder: [ktranslate (`fxgv9q`)](https://networko11ydev.grafana.net/dashboards/f/fxgv9q)

If `snmp_group` is on the board, the live Clos story is `srl-hq`, `srl-branch1`, `srl-branch2`. Leave **campus** alone — vendor extras, often empty, looks broken.

---

## The one-sentence open

Applications and the network still live in different tools. When checkout is slow, two teams open two consoles and argue. This demo puts device health, port traffic, routing, syslog/traps, and “who talked to whom” into the **same Grafana Cloud stack** as traces and logs — using an open collector they can deploy before a first-party Network product exists.

---

## What the live lab is

A small multi-site fabric in AWS, not screenshots. HQ plus two branches. Clients generate traffic. Collectors poll SNMP every 60 seconds and ingest NetFlow, sFlow, syslog, and traps.

| Name | Role | Plain English |
|------|------|---------------|
| `spine1` | HQ backbone | The core switch the sites hang off |
| `leaf1` / `leaf2` | HQ access | Where servers or clients plug in |
| `leaf-br1` / `leaf-br2` | Branch edges | The remote-office switches |

---

## Click path (15–20 min)

### 0:00 — Open

**Say:** “When checkout is slow, two teams open two consoles and argue. We are going to look at the network the same way you already look at apps — dashboards, alerts, Explore — without buying a second NMS.”

### 0:30 — 00. Architecture

**Click:** the architecture pictures, not the long text.

**Say:**

- Devices already speak **SNMP** (we ask the box for counters), **NetFlow/sFlow** (receipts for conversations), and **syslog/traps** (the box pushes an event).
- **ktranslate** is the open translator. A small **Alloy** agent only forwards OTLP into Grafana Cloud. You do not stand up Prometheus or Loki next to the collector.
- Discovery finds devices; a poller keeps walking them. Flow and syslog reuse the **same `device_name`**, so a CPU spike and a conversation share an identity.

**Highlight:** no lock-in, no per-node licence tax, same backend as APM. First-party Network o11y is on the roadmap. This pattern stays valid after, because the contract is OTLP.

**Do not say:** “Alloy fork,” `snmp_*`, “we are building the product on this stack.”

### 2:00 — 01. Health (90 seconds)

**Click:** glance at SNMP vs flow collectors (`ktranslate-snmp-*`, `ktranslate-flow-*`). Leave.

**Say:** “Before we trust the fleet, we prove the pipeline is alive. Collector health is a first-class service here. Vendor NMS often hides a dead poller behind ‘device down.’”

Skip CHF / jchf / `snmp_fail` codes unless they ask.

### 4:00 — 03. Device Summary (main stop)

This is the NOC wallboard. Walk the tabs; do not scroll randomly.

| Tab | What to show | Line |
|-----|--------------|------|
| **Overview** | Device count, polling health, active conditions | “How many boxes, are we still polling them, what is already sick.” |
| **Traffic** | Stacked bps | “Who is using the fabric right now.” |
| **Resources** | CPU / memory | “Same resource language as hosts — on the switch.” |
| **Interfaces** | Up/down, errors, hot ports | “This is every network ticket: a port or an error counter.” |
| **Routing** | BGP neighbors | “How routers stay neighbors. A down session is a path problem, not an app bug.” |
| **Events** | Syslog / traps | “The device yelled. Metrics show the trend; events show the moment.” |

**The demo click:** click a device name (`leaf1` or `spine1`) so it drills to Details.

### 10:00 — 04. Device Details

**Click:** set `instance` = `leaf1` (or arrive via the Summary drill). Overview, then **Interfaces**. If Routing/BGP has rows, show one established neighbor. Skip empty hardware-sensor sections — they hide when that MIB is absent.

**Say:** “Ticket says leaf1 is sad. One board, one box: CPU, ports, errors, events. Grafana already knows how to graph, alert, and drill. We did not invent a second UI.”

### 14:00 — 02. Flow Summary

**Click:** scroll rows (not tabs): **Devices → Applications → Conversations → Sankey**. Geo / Country only if public countries appear. East-west lab traffic is private IP — the world map can look empty. That is expected; say so.

**Say:** “SNMP answers ‘is the switch healthy?’ Flow answers ‘which clients and apps used the path?’ Together they end the app-vs-network argument.”

### 18:00 — Close

**Say:** “Same alerts, same Explore, same Grafana Assistant as the app stack. You can page the same way you page a service. When first-party Network lands, this OTLP path does not get thrown away.”

If a network alert is firing, show it. If not, do not apologize — a healthy lab is a feature.

---

## Words you can use

| Word they will say | Say instead |
|--------------------|-------------|
| SNMP | We ask each device for counters every minute — CPU, ports, BGP. |
| Trap | The device pushes a structured alert: link down, neighbor lost. |
| Syslog | The device’s diary — config change, auth failure, BGP notification. |
| NetFlow / sFlow / IPFIX | A receipt for each conversation: who, where, how many bytes. |
| Interface | A port on the box. |
| Oper down / admin down | The port is dead vs someone turned it off on purpose. |
| BGP | How routers tell each other they are still neighbors. |
| Polling health | Did the collector hear back from this device? |
| MIB / profile | The dictionary that says “this Cisco / Nokia / Arista exposes these counters.” |
| ktranslate | Open collector that turns those protocols into OTLP. |
| NMS | Network Management System — SolarWinds NPM, vendor GUI, etc. |

---

## SolarWinds product map (what they have → what you open)

Network teams rarely say “observability.” They name **modules**. Use this table to translate.

| They say | What it is | In this demo | Broader Grafana story (not this click path) |
|----------|------------|--------------|-----------------------------------------------|
| **NPM** | Device + interface SNMP, node details | 03 Summary + 04 Details | Same Grafana Cloud as apps |
| **NTA** | NetFlow / sFlow traffic analysis | 02 Flow Summary | Same UI — not a second licence |
| **Log Analyzer / Kiwi** | Syslog search | Summary / Details **Events** tab | Loki in the same stack |
| **Traps** | Device-pushed SNMP alerts | Events tab (same poller listens on UDP 162) | Loki, not a CHF-only story |
| **Network Atlas** | Topology map | Do not fake a full Atlas clone here | Topology / NetBox maps in the lab; say “inventory + LLDP,” not “we replaced Atlas on this tab” |
| **NetPath** | Periodic traceroute / hop movie to a SaaS or site | [se-demo-netpath-traceroute](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294) | Public Ohio + North Virginia → `grafana.com`. Same job as NetPath. Not Flow Sankey. |
| **PerfStack** | Ad-hoc multi-metric overlay | Explore, or dashboard variables | Same PromQL language as app metrics |
| **Advanced Alerts** | Rule engine + email / trap | Grafana Alerting (`category=network`) | IRM for on-call |
| **Custom properties / node groups** | Site, role, tier tags inside Orion | `tags_snmp_group`, `provider`, `device_name` | NetBox as SoT — [blog post 4](../blog/10_drafts/blog-post-04-netbox.md) |
| **IPAM** | IP / subnet inventory | Not this demo | NetBox |
| **NCM** | Config backup, drift, compliance | Not this demo | Ansible + Git + NetBox — [blog post 6](../blog/10_drafts/blog-post-06-ansible.md) |
| **UnDP** | Custom SNMP poller for a weird OID | SNMP profiles (`sysObjectID` → YAML) | Contribute a profile; do not hand-maintain a snowflake |
| **Polling engines** | Extra Windows boxes as you scale | ktranslate **groups** + more collector hosts | Linux / container, not Windows + SQL |
| **Elements** | Licence unit (node, interface, volume, flow) | Consumption (series + log volume) | [Migration post](../blog/10_drafts/blog-post-07-migration.md) |

---

## Customer asks

Each item is: **what they say**, **what they actually mean** (for SEs who have never sat a NOC shift), **what to show**, **what to say**, and **do not oversell**.

### “Is this Kentik? Are we buying another vendor?”

**What they mean:** ktranslate started at Kentik. They have been burned by “open” tools that become a licence.

**Show:** Architecture (00).

**Say:** ktranslate is open. The dashboards are the community [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) set. Grafana Cloud is the backend. You are not selling a Kentik licence. The northbound contract is OTLP — the same protocol their app teams already use.

### “When is Grafana’s own network product?”

**What they mean:** They do not want to migrate twice.

**Show:** Stay on ktranslate boards.

**Say:** First-party Network o11y is on the roadmap. Recommend this pattern until then. It stays valid after because devices still speak SNMP / flow / syslog, and Grafana still stores OTLP. You are not installing a dead-end collector.

### “Will it do Cisco / Arista / Juniper / Fortinet / Palo?”

**What they mean:** This lab is Nokia. They assume it is a Nokia-only toy.

**Show:** Device Summary Overview — fleet breakdown (provider / model) if populated. Do not click `campus` unless you have confirmed those series are alive.

**Say:** Yes. Discovery matches `sysObjectID` to an SNMP **profile**. This live fabric is Nokia SR Linux so the demo stays honest. Their gear is a profile, not a Grafana rewrite. Missing platform → [profile tutorial](https://github.com/kentik/ktranslate/wiki/Tutorial:-Writing-a-custom-yaml-file-for-SNMP) and a PR to [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles).

**Do not say:** “Every MIB SolarWinds has is already here.” Old or rare platforms may need a profile. That is a week of work, not a product purchase.

### “We have UnDPs for vendor-specific OIDs.”

**What they mean:** SolarWinds Universal Device Poller. Someone hand-built charts for “this weird temperature OID on the old chassis.” They are afraid of losing tribal polls.

**Show:** Device Details — rows that appear only when the profile has the metric (`has_*` gates). Empty sections hiding is the feature.

**Say:** Those UnDPs become metrics on a profile, then normal Grafana panels. You version the profile in git. You do not rebuild a poller UI per device. If the OID matters, we add it once and every box with that `sysObjectID` inherits it.

### “Our poll interval is 5 minutes / 2 minutes. Can you do 60 seconds? Can you do 10?”

**What they mean:** NPM’s default poll is coarse. They either live with blind windows or they already paid for extra polling engines to go faster. Fast polls also **hurt the device** (CPU on the switch).

**Show:** Device Details interface bps — the line has a point every minute.

**Say:** This lab polls at **60 seconds**. That is already finer than many NPM defaults. You can go faster per group, but we size pollers so we do not melt the box. For state that must move in seconds (BGP flap, link down), we also take **traps / syslog** (push) and, on modern OS, **gNMI** (device pushes YANG). SolarWinds has no gNMI path — that is a hard gap, not a setting.

**Do not say:** “We poll everything at 10 seconds.” That is how you get a war room about the collector.

### “How do I see interface utilization, errors, and discards?”

**What they mean:** The daily NPM job. A ticket is almost always “port X is down,” “we’re dropping,” or “this WAN is full.”

**Show:** Summary → **Interfaces**, then Details → **Interfaces**. Point at bps, oper status, error rate.

**Say:** Same counters they already know (`ifHCInOctets`, errors, discards). In Grafana they are graphs and alerts next to the syslog for that device — not a second console (Log Analyzer) with a copied timestamp.

### “What about fans, PSUs, optics, temperature?”

**What they mean:** Hardware / environmental. A data-center network team pages on “PSU failed” as hard as on “link down.”

**Show:** Summary → **Hardware** if the Nokia chassis rows are populated. If empty, say so.

**Say:** Those come from vendor MIBs (here, Nokia chassis). Profiles that include fans / PSU / temp light the Hardware tab. Devices without those OIDs stay hidden instead of showing “No data” forever. Cisco / Juniper / Arista use different OID names — same Grafana tab, different profile.

### “Show me BGP / OSPF / HSRP. Why did the neighbor drop at 14:32?”

**What they mean:** Routing adjacency. If BGP dies, a path dies. NPM can poll some BGP MIBs; they still cannot see the **syslog NOTIFICATION** in the same window without Log Analyzer.

**Show:** Summary → **Routing**, then Details routing if present. Events tab for the same time range.

**Say:** “A neighbor that is not established is a path problem, not an app bug.” We graph session state and we have the trap/syslog in the same dashboard. On gNMI-capable gear, the state change can appear in seconds instead of at the next poll. SolarWinds does not speak gNMI.

**Do not dive into AS numbers** unless they do. “Peer” = the router on the other end of that session.

### “Where is NetPath / traceroute / hop-by-hop?”

**What they mean:** SolarWinds NetPath. They want a repeating traceroute from a place they control to a SaaS, a VIP, or a branch — hops, latency per hop, “where did the path change.” That is **not** NTA. Flow Sankey is conversations, not hops.

**Show:** Leave the ktranslate boards. Open [se-demo-netpath-traceroute](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294) (or **Testing & synthetics → Synthetics → Checks** and pick that job). This is a **traceroute** check, not HTTP. Public probes **Ohio** and **North Virginia** to `grafana.com`. Click into the traceroute / hop view. First hops take up to two minutes after create.

**Say:** “NetPath is a synthetic traceroute. Grafana Cloud Synthetic Monitoring is the same job: a probe you place (public region or a private probe in *their* VPC / branch) runs mtr-style hops on a schedule. You see the path, hop latency, and whether the destination still answers. HTTP and ping checks sit next to it for ‘is the URL up’ vs ‘where did the path break.’”

Pair it with Flow only if they mix the two: SNMP = is the box healthy; Flow = who used the path; **traceroute = what hops the path took from this vantage point.**

**Do not open**

- Flow Sankey as if it were NetPath
- Laptop / WSL traceroute — SM mtr on WSL only sees hop 1
- `net-o11y-trace-nlb-internal-aws` — that job lives on the other lab stack and the NLB path is still broken. Stay on `se-demo-netpath-traceroute`.

**Do not say:** “We cloned the NetPath graph UI.” The product is hop metrics + the Synthetics check view, not Orion’s node-identified path cartoon. Private probes in *their* sites are the equivalent of NetPath agents.

### “Where are my top talkers? Can I see conversations like NTA?”

**What they mean:** NTA is a **separate licence** in SolarWinds. Many shops never bought it, so they only have SNMP and guess at traffic.

**Show:** Flow Summary → Conversations, then Sankey.

**Say:** This is NTA, in the same Grafana as NPM-equivalent boards. No second product. A flow is a receipt: source, destination, protocol, bytes. It does not replace packet capture. It answers “who is filling the WAN.”

**Expected empty:** Geo Maps on RFC1918 / lab east-west. Say “private IP has no country” and move on.

### “Can I search syslog the way we do in Kiwi / Log Analyzer?”

**What they mean:** They live in a log GUI. They filter by device, severity, “link down,” “BGP.”

**Show:** Summary or Details → **Events**.

**Say:** Syslog and traps land in **Loki** in this same stack. You filter by device and severity. When a metric spikes, you keep the time picker and the log panel is already scoped — you do not copy a timestamp into a second product.

### “We get trap storms. How do you handle that?”

**What they mean:** A flapping port can emit thousands of traps. NPM + Log Analyzer turns into noise. They want to know you will not page them 4,000 times.

**Show:** Events volume over time, not a single trap line.

**Say:** Traps are logs. You can rate-limit at the device, drop repeats in the collector, and alert on **elevated trap rate** plus the **parent interface down** — not on every child BGP flap. Grafana Alerting supports inhibit / grouping the same way app alerts do. Do not promise a full “trap manager” UI in this demo.

### “How do you do dependencies? We don’t want WAN-down to page every BGP neighbor.”

**What they mean:** SolarWinds parent/child. If the uplink is down, suppress the 40 alerts behind it.

**Show:** Stay conceptual unless a circuit-fault board is provisioned and you have practiced it. Do not inject a fault on a live opp.

**Say:** Same idea: a parent condition (interface oper-down) inhibits child conditions (BGP not established) that share a circuit id. Grafana Alerting can express that. The design-partner version in this lab is WAN parent/child on `spine1` — not the student hunt port. Ask the lab owner before touching it.

### “What about maintenance windows / unmanage a node?”

**What they mean:** Orion “Unmanage” so a planned change does not page the NOC.

**Show:** Nothing special — do not hunt for an Unmanage button.

**Say:** Mute timings and silences in Grafana Alerting. You can also stop polling a group or take a device out of the discovered list. It is not the Orion calendar UI. Parallel-run until the NOC trusts silences.

### “How do I group by site / role / tenant like custom properties?”

**What they mean:** They typed `Site=CHI` and `Role=Core` into NPM. Those fields go stale. Filters are node groups someone made in 2019.

**Show:** Device Summary `snmp_group` (HQ vs branches). Fleet breakdown on Overview.

**Say:** Labels on the time series, not a property stuck inside the NMS. This lab stamps the discovery group. Production should take **site / role / platform** from **NetBox** so the CMDB and the dashboard cannot disagree. SolarWinds IPAM does not automatically flow into NPM views — that is a real pain they already have ([blog post 4](../blog/10_drafts/blog-post-04-netbox.md)).

### “We need IPAM. We need NCM. We need compliance reports.”

**What they mean:** They think “replace SolarWinds” = replace **every** Orion module on day one. That is how migrations die.

**Show:** Do not open a fake IPAM in this demo.

**Say:** This click path replaces **NPM + NTA + syslog/traps**. IPAM → NetBox. Config backup / drift / compliance → Ansible + Git + NetBox. Those are separate workstreams. The migration post’s cutover order is: NTA first, logs second, NPM third, IPAM fourth, NCM last — SolarWinds stays up until each piece is proven ([blog post 7](../blog/10_drafts/blog-post-07-migration.md)).

**Honest gap:** NCM ships canned compliance templates. Grafana + Ansible is more flexible and more work up front. Do not claim “we have NCM today on this stack.”

### “Can it auto-discover a /16 the way NPM does?”

**What they mean:** They click Discover, walk a subnet, and nodes appear. They do not want to type every hostname.

**Show:** Architecture — discovery vs poller split.

**Say:** Yes for SNMP: CIDR (or NetBox) in, device list out, poller reloads. That is how this lab found the Clos. What NPM also does is a very opinionated Windows wizard plus a huge MIB library. Very old or odd devices may need a profile. Dynamic clouds of devices need the inventory automation (NetBox / discovery job), not a human in a GUI every week.

### “What about wireless, SD-WAN, voice, IP SLA, SAM, WMI?”

**What they mean:** Orion is a suite. NPM is one SKU. They may also own Wireless, VNQM, SAM, SCM, etc.

**Show:** Nothing. Do not wander into empty dashboards.

**Say:** This demo’s ktranslate boards are **wired device telemetry** (SNMP + flow + syslog/traps). Wireless controllers and SD-WAN endpoints are still SNMP/flow if the profile exists — ask for the vendor list. **IP SLA** ICMP/HTTP/UDP-echo is the same family as Synthetic Monitoring ping / HTTP / traceroute (see NetPath above). Voice MOS / VNQM and WMI/SAM are different conversations. Do not fold the whole Orion suite into one meeting.

### “How do you scale polling engines? We have four additional pollers.”

**What they mean:** NPM scales by buying Windows polling engines. Licence + hardware + SQL.

**Show:** Health — multiple `service_name`s (`ktranslate-snmp-<group>`).

**Say:** Split by **credential group** and/or collector host. Each group is a container, not a Windows VM. `deployment_host` keeps two collector VMs from mixing in Grafana. You scale out Linux processes. You do not buy another polling-engine SKU.

### “We have years of history in SQL Server. What about retention?”

**What they mean:** Capacity planning and “what happened last Black Friday.” They are afraid of a cliff.

**Show:** Time picker on Summary (Last 3 hours for the live demo). Do not claim this lab has two years of series.

**Say:** Grafana Cloud retention is a **plan** setting, not a SQL job an Orion DBA tunes. Typical pattern: high-resolution recent data, downsampled long-term. Parallel-run until they have a season of Grafana history they trust. Do not promise a lossless import of Orion SQL into Prometheus — that is a project, not a checkbox.

### “Alerts — we have hundreds of Advanced Alerts. Can you import them?”

**What they mean:** Years of SWQL / trigger conditions. Night-shift tribal knowledge.

**Show:** Summary Overview if **Firing Network Alerts** is visible; otherwise describe.

**Say:** We do not import Orion alert XML. We recreate the **ones that still page people** as PromQL (or LogQL) on the same queries the dashboard uses. That is a feature: unused alerts die. Run both systems 4–6 weeks. The notification can open this dashboard with the incident window set. IRM covers on-call if they want to drop the third-party pager.

### “How is this better than SolarWinds? We already have green dashboards.”

**What they mean:** Political. They need a reason to spend political capital.

**Say, in this order:**

1. **One pane with apps.** NPM + NTA + Log Analyzer is three consoles and three licences. Grafana is the UI their SRE team already uses.
2. **Correlation.** Interface error spike and the `linkDown` / BGP syslog share a time picker and a `device_name`.
3. **Cost model.** SolarWinds prices **elements**. Adding a site moves a licence counter. Grafana Cloud is consumption. Directional TCO from the [migration draft](../blog/10_drafts/blog-post-07-migration.md): mid-market 500-node NPM+NTA+IPAM+NCM often lands **$80k–$200k/year** loaded; crossover often appears around **100–200 nodes**. Use **their renewal quote**, not these numbers, in a real deal.
4. **Trust / supply chain.** SUNBURST made “privileged monitoring appliance is a black box” concrete. Open collectors are auditable. This is a CISO conversation, not a smear.
5. **Skills.** PromQL / Grafana / Loki transfer to the rest of the estate. Orion expertise transfers to other Orion shops.
6. **Capability SolarWinds does not have.** gNMI streaming. Native traces next to flows. Dashboards as code.

### “What does a migration actually look like? We can’t turn NPM off.”

**What they mean:** Fear of a big-bang cutover.

**Show:** Architecture — “this sits beside Orion.”

**Say:** Phase 1 is **add**, not replace. 10–20 well-known devices, compare numbers, train PromQL. Phase 2 expands vendors and stands up flow + logs + alerts in parallel. Phase 3 decommissions modules in this order: **NTA → Log Analyzer → NPM → IPAM → NCM**. Procurement sees licence drop at each step. Full write-up: [blog post 7](../blog/10_drafts/blog-post-07-migration.md).

**Frame:** “adding observability capability.” Same outcome, easier conversation.

### “Who supports this? We have TAC today.”

**What they mean:** They want a phone number when SNMP is wrong at 2am.

**Say:** Grafana Cloud support on paid plans for the backend and UI. Collector + profiles are open source (ktranslate, snmp-profiles, this dashboard set). That is a different support shape than Orion TAC. Be honest. Many network teams already run a mix of TAC + Cisco / Arista TAC + a local expert. The local expert’s skills get more portable.

### “Our security team won’t allow community strings / they’ll want SNMPv3.”

**What they mean:** v2c `public` is a lab joke. Production is v3 + least privilege + management VRF.

**Show:** Architecture — credential **groups**.

**Say:** Groups exist so HQ and branches (or prod vs lab) do not share secrets. SNMPv3 is a group setting, not a different product. Traps and syslog should stay on the **mgmt** plane, not the data plane — same rule they already have.

### “Can Grafana Assistant investigate a network incident?”

**What they mean:** They saw Assistant on the app side.

**Show:** Only if you have practiced it on this stack. Do not cold-open Assistant on a customer call.

**Say:** Same Assistant, same stack. It is only as good as the labels (`device_name`, site). That is why identity on ingest matters. Treat it as homework after they have seen Summary → Details → Flow.

---

## Do not open / do not promise

| Thing | Why |
|-------|-----|
| Alloy Network Fork (`fb9d2s`, A0–A4) | Different metric names. Wrong story for an opp that closes before first-party GA. |
| `campus` SNMP group | Looks empty / broken. |
| Explore `kentik_snmp_DeviceMetrics` | AWS `integrations/snmp` path. **Empty here.** Inventory is `count by (device_name) (kentik_snmp_CPU)`. |
| Circuit-fault / workshop inject | Easy to leave a port down on a live call. |
| Last 5 minutes | Charts have no shape. |
| “We replaced NCM / IPAM / SAM today” | Not this demo. Point at the blog series and a follow-up. |
| “We cloned the NetPath Orion graph” | Route them to **Synthetics traceroute**. Same job, different UI. Do not use Flow Sankey or the broken NLB traceroute check. |
| “Every SolarWinds MIB works unchanged” | Profiles cover a lot; UnDPs and antiques need work. |
| Official pricing from the blog ranges | Directional only. Use their renewal + a Cloud AE. |

---

## Five minutes before the call

Open Architecture, Summary, Details (`leaf1`), and Flow in four tabs. Set Last 3 hours. Confirm Summary shows `spine1` / `leaf1` / `leaf2` (and branches if All is selected). If Summary is empty, you are on the Alloy folder or the wrong time range — stop and fix that before they join.

If they are a NetPath shop, also open [se-demo-netpath-traceroute](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294) and wait until Ohio / North Virginia show hops (up to two minutes). Do not use a laptop/WSL probe or the lab NLB traceroute.
