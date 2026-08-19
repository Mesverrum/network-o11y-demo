#!/usr/bin/env python3
"""Split legacy combined sm-access.token into sm-probe-laptop.env + sm-probe-colocated.env."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "local" / "state"
SRC = STATE / "sm-access.token"


def main() -> int:
    if not SRC.is_file():
        print(f"No {SRC}", file=sys.stderr)
        return 1
    text = SRC.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^#\s*aws", text, maxsplit=1)
    laptop_block = parts[0]
    aws_block = parts[1] if len(parts) > 1 else ""

    def extract(block: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    laptop = extract(laptop_block)
    aws = extract(aws_block)
    if not laptop.get("api_token"):
        print("No laptop api_token found in sm-access.token", file=sys.stderr)
        return 1
    if not aws.get("api_token"):
        print("No aws api_token found (add '# aws creds' section)", file=sys.stderr)
        return 1

    def write_env(path: Path, data: dict[str, str]) -> None:
        path.write_text(
            f"api_token={data['api_token']}\n"
            f"api_server={data.get('api_server', 'synthetic-monitoring-grpc-us-east-0.grafana.net:443')}\n",
            encoding="utf-8",
        )

    write_env(STATE / "sm-probe-laptop.env", laptop)
    write_env(STATE / "sm-probe-colocated.env", aws)
    print("Optional: save Config Access tokens to local/state/sm-api.token for check CRUD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
