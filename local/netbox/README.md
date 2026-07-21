# NetBox Cloud (optional)

SNMP discovery works **without NetBox** using `DISCOVERY_SOURCE=cidr` in `groups/srl.env`
(the default in `groups/srl.env.sample`). Use this folder when you want inventory-driven
discovery from **NetBox Cloud**.

| Script / target | Purpose |
|-----------------|---------|
| `scripts/netbox-populate.py` | Idempotent seed: site, devices, interfaces, IPs, cables, tags |
| `scripts/update-netbox-mgmt-ips.py` | Push live clab mgmt /32s → `primary_ip4` on spine/leaf |
| `make netbox-sync` | Populate + mgmt sync (alias: `netbox-bootstrap`) |
| `make netbox-populate` | Populate only |
| `make netbox-sync-mgmt` | Mgmt IP sync only |

## Enable NetBox discovery

```bash
cp groups/srl.env.netbox.sample groups/srl.env
```

Add to `local/.env` (uncomment / fill in `.env.example` NetBox section):

```bash
NETBOX_URL=https://YOUR-TENANT.cloud.netboxapp.com
NETBOX_HOST_URL=https://YOUR-TENANT.cloud.netboxapp.com
NETBOX_API_URL=https://YOUR-TENANT.cloud.netboxapp.com/api/dcim/devices/
NETBOX_TOKEN=nbt_xxxxxxxx...
```

Then:

```bash
make generate          # bakes NETBOX_API_URL into discovery YAML
make netbox-sync       # seed Cloud + sync clab mgmt IPs
make up                # or: make discover GROUP=srl after fabric is up
```

After clab recreate (mgmt IP drift): `make netbox-sync-mgmt` then `make discover GROUP=srl`.

## Switch back to CIDR discovery

```bash
cp groups/srl.env.sample groups/srl.env
make generate
make up                # rewrites TARGETS from clab
```
