# Post 2: The Open Network Observability Stack

**Series:** Network Observability Without the Lock-in
**Audience:** Network engineers, infrastructure architects
**Tone:** Technical overview — architecture diagrams, component explanations, no code yet

---

## Outline

### I. The Three Pillars of Network Observability
- Metrics, logs, and flows — and why you need all three
- How SolarWinds covers them (NPM = metrics, NTA = flows, Log Analyzer/Kiwi = logs)
- How the open stack covers them — and goes further

### II. The Replacement Map

| SolarWinds Product | What It Does | Open Replacement |
|--------------------|-------------|-----------------|
| NPM | SNMP polling, interface metrics | Grafana Alloy + Prometheus |
| NTA | NetFlow/sFlow traffic analysis | ktranslate + Grafana |
| Log Analyzer / Kiwi Syslog | Syslog ingestion and search | Alloy + Loki |
| IPAM | IP address management | NetBox |
| NCM | Device config backup and compliance | Ansible + NetBox |
| Network Atlas | Topology maps | Grafana topology panel |
| — (no equivalent) | gNMI streaming telemetry | gnmic + Prometheus |

### III. Component Deep-Dives

#### Grafana Alloy
- The unified telemetry agent — collects, transforms, and forwards everything
- Replaces SolarWinds' proprietary polling engine
- Handles SNMP, OTLP ingestion, syslog, and Prometheus scraping in one process

#### gnmic + gNMI
- Streaming telemetry: devices push state changes as they happen (vs poll every 5 min)
- Supported by all modern network OSes (Nokia SR Linux, Juniper, Arista, Cisco IOS-XR)
- SolarWinds has no equivalent — this is a genuine capability gap

#### ktranslate
- Receives NetFlow v9 / sFlow from network devices
- Converts to OTLP and forwards to Alloy → Grafana Cloud
- Replaces SolarWinds NTA

#### Loki
- Log aggregation — stores and queries syslog, device events, BGP state changes
- Label-based indexing: filter by device, severity, facility without full-text scan cost
- Replaces Kiwi Syslog and SolarWinds Log Analyzer

#### NetBox
- The source of truth for device inventory, IP addressing, and topology
- Exposes a Prometheus HTTP SD endpoint — Alloy reads it to enrich metrics with labels
- Replaces SolarWinds IPAM (and partially NCM)

#### Grafana Cloud
- Unified dashboards over Prometheus (metrics) + Loki (logs)
- Alerting, on-call, SLOs — all in one place
- No Windows server, no Oracle DB, no dedicated appliance

### IV. How the Data Flows
- End-to-end architecture diagram
- Network device → protocol → collector → storage → dashboard
- Highlight: inventory labels from NetBox flowing into every metric at collection time

### V. Why This Combination Wins
- Each component is best-in-class at its job (Unix philosophy)
- All open source — audit the code, fork it, contribute to it
- Consumption-based cloud pricing vs per-node licensing
- One UI (Grafana) instead of 4–5 separate SolarWinds consoles

---

**Next post:** Building the Lab — spinning up a real SR Linux Clos fabric on Kubernetes to test against.
