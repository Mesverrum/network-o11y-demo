#!/usr/bin/env python3
"""Repair Fleet Traffic Δ 24h panel after BPS patch dropped offset 24h."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXED = (
    '(sum((kentik_snmp_ifHCInOctets{provider=~"$provider",device_name=~"$device_name"}) * 8 / 60) '
    '+ sum((kentik_snmp_ifHCOutOctets{provider=~"$provider",device_name=~"$device_name"}) * 8 / 60))\n'
    '- (\n'
    '  (sum((kentik_snmp_ifHCInOctets{provider=~"$provider",device_name=~"$device_name"} offset 24h) * 8 / 60) '
    '+ sum((kentik_snmp_ifHCOutOctets{provider=~"$provider",device_name=~"$device_name"} offset 24h) * 8 / 60))\n'
    '  or\n'
    '  (sum((kentik_snmp_ifHCInOctets{provider=~"$provider",device_name=~"$device_name"}) * 8 / 60) '
    '+ sum((kentik_snmp_ifHCOutOctets{provider=~"$provider",device_name=~"$device_name"}) * 8 / 60))\n'
    ')'
)


def gcx_get(uid: str) -> dict:
    out = subprocess.check_output(
        ["gcx", "--context", "commvault", "--agent", "api", f"/api/dashboards/uid/{uid}", "-o", "json"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    start = out.find("{")
    return json.loads(out[start:])


def gcx_post(body: dict) -> dict:
    tmp = ROOT / ".dash-payloads" / "_gcx-api-body.json"
    tmp.write_text(json.dumps(body), encoding="utf-8")
    try:
        out = subprocess.check_output(
            ["gcx", "--context", "commvault", "--agent", "api", "/api/dashboards/db", "-o", "json", "-d", f"@{tmp}"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        tmp.unlink(missing_ok=True)
    start = out.find("{")
    return json.loads(out[start:])


def main() -> None:
    data = gcx_get("mavgvqv")
    dash = data["dashboard"]
    meta = data.get("meta") or {}
    changed = False
    for p in dash.get("panels") or []:
        title = p.get("title") or ""
        if "24h" in title and "Fleet Traffic" in title:
            for t in p.get("targets") or []:
                if t.get("expr") != FIXED:
                    t["expr"] = FIXED
                    changed = True
    if not changed:
        print("already correct")
        return
    result = gcx_post(
        {
            "dashboard": dash,
            "folderUid": meta.get("folderUid") or "ftc8kv",
            "message": "Restore offset 24h on Fleet Traffic delta panel after BPS patch",
            "overwrite": True,
        }
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
