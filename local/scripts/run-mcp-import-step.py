#!/usr/bin/env python3
"""Print grafana_api_request MCP arguments for one ktranslate dashboard import step."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / ".dash-payloads" / "ktranslate-import"
NAMESPACE = "stacks-1061129"
BASE = f"/apis/dashboard.grafana.app/v2/namespaces/{NAMESPACE}/dashboards"
RESOURCE_VERSIONS = {
    "masjqrs": "2078196201357836592",
    "be8hpir89dds0a": "2078196194814722845",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run-mcp-import-step.py <uid>", file=sys.stderr)
        return 1
    uid = sys.argv[1]
    payload = json.loads((ROOT / f"{uid}.json").read_text(encoding="utf-8"))
    if uid in RESOURCE_VERSIONS:
        payload["metadata"]["resourceVersion"] = RESOURCE_VERSIONS[uid]
        args = {
            "endpoint": f"{BASE}/{uid}",
            "method": "PUT",
            "body": json.dumps(payload, separators=(",", ":")),
        }
    else:
        args = {
            "endpoint": BASE,
            "method": "POST",
            "body": json.dumps(payload, separators=(",", ":")),
        }
    print(json.dumps(args, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
