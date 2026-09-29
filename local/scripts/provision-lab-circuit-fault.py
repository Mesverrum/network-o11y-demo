#!/usr/bin/env python3
"""Deploy the colocated circuit-fault webhook and provision the Grafana control board.

AWS (profile mvr):
  - Copy catalog/script/webhook/unit to the colocated host via SSM
  - systemd lab-fault-webhook on :8788 (token in /etc/lab-fault-webhook.env)
  - SG TCP/8788 + NLB listener on the existing NetBox NLB
  - HTTP API Gateway (HTTPS) → NLB :8788 so grafana.net canvas/actions can POST

Grafana (GRAFANA_URL + GRAFANA_TOKEN in local/.env):
  - Infinity datasource uid=lab-fault-webhook (token in secureJsonData)
  - Alert group Network Lab / circuit-demo (parent iface + child BGP, circuit_id labels)
  - Inhibition rule: circuit_parent suppresses circuit_child notifications (same circuit_id)
  - Dashboard uid=lab-circuit-fault: first import from build_dashboard; later runs
    GET live and only insert Graphviz/inhibit panels if missing (never rebuild
    operator edits such as gnmic BGP tables).

Usage:
  python3 local/scripts/provision-lab-circuit-fault.py
  python3 local/scripts/provision-lab-circuit-fault.py --host-only
  python3 local/scripts/provision-lab-circuit-fault.py --grafana-only
"""
from __future__ import annotations

from grafana_env import apply_grafana_aliases

import argparse
import base64
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ENV_PATH = ROOT / ".env"
CATALOG = ROOT / "fixtures" / "lab-circuits.json"
FILES = [
    ROOT / "fixtures" / "lab-circuits.json",
    ROOT / "scripts" / "lab-circuit-fault.sh",
    ROOT / "scripts" / "lab-fault-webhook.py",
    ROOT / "scripts" / "lab-fault-webhook.service",
]
PROFILE, REGION = "mvr", "us-east-1"
INSTANCE_TAG = "network-o11y-demo-colocated-lab"
SG_ID = "sg-0d4a29db498435db0"
NLB_NAME = "network-o11y-netbox-ui"
NB_HOST = "network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com"
FAULT_PORT = 8788
TG_NAME = "network-o11y-demo-lab-fault"
APIGW_NAME = "network-o11y-lab-fault"
DS_UID = "lab-fault-webhook"
DS_NAME = "Lab circuit fault webhook"
DASH_UID = "lab-circuit-fault"
FOLDER_UID = "network-lab"
RULE_GROUP = "Network Lab / circuit-demo"
INHIBIT_NAME = "lab-circuit-parent-inhibits-child"
PROM_DS = "grafanacloud-prom"
REMOTE_ROOT = "/opt/network-o11y-demo/local"
HOST_ENV = "/etc/lab-fault-webhook.env"
UNIT_DST = "/etc/systemd/system/lab-fault-webhook.service"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return apply_grafana_aliases(env)
def upsert_env(key: str, value: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=.*$", text, flags=re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def aws(*args: str, check: bool = True) -> str:
    exe = shutil.which("aws") or shutil.which("aws.exe") or "aws"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["AWS_CLI_FILE_ENCODING"] = "utf-8"
    run = subprocess.run(
        [exe, "--profile", PROFILE, "--region", REGION, *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=env,
    )
    if check and run.returncode != 0:
        err = (run.stderr or run.stdout or "").strip()
        raise RuntimeError(f"aws {' '.join(args[:6])} -> {run.returncode}: {err[-2000:]}")
    return run.stdout or ""


def instance_id() -> str:
    out = aws(
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:Name,Values={INSTANCE_TAG}",
        "Name=instance-state-name,Values=running",
        "--query",
        "Reservations[0].Instances[0].InstanceId",
        "--output",
        "text",
    ).strip()
    if not out or out == "None":
        raise RuntimeError("no colocated instance")
    return out


def ssm_run(iid: str, commands: list[str], timeout: int = 180, label: str = "ssm") -> str:
    params_path = ROOT / f".ssm-lab-fault-{label}.json"
    params_path.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    cid = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        iid,
        "--document-name",
        "AWS-RunShellScript",
        "--timeout-seconds",
        str(timeout),
        "--parameters",
        f"file://{params_path.as_posix()}",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ).strip()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(4)
        inv = json.loads(
            aws(
                "ssm",
                "get-command-invocation",
                "--command-id",
                cid,
                "--instance-id",
                iid,
                "--output",
                "json",
            )
        )
        status = inv.get("Status")
        if status in {"Success", "Failed", "Cancelled", "TimedOut"}:
            stdout = inv.get("StandardOutputContent") or ""
            stderr = inv.get("StandardErrorContent") or ""
            if status != "Success":
                raise RuntimeError(stderr or stdout or status)
            return stdout
    raise RuntimeError(f"ssm timeout {label}")


def grafana_api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:4000]}
        return exc.code, payload


