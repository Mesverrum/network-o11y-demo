# Network observability primer

**Audience:** Teammates new to networking, ktranslate, or this demo repo.  
**Goal:** Enough context to understand what the lab does, why network teams care, and how Grafana Cloud fits in.

---

## 1. What problem are we solving?

Applications depend on the network, but network data usually lives in a different world from application data:

- App teams see **traces, logs, and APM** in tools like Grafana.
- Network teams see **SNMP counters, flow records, and device syslog** in tools like SolarWinds, vendor NMS, or spreadsheets.

When something breaks—a slow checkout, a failed API, a VPN outage—both sides start investigating in parallel. Without shared context, you get long war rooms, duplicate work, and guesses about whether the problem is “the app” or “the network.”

**Business impact of that gap:**

| Symptom in the war room | What the business feels |
|-------------------------|-------------------------|
| “Network looks fine from our dashboards.” | Longer outages, missed SLAs, revenue loss during incidents |
| “We can’t see which path traffic took.” | Slow root-cause analysis; blame ping-pong between teams |
| “Logs are in one tool, metrics in another.” | Higher mean time to repair (MTTR); engineer burnout |
| “We only poll every 5 minutes.” | Problems visible only after users complain |
| “Adding devices increases licence cost.” | Observability becomes a budget gate, not a safety net |

This repo demonstrates an **open, unified pipeline**: network telemetry lands in the **same Grafana Cloud stack** as application signals, using standard protocols and collectors you can inspect and extend.

---

## 2. Network terminology (just enough)

You do not need CCIE-level knowledge. These terms show up in the lab and dashboards.

### Topology (how things are wired)

| Term | Plain English | In this lab |
|------|---------------|-------------|
| **Fabric** | The set of switches/routers that move traffic between servers | Small Clos: 1 spine + 2 leaves |
| **Spine** | High-speed “backbone” switch; leaves connect to it | `spine1` |
| **Leaf** | Access switch; servers/clients hang off leaves | `leaf1`, `leaf2` |
| **Client / host** | A machine sending and receiving traffic | `client1`, `client2` (Linux containers) |
| **Interface** | A physical or logical port on a device | e.g. `ethernet-1/49` on a leaf |
| **Clos** | A common data-center pattern: every leaf reaches every spine | Simplified 3-tier demo |

```
        spine1
         /    \
     leaf1    leaf2
       |        |
   client1   client2
  172.17.0.1  172.17.0.2
```

### Routing and overlays (how packets find their way)

| Term | Plain English | In this lab |
|------|---------------|-------------|
| **BGP** | Protocol routers use to exchange “how to reach IP prefixes” | eBGP underlay between spine and leaves |
| **EVPN** | Way to stretch L2 (same subnet) across the fabric | Clients share `172.17.0.0/24` as if on one LAN |
| **MAC-VRF** | Virtual routing instance for MAC addresses in EVPN | Why `client1` can talk to `client2` at L2 |
| **Underlay vs overlay** | Underlay = physical/router IPs; overlay = tenant/app subnets on top | Underlay links spine↔leaf; overlay is client subnet |

### Discovery and inventory

| Term | Plain English | In this lab |
|------|---------------|-------------|
| **LLDP** | “Neighbor discovery” between devices (who is plugged into whom) | Used to draw topology **edges** |
| **SNMP** | Classic “ask the device for counters/state” protocol | Interface stats, CPU, BGP tables |
| **gNMI** | Modern streaming API (device pushes updates) | BGP neighbors, LLDP neighbors, etc. |
| **NetBox** (optional) | IP/device inventory | NetBox Cloud API | `netbox-populate.py` when `DISCOVERY_SOURCE=netbox` |

---

## 3. Telemetry types network engineers use

Think of four questions network ops asks every day:

| Question | Telemetry type | Typical source | Grafana backend |
|----------|----------------|----------------|-----------------|
| **How utilized / healthy is the hardware?** | **Metrics** (time-series numbers) | SNMP, gNMI | Prometheus (Mimir in Grafana Cloud) |
| **What event happened on the box?** | **Logs** (text events) | Syslog, SNMP traps | Loki |
| **Who talked to whom, how much?** | **Flows** (connection records) | NetFlow, sFlow, IPFIX | Often indexed as logs/metrics via OTLP |
| **What path did traffic take?** | **Topology** (graph of devices + links) | LLDP, SNMP, exporters | Prometheus metrics (`network_topology_*`) |

### Metrics (SNMP and gNMI)

**SNMP polling** is the decades-old default: every N minutes, a collector asks each device “what’s your interface error count, CPU, BGP state?”

- **Pros:** Works on almost everything; huge ecosystem.
- **Cons:** Poll interval hides short spikes; MIB/profile work per vendor; can be heavy on large devices.

**gNMI streaming** is newer: the device **pushes** changes when state changes.

