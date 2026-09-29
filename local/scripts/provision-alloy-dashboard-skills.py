#!/usr/bin/env python3
"""Upsert the Alloy network dashboard skill pair in Grafana Assistant."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "local"
ASSISTANT_API = "/api/plugins/grafana-assistant-app/resources/api/v1"
SKILLS = {
    "Alloy Network Dashboard — Design Patterns": (
        ROOT / "docs" / "grafana-alloy-network-dashboard-design-patterns.md"
    ),
    "Alloy Network Dashboard — Expanding for New Hardware": (
        ROOT / "docs" / "grafana-alloy-network-dashboard-expand-hardware.md"
    ),
}
STACKS = {
    "marc": ("GRAFANA_URL", "GRAFANA_TOKEN"),
    "dev": ("GRAFANA_URL_2", "GRAFANA_TOKEN_2"),
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = LOCAL / ".env"
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    env.update(os.environ)
    env["GRAFANA_URL"] = env.get("GRAFANA_URL") or env.get(
        "NETTERFIELD_GRAFANA_URL", ""
    )
    env["GRAFANA_TOKEN"] = env.get("GRAFANA_TOKEN") or env.get(
        "NETTERFIELD_GRAFANA_TOKEN", ""
    )
    return env


def request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + ASSISTANT_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:1000]}
        return exc.code, payload


def response_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def list_skills(base_url: str, token: str) -> list[dict[str, Any]]:
    code, payload = request(
        base_url, token, "GET", "/skills?scope=tenant&limit=100"
    )
    if code != 200:
        raise RuntimeError(f"list skills failed HTTP {code}: {payload}")
    data = response_data(payload)
    if isinstance(data, dict):
        skills = data.get("skills", [])
    else:
        skills = data
    if not isinstance(skills, list):
        raise RuntimeError(f"unexpected skills response: {payload}")
    return [skill for skill in skills if isinstance(skill, dict)]


def upsert_stack(label: str, base_url: str, token: str, dry_run: bool) -> None:
    existing = {str(skill.get("name")): skill for skill in list_skills(base_url, token)}
    for name, path in SKILLS.items():
        body = path.read_text(encoding="utf-8")
        body_bytes = body.encode("utf-8")
        if len(body_bytes) > 65_535:
            raise RuntimeError(f"{path.name} is {len(body_bytes)} bytes; limit is 65535")

        payload = {
            "name": name,
            "body": body,
            "scope": "tenant",
            "includeInKnowledgebase": True,
        }
        current = existing.get(name)
        action = "update" if current else "create"
        digest = hashlib.sha256(body_bytes).hexdigest()[:12]
        if dry_run:
            print(f"{label}: would {action} {name} sha256={digest}")
            continue

        if current:
            skill_id = current.get("id")
            if not skill_id:
                raise RuntimeError(f"{label}: existing {name} has no id")
            code, result = request(
                base_url,
                token,
                "PUT",
                f"/skills/{urllib.parse.quote(str(skill_id))}",
                payload,
            )
            expected = 200
        else:
            code, result = request(base_url, token, "POST", "/skills", payload)
            expected = 200
            if code == 201:
                expected = 201
        if code != expected:
            raise RuntimeError(f"{label}: {action} {name} failed HTTP {code}: {result}")
        print(f"{label}: {action}d {name} sha256={digest}")

    if not dry_run:
        names = {str(skill.get("name")) for skill in list_skills(base_url, token)}
        missing = set(SKILLS) - names
        if missing:
            raise RuntimeError(f"{label}: verification missing {sorted(missing)}")
        print(f"{label}: verified {len(SKILLS)} Alloy dashboard skills")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stack", choices=["all", *STACKS], default="all", help="target stack"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env = load_env()

    targets = STACKS if args.stack == "all" else {args.stack: STACKS[args.stack]}
    for label, (url_key, token_key) in targets.items():
        base_url = env.get(url_key, "")
        token = env.get(token_key, "")
        if not base_url or not token:
            raise SystemExit(f"{label}: need {url_key} and {token_key} in local/.env")
        upsert_stack(label, base_url, token, args.dry_run)


if __name__ == "__main__":
    main()