def load_pna():
    spec = importlib.util.spec_from_file_location(
        "provision_network_alerts", ROOT / "scripts" / "provision-network-alerts.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def token_from_env_or_new(env: dict[str, str]) -> str:
    existing = env.get("LAB_FAULT_TOKEN") or ""
    if existing and existing not in ("REPLACE_ME", "glc_REPLACE_ME"):
        return existing
    tok = secrets.token_urlsafe(24)
    upsert_env("LAB_FAULT_TOKEN", tok)
    print(f"generated LAB_FAULT_TOKEN (prefix={tok[:6]}... len={len(tok)})")
    return tok


def ensure_sg_open() -> None:
    raw = aws(
        "ec2",
        "describe-security-groups",
        "--group-ids",
        SG_ID,
        "--query",
        f"SecurityGroups[0].IpPermissions[?FromPort==`{FAULT_PORT}`].IpRanges[].CidrIp",
        "--output",
        "json",
    )
    cidrs = json.loads(raw or "[]")
    if "0.0.0.0/0" in cidrs:
        print(f"SG already allows 0.0.0.0/0 on :{FAULT_PORT}")
        return
    aws(
        "ec2",
        "authorize-security-group-ingress",
        "--group-id",
        SG_ID,
        "--ip-permissions",
        json.dumps(
            [
                {
                    "IpProtocol": "tcp",
                    "FromPort": FAULT_PORT,
                    "ToPort": FAULT_PORT,
                    "IpRanges": [
                        {
                            "CidrIp": "0.0.0.0/0",
                            "Description": "Lab Grafana Cloud circuit-fault webhook",
                        }
                    ],
                }
            ]
        ),
    )
    print(f"SG opened 0.0.0.0/0:{FAULT_PORT}")


def nlb_and_vpc() -> tuple[str, str, str]:
    lbs = json.loads(
        aws("elbv2", "describe-load-balancers", "--names", NLB_NAME, "--output", "json")
    )
    lb = (lbs.get("LoadBalancers") or [None])[0]
    if not lb:
        raise RuntimeError(f"NLB {NLB_NAME} not found")
    return lb["LoadBalancerArn"], lb["DNSName"], lb["VpcId"]


def ensure_nlb_listener(iid: str) -> str:
    lb_arn, dns, vpc_id = nlb_and_vpc()
    listeners = json.loads(
        aws("elbv2", "describe-listeners", "--load-balancer-arn", lb_arn, "--output", "json")
    )
    for lis in listeners.get("Listeners") or []:
        if int(lis.get("Port") or 0) == FAULT_PORT:
            print(f"NLB listener :{FAULT_PORT} already exists")
            return dns
    tgs = json.loads(aws("elbv2", "describe-target-groups", "--names", TG_NAME, "--output", "json", check=False) or "{}")
    groups = tgs.get("TargetGroups") or []
    if groups:
        tg_arn = groups[0]["TargetGroupArn"]
    else:
        created = json.loads(
            aws(
                "elbv2",
                "create-target-group",
                "--name",
                TG_NAME,
                "--protocol",
                "TCP",
                "--port",
                str(FAULT_PORT),
                "--vpc-id",
                vpc_id,
                "--target-type",
                "instance",
                "--health-check-protocol",
                "TCP",
                "--health-check-port",
                str(FAULT_PORT),
                "--healthy-threshold-count",
                "2",
                "--unhealthy-threshold-count",
                "2",
                "--output",
                "json",
            )
        )
        tg_arn = created["TargetGroups"][0]["TargetGroupArn"]
        print("created target group", TG_NAME)
    aws(
        "elbv2",
        "register-targets",
        "--target-group-arn",
        tg_arn,
        "--targets",
        f"Id={iid},Port={FAULT_PORT}",
        check=False,
    )
    aws(
        "elbv2",
        "create-listener",
        "--load-balancer-arn",
        lb_arn,
        "--protocol",
        "TCP",
        "--port",
        str(FAULT_PORT),
        "--default-actions",
        json.dumps([{"Type": "forward", "TargetGroupArn": tg_arn}]),
    )
    print(f"created NLB listener :{FAULT_PORT}")
    return dns


def ensure_apigw(http_origin: str, grafana_origin: str) -> str:
    apis = json.loads(aws("apigatewayv2", "get-apis", "--output", "json"))
    existing = next((a for a in apis.get("Items") or [] if a.get("Name") == APIGW_NAME), None)
    cors = {
        "AllowOrigins": [grafana_origin, "http://localhost"],
        "AllowMethods": ["GET", "POST", "OPTIONS"],
        "AllowHeaders": ["Authorization", "Content-Type", "X-Lab-Fault-Token"],
        "MaxAge": 300,
    }
    if existing:
        api_id = existing["ApiId"]
        aws(
            "apigatewayv2",
            "update-api",
            "--api-id",
            api_id,
            "--cors-configuration",
            json.dumps(cors),
            check=False,
        )
        print("reusing API Gateway", api_id)
    else:
        created = json.loads(
            aws(
                "apigatewayv2",
                "create-api",
                "--name",
                APIGW_NAME,
                "--protocol-type",
                "HTTP",
                "--cors-configuration",
                json.dumps(cors),
                "--output",
                "json",
            )
        )
        api_id = created["ApiId"]
        print("created API Gateway", api_id)

    ints = json.loads(aws("apigatewayv2", "get-integrations", "--api-id", api_id, "--output", "json"))
    integ = next((i for i in ints.get("Items") or [] if i.get("IntegrationType") == "HTTP_PROXY"), None)
    uri = http_origin.rstrip("/") + "/{proxy}"
    if integ:
        integ_id = integ["IntegrationId"]
        aws(
            "apigatewayv2",
            "update-integration",
            "--api-id",
            api_id,
            "--integration-id",
            integ_id,
            "--integration-uri",
            uri,
            check=False,
        )
    else:
        created_i = json.loads(
            aws(
                "apigatewayv2",
                "create-integration",
                "--api-id",
                api_id,
                "--integration-type",
                "HTTP_PROXY",
                "--integration-method",
                "ANY",
                "--payload-format-version",
                "1.0",
                "--integration-uri",
                uri,
                "--output",
                "json",
            )
        )
        integ_id = created_i["IntegrationId"]

    routes = json.loads(aws("apigatewayv2", "get-routes", "--api-id", api_id, "--output", "json"))
    keys = {r.get("RouteKey") for r in routes.get("Items") or []}
    for route_key in ("ANY /{proxy+}",):
        if route_key in keys:
            continue
        aws(
            "apigatewayv2",
            "create-route",
            "--api-id",
            api_id,
            "--route-key",
            route_key,
            "--target",
            f"integrations/{integ_id}",
        )
    stages = json.loads(aws("apigatewayv2", "get-stages", "--api-id", api_id, "--output", "json"))
    if not any(s.get("StageName") == "$default" for s in stages.get("Items") or []):
        aws(
            "apigatewayv2",
            "create-stage",
            "--api-id",
            api_id,
            "--stage-name",
            "$default",
            "--auto-deploy",
        )
    url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com"
    print("API Gateway HTTPS", url)
    return url


def deploy_host(iid: str, token: str, dash_url: str) -> None:
    chunks: list[str] = ["set -euo pipefail", f"mkdir -p {REMOTE_ROOT}/scripts {REMOTE_ROOT}/fixtures"]
    for src in FILES:
        rel = src.relative_to(ROOT).as_posix()
        dest = f"{REMOTE_ROOT}/{rel}"
        b64 = base64.b64encode(src.read_bytes()).decode()
        chunks.append(f"echo {b64} | base64 -d > {dest}")
        if dest.endswith(".sh") or dest.endswith(".py"):
            chunks.append(f"chmod +x {dest}")
            chunks.append(f"sed -i 's/\\r$//' {dest}")
    service_b64 = base64.b64encode((ROOT / "scripts" / "lab-fault-webhook.service").read_bytes()).decode()
    env_lines = "\n".join(
        [
            f"LAB_FAULT_TOKEN={token}",
            "LAB_FAULT_BIND=0.0.0.0",
            f"LAB_FAULT_PORT={FAULT_PORT}",
            f"LAB_CIRCUITS_FILE={REMOTE_ROOT}/fixtures/lab-circuits.json",
            f"LAB_FAULT_SCRIPT={REMOTE_ROOT}/scripts/lab-circuit-fault.sh",
            f"LAB_FAULT_DASH_URL={dash_url}",
        ]
    )
    env_b64 = base64.b64encode(env_lines.encode()).decode()
    chunks.extend(
        [
            f"echo {service_b64} | base64 -d > {UNIT_DST}",
            f"sed -i 's/\\r$//' {UNIT_DST}",
            f"echo {env_b64} | base64 -d > {HOST_ENV}",
            f"chmod 600 {HOST_ENV}",
            "systemctl daemon-reload",
            "systemctl enable --now lab-fault-webhook",
            "systemctl restart lab-fault-webhook",
            "sleep 1",
            "systemctl is-active lab-fault-webhook",
            f"curl -sf http://127.0.0.1:{FAULT_PORT}/healthz || true",
        ]
    )
    out = ssm_run(iid, chunks, timeout=180, label="deploy")
    print(out.strip()[-1500:] or "(host deploy ok)")


def upsert_infinity(env: dict[str, str], token: str, http_url: str, https_url: str) -> None:
    host = urllib.parse.urlparse(http_url).hostname or NB_HOST
    https_host = urllib.parse.urlparse(https_url).hostname or ""
    payload = {
        "uid": DS_UID,
        "name": DS_NAME,
        "type": "yesoreyeram-infinity-datasource",
        "access": "proxy",
        "url": http_url.rstrip("/"),
        "basicAuth": False,
        "jsonData": {
            "auth_method": "bearerToken",
            "allowedHosts": [
                host,
                f"{host}:{FAULT_PORT}",
                http_url.rstrip("/"),
                https_host,
                https_url.rstrip("/"),
            ],
            "oauthPassThru": False,
            "allowDangerousHTTPMethods": True,
        },
        "secureJsonData": {"bearerToken": token},
    }
    code, existing = grafana_api(env, "GET", f"/api/datasources/uid/{DS_UID}")
    if code == 200 and isinstance(existing, dict):
        payload["id"] = existing["id"]
        code2, out = grafana_api(env, "PUT", f"/api/datasources/{existing['id']}", payload)
        action = "updated"
    else:
        code2, out = grafana_api(env, "POST", "/api/datasources", payload)
        action = "created"
    if code2 not in (200, 201):
        raise RuntimeError(f"datasource {action} failed HTTP {code2}: {out}")
    print(f"{action} datasource uid={DS_UID}")


def iface_oper_down_expr(device: str, iface: str) -> str:
    """Physical or .0 subinterface oper-down. No regex escapes (Mimir rejects \\.)."""
    job = 'job="alloy-snmp"'
    a = f'snmp_ifOperStatus{{{job},device_name="{device}",if_interface_name="{iface}"}} == 2'
    b = f'snmp_ifOperStatus{{{job},device_name="{device}",if_interface_name="{iface}.0"}} == 2'
    return f"({a}) or ({b})"


def wan_bgp_expr(spec: dict, *, down_only: bool = False) -> str:
    """Alloy topology-tier BGP (snmp_tBgpPeerNgConnState).

    Exact IPv4 matchers only — Mimir rejects PromQL regex ``\\.``. TIMOS
    established is numeric 6 (no string ConnState label on this path).
    """
    clauses: list[str] = []
    for peer in spec.get("bgp_peers") or []:
        device = peer["device_name"]
        addr = peer.get("tBgpPeerNgAddress") or ""
        peer_as = str(peer.get("peer_as") or "")
        parts: list[str] = []
        if addr:
            parts.append(
                f'snmp_tBgpPeerNgConnState{{job="alloy-snmp",device_name="{device}",tBgpPeerNgAddress="{addr}"}}'
            )
        if peer_as:
            parts.append(
                f'snmp_tBgpPeerNgConnState{{job="alloy-snmp",device_name="{device}",peer_as="{peer_as}"}}'
            )
        if not parts:
            continue
        joined = " or ".join(parts)
        if down_only:
            clauses.append(f"({joined}) != 6")
        else:
            clauses.append(f"({joined})")
    return " or ".join(clauses) if clauses else (
        'snmp_tBgpPeerNgConnState{job="alloy-snmp",device_name="none"}'
    )


def circuit_rules(pna, grafana_url: str, catalog: dict) -> list[dict[str, Any]]:
    rules = []
    for cid, spec in (catalog.get("circuits") or {}).items():
        if not spec.get("bgp_peers"):
            continue
        node, iface = spec["node"], spec["iface"]
        parent = {
            "uid": f"cd-parent-{cid.lower()}",
            "title": f"Circuit parent down {cid}",
            "expr": iface_oper_down_expr(node, iface),
            "for": "30s",
            "severity": "critical",
            "summary": f"WAN circuit {cid} parent {node} {iface} is oper-down",
            "description": (
                "Admin-disable or link-down on the catalogued WAN port (physical or .0). "
                "Parent for notification inhibit (child alerts share circuit_id)."
            ),
            "labels": {
                "domain": "interfaces",
                "role": "circuit_parent",
                "circuit_id": cid,
                "site": spec.get("site") or "",
                "demo": "circuit-inhibit",
            },
            "per_device": True,
        }
        peer_node = spec.get("peer_node") or ""
        peer_iface = spec.get("peer_iface") or ""
        child_parts = []
        if peer_node and peer_iface:
            child_parts.append(iface_oper_down_expr(peer_node, peer_iface))
        child_parts.append(f"({wan_bgp_expr(spec, down_only=True)})")
        child = {
            "uid": f"cd-child-{cid.lower()}",
            "title": f"Circuit child {cid}",
            "expr": " or ".join(child_parts),
            "for": "30s",
            "severity": "warning",
            "summary": f"Downstream of {cid} is down ({{ $labels.device_name }} {{ $labels.if_interface_name }})",
            "description": (
                "Far-end WAN iface oper-down and/or BGP not established. Notifications "
                "are inhibited while the parent (same circuit_id) is firing."
            ),
            "labels": {
                "domain": "routing",
                "role": "circuit_child",
                "circuit_id": cid,
                "site": spec.get("site") or "",
                "demo": "circuit-inhibit",
            },
            "per_device": True,
        }
        rules.append(
            pna.build_rule(
                parent,
                grafana_url=grafana_url,
                source="alloy",
                dash_uid=DASH_UID,
                detail_uid="alloy-device-details",
            )
        )
        rules.append(
            pna.build_rule(
                child,
                grafana_url=grafana_url,
                source="alloy",
                dash_uid=DASH_UID,
                detail_uid="alloy-device-details",
            )
        )
    return rules


def provision_alerts(env: dict[str, str], catalog: dict) -> None:
    pna = load_pna()
    rules = circuit_rules(pna, env["GRAFANA_URL"], catalog)
    body = {"title": RULE_GROUP, "interval": 30, "rules": rules}
    path = (
        f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/"
        + urllib.parse.quote(RULE_GROUP, safe="")
    )
    status, out = grafana_api(env, "PUT", path, body)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT rule group -> {status}: {out}")
    out_path = ROOT / "fixtures" / "lab-circuit-alert-rules.json"
    out_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print(f"Provisioned {len(rules)} circuit-demo rules")


def grafana_namespace(env: dict[str, str]) -> str:
    if env.get("GRAFANA_NAMESPACE"):
        return env["GRAFANA_NAMESPACE"]
    host = urllib.parse.urlparse(env["GRAFANA_URL"]).hostname or ""
    if host.startswith("networko11ydev."):
        return "stacks-1544961"
    return "stacks-1061129"


def provision_inhibit(env: dict[str, str]) -> None:
    ns = grafana_namespace(env)
    base = f"/apis/notifications.alerting.grafana.app/v1beta1/namespaces/{ns}/inhibitionrules"
    spec = {
        "sourceMatchers": [
            {"label": "role", "type": "=", "value": "circuit_parent"},
        ],
        "targetMatchers": [
            {"label": "role", "type": "=", "value": "circuit_child"},
        ],
        "equal": ["circuit_id"],
    }
    body = {
        "apiVersion": "notifications.alerting.grafana.app/v1beta1",
        "kind": "InhibitionRule",
        "metadata": {"name": INHIBIT_NAME, "namespace": ns},
        "spec": spec,
    }
    code, existing = grafana_api(env, "GET", f"{base}/{INHIBIT_NAME}")
    if code == 200 and isinstance(existing, dict):
        body["metadata"] = existing.get("metadata", body["metadata"])
        code2, out = grafana_api(env, "PUT", f"{base}/{INHIBIT_NAME}", body)
        action = "updated"
    else:
        code2, out = grafana_api(env, "POST", base, body)
        action = "created"
        if code2 >= 400:
            body["spec"] = {
                "source_matchers": spec["sourceMatchers"],
                "target_matchers": spec["targetMatchers"],
                "equal": spec["equal"],
            }
            code2, out = grafana_api(env, "POST", base, body)
    if code2 not in (200, 201):
        print(f"WARN inhibit {action} HTTP {code2}: {out}")
        print("Parent/child alerts are still provisioned; notifications will not be inhibited until this API succeeds (Grafana 13+).")
        return
    print(f"{action} inhibition rule {INHIBIT_NAME} ns={ns}")


def _prom_target(expr: str, ref: str = "A", legend: str = "__auto") -> dict:
    return {
        "refId": ref,
        "datasource": {"type": "prometheus", "uid": PROM_DS},
        "expr": expr,
        "legendFormat": legend,
        "instant": False,
        "range": True,
        "editorMode": "code",
    }


def _infinity_target(path: str, ref: str = "A") -> dict:
    return {
        "refId": ref,
        "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": DS_UID},
        "type": "json",
        "source": "url",
        "url": path,
        "url_options": {"method": "GET", "data": ""},
        "format": "table",
        "parser": "backend",
        "root_selector": "circuits",
        "columns": [
            {"selector": "circuit_id", "text": "circuit_id", "type": "string"},
            {"selector": "admin_state", "text": "admin_state", "type": "string"},
            {"selector": "node", "text": "node", "type": "string"},
            {"selector": "iface", "text": "iface", "type": "string"},
            {"selector": "description", "text": "description", "type": "string"},
        ],
    }


