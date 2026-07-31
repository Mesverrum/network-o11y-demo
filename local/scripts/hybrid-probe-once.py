#!/usr/bin/env python3
"""Run one probe cycle from targets-laptop.yaml and push OTLP metrics."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hybrid-probe"))

from agent import emit, load_yaml, run_probe  # noqa: E402
from otel_push import load_otlp_env  # noqa: E402


def main() -> int:
    load_otlp_env()
    cfg = load_yaml(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "hybrid-probe" / "targets-laptop.yaml")
    agent_id = str(cfg.get("agent_id", "laptop"))
    region = str(cfg.get("region", "local"))
    for t in cfg.get("targets") or []:
        ok, ms, reason = run_probe(t)
        emit(agent_id, region, t, ok, ms)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {t.get('name')}: {ms:.0f}ms ({reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
