# Post 5: Observability with Grafana

**Series:** Network Observability Without the Lock-in
**Audience:** Network engineers, NOC teams, IT leadership
**Tone:** Visual/demo-driven — lots of screenshots, dashboard walkthroughs

---

## Outline

### I. One UI to Rule Them All
- SolarWinds requires switching between NPM, NTA, Log Analyzer, and IPAM consoles
- Grafana unifies metrics (Prometheus), logs (Loki), and flows (Grafana Cloud) in one place
- The same UI used by the SRE team, the NOC, and leadership — just different dashboards

### II. Dashboard Walkthrough

#### Network Topology
- Visual Clos fabric map with live link utilisation overlaid on the topology
- Click a link → drill down to interface metrics
- SolarWinds equivalent: Network Atlas (static maps, no live data overlay)

#### Interface Health
- Per-device, per-interface: traffic rates, error counters, discard counters, operational state
- Filtered by `device_role` (spine vs leaf) using NetBox-sourced labels — no manual grouping
- SolarWinds equivalent: NPM interface details — but without the role/site filter capability

#### BGP Session Status
- BGP neighbour state, prefixes received/advertised per peer
- Alert when a session drops — correlate with syslog events in the same time window
- SolarWinds equivalent: partial — NPM has some BGP MIB support but no log correlation

#### NetFlow / Traffic Flows
- Top talkers, protocol breakdown, flow volume over time
- Source: softflowd on Linux clients + sFlow counter-samples from SR Linux
- SolarWinds equivalent: NTA — but NTA is a separate product with a separate UI

#### Device Inventory
- Table view of all devices sourced live from NetBox
- Click through to device details — platform, role, site, rack position
- SolarWinds equivalent: IPAM node details — disconnected from NPM dashboards

#### Device Details
- Per-node: CPU, memory, uptime, BGP state, interface deep-dive
- Data source: gNMI streaming telemetry (sub-second granularity)
- SolarWinds equivalent: NPM node details — SNMP polling only, 5-min minimum granularity

### III. What Grafana Gives You That SolarWinds Can't

#### gNMI Streaming Telemetry
- State pushed by the device as it changes — not polled every 5 minutes
- Critical for fast-moving events: BGP flap, interface state change, queue depth spike
- SolarWinds has no gNMI support — this is a hard capability gap

#### Unified Log Correlation
- Syslog events in Loki, queryable in the same dashboard as metrics
- Annotate a metric chart with log events — "the interface error spike at 14:32 corresponds
  to this BGP NOTIFICATION message"
- SolarWinds: separate Log Analyzer product, no native metric/log correlation

#### Alerting and On-Call
- Grafana Alerting: rules defined in the same place as dashboards
- Grafana OnCall (incident management) and IRM built in
- SolarWinds: separate alerting engine, no native on-call routing

### IV. The Label-Driven Filtering Advantage
- Every metric carries inventory labels from NetBox (`device_role`, `site`, `platform`)
- A single dashboard serves all devices — filter by role, site, or rack without duplicating panels
- Demonstrate: "show me only leaf interface errors in site network-lab"
- SolarWinds: requires separate views per node group, manually maintained

### V. Deploying the Dashboards
- `grafana/dashboards/` in the repo: JSON definitions for all dashboards
- `scripts/deploy-dashboards.sh`: push to any Grafana Cloud stack with a service account token
- Provisioning is reproducible — dashboards are code

---

**Next post:** Network Config Management with Ansible — closing the loop on the SolarWinds NCM replacement.