GNMI_BGP_STATE = (
    "gnmi_bgp_neighbors_srl_nokia_network_instance:"
    "network_instance_protocols_srl_nokia_bgp:bgp_neighbor_session_state"
)

# Static DOT: colocated HQ + two WAN circuits. Parent/child is the talk track.
CIRCUIT_TOPOLOGY_DOT = r"""digraph wan_lab {
  rankdir=LR;
  splines=true;
  bgcolor="transparent";
  pad="0.2";
  nodesep=0.45;
  ranksep=0.9;
  node [
    shape=box
    style="filled,rounded"
    fontname="Helvetica"
    fontsize=11
    fontcolor="#111827"
    fillcolor="#ffffff"
    color="#334155"
    penwidth=1.6
    margin="0.18,0.12"
  ];
  edge [fontname="Helvetica" fontsize=9 fontcolor="#1f2937" color="#64748b" penwidth=1.4];

  subgraph cluster_hq {
    label="HQ  (BGP AS 201)";
    style=rounded;
    color="#1e40af";
    fontsize=13;
    fontcolor="#1e40af";
    bgcolor="#eff6ff";

    spine1 [
      color="#1e40af"
      penwidth=2.2
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="4">
          <TR><TD><FONT COLOR="#1e40af"><B>spine1</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">WAN hub + RR</FONT></TD></TR>
          <TR><TD><FONT COLOR="#1e40af">eth-1/3 WAN-HQ-BR1</FONT></TD></TR>
          <TR><TD><FONT COLOR="#0f766e">eth-1/4 WAN-HQ-BR2</FONT></TD></TR>
        </TABLE>
      >
    ];
    leaf1 [
      fillcolor="#f8fafc"
      color="#94a3b8"
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
          <TR><TD><FONT COLOR="#64748b"><B>leaf1</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#94a3b8">HQ Clos (workshop hunt)</FONT></TD></TR>
        </TABLE>
      >
    ];
    leaf2 [
      fillcolor="#f8fafc"
      color="#94a3b8"
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
          <TR><TD><FONT COLOR="#64748b"><B>leaf2</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#94a3b8">HQ Clos</FONT></TD></TR>
        </TABLE>
      >
    ];
    spine1 -> leaf1 [style=dashed color="#94a3b8" label=" fabric "];
    spine1 -> leaf2 [style=dashed color="#94a3b8"];
  }

  subgraph cluster_br1 {
    label="Branch 1  (AS 103)";
    style=rounded;
    color="#b45309";
    fontsize=13;
    fontcolor="#b45309";
    bgcolor="#fff7ed";

    leafbr1 [
      color="#b45309"
      penwidth=2.2
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="4">
          <TR><TD><FONT COLOR="#b45309"><B>leaf-br1</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">branch-edge</FONT></TD></TR>
          <TR><TD><FONT COLOR="#b45309">eth-1/49 WAN</FONT></TD></TR>
        </TABLE>
      >
    ];
  }

  subgraph cluster_br2 {
    label="Branch 2  (AS 104)";
    style=rounded;
    color="#0f766e";
    fontsize=13;
    fontcolor="#0f766e";
    bgcolor="#f0fdfa";

    leafbr2 [
      color="#0f766e"
      penwidth=2.2
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="4">
          <TR><TD><FONT COLOR="#0f766e"><B>leaf-br2</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">branch-edge</FONT></TD></TR>
          <TR><TD><FONT COLOR="#0f766e">eth-1/49 WAN</FONT></TD></TR>
        </TABLE>
      >
    ];
  }

  spine1 -> leafbr1 [
    color="#b45309"
    penwidth=2.4
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#b45309"><B>WAN-HQ-BR1</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">192.168.31.0/31  eBGP</FONT></TD></TR>
        <TR><TD><FONT COLOR="#b91c1c"><B>PARENT</B></FONT><FONT COLOR="#374151"> HQ port down</FONT></TD></TR>
        <TR><TD><FONT COLOR="#c2410c"><B>CHILD</B></FONT><FONT COLOR="#374151"> branch port / BGP</FONT></TD></TR>
      </TABLE>
    >
  ];
  spine1 -> leafbr2 [
    color="#0f766e"
    penwidth=2.4
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#0f766e"><B>WAN-HQ-BR2</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">192.168.41.0/31  eBGP</FONT></TD></TR>
        <TR><TD><FONT COLOR="#b91c1c"><B>PARENT</B></FONT><FONT COLOR="#374151"> HQ port down</FONT></TD></TR>
        <TR><TD><FONT COLOR="#c2410c"><B>CHILD</B></FONT><FONT COLOR="#374151"> branch port / BGP</FONT></TD></TR>
      </TABLE>
    >
  ];
}
"""

