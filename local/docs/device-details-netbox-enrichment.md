# Device Details × NetBox enrichment map

### NetBox vs raw SNMP — where SoT adds value

This board is a **clone** of [04. Network Device Details](/d/ktranslate-device-details) with NetBox enrichment.
SNMP (`kentik_snmp_*`) answers *is it healthy / how busy*. NetBox answers *what is it supposed to be / where does it live / how is it wired*.

| Tab | SNMP already shows | NetBox enrichment (this board) | Deep link |
|-----|--------------------|--------------------------------|-----------|
| **Overview** | **System Info** (sysName, model, mgmt IP, uptime) | Sibling **NetBox CMDB identity** panel via Infinity REST — not joined | Device page |
| **Interfaces** | **Interface Summary** (oper, speed, bps, util) | Sibling **NetBox interfaces (SoT)** panel via Infinity REST — not joined | Device → Interfaces / IPAM |
| **Hardware Sensors** | ENTITY-SENSOR live readings | Asset identity (serial/type) — see **NetBox SoT** tab | Device inventory |
| **Connections** | LLDP/BGP/OSPF *observed* adjacencies | *Intended* cabling / circuit SoT (when modeled) — see **NetBox SoT** tab | Cables / connections |
| **Network Flow** | SNMP IP table + flow roles | Primary IP + IPAM ownership — see **NetBox SoT** tab | IPAM addresses |
| **Events** | Syslog / traps | Change window / maintenance context — see **NetBox SoT** tab | Device journal (UI) |
| **Telemetry** | Poller / profile / age | Discovery provenance — see **NetBox SoT** tab | NetBox device + Orb boards |
| **NetBox SoT** (last) | — | Talk-track + CMDB identity: site, role, type, serial, rack, tenant, iface count | Device / site / IPAM pages |

**Identity key (visual, not SQL):** SNMP `device_name` / `if_interface_name` vs NetBox `name`. SoT panels query Infinity datasource `netbox-api` (`/api/dcim/devices/?name=$instance`, `/api/dcim/interfaces/?device=$instance`). Empty NetBox → empty table; SNMP panels are unaffected.

Per-tab markdown banners were removed. Overview / Interfaces show **side-by-side** SNMP vs NetBox panels (no LEFT JOIN). Talk-track remainder is the trailing **NetBox SoT** tab.

**Public NetBox UI:** [http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000](http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000/) — login `admin` / `NETBOX_ADMIN_PASSWORD` in `local/.env` (rotate: `make -C local netbox-rotate-admin`).


## Per-tab banners

### Overview

### NetBox enrichment — Overview

**Split:** **System Info** is SNMP-only. **NetBox CMDB identity** (Infinity) sits beside it and reads live `/api/dcim/devices/?name=$instance`. No SQL join, no inventory-OTLP sidecar on this row.

| SNMP panel | NetBox panel (Infinity) |
|-----------|-------------------------|
| `sysName` / model / mgmt IP / poll interval / uptime / `sysDescr` | Site, role, status, manufacturer, type, platform, serial, primary IP, rack, NetBox ID |

**Open:** [Device in NetBox](${netbox_url}/dcim/devices/${netbox_id}/) · [Search by name](${netbox_url}/dcim/devices/?q=${instance}) · [Site](${netbox_url}/dcim/sites/?q=)


### Interfaces

### NetBox enrichment — Interfaces

**Split:** **Interface Summary** is SNMP-only. **NetBox interfaces (SoT)** (Infinity) sits beside it and reads live `/api/dcim/interfaces/?device=$instance`. Compare by name; do not LEFT JOIN.

| Live (SNMP) | SoT (NetBox Infinity) |
|-------------|----------------------|
| ifHC* counters, errors/drops, oper state | Type, enabled, description, IP count, cable id |

**Open:** [Device interfaces](${netbox_url}/dcim/interfaces/?device_id=${netbox_id}) · [IP addresses for device](${netbox_url}/ipam/ip-addresses/?device_id=${netbox_id}) · [Device](${netbox_url}/dcim/devices/${netbox_id}/)


### Hardware Sensors

### NetBox enrichment — Hardware

Sensor *readings* stay on SNMP (`kentik_snmp_entity_sensor_*`, vendor MIBs). NetBox adds **what FRU/chassis this device is** (type, serial, rack/U) so a red fan sensor maps to an asset + location, not just a sysName.

**Open:** [Device inventory](${netbox_url}/dcim/devices/${netbox_id}/) · [Rack](${netbox_url}/dcim/racks/?q=)


### Connections

### NetBox enrichment — Connections

| Observed (SNMP / gNMI) | Intended (NetBox) |
|------------------------|-------------------|
| LLDP remotes, BGP/OSPF neighbors | Cable / circuit / rear-port SoT |
| Adjacency flaps | Change control / documented peers |

When cables are modeled in NetBox, use them as the **intent** layer next to LLDP **observation**.

**Open:** [Device connections](${netbox_url}/dcim/devices/${netbox_id}/) · [Cables](${netbox_url}/dcim/cables/?device_id=${netbox_id}) · [Circuits](${netbox_url}/circuits/circuits/)


### Network Flow

### NetBox enrichment — Addressing & flow identity

SNMP IP tables + ktranslate flows show **what is talking**. NetBox IPAM shows **who owns the address** (tenant, VRF, role) and the device primary IP used for management.

**Open:** [Primary device](${netbox_url}/dcim/devices/${netbox_id}/) · [IPAM search](${netbox_url}/ipam/ip-addresses/?q=) · [Prefixes](${netbox_url}/ipam/prefixes/)


### Events

### NetBox enrichment — Events context

Syslog/traps remain the event stream. NetBox **status / tags / tenant** explain whether a flap is unexpected (production active) vs maintenance.

**Open:** [Device](${netbox_url}/dcim/devices/${netbox_id}/) · [Journal / changelog in NetBox UI](${netbox_url}/dcim/devices/${netbox_id}/)


### Telemetry

### NetBox enrichment — Provenance

| Path | Signal |
|------|--------|
| ktranslate | Continuous SNMP poll → `kentik_snmp_*` |
| Orb → Diode → NetBox | Discovery reconcile → CMDB |
| Infinity `netbox-api` | Live NetBox REST on Device Details (CMDB + interfaces) and boards 20 / 22 / 24 |
| NetBox changelog / journal | Inventory audit history (who changed what). Not a Grafana timeseries. Optional later: a recording rule from Infinity snapshots if someone wants Grafana-side history of latest counts. |

**Open:** [NetBox device](${netbox_url}/dcim/devices/${netbox_id}/) · [Orb discovery dash](/d/orb-snmp-discovery) · [NetBox SoT dash](/d/netbox-inventory-sot) · [Leadership](/d/orb-ktranslate-entity-readiness)



Dashboard: `/d/ktranslate-device-details-netbox` · Folder: `NetBox × Device Details` (`netbox-enrichment`)
