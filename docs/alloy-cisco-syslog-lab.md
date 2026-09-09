# Alloy Cisco / non-RFC syslog lab

**Date:** 2026-08-17 (Loki experiment) · **Update:** 2026-09-08  
**Harness:** `local/fixtures/alloy-cisco-syslog/` + `local/scripts/lab-alloy-cisco-syslog.sh`  
**Image (this experiment):** `grafana/alloy:latest` with `--stability.level=experimental`

**Product path (2026-09-08):** lab and Fleet syslog is `otelcol.receiver.syslog` with `protocol = "none"` + `on_error = "send"`. That keeps non-RFC bodies (PRI still decoded when present) without Cisco-specific parsing. Use `loki.source.syslog` `rfc3164_cisco_components` only if those extra IOS fields must be *parsed*, not just ingested. The numbers below are the older Loki-listener experiment.

## Question

Will Alloy `loki.source.syslog` accept Cisco-style (non–fully-RFC) syslogs, or does it still reject them? Rumors said a `raw` mode was added — does it work?

## Method

Four UDP listeners, **identical** payloads (7 samples: clean RFC3164-ish, classic Cisco, host-id, seq+msec, full IOS extensions, CEF, and one real RFC5424 control):

| Mode | Port | Config |
|------|------|--------|
| `rfc5424` (Alloy default) | 15140 | `syslog_format = "rfc5424"` |
| `rfc3164` | 15141 | `syslog_format = "rfc3164"` |
| `rfc3164` + Cisco extensions | 15142 | `rfc3164` + `rfc3164_cisco_components { enable_all = true }` |
| `raw` | 15143 | `syslog_format = "raw"` |

Success metric: Alloy debug counters `loki_source_syslog_entries_total` vs `loki_source_syslog_parsing_errors_total` (per `component_id`).

## Results (this run)

| Mode | entries_total | parsing_errors | Outcome |
|------|---------------|----------------|---------|
| `rfc5424` | **1** | **5** | Mostly rejects Cisco-style |
| `rfc3164` | **2** | **3** | Partial; breaks on common IOS extras |
| `rfc3164` + `rfc3164_cisco_components` | **5** | **0** | **Works** for IOS-style samples |
| `raw` | **7** | **0** | **Works** for every non-empty payload |

## Verdict

**Yes — Cisco-style syslog can ingest in Alloy now**, but **not on the default path**.

1. **Default `rfc5424` is the wrong mode** for classic IOS/NX-OS remote logging (high parse-error rate).
2. **`syslog_format = "rfc3164"` alone is not enough** when devices emit sequence numbers, origin-id hostname, or msec timestamps.
3. **Intended Cisco path:** `syslog_format = "rfc3164"` + experimental `rfc3164_cisco_components` — must **match the device** (`service sequence-numbers`, `logging origin-id hostname`, `service timestamps log datetime msec`, etc.). Mismatch → parse failures or wrong fields ([docs](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.syslog/)).
4. **`syslog_format = "raw"` works** as a blunt instrument: accepts non-RFC bodies (incl. CEF), then you parse in `loki.process`. You do **not** get facility/severity labels from the source parser.
5. Both **cisco-components** and **raw** require `--stability.level=experimental` (still experimental as of this lab).

## Product note (Alloy gap framing)

Out of the box, Alloy syslog is **RFC-strict**. Network gear often is not. The product now has knobs, but operators must:

- discover the right mode,
- run Alloy with experimental stability,
- align Cisco component flags to device config (no auto-detect),
- or accept `raw` + custom parsing (weaker structure).

That is still a **footgun vs “point gear at Alloy and logs appear.”**

## Re-run

```bash
# From WSL ext4 clone
bash local/scripts/lab-alloy-cisco-syslog.sh
# Report: local/fixtures/alloy-cisco-syslog/report.md
```

Uses host networking, metrics on `:19191`, ephemeral container `alloy-cisco-syslog-test`.
