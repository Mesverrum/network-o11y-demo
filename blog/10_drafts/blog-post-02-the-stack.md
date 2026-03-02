# The Open Network Observability Stack

*Part 2 of 7 — Network Observability Without the Lock-in*

---

Before replacing SolarWinds, you need a clear picture of what it actually does — and what each component's open-source equivalent is. This post draws that map. By the end, you'll know exactly which tool replaces which, how they connect, and why the combination is stronger than what it replaces.

## Metrics, logs, and flows

Network monitoring lives and dies on three signal types. Metrics — interface rates, error counters, BGP prefix counts, CPU load — tell you the current state of the network. Logs — BGP session down, config change, authentication failure — tell you what happened and when. Flows — which source sent how many bytes to which destination — tell you who's talking to whom.

Miss any one of them and you'll have blind spots that surface at the worst possible time.

SolarWinds covers all three, and that's genuinely something. The problem is separate products, separate UIs, and separate licences — NPM for metrics, NTA for flows, Log Analyzer for logs — with no native correlation between them. When something breaks at 2am, you're switching tabs and copying timestamps. The open stack covers all three in a unified pipeline that feeds a single interface.

## The replacement map

| SolarWinds Product | What it does | Open replacement |
|---|---|---|
| NPM | SNMP polling, interface metrics | Grafana Alloy + Prometheus |
| NTA | NetFlow/sFlow traffic analysis | ktranslate + Grafana |
| Log Analyzer / Kiwi Syslog | Syslog ingestion and search | Alloy + Loki |
| IPAM | IP address management | NetBox |
| NCM | Config backup and compliance | Ansible + NetBox + Git |
| Network Atlas | Topology visualization | Grafana topology panel |
| *(no equivalent)* | gNMI streaming telemetry | gnmic + Prometheus |

That last row is worth noting. gNMI — the gRPC Network Management Interface — is a streaming telemetry protocol supported by Nokia, Juniper, Arista, and Cisco on current platforms. Devices push state changes to a collector in real time, at sub-second resolution. SolarWinds has no support for it. The open stack makes it a first-class citizen.

## The components

### Grafana Alloy

[Grafana Alloy](https://grafana.com/oss/alloy/) is the unified telemetry agent at the center of this stack. In a single process, it:

- Polls SNMP targets and exposes them as Prometheus metrics
- Receives OTLP data from ktranslate
- Ingests syslog over UDP and forwards to Loki
- Scrapes Prometheus endpoints (gnmic, node exporters)
- Applies relabeling rules to enrich metrics with inventory labels from NetBox

In SolarWinds terms, Alloy replaces the proprietary polling engine that NPM runs on dedicated Windows infrastructure. It runs as a single container, requires no Windows licence, and is configured as code.

### gnmic + gNMI

gnmic is an open-source gNMI client that subscribes to streaming telemetry on network devices — interface counters, BGP state, routing table sizes — and exposes them as Prometheus metrics for Alloy to scrape.

The difference from SNMP polling is significant. With SNMP, you ask the device for its state every five minutes. With gNMI, the device tells you the moment state changes. For operational response time, that difference matters.

### ktranslate

ktranslate receives NetFlow v9 and sFlow datagrams, normalizes them, converts to OTLP, and forwards to Alloy — which writes them to Grafana Cloud as log records. Flow data appears in Grafana alongside your SNMP metrics and syslog events, queryable in the same interface. No separate product, no separate licence.

### Grafana Loki

[Loki](https://grafana.com/oss/loki/) indexes only the labels attached to each log stream — device, severity, facility — and stores raw log content compressed. For network syslog — high volume but queried by device and severity — this model is extremely efficient. It replaces Kiwi Syslog and SolarWinds Log Analyzer, and because it lives in the same Grafana instance as your metrics, correlating a metric anomaly with the log event that caused it is a single click.

### NetBox

NetBox is the open-source standard for network inventory — DCIM and IPAM in a single application. Critically for observability, NetBox exposes a **Prometheus HTTP Service Discovery** endpoint. Alloy polls this endpoint and uses device metadata — role, site, platform, tenant — as labels on every metric it collects. The result: every SNMP counter and gNMI value carries context about *what kind of device* it came from, automatically.

### Ansible

Ansible handles what NetBox can't: pushing configuration changes, backing up running configs, and detecting drift. The `netbox.netbox.nb_inventory` plugin means Ansible's inventory is drawn directly from NetBox — when a device is added, it automatically appears in the next Ansible run. Together, NetBox and Ansible replace SolarWinds NCM.

### Grafana Cloud

[Grafana Cloud](https://grafana.com/products/cloud/) is the hosted Prometheus + Loki + Grafana platform. Metrics and logs from Alloy are forwarded here over HTTPS. You get fully managed storage, a multi-tenant Grafana instance, alerting, on-call management, and dashboard provisioning — without running any database infrastructure yourself. Grafana Cloud uses consumption-based pricing that scales with what you actually use, not per device.

## How the data flows

```
Network devices (SR Linux)              Linux clients
  │                                          │
  ├─ SNMP ──────────────────────────────► Alloy
  ├─ gNMI ──────────► gnmic ──────────► Alloy (scrape)
  ├─ syslog ────────────────────────────► Alloy → Loki
  └─ sFlow ──► ktranslate ─── OTLP ───► Alloy
                                              │
                                              ▼
                                       Grafana Cloud
                                    (Prometheus + Loki)
                                              │
                                              ▼
                                     Grafana Dashboards
```

NetBox runs alongside the pipeline. A small HTTP adapter (netbox-sd) translates NetBox's device database into Prometheus HTTP SD format. Every metric Alloy collects gets enriched with labels from NetBox before it reaches Grafana Cloud.

## Why this combination works

The components are small and focused, which means when something changes — gnmic adds support for a new gNMI path, Alloy gets a new relabeling feature — you update one thing, not the entire platform. That modularity also matters for trust: every component is open source. If Alloy's SNMP implementation does something unexpected, you can read the code. If a CVE is published, you can read the patch and the fix.

The real day-to-day difference is the single UI. Metrics, logs, and flows all live in Grafana, queryable in the same dashboard. Alert rules reference the same Prometheus queries you already visualize. When something fires at night, the context is already there — you're not logging into a second product to find the correlated syslog.

And the cost model is different in kind, not just degree. You pay for what you ingest, not per device. Adding a device to NetBox doesn't move a licence counter.

---

*Next: [Part 3 — Building the Lab](#), where we build a real Nokia SR Linux Clos fabric on Kubernetes to test this stack against.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, traces, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Network Observability, Grafana Alloy, Prometheus, Loki, NetBox, SNMP, gNMI, Open Source
