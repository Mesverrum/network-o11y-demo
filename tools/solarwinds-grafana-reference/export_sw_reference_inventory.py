#!/usr/bin/env python3
"""Bulk-export SolarWinds classic views (+ modern dashboards) via SWIS REST :17774.

Reads gitignored swis.env (SW_HOST / SW_USER / SW_PASSWORD / optional SW_PORT).
Writes the same raw/ tree as Export-SwReferenceInventory.ps1 for
build_grafana_reference_docs.py.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def safe_name(name: str, fallback: str = "unnamed") -> str:
    s = name or fallback
    s = re.sub(r'[<>:"/\\|?*\[\]]+', "_", s)
    s = re.sub(r"\s+", " ", s).strip() or fallback
    return s


class SwisRest:
    def __init__(self, host: str, user: str, password: str, port: int = 17774) -> None:
        self.base = f"https://{host}:{port}/SolarWinds/InformationService/v3/Json"
        token = base64.b64encode(f"{user}:{password}".encode("ascii")).decode("ascii")
        self.headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.ctx = ssl._create_unverified_context()

    def _request(self, method: str, url: str, body: bytes | None = None) -> Any:
        req = urllib.request.Request(url, data=body, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"HTTP {e.code} {url}: {detail}") from e

    def query(self, swql: str, **params: Any) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"query": swql}
        if params:
            payload["parameters"] = params
        data = self._request(
            "POST",
            f"{self.base}/Query",
            json.dumps(payload).encode("utf-8"),
        )
        return list((data or {}).get("results") or [])

    def invoke(self, entity: str, verb: str, args: list[Any]) -> Any:
        url = f"{self.base}/Invoke/{entity}/{verb}"
        return self._request("POST", url, json.dumps(args).encode("utf-8"))


def export_classic(swis: SwisRest, root: Path) -> int:
    views_root = root / "classic-views"
    views_root.mkdir(parents=True, exist_ok=True)
    views = swis.query(
        """
        SELECT
          v.ViewID, v.ViewTitle, v.ViewKey, v.ViewType, v.ViewGroup, v.ViewGroupName,
          v.ViewGroupPosition, v.ViewIcon, v.Columns,
          v.Column1Width, v.Column2Width, v.Column3Width,
          v.Column4Width, v.Column5Width, v.Column6Width,
          v.Customizable, v.NOCView, v.NOCViewRotationInterval
        FROM Orion.Views v
        ORDER BY v.ViewGroupName, v.ViewGroupPosition, v.ViewTitle
        """
    )
    index: list[dict[str, Any]] = []
    total = len(views)
    for i, v in enumerate(views, 1):
        group = v.get("ViewGroupName") or "NoViewGroup"
        title = v.get("ViewTitle") or f"view_{v.get('ViewID')}"
        folder = views_root / safe_name(str(group)) / safe_name(str(title))
        folder.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{total}] classic view {v.get('ViewID')} :: {title}", flush=True)

        resources = swis.query(
            """
            SELECT ResourceID, ViewID, ViewColumn, Position,
                   ResourceName, ResourceFile, ResourceTitle, ResourceSubTitle
            FROM Orion.Resources
            WHERE ViewID = @viewId
            ORDER BY ViewColumn, Position
            """,
            viewId=int(v["ViewID"]),
        )
        resource_objs: list[dict[str, Any]] = []
        for r in resources:
            rid = int(r["ResourceID"])
            props_rows = swis.query(
                """
                SELECT PropertyName, PropertyValue
                FROM Orion.ResourceProperties
                WHERE ResourceID = @rid
                """,
                rid=rid,
            )
            prop_map = {
                str(p.get("PropertyName")): ("" if p.get("PropertyValue") is None else str(p.get("PropertyValue")))
                for p in props_rows
                if p.get("PropertyName")
            }
            resource_objs.append(
                {
                    "resourceId": rid,
                    "viewColumn": r.get("ViewColumn"),
                    "position": r.get("Position"),
                    "resourceName": r.get("ResourceName") or "",
                    "resourceFile": r.get("ResourceFile") or "",
                    "resourceTitle": r.get("ResourceTitle") or "",
                    "resourceSubTitle": r.get("ResourceSubTitle") or "",
                    "properties": prop_map,
                }
            )

        view_obj = {
            "kind": "classic-view",
            "viewId": int(v["ViewID"]),
            "viewTitle": title,
            "viewKey": v.get("ViewKey") or "",
            "viewType": v.get("ViewType"),
            "viewGroup": v.get("ViewGroup"),
            "viewGroupName": group,
            "viewGroupPosition": v.get("ViewGroupPosition"),
            "viewIcon": v.get("ViewIcon") or "",
            "columns": v.get("Columns"),
            "columnWidths": [
                v.get("Column1Width"),
                v.get("Column2Width"),
                v.get("Column3Width"),
                v.get("Column4Width"),
                v.get("Column5Width"),
                v.get("Column6Width"),
            ],
            "customizable": v.get("Customizable"),
            "nocView": v.get("NOCView"),
            "nocViewRotationInterval": v.get("NOCViewRotationInterval"),
            "resources": resource_objs,
        }
        view_path = folder / "view.json"
        view_path.write_text(json.dumps(view_obj, indent=2), encoding="utf-8")
        index.append(
            {
                "viewId": int(v["ViewID"]),
                "viewTitle": title,
                "viewGroupName": group,
                "resourceCount": len(resource_objs),
                "path": str(view_path.relative_to(root)).replace("\\", "/"),
            }
        )

    (views_root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return len(index)


def export_modern(swis: SwisRest, root: Path, include_system: bool) -> int:
    md_root = root / "modern-dashboards"
    md_root.mkdir(parents=True, exist_ok=True)
    swql = (
        "SELECT DashboardID, DisplayName, UniqueKey, IsSystem "
        "FROM Orion.Dashboards.Instances WHERE ParentID IS NULL"
    )
    if not include_system:
        swql += " AND IsSystem = 'FALSE'"
    rows = swis.query(swql)
    index: list[dict[str, Any]] = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        did = int(row["DashboardID"])
        name = row.get("DisplayName") or f"dashboard_{did}"
        print(f"[{i}/{total}] modern dashboard {did} :: {name}", flush=True)
        try:
            exported = swis.invoke("Orion.Dashboards.Instances", "Export", [did])
            # Export verb usually returns a JSON string
            if isinstance(exported, str):
                obj = json.loads(exported)
            elif isinstance(exported, dict):
                obj = exported
            else:
                obj = json.loads(json.dumps(exported))
            dash = obj.get("dashboards") or {}
            if isinstance(dash, list):
                dash = dash[0] if dash else {}
            dash_name = dash.get("name") or name
            if row.get("IsSystem"):
                dash_name = f"SYSTEM_{dash_name}"
            path = md_root / f"{did}_{safe_name(dash_name)}.json"
            path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
            index.append(
                {
                    "dashboardId": did,
                    "name": dash_name,
                    "uniqueKey": row.get("UniqueKey") or "",
                    "isSystem": bool(row.get("IsSystem")),
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                }
            )
        except Exception as e:  # noqa: BLE001 — continue inventory on per-dash failure
            print(f"  WARN failed: {e}", flush=True)
            index.append({"dashboardId": did, "name": name, "error": str(e)})

    (md_root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return len(index)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", type=Path, default=Path(__file__).with_name("swis.env"))
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--classic-only", action="store_true")
    ap.add_argument("--modern-only", action="store_true")
    ap.add_argument("--include-system-modern", action="store_true")
    args = ap.parse_args()

    env = load_env(args.env_file)
    host = env.get("SW_HOST") or ""
    user = env.get("SW_USER") or ""
    password = env.get("SW_PASSWORD") or ""
    port = int(env.get("SW_PORT") or "17774")
    if not host or not user or not password or password == "REPLACE_ME":
        raise SystemExit(f"Incomplete credentials in {args.env_file}")

    out = args.out_dir or (Path(__file__).with_name("out") / datetime.now().strftime("%Y%m%d_%H%M"))
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    swis = SwisRest(host, user, password, port)
    probe = swis.query("SELECT TOP 1 ServerName FROM Orion.Websites")
    server = probe[0].get("ServerName") if probe else "?"
    print(f"Connected to {host}:{port} ({server})", flush=True)

    classic_n = 0
    modern_n = 0
    if not args.modern_only:
        classic_n = export_classic(swis, raw)
    if not args.classic_only:
        modern_n = export_modern(swis, raw, include_system=args.include_system_modern)

    manifest = {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "hostname": host,
        "port": port,
        "serverName": server,
        "classicViews": classic_n,
        "modernDashboards": modern_n,
        "transport": "SWIS REST JSON",
    }
    (raw / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nRaw export: {raw}")
    print(
        f'Next: python "{Path(__file__).with_name("build_grafana_reference_docs.py")}" '
        f'--input "{raw}" --output "{out / "docs"}"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
