#!/usr/bin/env python3
"""Print OTLP / Grafana Cloud .env lines from your stack settings.

This repo does not embed your Grafana Cloud stack. Copy values from:
  Grafana Cloud → Connections → OpenTelemetry (OTLP endpoint + instance id)
  Grafana Cloud → Security → Access policies (create a token with metrics:write, logs:write, traces:write)

Usage:
  export GRAFANA_URL=https://yourstack.grafana.net
  export GC_OTLP_URL=https://otlp-gateway-prod-REGION.grafana.net/otlp
  export GC_OTLP_ACCOUNT=123456
  export GC_OTLP_KEY=glc_your_token
  python3 scripts/retarget-otlp-gc.py

Or pass --write to merge into local/.env (never commits .env).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

KEYS = ("GC_OTLP_URL", "GC_OTLP_ACCOUNT", "GC_OTLP_KEY", "GRAFANA_URL", "LAB_TESTER_ID")


def load_example_defaults() -> dict[str, str]:
    out: dict[str, str] = {}
    if EXAMPLE.is_file():
        for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def merge_env(updates: dict[str, str]) -> None:
    lines: list[str] = []
    if ENV_PATH.is_file():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen = set()
    new_lines: list[str] = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        new_lines.append(line)
    for k, v in updates.items():
        if k not in seen and v:
            new_lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update local/.env OTLP settings from env vars")
    parser.add_argument("--write", action="store_true", help="merge into local/.env")
    args = parser.parse_args()

    defaults = load_example_defaults()
    values = {k: os.environ.get(k, defaults.get(k, "")).strip() for k in KEYS}
    missing = [k for k in ("GC_OTLP_URL", "GC_OTLP_ACCOUNT", "GC_OTLP_KEY") if not values.get(k) or "REPLACE" in values[k]]
    if missing:
        print("Missing or placeholder values for:", ", ".join(missing), file=sys.stderr)
        print(__doc__ or "", file=sys.stderr)
        return 1

    print("# Add to local/.env:")
    for k in KEYS:
        if values.get(k):
            print(f"{k}={values[k]}")

    if args.write:
        merge_env({k: v for k, v in values.items() if v})
        print(f"wrote {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
