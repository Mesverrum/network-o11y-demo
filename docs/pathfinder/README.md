# Pathfinder — ktranslate SE demo learning path

Live on [networko11ydev](https://networko11ydev.grafana.net/?doc=api:net-o11y-ktranslate-se-path). Same story as [`../ktranslate-se-demo-talk-track.md`](../ktranslate-se-demo-talk-track.md): one Grafana platform, then Assistant for **mean time to innocence**.

Custom guides stay on the stack you publish them to. They are not shared across Cloud orgs.

## Open it

| What | Where |
|------|--------|
| Start the path | https://networko11ydev.grafana.net/?doc=api:net-o11y-ktranslate-se-path |
| My learning | https://networko11ydev.grafana.net/a/grafana-pathfinder-app |
| Help sidebar | Custom guides → **Network in Grafana Cloud** |

Use the milestone arrows at the bottom (or Alt+Left / Alt+Right). Set time range to **Last 3 hours**. Stay on the ktranslate boards — not Alloy Network Fork.

## What a path is

One cover page plus six member guides. Completing a milestone fills the ring on My learning. That is different from the single-file `import-once.content.json` you used for the first click-through.

The path is the talk track. Say the open text. Collapsed sections are only if they ask. Last milestone is the SolarWinds module map.

| Milestone | Guide ID | Lands on |
|-----------|----------|----------|
| One platform | `net-o11y-one-platform` | Home |
| Architecture | `net-o11y-architecture` | `/d/ktranslate-architecture` |
| Device Summary | `net-o11y-device-summary` | `/d/ktranslate-device-summary` |
| Device Details | `net-o11y-device-details` | `/d/ktranslate-device-details` |
| Flow | `net-o11y-flow` | `/d/ktranslate-flow-summary` |
| Assistant | `net-o11y-assistant` | Device Details, then Assistant |
| If they ask | `net-o11y-if-they-ask` | SolarWinds map + #sme-network |

v1 highlights the **Network Dashboards** dropdown and the live tabs. It does not verify the dropdown menu items — those nodes are created after click and Pathfinder cannot pick them. Do not add a second highlight for the menu.

## Re-publish after JSON edits

```bash
python3 local/scripts/provision-se-pathfinder-path.py
```

Uses `GRAFANA_URL_2` / `GRAFANA_TOKEN_2`. `--status draft` keeps it in the Editor library only.

IDs use a `net-o11y-` prefix so they do not collide with bundled Pathfinder guides.

If you edit a milestone in the block editor, copy JSON back into that guide’s `content.json` so git stays the source of truth. Do not edit the path cover in the editor unless you have confirmed the save keeps `spec.manifest`.
