#!/usr/bin/env python3
"""Push v2 ktranslate dashboards from KtransToGrafana to Grafana Cloud.

Thin wrapper around the upstream push script. Dashboard JSON lives in
<KtransToGrafana>/dashboards/ — not in this repo.

Requires GRAFANA_URL + GRAFANA_TOKEN in local/.env (and KTRANS_UPSTREAM if not
../KtransToGrafana).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ktranslate_upstream import load_local_env, resolve_upstream

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_local_env()
    upstream = resolve_upstream()
    script = upstream / "scripts" / "push-dashboards.py"
    if not script.is_file():
        sys.exit(f"missing upstream push script: {script}")

    env = os.environ.copy()
    for key in ("GRAFANA_URL", "GRAFANA_TOKEN", "GC_OTLP_ACCOUNT", "GRAFANA_DASHBOARD_NAMESPACE", "GRAFANA_DASHBOARD_FOLDER", "KTRANS_PUSH_SKIP"):
        value = os.environ.get(key)
        if value:
            env[key] = value

    return subprocess.call([sys.executable, str(script)], cwd=upstream, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
