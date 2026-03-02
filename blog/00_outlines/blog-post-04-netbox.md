# Post 4: NetBox as Your Source of Truth

**Series:** Network Observability Without the Lock-in
**Audience:** Network engineers, NetOps teams
**Tone:** Technical — concepts + code walkthrough

---

## Outline

### I. The Inventory Problem
- Metrics without context are noise — you need to know *what* a device is, not just its IP
- The SolarWinds way: manually tag nodes in NPM (stale within weeks)
- The right approach: one authoritative inventory system, everything else reads from it
- Why NetBox is the open standard for this

### II. What NetBox Gives You
- DCIM: devices, device types, roles, racks, sites
- IPAM: IP addresses, prefixes, VLANs
- A REST API that everything else can query
- The Prometheus HTTP SD spec — a standard way to expose targets + labels to any collector

### III. Part A: Populating NetBox — Discovery vs Hardcoding

#### The Hardcoded Approach (What We Start With)
- The populate job in the demo: a Python script that creates all 8 devices via the NetBox API
- Good for a known, static lab — but not how real networks work

#### The Discovery Approach (Where Real Value Lives)
- NetBox's built-in scanning: using `nmap`-based discovery to find devices on subnets
- Integrating with existing CMDBs or DNS to seed NetBox automatically
- The `netbox-bgp` and other community plugins for protocol-specific state
- Webhooks: NetBox can notify downstream systems when inventory changes
- The goal: NetBox stays current without manual entry

### IV. Part B: Reading NetBox in Alloy — Closing the Enrichment Loop
- The netbox-sd adapter: a lightweight HTTP server that queries NetBox and returns
  Prometheus HTTP SD JSON
- What the output looks like: each device becomes a target with labels
  (`device_role`, `site`, `platform`, `tenant`, `rack`)
- How Alloy's `discovery.http` component polls netbox-sd every 5 minutes
- How `prometheus.relabel` attaches those labels to every SNMP and gNMI metric
- Result: filter your dashboards by role or site without touching the collector config

### V. The Before/After
- Before: a raw SNMP metric with only `instance` and `job` labels
- After: the same metric with `device_role=leaf`, `site=network-lab`, `platform=sr-linux`
- Demo: querying Grafana — "show me all leaf interface errors" with a single label filter

### VI. Why This Beats SolarWinds IPAM
- SolarWinds IPAM is siloed — data doesn't flow automatically into NPM dashboards
- NetBox + netbox-sd makes inventory a live data source, not a reference document
- When a device moves rack or changes role, the change propagates to dashboards automatically

---

**Next post:** Observability with Grafana — building the dashboards that make all this data useful.
