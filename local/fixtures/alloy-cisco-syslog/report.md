# Alloy Cisco / non-RFC syslog lab results

Harness: `local/fixtures/alloy-cisco-syslog/` — four UDP listeners, identical payloads, Alloy `--stability.level=experimental`.

| Mode | Port | entries_total | parsing_errors | Captured lines |
|------|------|---------------|----------------|----------------|
| `rfc5424` | 15140 | **1** | **5** | **0** |
| `rfc3164` | 15141 | **2** | **3** | **0** |
| `rfc3164_cisco` | 15142 | **5** | **0** | **0** |
| `raw` | 15143 | **7** | **0** | **0** |

## Verdict

- **rfc5424 (default):** accepted some lines (entries=1, errors=5, captured=0).
- **rfc3164:** accepted some lines (entries=2, errors=3, captured=0).
- **rfc3164 + `rfc3164_cisco_components` (experimental):** **works** — accepted Cisco-extension lines (entries=5, errors=0, captured=0).
- **raw (experimental):** **works** — accepted non-empty payloads without parsing (entries=7, errors=0, captured=0).

### Practical takeaway

Cisco-style syslog **can** get into Alloy today, but only with explicit config:
1. Prefer `syslog_format = "rfc3164"` + `rfc3164_cisco_components` matching the device (`service sequence-numbers`, `logging origin-id`, msec timestamps, etc.).
2. Or use experimental `syslog_format = "raw"` and parse in `loki.process` (no facility/severity labels from the source).
3. Default `rfc5424` is the wrong mode for classic IOS/NX-OS remote logging.
4. Both cisco-components and raw require `--stability.level=experimental`.


## Metrics (raw excerpts)

### entries_total
```
loki_source_syslog_entries_total{component_id="loki.source.syslog.raw",component_path="/"} 7
loki_source_syslog_entries_total{component_id="loki.source.syslog.rfc3164",component_path="/"} 2
loki_source_syslog_entries_total{component_id="loki.source.syslog.rfc3164_cisco",component_path="/"} 5
loki_source_syslog_entries_total{component_id="loki.source.syslog.rfc5424",component_path="/"} 1
```

### parsing_errors_total
```
loki_source_syslog_parsing_errors_total{component_id="loki.source.syslog.raw",component_path="/"} 0
loki_source_syslog_parsing_errors_total{component_id="loki.source.syslog.rfc3164",component_path="/"} 3
loki_source_syslog_parsing_errors_total{component_id="loki.source.syslog.rfc3164_cisco",component_path="/"} 0
loki_source_syslog_parsing_errors_total{component_id="loki.source.syslog.rfc5424",component_path="/"} 5
```

### empty_messages_total
```
loki_source_syslog_empty_messages_total{component_id="loki.source.syslog.raw",component_path="/"} 0
loki_source_syslog_empty_messages_total{component_id="loki.source.syslog.rfc3164",component_path="/"} 1
loki_source_syslog_empty_messages_total{component_id="loki.source.syslog.rfc3164_cisco",component_path="/"} 1
loki_source_syslog_empty_messages_total{component_id="loki.source.syslog.rfc5424",component_path="/"} 0
```


## Captured bodies by mode


### rfc5424 (0 lines)


### rfc3164 (0 lines)


### rfc3164_cisco (0 lines)


### raw (0 lines)