- **Pros:** Faster visibility; good for BGP/session flaps.
- **Cons:** Vendor/model support varies; different tooling than SNMP.

**In this lab:** SNMP via **ktranslate** (`kentik_snmp_*` metrics). gNMI via **gnmic** (`gnmi_*` metrics).

### Logs (syslog and traps)

Devices emit **syslog** for operational events: link down, BGP neighbor lost, config change, auth failure.

- Network teams search logs by **device, severity, facility**.
- **SNMP traps** are push alerts (often fed into the same pipeline).

**In this lab:** Syslog and traps → **ktranslate** → OTLP → Alloy → Grafana Cloud.

### Flows (NetFlow / sFlow)

A **flow** is a summary of traffic between endpoints: source/dest IP, ports, protocol, bytes/packets, timestamps.

- Answers: “Which apps or subnets are consuming bandwidth?” “Is traffic going where we expect?”
- Does **not** by itself prove application-level causality—but it’s the network’s view of conversations.

**In this lab:** `softflowd` on clients emits **NetFlow v9** → **ktranslate** → metrics like `network_io_by_flow`.

### Topology

**Topology** is the map: nodes (devices) and edges (links). It powers graph dashboards and “where could this packet go?”

**In this lab:**

- **Devices:** `topology_exporter` (SNMP discovery) → `network_topology_device_info`
- **Edges:** **gnmic** LLDP neighbors → Alloy remap → `network_topology_edge_info`

### Traces (application side—but we join them to the network)

**Distributed traces** (OpenTelemetry) follow a single request across services: duration, errors, attributes like `network.peer.address`.

App SREs live here. Network teams traditionally do not—but **correlating trace + flow + topology** is how you shorten incidents.

**In this lab:** The **join app** (`clos-join-demo`) sends HTTP requests client1→client2 and exports traces. The **Network join demo** dashboard shows the same 5-tuple in Tempo and in NetFlow.

---

## 4. What is ktranslate? (and why it’s in this stack)

