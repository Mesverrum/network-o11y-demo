# ktranslate dashboards (00–04)

**Source of truth:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) `dashboards/` — not this repo.

Clone alongside `network-o11y-demo` (default path `../KtransToGrafana`) or set `KTRANS_UPSTREAM` in `local/.env`.

| File (in KtransToGrafana) | UID | Layout |
|------|-----|--------|
| `00 Ktranslate Architecture.json` | `ktranslate-architecture` | GridLayout |
| `01 Ktranslate Health.json` | `ktranslate-health` | TabsLayout |
| `02 Network Flow Summary.json` | `ktranslate-flow-summary` | RowsLayout |
| `03 Network Device Summary.json` | `ktranslate-device-summary` | TabsLayout |
| `04 Network Device Details.json` | `ktranslate-device-details` | TabsLayout |

## Workflow

1. **Edit** dashboards in the KtransToGrafana checkout (commit/push there).
2. **Push** to your Grafana Cloud stack:

```bash
make -C local dash-push
```

Requires `GRAFANA_URL` + `GRAFANA_TOKEN` in `local/.env`.

3. **Drift check** (optional — compare live stack vs upstream):

```bash
make -C local dash-live-sync
```

Pulls live manifests into `local/.dash-payloads/marcnetterfield-live/` and reports `in-sync` / `drift` vs KtransToGrafana. Refreshes `local/docs/dashboard-query-lessons.md`.

## Import (v2 — preserves TabsLayout)

From the KtransToGrafana repo:

```bash
gcx --context <your-stack> --agent dashboards update ktranslate-device-details \
  -f dashboards/04\ Network\ Device\ Details.json
```

Or: `python3 scripts/push-dashboards.py` with `GRAFANA_URL` / `GRAFANA_TOKEN` set.

**Do not** use legacy `POST /api/dashboards/db` on tabbed v2 boards.

## Skills

Dashboard design guides: KtransToGrafana `skills/` (mirrored from `docs/grafana-network-dashboard-*.md` via `local/scripts/mirror-skills-to-upstream.py`).
