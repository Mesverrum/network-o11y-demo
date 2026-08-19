# SolarWinds → Grafana reference export

Turn Orion **classic views** (and modern dashboards) into inventory JSON + markdown, then clone high-value views onto Grafana Cloud using the **SolarWinds datasource plugin** (`grafana-solarwinds-datasource`).

## Background

Inspired by [ViewExporter.ps1](https://github.com/Mesverrum/MyPublicWork/blob/master/ViewExporter.ps1) / private `sw_backupViews.ps1`: SWIS → view + resource metadata. Classic widgets rarely embed SWQL in `ResourceProperties`, so clones use:

1. Export layout (`view.json` column/position + resource titles)
2. Hubble confirmation (UI active / `Hubble.loadFromId`)
3. SWQL library (validated against SWIS REST `:17774`) using [OrionSDK swagger](https://solarwinds.github.io/OrionSDK/swagger-ui/) entities
4. Grafana panels with `queryType: swql_query` on the SolarWinds plugin DS

## Credentials (do not paste into chat)

Gitignored [`swis.env`](swis.env.example):

```
SW_HOST=3.88.155.134
SW_USER=grafana
SW_PASSWORD=<password>
SW_PORT=17774
```

Web UI for Hubble is on **`:8787`** (separate from SWIS `:17774`).

## Datasource on marcnetterfield1

Use the healthy **AWS-SolarWinds** datasource:

| Field | Value |
|-------|--------|
| Name | `AWS-SolarWinds` |
| UID | `cfuwljtvzdclcb` |
| URL | `https://3.88.155.134` (plugin appends `:17774`) |
| TLS | skip verification (lab self-signed) |

There is also a `SolarWinds` DS (`efuwomkm492bkd`) that may fail health checks until TLS skip is enabled.

Plugin panel target shape:

```json
{
  "refId": "A",
  "datasource": {"type": "grafana-solarwinds-datasource", "uid": "cfuwljtvzdclcb"},
  "queryType": "swql_query",
  "serviceId": "solarwinds",
  "params": {"query": "SELECT TOP 10 Caption, CPULoad FROM Orion.Nodes ORDER BY CPULoad DESC"}
}
```

## Workflow

### 1) Bulk inventory (SWIS REST)

```powershell
cd tools\solarwinds-grafana-reference
python .\export_sw_reference_inventory.py --out-dir .\out\latest
python .\build_grafana_reference_docs.py --input .\out\latest\raw --output .\out\latest\docs
```

(PowerShell alternative with SwisPowerShell: `.\Export-SwReferenceInventory.ps1`)

### 2) Hubble capture (web UI)

Requires Hubble Active in Log Adjuster on the Orion box.

```powershell
python .\capture_hubble_view.py --viewname "Current Top 10 Lists"
# -> out/hubble/current-top-10-lists/{view.html,swql.json}
```

If `swqlCount` is 0, Hubble is still useful as a “queries are live on this page” signal; use `swql_library/` fallbacks (ASMX query dump is version-dependent).

### 3) Push Grafana clone (always into SolarWinds folder)

Folder UID `cf8311my2in7kf` (**SolarWinds**) is hard-coded in `build_sw_grafana_dashboard.py` — every clone we push goes there.

```powershell
# needs GRAFANA_URL + GRAFANA_TOKEN in ../../local/.env
python .\build_sw_grafana_dashboard.py
```

### Clones pushed so far

| Dashboard | UID | Orion source | Builder |
|-----------|-----|--------------|---------|
| [SW: Current Top 10 Lists](https://marcnetterfield1.grafana.net/d/sw-current-top-10-lists/) | `sw-current-top-10-lists` | viewId **65** / ViewKey `Current Top 10 Lists` | `build_sw_grafana_dashboard.py` |
| [SW: Node Details](https://marcnetterfield1.grafana.net/d/sw-node-details-summary/) | `sw-node-details-summary` | view group **Node Details** (22 Orion subviews / tabs) | `build_sw_node_details_dashboard.py` |
| [SW: Interface Details](https://marcnetterfield1.grafana.net/d/sw-interface-details/) | `sw-interface-details` | Interface Details (Summary + Map) | `build_sw_detail_dashboards.py` |
| [SW: Volume Details](https://marcnetterfield1.grafana.net/d/sw-volume-details/) | `sw-volume-details` | Volume Details (Summary + Map) | `build_sw_detail_dashboards.py` |
| [SW: Application Details](https://marcnetterfield1.grafana.net/d/sw-application-details/) | `sw-application-details` | Application Details | `build_sw_detail_dashboards.py` |
| [SW: Component Details](https://marcnetterfield1.grafana.net/d/sw-component-details/) | `sw-component-details` | NoViewGroup → Application Component Details | `build_sw_detail_dashboards.py` |
| [SW: Alert Details](https://marcnetterfield1.grafana.net/d/sw-alert-details/) | `sw-alert-details` | NoViewGroup → Active Alert Details | `build_sw_detail_dashboards.py` |
| [SW: Application Summary](https://marcnetterfield1.grafana.net/d/sw-application-summary/) | `sw-application-summary` | NoViewGroup → Application Summary | `build_sw_summary_dashboards.py` |
| [SW: Network Top 10](https://marcnetterfield1.grafana.net/d/sw-network-top-10/) | `sw-network-top-10` | NoViewGroup → Network Top 10 | `build_sw_summary_dashboards.py` |
| [SW: NPM Summary](https://marcnetterfield1.grafana.net/d/sw-npm-summary/) | `sw-npm-summary` | NoViewGroup → NPM Summary | `build_sw_summary_dashboards.py` |

Folder: [SolarWinds](https://marcnetterfield1.grafana.net/dashboards/f/cf8311my2in7kf/solarwinds)

```powershell
python .\build_sw_grafana_dashboard.py
python .\build_sw_node_details_dashboard.py
python .\build_sw_detail_dashboards.py
python .\build_sw_summary_dashboards.py
```

**Top 10:** response time, packet loss, CPU, memory, volumes. APM / wireless / NetFlow / WPM skipped until module entities exist.

**Summary views:** Application Summary (SAM apps + component/host proxies), Network Top 10 (interface/node/volume Top XX; wireless → markdown), NPM Summary (nodes, alerts, high util/errors; map/VLAN/VRF/multicast/thwack → markdown).

**Cross-links:** every clone has a dashboard link bar to the other SW boards. Table data links are **scoped by panel** (interface tables → Interface/Node only; volume tables → Volume/Node; etc.). IDs stay in the frame and are hidden via field override (not organize-exclude) so `${__data.fields["InterfaceID"]}` resolves. Drill URLs look like `/d/sw-interface-details?var-interface_id=…`.

**Node Details:** TabsLayout with one Grafana tab per Orion subview (Summary, Vital Stats, Network, Asset Inventory, Configs, …). Orion chart widgets map to Grafana **timeseries** panels over SWIS history entities (`Orion.CPULoad`, `Orion.ResponseTime`, `Orion.NPM.InterfaceTraffic`, `Orion.VolumeUsageHistory`, …) with `DateTime` converted to time; default range is `now-2y` because lab history is older than a few hours. Tables use validated catalog fields; UI-only chrome stays markdown. Rebuild: `build_sw_node_details_dashboard.py` / `build_sw_detail_dashboards.py` (+ `sw_detail_guesses.py`).

Note: plugin-provisioned boards (**SolarWinds Top 10**, **SolarWinds Alerts**) live under General and cannot be moved via API (`Cannot save provisioned dashboard`). Our agent-built clones are writable and stay in **SolarWinds**.

## Layout

```
tools/solarwinds-grafana-reference/
  swis.env.example
  export_sw_reference_inventory.py   # SWIS REST bulk export
  Export-SwReferenceInventory.ps1    # SwisPowerShell variant
  build_grafana_reference_docs.py    # markdown catalog
  capture_hubble_view.py             # Orion web + Hubble probe
  build_sw_grafana_dashboard.py      # Top 10 Grafana upsert
  build_sw_node_details_dashboard.py # Node Details Summary upsert
  build_sw_detail_dashboards.py      # Interface/Volume/App/Component/Alert Details
  build_sw_summary_dashboards.py     # Application Summary / Network Top 10 / NPM Summary
  sw_detail_guesses.py               # SWQL + viz (table|timeseries) guesses for detail boards
  swql_library/current-top-10-lists.json
  swql_library/node-details-summary.json
  out/   # gitignored raw dumps + grafana JSON
```

## Notes / limitations

- SWIS REST port is **17774** (legacy 17778 deprecated).
- Classic ResourceProperties almost never contain SWQL; do not expect mechanical query extraction from export alone.
- Tabbed modern dashboard groups may need per-child export.
- History charts: SolarWinds datasource does not auto-filter by Grafana time picker in SWQL — expand range (dashboards default to `now-2y`) if plots look empty.
- Raw `out/` can contain internal hostnames — gitignored.