INHIBIT_DOT = r"""digraph inhibit {
  rankdir=TB;
  bgcolor="transparent";
  pad="0.15";
  nodesep=0.35;
  ranksep=0.45;
  node [
    shape=box
    style="filled,rounded"
    fontname="Helvetica"
    fontsize=10
    fontcolor="#111827"
    fillcolor="#ffffff"
    color="#334155"
    penwidth=1.4
    margin="0.16,0.10"
  ];
  edge [fontname="Helvetica" fontsize=9 fontcolor="#1f2937" color="#64748b"];

  cut [
    color="#b91c1c"
    fillcolor="#fef2f2"
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#b91c1c"><B>1. Cut the circuit</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">Disable HQ WAN port</FONT></TD></TR>
      </TABLE>
    >
  ];
  both [
    color="#b45309"
    fillcolor="#fff7ed"
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#9a3412"><B>2. Both rules fire</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">Parent: HQ oper-down</FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">Child: far-end / BGP</FONT></TD></TR>
        <TR><TD><FONT COLOR="#6b7280">same circuit_id</FONT></TD></TR>
      </TABLE>
    >
  ];
  dash [
    color="#1e40af"
    fillcolor="#eff6ff"
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#1e40af"><B>Dashboard list</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">Shows parent + child</FONT></TD></TR>
      </TABLE>
    >
  ];
  am [
    color="#0f766e"
    fillcolor="#f0fdfa"
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#0f766e"><B>3. Alertmanager inhibit</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">source role=circuit_parent</FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">target role=circuit_child</FONT></TD></TR>
        <TR><TD><FONT COLOR="#0f766e"><B>equal: circuit_id</B></FONT></TD></TR>
      </TABLE>
    >
  ];
  page [
    color="#047857"
    fillcolor="#ecfdf5"
    label=<
      <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">
        <TR><TD><FONT COLOR="#047857"><B>Notify parent only</B></FONT></TD></TR>
        <TR><TD><FONT COLOR="#374151">Child page is held</FONT></TD></TR>
        <TR><TD><FONT COLOR="#6b7280">not a silence / not noData</FONT></TD></TR>
      </TABLE>
    >
  ];

  cut -> both;
  both -> dash [label=" still visible "];
  both -> am;
  am -> page [label=" notifications "];
}
"""


