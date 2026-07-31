#!/usr/bin/env python3
"""Tiny SSM sync — single file or small set (under 97KB SSM limit)."""
from __future__ import annotations

import argparse
import base64
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="repo-relative paths to sync")
    parser.add_argument("-o", "--output", default="local/.ssm-sync-small.json")
    args = parser.parse_args()

    commands = ["set -euo pipefail", "ROOT=/opt/network-o11y-demo"]
    for rel in args.paths:
        rel = rel.replace("\\", "/")
        src = REPO / rel
        if not src.is_file():
            raise SystemExit(f"missing: {src}")
        dest = f"$ROOT/{rel}"
        commands.append(f'mkdir -p "$(dirname \"{dest}\")"')
        b64 = base64.b64encode(src.read_bytes()).decode()
        commands.append(f'echo {b64} | base64 -d > "{dest}"')
        if rel.endswith(".sh"):
            commands.append(f'chmod +x "{dest}"')

    out = REPO / args.output
    out.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
