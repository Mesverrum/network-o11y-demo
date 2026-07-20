#!/usr/bin/env python3
"""Execute dashboard v2 imports by reading prepared MCP arg files.

Prints one JSON object per line for an outer MCP driver:
  {"uid":"...","title":"...","endpoint":"...","method":"...","body_file":"..."}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / ".dash-payloads" / "ktranslate-import"
UIDS = ["masjqrs", "mavgvqv", "be8hpir89dds0a", "magz6qw1"]


def main() -> int:
    for uid in UIDS:
        src = ROOT / f"{uid}.json"
        payload = json.loads(src.read_text(encoding="utf-8"))
        args_path = ROOT / f"_call-{uid}-args.json"
        if not args_path.exists():
            print(json.dumps({"uid": uid, "error": f"missing {args_path.name}"}))
            continue
        args = json.loads(args_path.read_text(encoding="utf-8-sig"))
        body_path = ROOT / f"_tmp-{uid}-body.json"
        body_path.write_text(args["body"], encoding="utf-8")
        print(
            json.dumps(
                {
                    "uid": uid,
                    "title": payload["spec"]["title"],
                    "endpoint": args["endpoint"],
                    "method": args["method"],
                    "body_file": str(body_path),
                    "body_len": len(args["body"]),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