def _graphviz_panel(pid: int, title: str, description: str, dot: str, grid: dict) -> dict:
    return {
        "id": pid,
        "type": "grafana-graphviz-panel",
        "title": title,
        "description": description,
        "gridPos": grid,
        "pluginVersion": "0.0.5",
        "targets": [{"refId": "A"}],
        "options": {
            "inputMode": "code",
            "dotDiagram": dot,
            "layoutEngine": "dot",
            "rankDirection": "LR",
            "splineType": "true",
            "namedThresholds": [],
            "edgeOverrides": [],
            "nodeOverrides": [],
            "dotQueryConfig": {"fieldName": "dot_diagram"},
            "builderModeActions": {},
            "_assistantHelp": "",
        },
    }


def _gnmi_bgp_table(pid: int, title: str, description: str, expr: str, grid: dict) -> dict:
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "description": description,
        "gridPos": grid,
        "datasource": {"type": "prometheus", "uid": PROM_DS},
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "align": "auto",
                    "cellOptions": {"type": "auto"},
                    "inspect": False,
                },
                "mappings": [
                    {
                        "type": "value",
                        "options": {
                            "established": {"text": "ESTABLISHED", "color": "green", "index": 0},
                            "active": {"text": "ACTIVE", "color": "orange", "index": 1},
                            "openconfirm": {"text": "OPENCONFIRM", "color": "orange", "index": 2},
                            "connect": {"text": "CONNECT", "color": "red", "index": 3},
                            "idle": {"text": "IDLE", "color": "red", "index": 4},
                        },
                    }
                ],
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "State"},
                    "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}}],
                }
            ],
        },
        "options": {"cellHeight": "sm", "showHeader": True},
        "targets": [
            {
                "datasource": {"type": "prometheus", "uid": PROM_DS},
                "editorMode": "code",
                "expr": expr,
                "format": "table",
                "instant": True,
                "range": False,
                "refId": "A",
            }
        ],
        "transformations": [
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True,
                        "Value": True,
                        "__name__": True,
                        "deployment_host": True,
                        "job": True,
                        "network_instance_name": True,
                        "service_name": True,
                        "subscription_name": True,
                    },
                    "renameByName": {
                        "neighbor_peer_address": "Peer Address",
                        "source": "Device",
                        "value": "State",
                    },
                },
            }
        ],
    }


