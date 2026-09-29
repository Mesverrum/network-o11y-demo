#!/usr/bin/env python3
"""Upload the ktranslate SE demo as a Pathfinder learning path.

Uploads milestone InteractiveGuides first, then the path cover with
spec.manifest.milestones, on GRAFANA_URL_2 (networko11ydev).

Usage:
  python3 local/scripts/provision-se-pathfinder-path.py
  python3 local/scripts/provision-se-pathfinder-path.py --status draft
"""
from __future__ import annotations

from grafana_env import apply_grafana_aliases

import argparse
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "docs" / "pathfinder" / "net-o11y-ktranslate-se-path"
API_GROUP = "pathfinderbackend.ext.grafana.app/v1alpha1"
MANAGED_BY = "pathfinderbackend.ext.grafana.app/managed-by"
MANAGED_VALUE = "provision-se-pathfinder-path.py"
SOURCE_KEY = "pathfinderbackend.ext.grafana.app/source-package"
CTX = ssl.create_default_context()

TYPED_MANIFEST = {
    "type",
    "repository",
    "description",
    "milestones",
    "author",
    "category",
    "depends",
    "additionalFields",
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / "local" / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return apply_grafana_aliases(env)
def req(url: str, token: str, method: str = "GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, context=CTX, timeout=45) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw.decode("utf-8", "replace")[:500]
        raise RuntimeError(f"{e.code} {method} {url}: {parsed}") from e


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(manifest: dict) -> dict:
    extra = {k: v for k, v in manifest.items() if k not in TYPED_MANIFEST and k not in {"id", "schemaVersion", "language"}}
    author = manifest.get("author") or {}
    typed_author = {k: v for k, v in author.items() if k in {"name", "team"} and v}
    extra_author = {k: v for k, v in author.items() if k not in {"name", "team"} and v}
    if extra_author:
        extra["author"] = extra_author
    out: dict = {"type": manifest["type"]}
    if manifest.get("repository"):
        out["repository"] = manifest["repository"]
    if manifest.get("description"):
        out["description"] = manifest["description"]
    if manifest.get("category"):
        out["category"] = manifest["category"]
    if typed_author:
        out["author"] = typed_author
    if manifest.get("type") in {"path", "journey"} and manifest.get("milestones"):
        out["milestones"] = list(manifest["milestones"])
    if extra:
        out["additionalFields"] = extra
    return out


def build_spec(dir_path: Path, status: str) -> dict:
    content = load_json(dir_path / "content.json")
    manifest = load_json(dir_path / "manifest.json")
    if content["id"] != manifest["id"]:
        raise SystemExit(f"id mismatch in {dir_path}: content={content['id']} manifest={manifest['id']}")
    spec = {
        "id": content["id"],
        "title": content["title"],
        "schemaVersion": content.get("schemaVersion") or "1.0.0",
        "status": status,
        "blocks": content["blocks"],
        "manifest": build_manifest(manifest),
    }
    return spec


def upsert(base: str, ns: str, token: str, spec: dict, source_package: str) -> str:
    name = spec["id"]
    url = f"{base}/apis/{API_GROUP}/namespaces/{ns}/interactiveguides/{name}"
    collection = f"{base}/apis/{API_GROUP}/namespaces/{ns}/interactiveguides"
    annotations = {MANAGED_BY: MANAGED_VALUE, SOURCE_KEY: source_package}
    try:
        code, existing = req(url, token)
    except RuntimeError as e:
        if not str(e).startswith("404 "):
            raise
        code, existing = 404, None
    if code == 200 and isinstance(existing, dict):
        live_ann = (existing.get("metadata") or {}).get("annotations") or {}
        if live_ann.get(MANAGED_BY) not in {None, "", MANAGED_VALUE}:
            raise SystemExit(f"refusing to overwrite {name}: managed by {live_ann.get(MANAGED_BY)}")
        merged = {**live_ann, **annotations}
        rv = existing["metadata"]["resourceVersion"]
        envelope = {
            "apiVersion": API_GROUP,
            "kind": "InteractiveGuide",
            "metadata": {
                "name": name,
                "namespace": ns,
                "resourceVersion": rv,
                "annotations": merged,
            },
            "spec": spec,
        }
        req(url, token, method="PUT", body=envelope)
        return "updated"
    envelope = {
        "apiVersion": API_GROUP,
        "kind": "InteractiveGuide",
        "metadata": {"name": name, "namespace": ns, "annotations": annotations},
        "spec": spec,
    }
    req(collection, token, method="POST", body=envelope)
    return "created"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", choices=("draft", "published"), default="published")
    args = parser.parse_args()

    env = load_env()
    base = (env.get("GRAFANA_URL_2") or "").rstrip("/")
    token = env.get("GRAFANA_TOKEN_2") or ""
    if not base or not token:
        raise SystemExit("Need GRAFANA_URL_2 and GRAFANA_TOKEN_2 in local/.env")

    settings_code, settings = req(f"{base}/api/frontend/settings", token)
    ns = (settings or {}).get("namespace") if settings_code == 200 else None
    if not ns:
        raise SystemExit("could not read stack namespace from /api/frontend/settings")

    root_manifest = load_json(PACKAGE / "manifest.json")
    pkg_id = root_manifest["id"]
    milestone_ids = list(root_manifest["milestones"])
    by_id = {}
    for child in PACKAGE.iterdir():
        if not child.is_dir() or not (child / "manifest.json").exists():
            continue
        mid = load_json(child / "manifest.json")["id"]
        by_id[mid] = child
    missing = [m for m in milestone_ids if m not in by_id]
    if missing:
        raise SystemExit(f"milestone dirs missing for {missing}")

    print(f"stack {base} namespace {ns} status {args.status}")
    for mid in milestone_ids:
        spec = build_spec(by_id[mid], args.status)
        action = upsert(base, ns, token, spec, pkg_id)
        print(f"  milestone {mid} {action}")
    cover = build_spec(PACKAGE, args.status)
    action = upsert(base, ns, token, cover, pkg_id)
    print(f"  path     {pkg_id} {action}")
    print(f"open {base}/?doc=api:{pkg_id}")
    print(f"or   {base}/a/grafana-pathfinder-app?doc=api:{pkg_id}")


if __name__ == "__main__":
    main()
