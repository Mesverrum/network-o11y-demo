#!/usr/bin/env python3
"""Score Alloy Cisco syslog capture + metrics → report.md."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    capture_path = Path(sys.argv[1])
    report_path = Path(sys.argv[2])
    metrics_path = Path(sys.argv[3])

    metrics = metrics_path.read_text(encoding="utf-8") if metrics_path.is_file() else ""
    entries_blob = "\n".join(
        ln for ln in metrics.splitlines() if ln.startswith("loki_source_syslog_entries_total")
    )
    errors_blob = "\n".join(
        ln
        for ln in metrics.splitlines()
        if ln.startswith("loki_source_syslog_parsing_errors_total")
    )
    empty_blob = "\n".join(
        ln
        for ln in metrics.splitlines()
        if ln.startswith("loki_source_syslog_empty_messages_total")
    )

    by_mode: dict[str, list[str]] = defaultdict(list)
    if capture_path.is_file():
        for line in capture_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            mode = (rec.get("labels") or {}).get("mode", "?")
            by_mode[mode].append(rec.get("line") or "")

    def sum_by_component(blob: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in re.finditer(r"\{([^}]*)\}\s+([0-9.eE+-]+)", blob):
            labels, val = m.group(1), float(m.group(2))
            cm = re.search(r'component_id="([^"]+)"', labels)
            key = cm.group(1) if cm else labels
            # Map component_id → short mode
            for mode in ("rfc3164_cisco", "rfc5424", "rfc3164", "raw"):
                if mode in key:
                    key = mode
                    break
            out[key] = out.get(key, 0.0) + val
        return out

    entries = sum_by_component(entries_blob)
    errors = sum_by_component(errors_blob)

    modes = ["rfc5424", "rfc3164", "rfc3164_cisco", "raw"]
    port = {
        "rfc5424": 15140,
        "rfc3164": 15141,
        "rfc3164_cisco": 15142,
        "raw": 15143,
    }

    lines: list[str] = []
    lines.append("# Alloy Cisco / non-RFC syslog lab results\n")
    lines.append(
        "Harness: `local/fixtures/alloy-cisco-syslog/` — four UDP listeners, "
        "identical payloads, Alloy `--stability.level=experimental`.\n"
    )
    lines.append("| Mode | Port | entries_total | parsing_errors | Captured lines |")
    lines.append("|------|------|---------------|----------------|----------------|")
    for mode in modes:
        n = len(by_mode.get(mode, []))
        e = int(entries.get(mode, 0))
        err = int(errors.get(mode, 0))
        lines.append(f"| `{mode}` | {port[mode]} | **{e}** | **{err}** | **{n}** |")

    # Verdict
    lines.append("\n## Verdict\n")

    def ok(mode: str) -> bool:
        return len(by_mode.get(mode, [])) > 0 or entries.get(mode, 0) > 0

    rfc5424_ok = ok("rfc5424")
    rfc3164_ok = ok("rfc3164")
    cisco_ok = ok("rfc3164_cisco")
    raw_ok = ok("raw")

    lines.append(
        f"- **rfc5424 (default):** {'accepted some lines' if rfc5424_ok else 'did **not** usefully accept Cisco-style lines'} "
        f"(entries={int(entries.get('rfc5424', 0))}, errors={int(errors.get('rfc5424', 0))}, captured={len(by_mode.get('rfc5424', []))})."
    )
    lines.append(
        f"- **rfc3164:** {'accepted some lines' if rfc3164_ok else 'little/no accept'} "
        f"(entries={int(entries.get('rfc3164', 0))}, errors={int(errors.get('rfc3164', 0))}, captured={len(by_mode.get('rfc3164', []))})."
    )
    lines.append(
        f"- **rfc3164 + `rfc3164_cisco_components` (experimental):** "
        f"{'**works** — accepted Cisco-extension lines' if cisco_ok else '**did not accept** Cisco-extension lines in this run'} "
        f"(entries={int(entries.get('rfc3164_cisco', 0))}, errors={int(errors.get('rfc3164_cisco', 0))}, captured={len(by_mode.get('rfc3164_cisco', []))})."
    )
    lines.append(
        f"- **raw (experimental):** {'**works** — accepted non-empty payloads without parsing' if raw_ok else '**failed** to accept raw payloads'} "
        f"(entries={int(entries.get('raw', 0))}, errors={int(errors.get('raw', 0))}, captured={len(by_mode.get('raw', []))})."
    )

    lines.append("\n### Practical takeaway\n")
    if cisco_ok or raw_ok:
        lines.append(
            "Cisco-style syslog **can** get into Alloy today, but only with explicit config:\n"
            "1. Prefer `syslog_format = \"rfc3164\"` + `rfc3164_cisco_components` matching the device "
            "(`service sequence-numbers`, `logging origin-id`, msec timestamps, etc.).\n"
            "2. Or use experimental `syslog_format = \"raw\"` and parse in `loki.process` "
            "(no facility/severity labels from the source).\n"
            "3. Default `rfc5424` is the wrong mode for classic IOS/NX-OS remote logging.\n"
            "4. Both cisco-components and raw require `--stability.level=experimental`.\n"
        )
    else:
        lines.append(
            "This run did **not** show successful Cisco ingest — check Alloy version, "
            "docker logs, and whether UDP reached the listeners.\n"
        )

    lines.append("\n## Metrics (raw excerpts)\n")
    lines.append("### entries_total\n```\n" + (entries_blob or "(none)") + "\n```\n")
    lines.append("### parsing_errors_total\n```\n" + (errors_blob or "(none)") + "\n```\n")
    lines.append("### empty_messages_total\n```\n" + (empty_blob or "(none)") + "\n```\n")

    lines.append("\n## Captured bodies by mode\n")
    for mode in modes:
        lines.append(f"\n### {mode} ({len(by_mode.get(mode, []))} lines)\n")
        for body in by_mode.get(mode, []):
            safe = body.replace("`", "'")[:240]
            lines.append(f"- `{safe}`")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