def build_dashboard(env: dict[str, str], token: str, https_url: str, catalog: dict) -> dict:
    gurl = env["GRAFANA_URL"].rstrip("/")
    base = https_url.rstrip("/")
    wan = [
        (cid, spec)
        for cid, spec in (catalog.get("circuits") or {}).items()
        if spec.get("bgp_peers")
    ]

    def get_url(cid: str, action: str) -> str:
        return (
            f"{base}/v1/circuits/{cid}?admin_state={action}"
            f"&token={urllib.parse.quote(token)}&redirect=1"
        )

    md = f"""**This is a notification-inhibit demo, not a silence.**

Two WAN circuits leave HQ `spine1` for the branch-edge leaves. Disable a HQ WAN port (Toggle, right). Alloy SNMP sees the HQ `.0` subinterface **oper-down**; the far-end `ethernet-1/49` goes down and eBGP on that `/31` drops. Each circuit has **two** alert rules that share `circuit_id` and `demo=circuit-inhibit`.

### Parent vs child (independent evaluation)

| | Parent | Child |
|---|---|---|
| `role` | `circuit_parent` | `circuit_child` |
| Severity | critical | warning |
| Fires when | HQ WAN `snmp_ifOperStatus == 2` (physical **or** `.0`) | Far-end leaf port oper-down **or** BGP not established |
| Example | `spine1 ethernet-1/3.0` | `leaf-br1 ethernet-1/49` |

Both still **fire**. The alert list on this board shows both. Inhibition only changes **who gets paged**.

### How suppression works

Grafana Alertmanager inhibit: a firing **source** (`role=circuit_parent`) holds **notifications** for a **target** (`role=circuit_child`) when `circuit_id` is equal.

- Cut **WAN-HQ-BR1** → BR1 child pages are held; **BR2 is untouched** (different `circuit_id`).
- This is **not** a mute of the child rule. If the HQ port comes back up but BGP stays down (session/config), the child notifies again — the parent is no longer firing, so inhibit lifts.
- `noData` is OK on purpose: admin-disable removes the physical IF-MIB series. Parent matches the remaining `.0`.
- Pending window is **30s**. Workshop hunt stays `leaf1 ethernet-1/1` (dashed HQ Clos) — not these WAN links.

Alloy SNMP (`job="alloy-snmp"`). BGP session tables are gnmic. Webhook `{base}`."""
    toggle_html = [
        "<p><b>Click a link to toggle the HQ WAN port</b> (new tab, then redirect back).</p>",
        "<p>Disable = <code>admin-state disable</code> on the catalogued spine port. "
        "That is the <b>parent</b> fault. Branch <code>ethernet-1/49</code> and eBGP follow.</p>",
    ]
    for cid, spec in wan:
        toggle_html.append(
            "<p><b>{cid}</b> — {node} {iface} → {peer} {pif} &nbsp; "
            '<a href="{dis}">Disable</a> &nbsp;·&nbsp; '
            '<a href="{en}">Enable</a></p>'.format(
                cid=cid,
                node=spec["node"],
                iface=spec["iface"],
                peer=spec.get("peer_node") or "",
                pif=spec.get("peer_iface") or "",
                dis=get_url(cid, "disable"),
                en=get_url(cid, "enable"),
            )
        )
    panels: list[dict[str, Any]] = [
        _graphviz_panel(
            20,
            "Colocated WAN topology",
            "HQ spine1 is the WAN hub. Orange/teal edges are the two inhibit circuits. "
            "Dashed HQ Clos (leaf1/leaf2) is the workshop hunt — not this demo.",
            CIRCUIT_TOPOLOGY_DOT,
            {"h": 14, "w": 16, "x": 0, "y": 0},
        ),
        _graphviz_panel(
            21,
            "Inhibit is notification-only",
            "Parent and child both fire. Alertmanager holds the child page while the "
            "parent for the same circuit_id is firing.",
            INHIBIT_DOT,
            {"h": 14, "w": 8, "x": 16, "y": 0},
        ),
        {
            "id": 1,
            "type": "text",
            "title": "Alert suppression strategy",
            "gridPos": {"h": 14, "w": 16, "x": 0, "y": 14},
            "options": {"mode": "markdown", "content": md},
        },
        {
            "id": 4,
            "type": "text",
            "title": "Toggle circuits",
            "description": "GET to the token-gated webhook (HTTPS). Disable = admin-down on the catalogued WAN port.",
            "gridPos": {"h": 14, "w": 8, "x": 16, "y": 14},
            "options": {"mode": "html", "content": "\n".join(toggle_html)},
            "links": [
                {"title": f"Disable {cid}", "url": get_url(cid, "disable"), "targetBlank": True}
                for cid, _ in wan
            ]
            + [
                {"title": f"Enable {cid}", "url": get_url(cid, "enable"), "targetBlank": True}
                for cid, _ in wan
            ],
        },
        {
            "id": 2,
            "type": "table",
            "title": "Circuit admin-state (webhook)",
            "description": "Infinity GET /v1/circuits via Grafana Cloud proxy",
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 28},
            "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": DS_UID},
            "targets": [_infinity_target("/v1/circuits")],
        },
        {
            "id": 3,
            "type": "alertlist",
            "title": "Circuit-demo alerts (both roles still list here)",
            "description": "Firing/pending instances with demo=circuit-inhibit. Children remain visible even when Alertmanager has inhibited their notifications.",
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 28},
            "options": {
                "viewMode": "list",
                "groupMode": "default",
                "alertName": "",
                "alertInstanceLabelFilter": "demo=circuit-inhibit",
                "stateFilter": {
                    "firing": True,
                    "pending": True,
                    "recovering": True,
                    "noData": False,
                    "normal": False,
                    "error": True,
                },
                "maxItems": 20,
                "sortOrder": 1,
                "dashboardAlerts": False,
            },
        },
    ]
    y = 36
    pid = 10
    bgp_tables = {
        "WAN-HQ-BR1": {
            "expr": (
                f'{GNMI_BGP_STATE}{{source="leaf-br1",neighbor_peer_address="192.168.31.1"}} or '
                f'{GNMI_BGP_STATE}{{source="spine1",neighbor_peer_address="192.168.21.1"}}'
            ),
            "description": (
                "gnmic bgp_neighbor_session_state (state is the value label; sample is always 1). "
                "WAN eBGP peers for the BR1 circuit."
            ),
        },
        "WAN-HQ-BR2": {
            "expr": f'{GNMI_BGP_STATE}{{source="leaf-br2",neighbor_peer_address="192.168.41.1"}}',
            "description": (
                "gnmic bgp_neighbor_session_state (state is the value label; sample is always 1). "
                "No distinct spine1-side WAN peer address is currently reported for BR2, so this "
                "shows the leaf-br2 side."
            ),
        },
    }
    for cid, spec in wan:
        node, iface = spec["node"], spec["iface"]
        panels.append(
            {
                "id": pid,
                "type": "stat",
                "title": f"{cid} oper-state",
                "description": "1=up, 2=down. Physical IF-MIB series vanish on admin-disable; .0 remains.",
                "gridPos": {"h": 6, "w": 8, "x": 0, "y": y},
                "datasource": {"type": "prometheus", "uid": PROM_DS},
                "fieldConfig": {
                    "defaults": {
                        "unit": "none",
                        "mappings": [
                            {
                                "type": "value",
                                "options": {
                                    "1": {"text": "UP", "color": "green", "index": 0},
                                    "2": {"text": "DOWN", "color": "red", "index": 1},
                                },
                            }
                        ],
                        "thresholds": {
                            "mode": "absolute",
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "red", "value": 2},
                            ],
                        },
                        "links": [
                            {
                                "title": f"Disable {cid}",
                                "url": get_url(cid, "disable"),
                                "targetBlank": True,
                            },
                            {
                                "title": f"Enable {cid}",
                                "url": get_url(cid, "enable"),
                                "targetBlank": True,
                            },
                        ],
                    }
                },
                "options": {
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background",
                    "graphMode": "none",
                    "justifyMode": "auto",
                    "textMode": "value_and_name",
                },
                "targets": [
                    _prom_target(
                        f'snmp_ifOperStatus{{job="alloy-snmp",device_name="{node}",if_interface_name="{iface}"}}',
                        legend="{{if_interface_name}}",
                    ),
                    _prom_target(
                        f'snmp_ifOperStatus{{job="alloy-snmp",device_name="{node}",if_interface_name="{iface}.0"}}',
                        ref="B",
                        legend="{{if_interface_name}}",
                    ),
                ],
            }
        )
        pid += 1
        bgp = bgp_tables.get(cid) or {
            "expr": wan_bgp_expr(spec, down_only=False),
            "description": "WAN eBGP session state.",
        }
        panels.append(
            _gnmi_bgp_table(
                pid,
                f"{cid} BGP session state",
                bgp["description"],
                bgp["expr"],
                {"h": 6, "w": 16, "x": 8, "y": y},
            )
        )
        pid += 1
        y += 6
    return {
        "uid": DASH_UID,
        "title": "Lab: WAN circuit fault + inhibit",
        "tags": ["lab", "circuit", "inhibit", "alloy"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 0,
        "refresh": "10s",
        "time": {"from": "now-1h", "to": "now"},
        "editable": True,
        "graphTooltip": 1,
        "panels": panels,
        "annotations": {"list": []},
        "templating": {
            "list": [
                {
                    "name": "flash",
                    "type": "custom",
                    "hide": 2,
                    "query": "",
                    "current": {"text": "", "value": ""},
                    "options": [{"text": "", "value": ""}],
                    "skipUrlSync": False,
                }
            ]
        },
        "links": [
            {
                "title": "Alloy Device Details",
                "type": "link",
                "url": f"{gurl}/d/alloy-device-details",
                "targetBlank": True,
            }
        ],
    }


def _insert_topology_panels(dash: dict) -> dict:
    """Add Graphviz + inhibit explainer above existing panels. Do not rewrite them."""
    panels = dash.get("panels") or []
    if any(p.get("type") == "grafana-graphviz-panel" for p in panels):
        return dash
    nid = 0
    for p in panels:
        try:
            nid = max(nid, int(p.get("id") or 0))
        except (TypeError, ValueError):
            pass
    for p in panels:
        gp = p.get("gridPos") or {}
        if "y" in gp:
            gp["y"] = int(gp["y"]) + 22
    extra = [
        _graphviz_panel(
            nid + 1,
            "Colocated WAN topology",
            "HQ spine1 is the WAN hub. Orange/teal edges are the two inhibit circuits. "
            "Dashed HQ Clos (leaf1/leaf2) is the workshop hunt — not this demo.",
            CIRCUIT_TOPOLOGY_DOT,
            {"h": 14, "w": 16, "x": 0, "y": 0},
        ),
        _graphviz_panel(
            nid + 2,
            "Inhibit is notification-only",
            "Parent and child both fire. Alertmanager holds the child page while the "
            "parent for the same circuit_id is firing.",
            INHIBIT_DOT,
            {"h": 14, "w": 8, "x": 16, "y": 0},
        ),
        {
            "id": nid + 3,
            "type": "text",
            "title": "Alert suppression strategy",
            "gridPos": {"h": 8, "w": 24, "x": 0, "y": 14},
            "options": {
                "mode": "markdown",
                "content": (
                    "**Inhibit holds notifications, not evaluation.**\n\n"
                    "Grafana Alertmanager: a firing **source** (`role=circuit_parent`) "
                    "suppresses **pages** for a **target** (`role=circuit_child`) when "
                    "`circuit_id` matches.\n\n"
                    "- Both rules still fire. This board's alert list still shows parent **and** child.\n"
                    "- Cut WAN-HQ-BR1 → only BR1 child notifications are held. BR2 is a different `circuit_id`.\n"
                    "- Not a silence and not a mute of the child rule. If the HQ port recovers but BGP stays "
                    "down, the child pages again.\n"
                    "- Admin-disable drops the physical IF-MIB series; parent matches the remaining `.0` "
                    "subinterface (`for: 30s`).\n"
                    "- Workshop hunt stays `leaf1 ethernet-1/1` (dashed HQ Clos on the left) — not these WAN links.\n"
                ),
            },
        },
    ]
    dash["panels"] = extra + panels
    return dash


def provision_dashboard(env: dict[str, str], token: str, https_url: str, catalog: dict) -> None:
    url = env["GRAFANA_URL"].rstrip("/") + f"/d/{DASH_UID}"
    code, body = grafana_api(env, "GET", f"/api/dashboards/uid/{DASH_UID}")
    if code == 200 and isinstance(body, dict) and isinstance(body.get("dashboard"), dict):
        dash = body["dashboard"]
        meta = body.get("meta") or {}
        before = json.dumps(dash.get("panels") or [], sort_keys=True)
        dash = _insert_topology_panels(dash)
        after = json.dumps(dash.get("panels") or [], sort_keys=True)
        if before != after:
            payload = {
                "dashboard": dash,
                "folderUid": meta.get("folderUid") or FOLDER_UID,
                "overwrite": True,
                "message": "add graphviz topology + inhibit explainer; keep live panels",
            }
            code2, out = grafana_api(env, "POST", "/api/dashboards/db", payload)
            if code2 not in (200, 201):
                raise RuntimeError(f"dashboard patch HTTP {code2}: {out}")
            print(f"patched live dashboard (kept operator panels) uid={DASH_UID} {url}")
        else:
            print(f"kept live dashboard uid={DASH_UID} {url}")
        template = json.loads(json.dumps(dash).replace(token, "__LAB_FAULT_TOKEN__"))
        (ROOT / "fixtures" / "lab-circuit-fault-dashboard.json").write_text(
            json.dumps(template, indent=2), encoding="utf-8"
        )
        upsert_env("LAB_FAULT_DASH_URL", url)
        return url

    dash = build_dashboard(env, token, https_url, catalog)
    template = json.loads(json.dumps(dash).replace(token, "__LAB_FAULT_TOKEN__"))
    (ROOT / "fixtures" / "lab-circuit-fault-dashboard.json").write_text(
        json.dumps(template, indent=2), encoding="utf-8"
    )
    payload = {"dashboard": dash, "folderUid": FOLDER_UID, "overwrite": True, "message": "lab circuit fault control"}
    payload["dashboard"]["id"] = None
    code, out = grafana_api(env, "POST", "/api/dashboards/db", payload)
    if code not in (200, 201):
        raise RuntimeError(f"dashboard import HTTP {code}: {out}")
    print(f"dashboard {code} uid={DASH_UID} {url}")
    upsert_env("LAB_FAULT_DASH_URL", url)
    return url


def probe_webhook(url: str, token: str) -> None:
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/circuits",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        n = len(body.get("circuits") or [])
        print(f"webhook probe OK circuits={n}")
    except Exception as exc:
        print(f"WARN webhook probe failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host-only", action="store_true")
    ap.add_argument("--grafana-only", action="store_true")
    args = ap.parse_args()

    env = load_env()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    token = token_from_env_or_new(env)
    env = load_env()
    if not args.host_only:
        if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
            raise SystemExit("GRAFANA_URL/TOKEN required in local/.env")

    gurl = (env.get("GRAFANA_URL") or "").rstrip("/")
    dash_url = env.get("LAB_FAULT_DASH_URL") or (f"{gurl}/d/{DASH_UID}" if gurl else "")
    grafana_origin = gurl

    http_url = env.get("LAB_FAULT_HTTP_URL") or f"http://{NB_HOST}:{FAULT_PORT}"
    https_url = env.get("LAB_FAULT_WEBHOOK_URL") or http_url

    if not args.grafana_only:
        iid = instance_id()
        print("instance", iid)
        deploy_host(iid, token, dash_url)
        ensure_sg_open()
        dns = ensure_nlb_listener(iid)
        http_url = f"http://{dns}:{FAULT_PORT}"
        upsert_env("LAB_FAULT_HTTP_URL", http_url)
        time.sleep(3)
        if grafana_origin:
            https_url = ensure_apigw(http_url, grafana_origin)
            upsert_env("LAB_FAULT_WEBHOOK_URL", https_url)
        probe_webhook(http_url, token)

    if not args.host_only:
        env = load_env()
        https_url = env.get("LAB_FAULT_WEBHOOK_URL") or https_url
        http_url = env.get("LAB_FAULT_HTTP_URL") or http_url
        upsert_infinity(env, token, http_url, https_url)
        provision_alerts(env, catalog)
        provision_inhibit(env)
        url = provision_dashboard(env, token, https_url, catalog)
        # Refresh host env with final dash URL
        if not args.grafana_only:
            try:
                deploy_host(instance_id(), token, url)
            except Exception as exc:
                print(f"WARN host dash-url refresh: {exc}")
        print("done")
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
