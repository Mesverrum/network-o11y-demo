# ktranslate dashboards (00–04)

Git-tracked **v2 manifests** synced from the live Grafana Cloud stack (marcnetterfield1 Network Lab folder). These are the canonical copies for agents and for mirroring into [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana).

| File | UID | Layout |
|------|-----|--------|
| `00 Ktranslate Architecture.json` | `ktranslate-architecture` | GridLayout |
| `01 Ktranslate Health.json` | `ktranslate-health` | TabsLayout |
| `02 Network Flow Summary.json` | `ktranslate-flow-summary` | RowsLayout |
| `03 Network Device Summary.json` | `ktranslate-device-summary` | TabsLayout |
| `04 Network Device Details.json` | `ktranslate-device-details` | TabsLayout |

## Refresh

Requires `GRAFANA_URL` + `GRAFANA_TOKEN` in `local/.env`:

```bash
make -C local dash-live-sync
```

Pulls live manifests → updates this folder → refreshes `local/docs/dashboard-query-lessons.md` and `local/docs/ktranslate-dashboard-live-snapshot.md`.

## Import (v2 — preserves TabsLayout)

Use gcx or HTTP v2 PUT — **not** legacy `POST /api/dashboards/db` on tabbed boards.

```bash
gcx --context <your-stack> --agent dashboards update ktranslate-device-details \
  -f local/dashboards/ktranslate/04\ Network\ Device\ Details.json
```

Or import via Grafana UI: **Dashboards → New → Import** and paste JSON.

## Skills

Dashboard design and hardware expansion guides: [`docs/grafana-network-dashboard-skills-README.md`](../../../docs/grafana-network-dashboard-skills-README.md).
