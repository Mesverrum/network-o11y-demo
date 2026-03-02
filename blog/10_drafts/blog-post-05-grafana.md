# Observability with Grafana

*Part 5 of 7 — Network Observability Without the Lock-in*

---

Everything built in the previous posts — the SR Linux fabric, the four telemetry streams, the NetBox inventory enrichment — exists to answer questions. Is the network healthy right now? Which leaf interface is saturated? Why did BGP go down at 14:32? Who is generating that traffic spike?

This post walks through the Grafana dashboards that answer those questions, shows what each replaces in the SolarWinds world, and highlights capabilities this stack has that SolarWinds simply cannot provide.

## One UI instead of four

In a typical SolarWinds deployment, answering one incident question requires switching between at least three consoles: NPM for interface metrics, Log Analyzer for the correlated syslog, NTA if you need the traffic pattern. None are natively linked. You correlate manually, copying timestamps, noting IPs, switching tabs.

[Grafana](https://grafana.com/grafana/) changes this. Metrics (Prometheus), logs (Loki), and flows (ktranslate via Loki) all sit in the same data store, queryable in the same dashboard panel row. When you see an interface error spike, the syslog events from that device in that time window are one click away — not a separate login to a separate product.

The dashboards are also **code** — JSON files in the repo, deployed with a script, version-controlled. If a dashboard is deleted, you `git checkout` and redeploy. SolarWinds dashboards live in a SQL Server database with no native version control.

## Dashboard walkthrough

### Network topology

The topology dashboard shows a live visual map of the Clos fabric with link utilization overlaid on each connection — green at low utilization, yellow approaching capacity, red at saturation. Clicking a link drills down to interface metrics. Clicking a device node opens its detail dashboard.

SolarWinds Network Atlas draws topology from proprietary discovery and renders a static map. This Grafana panel uses structured data from NetBox and overlays live Prometheus metrics on top. The map updates when the inventory updates.

### Interface health

The interface health dashboard shows per-device, per-interface traffic rates, error counters, discard counters, and operational state. The top of the dashboard has label filter variables — `device_role`, `site`, `platform` — populated from the actual values present in Prometheus.

To see all leaf interface errors across the fabric: set `device_role=leaf` in the dropdown. Every panel updates. No manual node grouping required. This works because every metric carries the NetBox-sourced labels from Post 4.

SolarWinds NPM shows the same underlying data, but filtered views require manual node group configuration that goes stale as the network changes.

### BGP session status

The BGP dashboard shows the state of every BGP session — Established, Idle, prefixes received and advertised per peer — sourced from gNMI streaming telemetry via gnmic.

When a BGP session drops, the state change appears in Grafana within seconds, not after the next five-minute SNMP poll. An alert fires immediately, and a Loki panel in the same dashboard shows the BGP NOTIFICATION message from syslog in the same time window — no manual correlation.

SolarWinds NPM does have some BGP MIB support. What it doesn't have is sub-second granularity from gNMI, and it has no native mechanism to show the correlated syslog event in the same panel.

### NetFlow / traffic flows

The flows dashboard shows top talkers by byte volume, protocol breakdown, and flow volume over time. Data comes from ktranslate, receiving NetFlow v9 from softflowd on the Linux clients and sFlow from SR Linux.

This replaces SolarWinds NTA — but NTA requires a separate product licence and separate interface. In this stack, flows appear in the same Grafana instance as every other signal type.

### Device inventory and device details

The inventory dashboard renders a live table sourced directly from NetBox — device name, role, site, platform, status, primary IP. Clicking a row opens the device detail dashboard: CPU, memory, uptime, BGP state table, per-interface deep-dive.

Where available, CPU and memory come from gNMI (sub-second push). Interface counters come from SNMP (60-second poll). Syslog events from this device appear in a log panel below the metric charts, automatically filtered to the selected hostname.

SolarWinds NPM's node detail view covers CPU and interfaces via SNMP only. No gNMI data, no inline log correlation without a separate Log Analyzer licence.

## What Grafana gives you that SolarWinds can't

### gNMI streaming telemetry

This is a hard capability gap. gNMI delivers state changes from the device in real time — no polling interval, no five-minute blind window. For fast-moving events — BGP flaps, interface state changes, queue depth spikes — the difference between knowing in seconds and knowing in five minutes is often the difference between containing an incident and escalating one.

Every modern network OS supports gNMI. SolarWinds NPM does not.

### Unified log correlation

[Loki](https://grafana.com/oss/loki/) is a first-class data source in Grafana, sitting alongside Prometheus in the same dashboard. You can annotate a metric time series with log events from the same time window, from the same device, inline — not as a link to a separate log tool. The investigation workflow becomes: see the anomaly → hover to set the time range → the Loki panel below shows the cause. Usually visible immediately.

### Alerting without a separate product

[Grafana Alerting](https://grafana.com/docs/grafana/latest/alerting/) evaluates rules against the same Prometheus queries used in dashboards. When a rule fires, the notification includes a direct link to the relevant dashboard with the incident time window pre-set. [Grafana IRM](https://grafana.com/products/cloud/irm/) routes through on-call schedules and escalation policies. This replaces SolarWinds Alerts plus a third-party on-call integration plus a separate incident management tool — in one coherent system.

## Deploying the dashboards

All dashboards are defined as JSON in `grafana/dashboards/` in the repo. The deploy script pushes them to any Grafana Cloud stack:

```bash
echo "glsa_your_token" > grafana-cloud-api.token

cat > grafana-cloud.instance <<EOF
url=https://your-instance.grafana.net
instance_name=your-instance
instance_id=123456
EOF

./scripts/deploy-dashboards.sh
```

If a dashboard is deleted, run the script again. If you want to share the entire stack with a colleague's Grafana Cloud account, copy the token file and run the script. Dashboards are reproducible and portable.

---

*Next: [Part 6 — Network Config Management with Ansible](#), where we close the loop on the SolarWinds NCM replacement.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, traces, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Network Observability, Grafana, Prometheus, Loki, gNMI, Dashboards, Alerting
