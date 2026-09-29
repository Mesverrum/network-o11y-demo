"""Grafana HTTP API env aliases.

Lab scripts historically read GRAFANA_URL / GRAFANA_TOKEN. The operator .env
may instead set NETTERFIELD_GRAFANA_URL / NETTERFIELD_GRAFANA_TOKEN for the
primary marcnetterfield1 stack. Apply this after parsing .env.
"""
from __future__ import annotations


def apply_grafana_aliases(env: dict[str, str]) -> dict[str, str]:
    if not (env.get("GRAFANA_URL") or "").strip():
        env["GRAFANA_URL"] = (env.get("NETTERFIELD_GRAFANA_URL") or "").strip()
    if not (env.get("GRAFANA_TOKEN") or "").strip():
        env["GRAFANA_TOKEN"] = (env.get("NETTERFIELD_GRAFANA_TOKEN") or "").strip()
    return env
