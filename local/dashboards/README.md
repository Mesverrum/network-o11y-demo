# Local-schema dashboards

These are **local-lab variants** of the `net-o11y-*` dashboards under
[`../../grafana/dashboards/`](../../grafana/dashboards/). The originals were
authored for the **AWS / EKS** path (Grafana Cloud SNMP + gNMI integrations) and
their panels are **empty against a local `local/` deployment**, because the local
ktranslate + Alloy OTLP pipeline emits different metric names and labels.

These variants are regenerated from the AWS originals by
[`../scripts/retarget-dashboards-local.py`](../scripts/retarget-dashboards-local.py)
— the AWS dashboards are **not** modified, so the AWS / EKS path is unaffected.

## Regenerate

```bash
python3 local/scripts/retarget-dashboards-local.py   # writes local/dashboards/*.json
```

## Import into your stack

Folder `network-lab`. With gcx (OAuth or token):

```bash
for f in local/dashboards/*.json; do
  jq -n --slurpfile d "$f" \
     '{dashboard: ($d[0] | del(.id)), folderUid: "network-lab", overwrite: true}' \
   | gcx --context <your-context> api /api/dashboards/db -d @- -o json
done
```

Or with the repo's HTTP importer pattern (`GRAFANA_URL` + `GRAFANA_TOKEN`).

## Schema mapping (AWS → local)

| Aspect | AWS integration path | Local ktranslate / OTLP |
|---|---|---|
| SNMP metric names | `ifHCInOctets`, `ifOperStatus`, `sysUpTime` | `kentik_snmp_ifHCInOctets`, `kentik_snmp_if_OperStatus`, `kentik_snmp_Uptime` |
| SNMP device selector | `job=~"integrations/snmp/<dev>"` | `device_name` label (single job `ktranslate-snmp-srl-<host>`) |
| SNMP interface label | `ifDescr` | `if_Description` (e.g. `ethernet-1/1`) |
| gNMI job label | `job="gnmic"` | `job="network-topology-exporter"` |
| gNMI device label | `source` | `source` (unchanged) |
| gNMI CPU / interface | `srl_cpu_*`, `srl_iface_*`, `srl_memory_*` | **not collected** (gnmic subscribes BGP + LLDP only) → remapped to `kentik_snmp_*` |
| Flow | `network_io_by_flow_bytes` | unchanged |
| Syslog (Loki) | `{job="syslog/srl", hostname=…} \| severity=~…` | `{service_name="ktranslate"}` (ktranslate `--tee_logs`; no hostname/severity stream labels) |

## Known limitations

- **BGP overlay route counts** (`net-o11y-bgp-status`): the "Overlay (loopback)
  ipv4-unicast" columns are empty by design — EVPN overlay neighbors exchange
  `evpn` AFI/SAFI routes, not `ipv4-unicast`.
- **Device Details "Model" / "OS Version"** stat tiles: the local SNMP path does
  not expose a `sysDescr` string to regex-extract; the device model is in the
  `tags_kentik_model` label instead.
- **`traffic-sankey`** retains a no-op `label_replace(..., "job",
  "integrations/snmp/(.*)")`; locally the `job` label does not match that regex,
  so `device_name` (already correct on the metric) is left untouched.
