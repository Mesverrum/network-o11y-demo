#!/usr/bin/env python3
"""Sanitize Commvault-specific copy from ktranslate dashboards and re-import."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMP = ROOT / ".dash-payloads" / "ktranslate-import"
NS = "stacks-1061129"
FOLDER = "network-lab"

DS_REPLACEMENTS = {
    "grafanacloud-commvault-prom": "grafanacloud-prom",
    "grafanacloud-commvault-logs": "grafanacloud-logs",
    "grafanacloud-commvault-alert-state-history": "grafanacloud-alert-state-history",
}

# Lab-generic replacements for Health dashboard markdown
TEXT_REPLACEMENTS = [
    (
        r"Monitors \*\*ktranslate\*\* collector containers polling SNMP devices on `netgraff-in01`\.",
        "Monitors **ktranslate** collector containers polling SNMP devices in this lab.",
    ),
    (
        r"\| Container group \| Devices \|\\n\|---\|---\|\\n\| TF / NJ / USHV \| `N9K-\*`, `CV-TF-\*`, `CVNJ-\*`, `G8332-\*` \|\\n\| COE / BLR / India \| `COEProdCore`, `BLRCOESRV\*`, `CVINHYD\*`, `CVBANG1` \|\\n\\n",
        "",
    ),
    (
        r"Devices with hundreds of interfaces \(e\.g\. `COEProdCore` with 867 interfaces\) blow up batch sizes fast\.",
        "Devices with hundreds of interfaces blow up batch sizes fast.",
    ),
    (
        r"3\. \*\*Split large devices\*\* \\u2192 move `COEProdCore` and similar into a dedicated low-device-count container\.",
        "3. **Split large devices** → move high-interface-count devices into a dedicated low-device-count container.",
    ),
    (
        r"Import ktranslate dashboard from Commvault \([^)]+\)",
        "Import sanitized ktranslate dashboard for local lab",
    ),
]


def rewrite_health_help(data: dict) -> dict:
    """Replace Commvault inventory markdown in KTranslate Health text panels."""
    elements = (data.get("spec") or {}).get("elements") or {}
    overview = (
        "## KTranslate Health Dashboard\n\n"
        "Monitors **ktranslate** collector containers polling SNMP devices in this lab. "
        "Use the **Container** dropdown to filter panels to a specific container.\n\n"
        "**Reading the stats above:** all four error counters should be zero. "
        "Work top-to-bottom — upload failures drop entire batches before they reach Prometheus; "
        "0-interface counts mean individual devices are reachable but returning nothing useful.\n\n"
        "> Container IDs change on every recycle. The **Container** variable auto-discovers "
        "active containers from Loki logs."
    )
    resource = (
        "### ResourceExhausted — batch too large\n"
        "ktranslate packed too many metrics into one gRPC call and the Alloy receiver rejected it "
        "(default 4 MB limit). Devices with hundreds of interfaces blow up batch sizes fast.\n\n"
        "**Fix — choose one:**\n"
        "1. **Increase Alloy limit** → set `max_recv_msg_size_mib = 16` in the `otelcol.receiver.otlp` block.\n"
        "2. **Reduce ktranslate batch size** → lower `--max_flows_per_message` in the container command.\n"
        "3. **Split large devices** → move high-interface-count devices into a dedicated "
        "low-device-count container.\n\n"
        "---\n"
        "### Invalid UTF-8 — bad encoding in a device field\n"
        "A device OID (often `sysDescr`, `ifAlias`, or `sysContact`) returned a non-UTF-8 byte sequence. "
        "ktranslate cannot JSON-marshal it and drops the metric.\n\n"
        "**Fix:**\n"
        "1. Find the device → search Loki: `{service_name=\"ktranslate\"} |= \"invalid UTF-8\"` — "
        "the device name usually appears in the same log line.\n"
        "2. Identify the field → look for the OID or field name preceding the error.\n"
        "3. Exclude that OID in the ktranslate SNMP profile for that device type, or sanitise it "
        "with a `string_strip` transform in the profile."
    )

    for key, el in elements.items():
        try:
            content = el["spec"]["vizConfig"]["spec"]["options"]["content"]
        except (KeyError, TypeError):
            continue
        if not isinstance(content, str):
            continue
        low = content.lower()
        if "ktranslate health dashboard" in low and ("netgraff" in low or "container group" in low or "cv-" in low):
            el["spec"]["vizConfig"]["spec"]["options"]["content"] = overview
        elif "resourceexhausted" in low and ("coeprodcore" in low or "867 interfaces" in low):
            # Keep the UTF-8 section from original after our resource rewrite if present
            if "invalid utf-8" in low:
                # split and rebuild with clean resource section + existing utf8 section
                utf_idx = content.lower().find("###")
                # find second ### for Invalid UTF-8
                parts = re.split(r"(?=###\s*)", content)
                utf_parts = [p for p in parts if "invalid utf-8" in p.lower() or "invalid utf" in p.lower()]
                utf_section = utf_parts[0] if utf_parts else ""
                # normalize utf section heading emoji leftovers
                utf_section = re.sub(r"^###\s*[^\n]*Invalid UTF-8[^\n]*\n", "### Invalid UTF-8 — bad encoding in a device field\n", utf_section, flags=re.I)
                el["spec"]["vizConfig"]["spec"]["options"]["content"] = resource if not utf_section else (
                    "### ResourceExhausted — batch too large\n"
                    "ktranslate packed too many metrics into one gRPC call and the Alloy receiver rejected it "
                    "(default 4 MB limit). Devices with hundreds of interfaces blow up batch sizes fast.\n\n"
                    "**Fix — choose one:**\n"
                    "1. **Increase Alloy limit** → set `max_recv_msg_size_mib = 16` in the `otelcol.receiver.otlp` block.\n"
                    "2. **Reduce ktranslate batch size** → lower `--max_flows_per_message` in the container command.\n"
                    "3. **Split large devices** → move high-interface-count devices into a dedicated "
                    "low-device-count container.\n\n"
                    "---\n" + utf_section.lstrip()
                )
            else:
                el["spec"]["vizConfig"]["spec"]["options"]["content"] = resource
    return data


def walk_replace_strings(obj):
    """Apply text replacements to all string leaves."""
    if isinstance(obj, str):
        s = obj
        for old, new in DS_REPLACEMENTS.items():
            s = s.replace(old, new)
        for pat, repl in TEXT_REPLACEMENTS:
            s = re.sub(pat, repl, s)
        return s
    if isinstance(obj, list):
        return [walk_replace_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: walk_replace_strings(v) for k, v in obj.items()}
    return obj


def sanitize_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = walk_replace_strings(data)
    if path.name == "masjqrs.json":
        data = rewrite_health_help(data)
        data = walk_replace_strings(data)  # catch any leftovers after rewrite
    meta = data.setdefault("metadata", {})
    meta["namespace"] = NS
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = "Lab-generic ktranslate dashboards (customer-specific copy removed)"
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return data


def req(base: str, token: str, method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def upsert(base: str, token: str, dash: dict) -> None:
    name = dash["metadata"]["name"]
    title = (dash.get("spec") or {}).get("title")
    create = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards"
    status, out = req(base, token, "POST", create, dash)
    if status in (200, 201):
        print(f"{name}: created http={status} ({title})")
        return
    get_path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{name}"
    gstatus, existing = req(base, token, "GET", get_path)
    if gstatus == 200:
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash["metadata"]["resourceVersion"] = rv
    status, out = req(base, token, "PUT", get_path, dash)
    ok = 200 <= int(status) < 300
    print(f"{name}: updated http={status} ok={ok} ({title})")
    if not ok:
        print(json.dumps(out, indent=2)[:1200])
        raise SystemExit(1)


def main() -> None:
    env = ROOT / ".env"
    # load .env without printing secrets
    for line in env.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    base = os.environ.get("GRAFANA_URL", "").rstrip("/")
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not base or not token:
        raise SystemExit("missing GRAFANA_URL / GRAFANA_TOKEN in local/.env")

    # Prefer fresh Commvault exports when present, else sanitize prepared files.
    sources = {
        "mavgvqv.json": "dashboard-1784313151319.json",
        "magz6qw1.json": "dashboard-1784313137315.json",
        "be8hpir89dds0a.json": "dashboard-1784313167585.json",
        "masjqrs.json": "dashboard-1784313199685.json",
    }
    payloads = ROOT / ".dash-payloads"
    for dest_name, src_name in sources.items():
        src = payloads / src_name
        dest = IMP / dest_name
        if src.exists():
            data = json.loads(src.read_text(encoding="utf-8"))
            meta = data.setdefault("metadata", {})
            meta["name"] = dest_name.removesuffix(".json")
            dest.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    files = list(sources.keys())
    for name in files:
        path = IMP / name
        dash = sanitize_file(path)
        blob = json.dumps(dash).lower()
        leftovers = [w for w in ("commvault", "netgraff", "coeprod", "cvbang", "cvnj-", "cv-tf-", "cvinhyd") if w in blob]
        if leftovers:
            print(f"WARNING leftovers in {name}: {leftovers}")
        upsert(base, token, dash)

    print("--- post-sanitize scan ---")
    for name in files:
        text = (IMP / name).read_text(encoding="utf-8").lower()
        hits = [w for w in ("commvault", "netgraff", "coeprod", "cvbang", "cvnj-", "cv-tf", "cvinhyd") if w in text]
        print(f"{name}: {'CLEAN' if not hits else hits}")


if __name__ == "__main__":
    main()
