# NetBox as Your Source of Truth

*Part 4 of 7 — Network Observability Without the Lock-in*

---

A metric that says `ifHCInOctets{instance="192.168.1.1"}` isn't very useful by itself. You know there's traffic on an interface somewhere. You don't know whether it's on a spine or a leaf, whether the device is in production or staging, or what site it belongs to. Answering those questions means correlating the metric with your device inventory — and if that inventory lives in a spreadsheet or a siloed IPAM tool, that correlation is manual, slow, and immediately stale.

This post covers how to solve that with NetBox: first by populating it with your device data, then by wiring it directly into the metrics pipeline so that inventory context flows automatically into every metric — without touching the collector configuration.

## The inventory problem

SolarWinds NPM lets you add custom properties to nodes — fields like `Role`, `Site`, `Tier` — that appear in dashboards and alerts. The problem is these properties are maintained manually inside NPM itself. When a device moves rack or changes function, someone has to remember to update NPM. In practice, they usually don't.

The right approach is to have **one authoritative inventory system** and make every other tool read from it. In the open stack, that's NetBox.

NetBox is not just an IP address database. It models the full operational context of a network:

- **Devices** — hostname, device type, platform, status
- **Device roles** — spine, leaf, router, firewall (your taxonomy)
- **Sites and racks** — physical location, rack unit position
- **Interfaces** — name, type, speed, connected to which peer (the cable map)
- **IP addresses and prefixes** — address plan, VRF context, VLAN assignment

All of this is exposed via a REST API with full filtering and pagination. And critically, NetBox implements the **Prometheus HTTP Service Discovery** specification — a standard way to expose scrape targets and their labels to any Prometheus-compatible collector.

## Getting data into NetBox

### The populate script (what we do in the lab)

For our static lab topology, a Python Job calls the NetBox REST API to create all 8 devices with their roles, interfaces, IP addresses, and network prefixes. The script is idempotent — it checks whether an object exists before creating it, so it can be re-run safely:

```python
def ensure(path, data, key="name"):
    existing = get_list(path, **{key: data[key]})
    if existing:
        return existing[0]
    return _request("POST", path, data)

ensure("/dcim/devices/", {
    "name": "spine1",
    "device_type": {"slug": "srlinux-ixr-d2"},
    "device_role": {"slug": "spine"},
    "platform": {"slug": "nokia-srlinux"},
    "site": {"slug": "network-lab"},
    "status": "active",
})
```

### The discovery approach (for real networks)

A static script works for a lab, but real networks change continuously. For production, the right approach is treating NetBox as a living system that stays current through automation:

- **Subnet scanning** — tools like `netdisco` can scan your address space, identify devices via SNMP or LLDP, and push discovered devices into NetBox automatically
- **LLDP-based topology discovery** — walk LLDP neighbour tables via SNMP or gNMI and automatically model cable connections in NetBox
- **CMDB sync** — if you already have a ServiceNow or Infoblox record, sync into NetBox on a schedule via the API
- **Webhooks** — NetBox fires webhooks when inventory changes; Alloy can respond by picking up a new device within minutes of it being added, with no manual reconfiguration

## Reading NetBox in Alloy

Populating NetBox is valuable on its own. The real payoff is making that inventory data flow automatically into every metric the pipeline collects.

### The netbox-sd adapter

[Grafana Alloy](https://grafana.com/oss/alloy/)'s `discovery.http` component polls any URL returning JSON in the Prometheus HTTP SD format. We run a small HTTP server (`netbox-sd`) as a Kubernetes Deployment alongside Alloy. It queries the NetBox REST API on a schedule and serves the results:

```json
[
  {
    "targets": ["192.168.0.1:161"],
    "labels": {
      "__meta_netbox_name": "spine1",
      "__meta_netbox_device_role": "spine",
      "__meta_netbox_site": "network-lab",
      "__meta_netbox_platform": "nokia-srlinux"
    }
  }
]
```

Every time it runs, the list reflects current NetBox state. No manual intervention needed.

### Alloy configuration

In Alloy's River config, `discovery.http` polls netbox-sd every five minutes:

```river
discovery.http "netbox" {
  url              = "http://netbox-sd.network-tools.svc.cluster.local:9000/targets"
  refresh_interval = "5m"
}
```

Labels prefixed with `__meta_` are available during scraping but dropped from stored metrics by default. `prometheus.relabel` promotes them to permanent metric labels:

```river
prometheus.relabel "netbox_labels" {
  rule {
    source_labels = ["__meta_netbox_name"]
    target_label  = "device"
  }
  rule {
    source_labels = ["__meta_netbox_device_role"]
    target_label  = "device_role"
  }
  rule {
    source_labels = ["__meta_netbox_site"]
    target_label  = "site"
  }
}
```

## The before and after

**Before NetBox enrichment:**
```
ifHCInOctets{instance="192.168.0.1:161", job="snmp", ifDescr="ethernet-1/1"} 4823910
```

**After NetBox enrichment:**
```
ifHCInOctets{instance="192.168.0.1:161", job="snmp", ifDescr="ethernet-1/1",
  device="spine1", device_role="spine", site="network-lab",
  platform="nokia-srlinux"} 4823910
```

Now a Grafana dashboard can show all interface errors across your leaf tier with a single label filter: `device_role="leaf"`. No manual grouping. No static node lists. Add a new leaf to NetBox, and it appears in that dashboard automatically at the next poll cycle.

## Why this matters more than SolarWinds IPAM

SolarWinds IPAM manages IP addresses, but the data doesn't flow into NPM dashboards automatically. If you want a node's site or role to appear in an alert, you go configure it manually in NPM's custom properties — separately from the IPAM record. It goes stale almost immediately.

NetBox with netbox-sd turns inventory into a live input to the metrics pipeline, not a reference document you consult after the fact. When a device changes role in NetBox, every metric label reflecting that role updates within five minutes. And it generalizes: any new collector you add reads the same netbox-sd endpoint and inherits the same labels, with no additional configuration.

---

*Next: [Part 5 — Observability with Grafana](#), where we build the dashboards that make all this data genuinely useful.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, traces, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Network Observability, NetBox, Grafana Alloy, Prometheus, Service Discovery, IPAM
