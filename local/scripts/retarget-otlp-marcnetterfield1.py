#!/usr/bin/env python3
"""Create OTLP write token for marcnetterfield1 and update local/.env."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
CRED_TARGETS = [
    os.environ.get("GCLOUD_RW_API_KEY", "").strip() or None,
    "gcx:marcnetterfield1:cloud-token",
    os.environ.get("MARC_GCOM_TOKEN", "").strip() or None,
]
POLICY_NAME = "local-lab-otlp-alloy"
TOKEN_NAME = "local-lab-alloy"
STACK_ID = "1061129"
REGION = "prod-us-east-0"
OTLP_URL = "https://otlp-gateway-prod-us-east-0.grafana.net/otlp"
OTLP_ACCOUNT = "1061129"
PROM_USER = "1839247"
PROM_PUSH = "https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push"
GRAFANA_URL = "https://marcnetterfield1.grafana.net"
LAB_TESTER_ID = "marcnetterfield-lab"


def win_cred_get(target: str) -> str:
    ps = f"""
$ErrorActionPreference = 'Stop'
$code = @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Cred {{
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct CREDENTIAL {{
    public uint Flags; public uint Type; public string TargetName; public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten; public uint CredentialBlobSize;
    public IntPtr CredentialBlob; public uint Persist; public uint AttributeCount; public IntPtr Attributes;
    public string TargetAlias; public string UserName;
  }}
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  public static extern bool CredRead(string target, uint type, uint flags, out IntPtr cred);
  [DllImport("advapi32.dll", SetLastError = true)]
  public static extern void CredFree(IntPtr cred);
  public static string Get(string target) {{
    IntPtr p;
    if (!CredRead(target, 1, 0, out p)) throw new Exception("CredRead failed " + Marshal.GetLastWin32Error());
    try {{
      var c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
      byte[] b = new byte[c.CredentialBlobSize];
      Marshal.Copy(c.CredentialBlob, b, 0, (int)c.CredentialBlobSize);
      string utf8 = Encoding.UTF8.GetString(b).TrimEnd((char)0).Trim();
      if (utf8.StartsWith("glc_") || utf8.StartsWith("glsa_") || utf8.StartsWith("eyJ"))
        return utf8;
      string uni = Encoding.Unicode.GetString(b).TrimEnd((char)0).Trim();
      return string.IsNullOrEmpty(uni) ? utf8 : uni;
    }} finally {{ CredFree(p); }}
  }}
}}
"@
Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue
[Cred]::Get('{target}')
"""
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"cred read failed for {target}: {r.stderr or r.stdout}")
    token = (r.stdout or "").strip()
    if not token:
        raise RuntimeError(f"empty token for {target}")
    return token


def cloud_token() -> str:
    for target in CRED_TARGETS:
        if not target:
            continue
        if target.startswith("glc_"):
            return target
        try:
            tok = win_cred_get(target)
            print(f"using cloud token from {target}", file=sys.stderr)
            return tok
        except Exception as e:
            print(f"skip {target}: {e}", file=sys.stderr)
    raise SystemExit("No Grafana Cloud token — set MARC_GCOM_TOKEN or gcx:marcnetterfield1:cloud-token")


def gcom(token: str, method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        "https://grafana.com/api" + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"gcom {method} {path}: {e.code} {err}") from e


def upsert_env(replacements: dict[str, str]) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in replacements:
                lines.append(f"{k}={replacements[k]}")
                seen.add(k)
                continue
        lines.append(line)
    for k, v in replacements.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    cloud = cloud_token()
    otlp_key = None
    try:
        listed = gcom(
            cloud,
            "GET",
            f"/v1/accesspolicies?{urllib.parse.urlencode({'region': REGION})}",
        )
        items = (listed.get("items") if isinstance(listed, dict) else None) or []
        match = next((p for p in items if p.get("name") == POLICY_NAME), None)
        if match:
            policy_id = match["id"]
            print("reusing policy", policy_id)
        else:
            created = gcom(
                cloud,
                "POST",
                f"/v1/accesspolicies?{urllib.parse.urlencode({'region': REGION})}",
                {
                    "name": POLICY_NAME,
                    "displayName": "Local lab Alloy OTLP (marcnetterfield1)",
                    "scopes": ["metrics:write", "logs:write", "traces:write"],
                    "realms": [{"type": "stack", "identifier": STACK_ID}],
                },
            )
            policy_id = created["id"]
            print("created policy", policy_id)

        for name in (TOKEN_NAME, f"{TOKEN_NAME}-2", f"{TOKEN_NAME}-3"):
            try:
                token_obj = gcom(
                    cloud,
                    "POST",
                    f"/v1/tokens?{urllib.parse.urlencode({'region': REGION})}",
                    {
                        "name": name,
                        "displayName": name,
                        "accessPolicyId": policy_id,
                    },
                )
                otlp_key = token_obj.get("token")
                print("created token", name)
                break
            except RuntimeError as e:
                print("token create attempt failed:", e)
    except RuntimeError as e:
        print("access policy API unavailable, trying OAuth cloud token for OTLP:", e)

    if not otlp_key:
        raise SystemExit(
            "could not resolve OTLP token — set GCLOUD_RW_API_KEY (glc_ with metrics/logs/traces:write) "
            "or run gcx cloud login --cloud-token with accesspolicies scopes"
        )

    upsert_env(
        {
            "GC_OTLP_URL": OTLP_URL,
            "GC_OTLP_ACCOUNT": OTLP_ACCOUNT,
            "GC_OTLP_KEY": otlp_key,
            "GC_PROM_URL": PROM_PUSH,
            "GC_PROM_USER": PROM_USER,
            "GRAFANA_URL": GRAFANA_URL,
            "LAB_TESTER_ID": LAB_TESTER_ID,
        }
    )
    print("updated", ENV_PATH)
    print("GRAFANA_URL=", GRAFANA_URL)
    print("GC_OTLP_URL=", OTLP_URL)
    print("GC_OTLP_ACCOUNT=", OTLP_ACCOUNT)
    print("GC_PROM_USER=", PROM_USER)
    print("LAB_TESTER_ID=", LAB_TESTER_ID)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
