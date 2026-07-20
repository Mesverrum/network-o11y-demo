"""Shared env helpers for local lab scripts."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def tester_id(default: str = "network-lab") -> str:
    load_dotenv()
    for key in ("LAB_TESTER_ID", "KTRANS_HOST"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return default
