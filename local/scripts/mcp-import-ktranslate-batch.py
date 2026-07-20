#!/usr/bin/env python3
"""Emit compact dashboard bodies and metadata for MCP grafana_api_request imports."""
from __future__ import annotations

import json
import sys
from pathlib import Path

NAMESPACE = "stacks-1061129"
BASE = f"/apis/dashboard.grafana.app/v2/namespaces/{NAMESPACE}/dashboards"
FILES = [
    "masjqrs.json",
    "mavgvqv.json",
    "be8hpir89dds0a.json",
    "magz6qw1.json",
]


def main() -> int:
    root = Path(__file__).resolve().parent.parent / ".dash-payloads" / "ktranslate-import"
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for name in FILES:
            payload = json.loads((root / name).read_text(encoding="utf-8"))
            body = json.dumps(payload, separators=(",", ":"))
            print(
                json.dumps(
                    {
                        "file": name,
                        "uid": payload["metadata"]["name"],
                        "title": payload["spec"]["title"],
                        "body_len": len(body),
                    }
                )
            )
        return 0

    stem = cmd.removesuffix(".json")
    path = root / f"{stem}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = json.dumps(payload, separators=(",", ":"))
    print(
        json.dumps(
            {
                "endpoint": BASE,
                "method": "POST",
                "body": body,
                "uid": payload["metadata"]["name"],
                "title": payload["spec"]["title"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
