# Halvorsen SOC console: Grafana Assistant page kit

Turns the eight `hm-*` workflow dashboards into one interactive Assistant page on **marcnetterfield1**: a triage queue, one-step-at-a-time workflows with analyst verdicts, a computed Decide step, a hop map that grows as you follow the attacker, a merged case timeline with ATT&CK tactics, and a copyable case report. Case state lives in per-user storage.

## Files

| File | What |
|---|---|
| `PROMPT.md` | The build spec. Send first. |
| `attach/send/02a-meta-triage-case.json` | Datasource, replay note, triage leads, case timeline |
| `attach/send/02b-wf1.json` ... `02g-wf6.json` | One workflow each (sign-in, endpoint, lateral, exfil, plant floor, vehicle API) |
| `attach/02-workflows.json` | The same data in one readable file. Reference only; do not send (59 KB, past the size that stalled earlier page builds). |

Regenerate after any dashboard change, so the page and the dashboards share one source:

```
python build_dashboards.py
python build_page_kit.py
```

## Send

1. Open marcnetterfield1 in the **work** browser profile. Grafana Assistant, **Create a page**.
2. Tier picker next to the composer: turn Auto off, pick **Large**. Read it back before every send, including after a reload (the tier does not survive a reload).
3. One message per file, waiting for Stop to clear between them: `PROMPT.md`, then `02a`, `02b`, `02c`, `02d`, `02e`, `02f`, `02g`.
4. Last message: "Build it. Draft only. Do not publish or share."
5. Paste multi-line text as a clipboard paste and check the end of the composer matches the end of the file. If the composer doubled a paste, reload and insert once.
6. A "network issue" mid-stream is not a failed build. Reload the chat and check before resending.

The first **Save** creates an Unlisted page under `/a/grafana-assistant-app/pages/<slug>`. Record the slug here when it happens.

- Slug: _not created yet_

## Check after the build

The "Done when" list at the end of `PROMPT.md` is the test. Run it during an attack cycle: start after HH:32 UTC, or use **Latest attack cycle**. The first cycle with the full hop chain (workstation, jump host, engineering workstation, HMI) was 02:00 UTC on 2026-11-18.

## Confirm before anyone outside the team sees it

- Halvorsen Motors, its sites, people and domains are invented. No real automaker, customer or person is named. Recheck the built page copy, since Assistant sometimes adds examples.
- Draft on marcnetterfield1 only. Nothing is shared or published by this kit.
- The "Ask Assistant" and "Draft summary" buttons spend Assistant tokens on every click ([pricing](https://grafana.com/docs/grafana-cloud/machine-learning/assistant/pricing/)).
- Verdict suggestions are heuristics (a stat in the red, or rows where the card calls them bad). The analyst confirms every one; the page must never auto-close a lead.
- The ATT&CK technique ids come from the synthetic generator (`secgen.py`), not from a detection product.