**[ktranslate](https://github.com/kentik/ktranslate)** is an open-source **telemetry multiplexer** originally from Kentik. In this project it plays the role SolarWinds NTA + parts of NPM often fill:

| ktranslate role | What it does |
|-----------------|--------------|
| **SNMP poller** | Discovers devices, runs vendor SNMP profiles, exports metrics via OTLP |
| **Flow collector** | Listens for NetFlow/sFlow, normalizes records, exports via OTLP |
| **Syslog/trap receiver** | Ingests device logs and traps, forwards via OTLP |

**Why not poll SNMP directly in Alloy?** You can—for simple cases. ktranslate adds:

- **SNMP profiles** per vendor/platform (Nokia SR Linux, Cisco, Juniper, …)
- **Discovery** workflows (find devices, assign profiles, split pollers)
- **Flow parsing** at scale with Kentik’s battle-tested pipeline
- **OTLP out** so everything lands in one modern pipeline

**Mental model:** ktranslate is a **specialized network ingest layer**. It speaks legacy/network-native protocols on the southbound side and **OpenTelemetry** on the northbound side.

**In this repo** we follow the [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) pattern:

- Credential **groups** (`groups/srl.env`) → generated poller/discovery configs
- Separate containers for SNMP, flow, and syslog
- Alloy receives OTLP and forwards to **Grafana Cloud**

You’ll see metrics prefixed like `kentik_snmp_*` and flow series like `network_io_by_flow`—that’s ktranslate’s export shape into Prometheus-compatible OTLP.

---

## 5. The rest of the stack (one paragraph each)

| Component | Role |
|-----------|------|
| **Grafana Alloy** | Telemetry router: OTLP in, relabel/enrich, forward to Grafana Cloud; also scrapes some sources and remaps LLDP into topology edge metrics |
| **gnmic** | gNMI client; streams YANG paths (BGP, LLDP, …) as OTLP/Prometheus metrics |
| **topology_exporter** | Discovers devices via SNMP; publishes device graph metrics |
| **Grafana Cloud** | Hosted Prometheus + Loki + Tempo + Grafana UI—one place to query, dashboard, and alert |
| **NetBox + Ansible** | Inventory and config automation | NetBox in local compose; Ansible on EKS path |

**Data path (local lab):**

```
SR Linux devices ──SNMP──► ktranslate_snmp ──┐
              ──syslog──► ktranslate_syslog ─┤
clients ──NetFlow──────► ktranslate_flow ───┼──► Alloy ──OTLP──► Grafana Cloud
              ──gNMI────► gnmic ─────────────┤
              ──SNMP────► topology_exporter ─┘
join-app ──traces/metrics────────────────────► Alloy
```

---

## 6. Typical network team pain points → business problems

### Pain: “We have dashboards, but incidents still take hours.”

**Why:** Metrics, logs, and flows live in different products with different timestamps and no shared keys.

**Business cost:** SLA breaches, overtime, customer churn.

**How this stack helps:** One Grafana Cloud stack; dashboards can combine Prometheus, Loki, and Tempo; the join demo explicitly ties **app peer IP:port** to **flow labels** and **topology**.

---

### Pain: “We can’t prove whether the network path is involved.”

**Why:** App tools stop at the host NIC; network tools stop at the device. Nobody owns the middle.

**Business cost:** App team and net team deadlock; executive pressure with no evidence.

**How this stack helps:** Traces carry `network.peer.*`; flows carry `network_peer_*`; topology shows **candidate** paths (LLDP). Investigation row on `lab-network-join-demo` walks app → flow → subway graph → device CPU/errors.

---

### Pain: “SNMP polling is too slow or too coarse.”

**Why:** Five-minute polls miss microbursts; large devices have thousands of interfaces.

**Business cost:** “Green dashboards, angry users”; capacity surprises.

**How this stack helps:** gNMI streaming for fast-changing state; flow data for traffic reality; you can tune poll intervals and split pollers (ktranslate groups pattern).

---

### Pain: “Vendor lock-in and licence math.”

**Why:** Per-node pricing; separate products for NPM, NTA, syslog, NCM.

**Business cost:** Six-figure renewals; observability deferred on new sites.

**How this stack helps:** Open collectors + consumption-based Grafana Cloud; add devices without a licence counter (you pay for ingest/storage used).

---

### Pain: “Inventory labels never match monitoring.”

**Why:** CMDB says one hostname; SNMP says another; flows use IPs.

**Business cost:** Can’t filter by site/role/tenant; automation breaks.

**How this stack helps:** Default local bring-up discovers SNMP targets from ContainerLab mgmt CIDRs. Optionally, ktranslate can discover from **NetBox Cloud** (`make netbox-sync`). Local lab also uses `tester_id` / `deployment.host` labels. Identity demo tabs (`entity_demo_*`) explore how **entity identity** should work across sources.

---

## 7. What Grafana Cloud adds (beyond “hosted Grafana”)

| Capability | Why network + app teams care |
|------------|------------------------------|
| **Unified query UI** | Metrics (PromQL), logs (LogQL), traces (TraceQL) in one place |
| **Dashboards + variables** | Filter by device, site, peer IP—same board for net and app |
| **Alerting** | Alert on Prometheus rules (e.g. interface errors, BGP down) |
| **Cardinality controls** | Important for flow and label-heavy network data |
| **SaaS operations** | No self-running Prometheus/Loki clusters for a pilot |

**Forever-free tier** is enough to run this lab and show value before production sizing.

---

## 8. What to look at in this repo

| If you want to… | Start here |
|-----------------|------------|
| Run the laptop lab | [local/README.md](../local/README.md) |
| Clone from scratch | [README.md](../README.md) — “Local lab → Clone and run” |
| Understand agents/automation context | [AGENTS.md](../AGENTS.md) |
| See app↔network join story | `make -C local join-app`; dashboard UID `lab-network-join-demo` |
| Full production-shaped path | EKS + NetBox path in root README |

**Suggested 30-minute walkthrough for a new teammate:**

1. Bring up the lab (`make up`, `make traffic`).
2. In Grafana Cloud Explore, run `count by (device_name) (kentik_snmp_DeviceMetrics)` — confirm SNMP.
3. Run `sum by (device_name) (rate(network_io_by_flow[5m]))` — confirm flows.
4. Open **Network join demo** dashboard; run `make join-app`; see traces and flows align on `172.17.0.2:8080`.
5. Optional: `make join-fault` — watch app latency rise while flows continue (talk track: “network path degraded, not blackholed”).

---

## 9. Glossary (quick reference)

| Term | One-line definition |
|------|---------------------|
| **OTLP** | OpenTelemetry Protocol—how collectors send data to backends |
| **Poller** | Process that periodically queries devices (SNMP) |
| **MIB / profile** | Schema of what SNMP OIDs to collect for a platform |
| **5-tuple** | src IP, dst IP, protocol, src port, dst port—identifies a conversation |
| **tester_id** | Label identifying this lab instance in metrics (`network-lab` by default) |
| **SIG** | Grafana “service inference graph” direction—unified service + network entity model |
| **NMS** | Network Management System (e.g. SolarWinds NPM) |

---

## 10. Further reading

- Blog series outline: [blog/blog-series-overview.md](../blog/blog-series-overview.md)
- ktranslate → Grafana pattern: [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana)
- Grafana Alloy: https://grafana.com/docs/alloy/latest/
- OpenTelemetry: https://opentelemetry.io/docs/

---

*Questions or corrections? Open an issue or PR on the repo—this primer is meant to evolve with the lab.*
