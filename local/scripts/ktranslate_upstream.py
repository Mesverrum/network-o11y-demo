#!/usr/bin/env python3
"""Resolve the KtransToGrafana checkout used as the dashboard source of truth."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

DASHBOARD_FILES = {
    "ktranslate-architecture": "00 Ktranslate Architecture.json",
    "ktranslate-health": "01 Ktranslate Health.json",
    "ktranslate-flow-summary": "02 Network Flow Summary.json",
    "ktranslate-device-summary": "03 Network Device Summary.json",
    "ktranslate-device-details": "04 Network Device Details.json",
}


def load_local_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def resolve_upstream(*, required: bool = True) -> Path:
    """Return KtransToGrafana repo path (KTRANS_UPSTREAM or ../KtransToGrafana)."""
    load_local_env()
    raw = os.environ.get("KTRANS_UPSTREAM", "").strip()
    upstream = Path(raw).expanduser().resolve() if raw else (REPO.parent / "KtransToGrafana").resolve()
    if required and not upstream.is_dir():
        raise SystemExit(
            f"KtransToGrafana checkout not found: {upstream}\n"
            "Clone it alongside network-o11y-demo or set KTRANS_UPSTREAM in local/.env"
        )
    return upstream


def dashboard_dir() -> Path:
    upstream = resolve_upstream()
    dash_dir = upstream / "dashboards"
    if not dash_dir.is_dir():
        raise SystemExit(f"missing dashboards/ in KtransToGrafana checkout: {dash_dir}")
    return dash_dir


def dashboard_paths() -> list[Path]:
    dash_dir = dashboard_dir()
    paths: list[Path] = []
    for filename in DASHBOARD_FILES.values():
        path = dash_dir / filename
        if not path.is_file():
            raise SystemExit(f"missing dashboard in KtransToGrafana: {path}")
        paths.append(path)
    return paths


def path_for_uid(uid: str) -> Path:
    filename = DASHBOARD_FILES.get(uid)
    if not filename:
        raise KeyError(uid)
    return dashboard_dir() / filename
