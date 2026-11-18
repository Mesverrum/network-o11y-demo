#!/usr/bin/env python3
"""Build the Halvorsen Motors SOC analyst workflows (classic dashboard JSON).

  python3 build_dashboards.py        # write dashboards/*.json, then stage_for_gcx.py + gcx resources push

Layout contract: every workflow is a column of numbered steps. Each step is a row with a
card on the left (question, what to look at, what bad looks like, what to do next) and only
the evidence needed to answer it on the right. Blue values in tables open the next workflow
with the entity filled in.
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent / "dashboards"
DS = {"type": "loki", "uid": "${ds}"}
TAG = "halvorsen-soc"

E = '{service_name="secdemo-edr"} | json'
IDP = '{service_name="secdemo-idp"} | json'
AD = '{service_name="secdemo-ad"} | json'
FW = '{service_name="secdemo-firewall"} | json'
DNS = '{service_name="secdemo-dns"} | json'
PX = '{service_name="secdemo-proxy"} | json'
VPN = '{service_name="secdemo-vpn"} | json'
MAIL = '{service_name="secdemo-email"} | json'
OT = '{service_name="secdemo-ot"} | json'
TM = '{service_name="secdemo-telematics"} | json'
ALL = '{service_name=~"secdemo-.+"}'

TR = "${__url_time_range}"
T_TEXT = "from=${__from}&to=${__to}"

WF = {
    "triage": "hm-00-triage",
    "wf1": "hm-wf1-signin",
    "wf2": "hm-wf2-endpoint",
    "wf3": "hm-wf3-lateral",
    "wf4": "hm-wf4-exfil",
    "wf5": "hm-wf5-ot",
    "wf6": "hm-wf6-api",
    "case": "hm-case-timeline",
}


def link(wf, **params):
    """Data-link URL. Values may use ${__value.raw} or ${__data.fields.x}."""
    q = "&".join(f"var-{k}={v}" for k, v in params.items())
    return f"/d/{WF[wf]}?{q}{'&' if q else ''}{TR}"


def mdlink(label, wf, **params):
    q = "&".join(f"var-{k}={v}" for k, v in params.items())
    return f"[{label}](/d/{WF[wf]}?{q}{'&' if q else ''}{T_TEXT})"


SEV_RED = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
SEV_INFO = [{"color": "blue", "value": None}]


class Board:
    CARD_W = 7

    def __init__(self, uid, title, desc):
        self.uid, self.title, self.desc = uid, title, desc
        self.panels, self.y, self.x, self.row_h, self.pid = [], 0, 0, 0, 1
        self.left = 0
        self.card = None
        self.vars = []
        self.links = []

    def _place(self, w, h):
        if self.x + w > 24:
            self.x, self.y = self.left, self.y + self.row_h
            self.row_h = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_h = max(self.row_h, h)
        return pos

    def _add(self, p, w, h):
        p["id"] = self.pid
        self.pid += 1
        p["gridPos"] = self._place(w, h)
        p.setdefault("datasource", DS)
        self.panels.append(p)
        return p

    def _close_step(self):
        if self.x:
            self.x, self.y = 0, self.y + self.row_h
        self.row_h = 0
        if self.card is not None:
            card_y = self.card["gridPos"]["y"]
            self.card["gridPos"]["h"] = max(self.card["gridPos"]["h"], self.y - card_y)
            self.y = max(self.y, card_y + self.card["gridPos"]["h"])
        self.card, self.left = None, 0

    def row(self, title):
        self._close_step()
        p = {"type": "row", "title": title, "collapsed": False, "panels": [], "id": self.pid,
             "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}}
        self.pid += 1
        self.y += 1
        self.panels.append(p)

    def text(self, md, w=24, h=4, title=""):
        return self._add({"type": "text", "title": title, "transparent": False,
                          "options": {"mode": "markdown", "content": md}}, w, h)

    def step(self, n, title, look, bad, if_bad, if_clean, min_h=8):
        """Row plus left-hand card. Evidence panels added afterwards fill the right column."""
        self.row(f"Step {n}. {title}")
        md = (f"### {n}. {title}\n\n"
              f"**Look at:** {look}\n\n"
              f"**Suspicious if:** {bad}\n\n"
              f"**If suspicious:** {if_bad}\n\n"
              f"**If clean:** {if_clean}")
        self.card = self.text(md, w=self.CARD_W, h=min_h)
        self.left = self.CARD_W

    def stat(self, title, expr, w=4, h=4, unit="short", thresholds=None, desc=""):
        return self._add({
            "type": "stat", "title": title, "description": desc,
            "targets": [{"refId": "A", "expr": expr, "queryType": "instant", "instant": True, "range": False}],
            "fieldConfig": {"defaults": {"unit": unit, "noValue": "0",
                                         "thresholds": {"mode": "absolute", "steps": thresholds or SEV_RED},
                                         "color": {"mode": "thresholds"}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "none",
                        "textMode": "value"}}, w, h)

    def ts(self, title, exprs, w=17, h=7, unit="short", stack=False, legend="", bars=False, desc=""):
        if isinstance(exprs, str):
            exprs = [exprs]
        return self._add({
            "type": "timeseries", "title": title, "description": desc,
            "targets": [{"refId": chr(65 + i), "expr": e, "queryType": "range", "legendFormat": legend}
                        for i, e in enumerate(exprs)],
            "fieldConfig": {"defaults": {"unit": unit, "custom": {
                "drawStyle": "bars" if bars else "line", "fillOpacity": 60 if bars else 15, "lineWidth": 1,
                "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}, "overrides": []},
            "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["sum"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}, w, h)

    def table(self, title, expr, w=17, h=7, value_name="count", links=None, unit="short", desc="", sort_desc=True):
        """links: {column: (link title, url)}"""
        overrides = [{"matcher": {"id": "byName", "options": c},
                      "properties": [{"id": "links", "value": [{"title": t, "url": u}]}]}
                     for c, (t, u) in (links or {}).items()]
        overrides.append({"matcher": {"id": "byName", "options": value_name},
                          "properties": [{"id": "unit", "value": unit},
                                         {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
                                         {"id": "color", "value": {"mode": "continuous-YlRd"}}]})
        return self._add({
            "type": "table", "title": title, "description": desc,
            "targets": [{"refId": "A", "expr": expr, "queryType": "instant", "instant": True, "range": False, "legendFormat": ""}],
            "transformations": [
                {"id": "labelsToFields", "options": {"mode": "columns"}},
                {"id": "merge", "options": {}},
                {"id": "organize", "options": {"excludeByName": {"Time": True},
                                               "renameByName": {"Value": value_name, "Value #A": value_name}}},
                {"id": "sortBy", "options": {"sort": [{"field": value_name, "desc": sort_desc}]}},
            ],
            "fieldConfig": {"defaults": {"custom": {"filterable": True}, "noValue": "Nothing found"}, "overrides": overrides},
            "options": {"showHeader": True, "cellHeight": "sm"}}, w, h)

    def logs(self, title, expr, w=17, h=8, desc=""):
        if "line_format" in expr:
            expr += " | keep service_name"
        return self._add({
            "type": "logs", "title": title, "description": desc,
            "targets": [{"refId": "A", "expr": expr, "queryType": "range"}],
            "options": {"showTime": True, "showLabels": False, "showCommonLabels": False, "wrapLogMessage": True, "sortOrder": "Ascending",
                        "enableLogDetails": True, "dedupStrategy": "none", "prettifyLogMessage": False}}, w, h)

    def textbox(self, name, label, default):
        self.vars.append({"type": "textbox", "name": name, "label": label, "query": default,
                          "current": {"text": default, "value": default},
                          "options": [{"selected": True, "text": default, "value": default}]})

    def custom(self, name, label, values):
        opts = [{"text": v, "value": v, "selected": i == 0} for i, v in enumerate(values)]
        self.vars.append({"type": "custom", "name": name, "label": label, "query": ",".join(values),
                          "includeAll": False, "multi": False, "current": {"text": values[0], "value": values[0]},
                          "options": opts})

    def nav(self, title, wf, include_vars=False):
        self.links.append({"type": "link", "title": title, "url": f"/d/{WF[wf]}", "keepTime": True,
                           "includeVars": include_vars, "targetBlank": False, "asDropdown": False, "icon": "dashboard"})

    def json(self):
        self._close_step()
        ds_var = {"type": "datasource", "name": "ds", "label": "Logs", "query": "loki", "regex": "", "hide": 2,
                  "current": {"text": "grafanacloud-logs", "value": "grafanacloud-logs"}}
        links = [{"type": "link", "title": "Back to triage queue", "url": f"/d/{WF['triage']}", "keepTime": True,
                  "includeVars": False, "icon": "dashboard"}] if self.uid != WF["triage"] else []
        return {
            "uid": self.uid, "title": self.title, "description": self.desc, "tags": [TAG, "security", "demo"],
            "timezone": "browser", "schemaVersion": 39, "editable": True, "graphTooltip": 1,
            "time": {"from": "now-3h", "to": "now"}, "refresh": "1m",
            "templating": {"list": [ds_var] + self.vars},
            "links": links + self.links + [{"type": "dashboards", "tags": [TAG], "asDropdown": True, "includeVars": False,
                                            "keepTime": True, "title": "All workflows"}],
            "panels": self.panels,
        }


def header(b, use_when, you_need, goal, extra=""):
    b.text(f"**Use when:** {use_when}  \n**You need:** {you_need}  \n**Goal:** {goal}"
           + (f"\n\n{extra}" if extra else "") +
           "\n\nWork the steps in order. Each card says what to look at, what bad looks like and where to go next. "
           "Blue values in tables open the next workflow with that value filled in.", h=4)


# --------------------------------------------------------------------------- triage

def triage():
    b = Board(WF["triage"], "Halvorsen SOC / 00 Start here: triage queue",
              "Work leads top to bottom. Red means there is something to work. Click the blue name to open its workflow.")
    b.text("## Start here\n"
           "1. Work the leads **top to bottom**. They are ordered by how often they turn out to be the start of an intrusion.\n"
           "2. A **red number** means the lead has something to work. Green means skip it.\n"
           "3. In the lead's table, **click the blue value**. It opens the workflow for that lead with the user, host or asset filled in.\n"
           "4. Each workflow ends with a **Decide** step that tells you whether to escalate and which workflow comes next. "
           "Add every user, host and IP you touch to the **case timeline**.\n\n"
           "_Synthetic data. A scripted intrusion replays at the top of every UTC hour over about 30 minutes._", h=6)

    def lane(letter, title, why, wf_name, stat_title, stat_expr, tbl_title, tbl_expr, links, value_name="count", unit="short",
             thresholds=None):
        b.row(f"Lead {letter}. {title}")
        b.text(f"**Why it matters:** {why}\n\n**Work it in:** {wf_name}", w=6, h=7)
        b.stat(stat_title, stat_expr, w=4, h=7, unit=unit, thresholds=thresholds)
        b.table(tbl_title, tbl_expr, w=14, h=7, links=links, value_name=value_name, unit=unit)

    lane("A", "Suspicious sign-in",
         "Repeated MFA prompts the user did not start (MFA fatigue) are how a sprayed password becomes a working session.",
         "WF1 Suspicious sign-in",
         "Users with 5+ denied MFA pushes",
         f'count(sum by (user) (count_over_time({IDP} | event_type="user.mfa.push" | outcome="FAILURE" [$__range])) >= 5)',
         "Denied MFA pushes by user (click the user)",
         f'sum by (user) (count_over_time({IDP} | event_type="user.mfa.push" | outcome="FAILURE" [$__range])) >= 5',
         {"user": ("Open WF1 Suspicious sign-in", link("wf1", user="${__value.raw}"))}, value_name="denied pushes")

    lane("B", "Endpoint detection that was not blocked",
         "High and critical EDR detections where the action was *allowed* ran to completion. Someone has to look.",
         "WF2 Compromised endpoint",
         "Hosts with allowed high/critical detections",
         f'count(sum by (host) (count_over_time({E} | event_type="Detection" | severity=~"high|critical" | action="allowed" [$__range])))',
         "Allowed high/critical detections (click the host)",
         f'topk(20, sum by (host, user, detection_name) (count_over_time({E} | event_type="Detection" | severity=~"high|critical" | action="allowed" [$__range])))',
         {"host": ("Open WF2 Compromised endpoint", link("wf2", host="${__value.raw}", user="${__data.fields.user}"))},
         value_name="detections")

    lane("C", "Credential theft and lateral movement",
         "RC4 Kerberos service tickets (0x17). The fleet is AES-only, so RC4 requests mean someone is Kerberoasting service accounts.",
         "WF3 Lateral movement and privilege escalation",
         "Hosts requesting RC4 service tickets",
         f'count(sum by (src_host) (count_over_time({AD} | event_id="4769" | ticket_encryption="0x17" [$__range])))',
         "RC4 service tickets by source host (click the host)",
         f'sum by (src_host, user) (count_over_time({AD} | event_id="4769" | ticket_encryption="0x17" [$__range]))',
         {"src_host": ("Open WF3 Lateral movement", link("wf3", host="${__value.raw}", user="${__data.fields.user}"))},
         value_name="RC4 tickets")

    lane("D", "Large upload to file sharing",
         "Over 100 MB to a personal file-sharing site from a corporate host. Vehicle program data is the crown jewel here.",
         "WF4 Data exfiltration",
         "Users over 100 MB",
         f'count(sum by (user) (sum_over_time({PX} | category="file-sharing" | method="POST" | unwrap bytes_out [$__range])) > 100000000)',
         "Uploads to file sharing over 100 MB (click the user)",
         f'sum by (user, host, url_domain) (sum_over_time({PX} | category="file-sharing" | method="POST" | unwrap bytes_out [$__range])) > 100000000',
         {"user": ("Open WF4 Data exfiltration", link("wf4", user="${__value.raw}"))}, value_name="bytes out", unit="bytes")

    lane("E", "Unticketed change on the plant floor",
         "A program download, mode change or setpoint write with no change ticket. This can stop a line or hurt someone.",
         "WF5 Plant floor change",
         "Unticketed controller changes",
         f'sum(count_over_time({OT} | change_ticket="" | event_type=~"program_download|controller_mode_change|write_request" [$__range]))',
         "Unticketed controller changes by asset (click the asset)",
         f'sum by (site, asset, event_type) (count_over_time({OT} | change_ticket="" | event_type=~"program_download|controller_mode_change|write_request" [$__range]))',
         {"asset": ("Open WF5 Plant floor change", link("wf5", site="${__data.fields.site}", asset="${__value.raw}"))},
         value_name="changes")

    lane("F", "Vehicle API key abuse",
         "Hundreds of 404s on one key means someone is guessing VINs. A hit returns a customer's car location.",
         "WF6 Vehicle API abuse",
         "Keys with over 150 404s",
         f'count(sum by (api_key_id) (count_over_time({TM} | status=404 [$__range])) > 150)',
         "404s by API key, all keys (click the key)",
         f'sum by (api_key_id) (count_over_time({TM} | status=404 [$__range]))',
         {"api_key_id": ("Open WF6 Vehicle API abuse", link("wf6", api_key="${__value.raw}"))}, value_name="404s")
    return b


# --------------------------------------------------------------------------- WF1

def wf1():
    b = Board(WF["wf1"], "Halvorsen SOC / WF1 Suspicious sign-in",
              "Decide whether a user's account is compromised. MFA fatigue, password spray, impossible travel.")
    b.textbox("user", "User", "jakub.kowalski")
    header(b, "Lead A on the triage queue, or a user reports MFA prompts they did not start.",
           "the user name (top of the page).", "decide whether this account is compromised. About 5 minutes.")
    u = '"$user"'

    b.step(1, "Is this MFA fatigue?",
           "denied pushes over time, then the push log in order.",
           "3 or more denied or timed-out pushes within about 10 minutes, followed by a SUCCESS.",
           "note the source IP of the success and go to Step 2.",
           "one or two failures then a success from the usual device is a fumble. Still do Step 3.")
    b.stat("Denied pushes", f'sum(count_over_time({IDP} | user={u} | event_type="user.mfa.push" | outcome="FAILURE" [$__range]))',
           thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 2}, {"color": "red", "value": 3}])
    b.stat("Approved pushes", f'sum(count_over_time({IDP} | user={u} | event_type="user.mfa.push" | outcome="SUCCESS" [$__range]))',
           thresholds=SEV_INFO)
    b.ts("Push outcomes", f'sum by (outcome) (count_over_time({IDP} | user={u} | event_type="user.mfa.push" [$__interval]))',
         w=9, h=4, legend="{{outcome}}", bars=True, stack=True)
    b.logs("Push log, oldest first",
           f'{IDP} | user={u} | event_type="user.mfa.push" | line_format "{{{{.outcome}}}} {{{{.reason}}}}  from {{{{.src_ip}}}} {{{{.src_country}}}} {{{{.src_city}}}}  app={{{{.app}}}}"',
           h=6)

    b.step(2, "Where did the sign-in come from?",
           "every source the user signed in from, with country and client.",
           "a country the user does not work in, a hosting or residential IP nobody else uses, or a script client "
           "(`python-requests`, `curl`).",
           "this is the attacker's address. Copy it into the case timeline and go to Step 3.",
           "US or MX home and office addresses with a normal browser are expected.")
    b.table("Sign-in and VPN sources for this user",
            f'topk(25, sum by (service_name, src_ip, src_country, outcome, user_agent) (count_over_time({{service_name=~"secdemo-idp|secdemo-vpn"}} | json | user={u} [$__range])))',
            value_name="events", h=8, desc="VPN rows have no user_agent.")

    b.step(3, "Was the password already known?",
           "high-risk sign-in attempts against this user, and how many other users the same spray hit.",
           "a SUCCESS or `PASSWORD_OK_MFA_REQUIRED` from a spray address. The password is compromised even if MFA held.",
           "the password must be reset regardless of anything else. Continue to Step 4.",
           "no high-risk attempts against this user. The sign-in may still be bad if Step 1 or 2 was red.")
    b.table("High-risk attempts against this user",
            f'sum by (src_ip, src_country, outcome, reason, user_agent) (count_over_time({IDP} | user={u} | risk_level="HIGH" [$__range]))',
            w=12, h=7, value_name="attempts")
    b.stat("Users hit by script-client sign-ins", f'count(sum by (user) (count_over_time({IDP} | user_agent=~"python.*|curl.*" [$__range])))',
           w=5, h=7, thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 5}, {"color": "red", "value": 20}],
           desc="Breadth of the spray. Every one of these users needs a password check, not just this one.")

    b.step(4, "Can the user be in two places?",
           "badge reads and VPN connections for this user, in time order.",
           "a badge read at a US site within an hour of a VPN connect from abroad, or `hip_compliant=false` "
           "(device failed the posture check).",
           "the remote session is not the user. Treat as compromised. Go to Step 5.",
           "badge and VPN tell one consistent story.")
    b.logs("Badge and VPN, oldest first",
           f'{{service_name=~"secdemo-badge|secdemo-vpn"}} | json | user={u} | line_format "{{{{.service_name}}}}  {{{{or .door .event}}}}  {{{{.site}}}}  {{{{.src_country}}}} {{{{.src_ip}}}}  hip={{{{.hip_compliant}}}}"',
           h=7)

    b.step(5, "What did the session do?",
           "the hosts this user was active on, privilege changes made to the account, and uploads.",
           "a host with EDR detections, the user added to a group, or large uploads.",
           "click the host to open WF2. If uploads are large, open WF4 from the Decide step.",
           "ordinary activity on the user's own workstation.")
    b.table("Hosts this user was active on (click to open WF2)",
            f'topk(10, sum by (host) (count_over_time({{service_name=~"secdemo-edr|secdemo-proxy"}} | json | user={u} | host!="" [$__range])))',
            w=9, h=7, value_name="events",
            links={"host": ("Open WF2 Compromised endpoint", link("wf2", host="${__value.raw}", user="$user"))})
    b.stat("Times added to a group", f'sum(count_over_time({AD} | target_user={u} | event_id=~"4728|4732|4756" [$__range]))', w=4, h=7)
    b.stat("Uploaded to file sharing", f'sum(sum_over_time({PX} | user={u} | category="file-sharing" | method="POST" | unwrap bytes_out [$__range]))',
           w=4, h=7, unit="bytes", thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 100000000}])

    b.row("Decide")
    b.text("### Decide\n"
           "**Compromised** if Step 1 or Step 3 was red **and** Step 2 or Step 4 was red.\n\n"
           "**If compromised, do these now:**\n"
           "1. Revoke all IdP sessions and refresh tokens for the user.\n"
           "2. Reset the password and force MFA re-enrolment.\n"
           "3. Block the source IP from Step 2 at the IdP and VPN.\n"
           "4. Open a case and add the user, IP and hosts to it.\n\n"
           "**Then go to:**\n"
           "- WF2 for each host in Step 5 (click it in the table)\n"
           f"- {mdlink('WF4 Data exfiltration', 'wf4', user='${user}')} if Step 5 showed uploads\n"
           f"- {mdlink('Case timeline', 'case', entity='${user}')}\n\n"
           "**Not compromised:** close the lead with a note on which step cleared it.", h=10)
    return b


# --------------------------------------------------------------------------- WF2

def wf2():
    b = Board(WF["wf2"], "Halvorsen SOC / WF2 Compromised endpoint",
              "Scope one host: what ran, how it got in, whether it persists, whether it calls out, whether it spread.")
    b.textbox("host", "Host", "WKS-NTC-1072")
    b.textbox("user", "User", "jakub.kowalski")
    header(b, "Lead B, or WF1 Step 5 pointed at a host.", "the host name, and the user if you have it.",
           "decide whether to contain the host and find where the attacker went next. About 10 minutes.")
    h = '"$host"'

    b.step(1, "What fired on this host?",
           "every detection on the host, worst first.",
           "high or critical with action `allowed`, or several tactics in a row (Execution, Persistence, Discovery, Credential Access).",
           "go to Step 2 to see how it started.",
           "a single low or medium detection that was blocked or quarantined. Close the lead.")
    b.table("Detections on this host",
            f'sum by (severity, detection_name, technique_id, action, user) (count_over_time({E} | host={h} | event_type="Detection" [$__range]))',
            h=7, value_name="detections")

    b.step(2, "How did it start?",
           "the process chain, oldest first.",
           "an Office app (`excel.exe`, `winword.exe`, `outlook.exe`) starting `powershell`, `cmd`, `rundll32` or `mshta`; "
           "`-enc` or `-w hidden` on the command line.",
           "Office as the parent means a malicious attachment. Go to Step 3.",
           "the chain starts from explorer or a known updater.")
    b.logs("Suspicious process chain on this host",
           f'{E} | host={h} | event_type="Detection" | line_format "{{{{.parent_process}}}} -> {{{{.process}}}}   [{{{{.technique_id}}}}]  {{{{.cmdline}}}}"',
           h=7)

    b.step(3, "Did it come in by email?",
           "mail the user received from domains younger than 30 days, then everyone else who got the same mail.",
           "a delivered message from a new lookalike domain with a macro attachment (`.xlsm`, `.docm`) shortly before Step 2.",
           "every other delivered recipient is a potential second victim. Click each one to open WF1.",
           "nothing from a new domain. The entry point was something else (web, USB, VPN). Keep going.")
    b.table("Mail to this user from new domains",
            f'sum by (sender_domain, subject, attachment, verdict, domain_age_days) (count_over_time({MAIL} | recipient=~"$user@.*" | domain_age_days < 30 [$__range]))',
            w=17, h=5, value_name="messages")
    b.table("Everyone who got mail from new domains (click to open WF1)",
            f'topk(40, sum by (recipient_user, sender_domain, verdict) (count_over_time({MAIL} | domain_age_days < 30 | label_format recipient_user=`{{{{ regexReplaceAll "@.*" .recipient "" }}}}` [$__range])))',
            w=17, h=7, value_name="messages",
            links={"recipient_user": ("Open WF1 for this recipient", link("wf1", user="${__value.raw}"))})

    b.step(4, "Will it survive a reboot?",
           "scheduled tasks, services and run keys created on the host.",
           "`schtasks /create`, a new service or a run key pointing at a user-writable path (AppData, Temp, ProgramData).",
           "note the task name and binary for the eradication list.",
           "no persistence found. Containment may be enough.")
    b.table("Persistence on this host",
            f'sum by (detection_name, technique_id, process, cmdline) (count_over_time({E} | host={h} | technique_id=~"T1053.*|T1543.*|T1547.*" [$__range]))',
            h=6, value_name="events")

    b.step(5, "Is it talking to command and control?",
           "small, regular outbound connections per destination, and new domains the host resolved.",
           "one destination every minute with almost identical size (a flat line), or a domain under 30 days old.",
           "block the domain and IP at the firewall and DNS. Add them to the case.",
           "outbound traffic is bursty and goes to known SaaS.")
    b.ts("Small outbound sessions per destination (beacons are flat lines)",
         f'topk(5, sum by (dst_domain) (count_over_time({FW} | src_host={h} | dst_zone="internet" | bytes < 2000 [5m])))',
         h=6, legend="{{dst_domain}}")
    b.table("New domains this host resolved",
            f'sum by (query, domain_age_days, category) (count_over_time({DNS} | host={h} | domain_age_days < 30 [$__range]))',
            h=5, value_name="lookups")

    b.step(6, "Did it reach other machines?",
           "three counters for movement off this host.",
           "any red counter.",
           f"open {mdlink('WF3 Lateral movement from this host', 'wf3', host='${host}', user='${user}')}.",
           "all green. The attacker probably stayed on this host.")
    b.stat("RC4 service tickets requested", f'sum(count_over_time({AD} | src_host={h} | event_id="4769" | ticket_encryption="0x17" [$__range]))',
           w=5, h=5, desc="Kerberoasting. The fleet is AES-only.")
    b.stat("Explicit-credential logons to other hosts", f'sum(count_over_time({AD} | src_host={h} | event_id="4648" | target_user!~"adm-.*" [$__range]))',
           w=6, h=5, desc="4648 with a different account. Personal adm- accounts via runas are excluded.")
    b.stat("RDP or SMB sessions out", f'sum(count_over_time({FW} | src_host={h} | dst_port=~"3389|445|5985" | action="allow" [$__range]))',
           w=6, h=5)

    b.row("Decide")
    b.text("### Decide\n"
           "**Contain the host** if Step 1 had an allowed high/critical detection **and** Step 2 or Step 5 was bad.\n\n"
           "**Do these now:**\n"
           "1. Network-contain the host in EDR. Do not power it off; memory is evidence.\n"
           "2. Block the C2 domain and IP from Step 5.\n"
           "3. Purge the lure email from every mailbox in Step 3.\n"
           "4. Add the persistence items from Step 4 to the eradication list.\n\n"
           "**Then go to:**\n"
           f"- {mdlink('WF3 Lateral movement from this host', 'wf3', host='${host}', user='${user}')} if any Step 6 counter was red\n"
           f"- {mdlink('WF1 for the user', 'wf1', user='${user}')} to check the account\n"
           f"- {mdlink('WF4 Data exfiltration', 'wf4', user='${user}')}\n"
           f"- {mdlink('Case timeline for the host', 'case', entity='${host}')}", w=18, h=10)
    b.stat("Already contained?", f'sum(count_over_time({E} | host={h} | event_type="Containment" [$__range]))', w=6, h=10,
           thresholds=[{"color": "orange", "value": None}, {"color": "green", "value": 1}],
           desc="Orange 0 = not contained yet. Green = an analyst already contained it.")
    return b


# --------------------------------------------------------------------------- WF3

def wf3():
    b = Board(WF["wf3"], "Halvorsen SOC / WF3 Lateral movement and privilege escalation",
              "Follow the attacker host by host. Run once per hop.")
    b.textbox("host", "Current hop (host)", "WKS-NTC-1072")
    b.textbox("user", "User", "jakub.kowalski")
    header(b, "WF2 Step 6 was red, or Lead C.", "the host you are on now.",
           "build the full list of hosts and accounts the attacker used. That list is your containment scope.",
           "> **How to follow the trail:** write the current host on your case notes. In **Step 4**, click a destination host. "
           "The page reloads with that host as the current hop. Repeat until Step 4 is empty. Every host you wrote down gets contained.")
    h = '"$host"'

    b.step(1, "Were credentials stolen here?",
           "credential-access detections on this host and Kerberos tickets it requested with RC4.",
           "LSASS access, `sekurlsa`, `procdump lsass`, or RC4 tickets for many service accounts in a few seconds.",
           "every account that logged on to this host and every listed service account is burned. Add them to the reset list.",
           "no credential theft here. The attacker may be reusing credentials stolen elsewhere.")
    b.table("Credential theft detections", f'sum by (detection_name, technique_id, process, user) (count_over_time({E} | host={h} | tactic="Credential Access" | action="allowed" [$__range]))',
            w=17, h=5, value_name="detections")
    b.table("RC4 tickets requested from this host (service accounts at risk)",
            f'sum by (spn, user) (count_over_time({AD} | src_host={h} | event_id="4769" | ticket_encryption="0x17" [$__range]))',
            w=17, h=6, value_name="tickets")

    b.step(2, "Which accounts were used from here?",
           "logons from this host to anywhere, and logons that switched to a different account.",
           "a service account (`svc_*`) or admin account used from a workstation, or a 4648 where `target_user` is not the person at the keyboard.",
           "add each account to the reset list. Service accounts also need their SPN password rotated.",
           "only the host's own user, logging on to the usual servers.")
    b.table("Accounts used from this host",
            f'sum by (event_id, user, target_user, logon_type, dst_host) (count_over_time({AD} | src_host={h} | event_id=~"4624|4648" [$__range]))',
            h=8, value_name="logons", desc="logon_type 3 = network, 10 = RDP. 4648 = explicit credentials (runas, PsExec).")

    b.step(3, "Did anyone gain privileges?",
           "privileged logons, group additions and services installed from this host.",
           "an account added to an admin or OT engineering group, `SeDebugPrivilege` on a service account, or a service like `PSEXESVC` installed on another machine.",
           "undo the group change now and add the account to the case.",
           "no privilege changes from this host.")
    b.table("Privilege changes from this host",
            f'sum by (event_id, event_name, user, target_user, group, service, dst_host) (count_over_time({AD} | src_host={h} | event_id=~"4672|4728|4732|4756|7045" [$__range]))',
            h=7, value_name="events")

    b.step(4, "Where did they go next?",
           "machines this host logged on to or opened RDP, SMB or WinRM sessions to.",
           "RDP (3389), SMB (445) or WinRM (5985) to a server, jump host or plant system, especially into an `ot-*` zone.",
           "write this host down, then **click the destination** to make it the current hop. Start again at Step 1.",
           "nothing here means this is the end of the trail. Go to Step 5, then Decide.")
    b.table("Logons from this host (click a destination to follow)",
            f'sum by (dst_host, user, logon_type) (count_over_time({AD} | src_host={h} | event_id="4624" | dst_host!="" | dst_host!={h} [$__range]))',
            w=17, h=6, value_name="logons",
            links={"dst_host": ("Follow to this hop", link("wf3", host="${__value.raw}", user="${__data.fields.user}"))})
    b.table("Allowed admin sessions from this host (click to follow)",
            f'sum by (dst_host, dst_port, dst_zone, rule) (count_over_time({FW} | src_host={h} | dst_port=~"3389|445|5985" | action="allow" [$__range]))',
            w=12, h=6, value_name="sessions",
            links={"dst_host": ("Follow to this hop", link("wf3", host="${__value.raw}", user="$user"))})
    b.stat("Addresses scanned and denied", f'count(sum by (dst_ip) (count_over_time({FW} | src_host={h} | action="deny" | dst_zone!="internet" [$__range])))',
           w=5, h=6, thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 5}, {"color": "red", "value": 20}],
           desc="Distinct internal addresses this host was blocked from. A high number is a scan for the next target.")

    b.step(5, "Did they cross into the plant network?",
           "plant controller events that came from this host.",
           "any controller change sourced from this host.",
           "click the asset to open WF5. Call the plant controls engineer before touching anything.",
           "nothing from this host reached a controller.")
    b.table("Controller events from this host (click to open WF5)",
            f'sum by (site, asset, event_type, severity) (count_over_time({OT} | src_host={h} [$__range]))',
            h=6, value_name="events",
            links={"asset": ("Open WF5 Plant floor change", link("wf5", site="${__data.fields.site}", asset="${__value.raw}"))})

    b.row("Decide")
    b.text("### Decide\n"
           "You are done when Step 4 is empty on the last host. Your notes now hold the **host list** and the **account list**.\n\n"
           "**Do these now:**\n"
           "1. Contain every host on the list in EDR (plant systems: through the controls engineer, not EDR).\n"
           "2. Disable or reset every account from Steps 1 to 3. Rotate passwords for each service account behind an RC4 ticket.\n"
           "3. Revert group additions from Step 3 and remove installed services such as `PSEXESVC`.\n\n"
           "**Then go to:**\n"
           f"- WF5 for any asset in Step 5 (click it)\n"
           f"- {mdlink('WF2 for the current hop', 'wf2', host='${host}', user='${user}')}\n"
           f"- {mdlink('Case timeline for the current hop', 'case', entity='${host}')}", h=9)
    return b


# --------------------------------------------------------------------------- WF4

def wf4():
    b = Board(WF["wf4"], "Halvorsen SOC / WF4 Data exfiltration",
              "Size an outbound transfer, name the data, find where it came from, and confirm who sent it.")
    b.textbox("user", "User", "jakub.kowalski")
    header(b, "Lead D, or WF1/WF2 showed large uploads.", "the user name.",
           "decide whether intellectual property left the company and how much. About 5 minutes.")
    u = '"$user"'

    b.step(1, "How much left, and to where?",
           "upload volume over time per destination.",
           "over 100 MB to a personal file-sharing or paste site, especially a run of near-identical chunks.",
           "block the destination at the proxy for everyone, then Step 2.",
           "uploads go to the corporate SharePoint or a sanctioned SaaS. Close the lead.")
    b.stat("Total to file sharing", f'sum(sum_over_time({PX} | user={u} | category="file-sharing" | method="POST" | unwrap bytes_out [$__range]))',
           w=5, h=7, unit="bytes", thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 100000000}])
    b.ts("Upload volume by destination", f'sum by (url_domain) (sum_over_time({PX} | user={u} | method="POST" | unwrap bytes_out [$__interval]))',
         w=12, h=7, unit="bytes", legend="{{url_domain}}", bars=True)

    b.step(2, "What was sent?",
           "file names on the uploads.",
           "archives split into numbered parts (`.7z.001`), program or vehicle platform names, CAD or battery data.",
           "send the file names to the data owner (engineering) to confirm sensitivity.",
           "personal files or nothing named. Check Step 3 before closing.")
    b.table("Uploaded files", f'topk(50, sum by (url_domain, file_name) (sum_over_time({PX} | user={u} | category="file-sharing" | method="POST" | file_name!="" | unwrap bytes_out [$__range])))',
            h=7, value_name="bytes", unit="bytes")

    b.step(3, "Where did the files come from?",
           "file shares the user opened.",
           "an engineering share the user does not normally use, opened just before the uploads.",
           "the share owner needs to know. Add the share to the case.",
           "no share access. The data may have been local.")
    b.table("Shares opened by this user", f'sum by (share, relative_target) (count_over_time({AD} | user={u} | event_id="5145" [$__range]))',
            h=6, value_name="accesses")

    b.step(4, "Was it really the user?",
           "how the user was connected while the uploads happened.",
           "VPN from abroad, a failed device posture check, or a sign-in workflow (WF1) that came back compromised.",
           f"treat it as an attacker, not an insider. Run {mdlink('WF1 for this user', 'wf1', user='${user}')}.",
           "on-site or normal VPN. Insider risk: involve HR and legal before contacting the user.")
    b.table("VPN sessions for this user", f'sum by (event, src_ip, src_country, hip_compliant) (count_over_time({VPN} | user={u} [$__range]))',
            h=6, value_name="events")

    b.row("Decide")
    b.text("### Decide\n"
           "**Confirmed exfiltration** if Step 1 was red and Step 2 or Step 3 names sensitive data.\n\n"
           "**Do these now:**\n"
           "1. Block the destination domain at the proxy for all users.\n"
           "2. Notify the data owner with the file names and the total from Step 1.\n"
           "3. If Step 4 says attacker: legal and privacy start the IP-theft process. If insider: HR and legal before anyone talks to the user.\n\n"
           "**Then go to:**\n"
           f"- {mdlink('WF1 for this user', 'wf1', user='${user}')}\n"
           f"- {mdlink('Case timeline', 'case', entity='${user}')}", h=8)
    return b


# --------------------------------------------------------------------------- WF5

def wf5():
    b = Board(WF["wf5"], "Halvorsen SOC / WF5 Plant floor change",
              "Is an unticketed controller change an attack, is the process still safe, and how did they get there.")
    b.custom("site", "Plant", ["riverside-assembly", "cedar-hollow", "monterra"])
    b.textbox("asset", "Asset", "PLC-PAINT-L2-07")
    b.text("### Safety first\n"
           "Do **not** isolate, reboot or push anything to a controller from the SOC. **Call the plant controls engineer on shift and the line "
           "supervisor before any action.** A controller in a bad state can hurt people. The SOC's job is to tell them what changed and from where.",
           h=3)
    header(b, "Lead E, or WF3 Step 5 showed a controller event.", "the plant and the asset.",
           "tell the plant team what changed, whether the process is safe, and who did it.")
    a = f'{OT} | site="$site" | asset="$asset"'

    b.step(0, "Pick the asset",
           "every unticketed controller change at this plant.",
           "more than one asset changed in a short window.",
           "click the asset to work it. Do the busiest one first.",
           "if the asset you were sent here for is not listed, its change had a ticket. Close the lead.")
    b.table("Unticketed changes at this plant (click an asset)",
            f'sum by (ot_line, asset, event_type) (count_over_time({OT} | site="$site" | change_ticket="" | event_type=~"program_download|controller_mode_change|write_request" [$__range]))',
            h=6, value_name="changes",
            links={"asset": ("Work this asset", link("wf5", site="$site", asset="${__value.raw}"))})

    b.step(1, "What changed?",
           "every event on the asset, oldest first.",
           "RUN to PROGRAM mode change, program download, then PROGRAM back to RUN, with no change ticket. That is someone replacing logic.",
           "phone the controls engineer now with the asset name and the time. Then Step 2.",
           "a ticketed change inside the window. Close the lead.")
    b.logs("Asset event log", f'{a} | line_format "{{{{.severity}}}}  {{{{.event_type}}}}  {{{{.description}}}}  [{{{{.technique_id}}}}]  ticket={{{{.change_ticket}}}}"',
           h=7)

    b.step(2, "Is the process still safe?",
           "setpoint writes on this asset.",
           "a setpoint pushed outside its engineering limits (oven, press force, torque, battery charge current).",
           "the controls engineer verifies the real value at the HMI and puts the line in a safe state. That is their call, not the SOC's.",
           "no setpoint writes. The logic change alone still needs review.")
    b.stat("Setpoint writes", f'sum(count_over_time({a} | event_type="write_request" [$__range]))', w=4, h=5)
    b.logs("Setpoint writes", f'{a} | event_type="write_request" | line_format "{{{{.description}}}}  by {{{{.user}}}} from {{{{.src_host}}}}"',
           w=13, h=5)

    b.step(3, "Who made it, from where?",
           "the workstation and account behind the change.",
           "an account that is not on the controls team, or an engineering workstation that also has EDR detections.",
           "click the host to open WF2 for it.",
           "the line's own engineer from their own workstation. Ask them whether they made the change.")
    b.table("Source of the change (click the host)", f'sum by (src_host, user, event_type) (count_over_time({a} [$__range]))',
            h=5, value_name="events",
            links={"src_host": ("Open WF2 for this workstation", link("wf2", host="${__value.raw}", user="${__data.fields.user}"))})

    b.step(4, "How did they reach the cell?",
           "who connected into the plant network zones at this site.",
           "a VPN address or office workstation going through the jump host, or anything into `ot-cell` that is not the historian.",
           "click the first host in the chain to open WF3 and walk it.",
           "only the historian and known engineering workstations.")
    b.table("Connections into plant zones (click to open WF3)",
            f'sum by (src_host, src_zone, dst_host, dst_zone, dst_port, rule) (count_over_time({FW} | site="$site" | dst_zone=~"ot-.*" | action="allow" | src_host!~"HIST-.*" [$__range]))',
            h=6, value_name="sessions",
            links={"src_host": ("Open WF3 from this host", link("wf3", host="${__value.raw}", user=".*")),
                   "dst_host": ("Open WF3 from this host", link("wf3", host="${__value.raw}", user=".*"))})

    b.step(5, "What else did they touch?",
           "new devices and scans inside the cells at this plant.",
           "an unknown device on a cell switch, or a workstation scanning controller ports (102 S7, 44818 EtherNet/IP, 502 Modbus).",
           "give the list to the controls engineer. Each one gets checked.",
           "no new devices and no scans.")
    b.table("New devices at this plant", f'sum by (ot_line, asset, description) (count_over_time({OT} | site="$site" | event_type="new_asset" [$__range]))',
            w=9, h=6, value_name="sightings")
    b.table("Controller-port scans inside cells", f'count by (src_host) (sum by (src_host, dst_ip) (count_over_time({FW} | site="$site" | src_zone="ot-cell" | action="deny" [$__range])))',
            w=8, h=6, value_name="targets")

    b.row("Decide")
    b.text("### Decide\n"
           "**Attack** if Step 1 shows an unticketed download or mode change **and** Step 3 or Step 4 is unexpected.\n\n"
           "**Do these now (with the plant):**\n"
           "1. Controls engineer restores the last known-good program and confirms setpoints.\n"
           "2. Disable the account from Step 3 in the OT domain. Close the firewall rule from Step 4 that let the session in.\n"
           "3. Preserve the controller project file and the workstation for forensics.\n\n"
           "**Then go to:**\n"
           "- WF2 for the workstation in Step 3 (click it)\n"
           "- WF3 for the first host in Step 4 (click it)\n"
           f"- {mdlink('Case timeline for this asset', 'case', entity='${asset}')}", h=8)
    return b


# --------------------------------------------------------------------------- WF6

def wf6():
    b = Board(WF["wf6"], "Halvorsen SOC / WF6 Vehicle API abuse",
              "Partner or app key enumerating VINs or trying remote commands on customer cars.")
    b.textbox("api_key", "API key", "ak_fleetpartner07")
    header(b, "Lead F.", "the API key id.",
           "decide whether a key is being abused and whether any customer vehicle data was exposed.")
    k = f'{TM} | api_key_id="$api_key"'

    b.step(1, "Is this key behaving differently from the others?",
           "error rate per key over time.",
           "one key's error rate far above the others (normal is about 2%).",
           "go to Step 2.",
           "this key looks like every other key. Close the lead.")
    b.ts("Error rate by key", f'sum by (api_key_id) (count_over_time({TM} | status >= 400 [$__interval])) / sum by (api_key_id) (count_over_time({TM} [$__interval]))',
         h=7, unit="percentunit", legend="{{api_key_id}}")

    b.step(2, "Where are the requests coming from?",
           "source addresses for this key.",
           "an address outside the partner's registered egress range (`198.18.0.0/15` in this demo) sending most of the errors.",
           "that address is the abuser. Block it at the gateway and go to Step 3.",
           "all traffic is from the partner's range. Their system may be broken, not compromised. Call the partner.")
    b.table("Sources getting errors on this key", f'topk(25, sum by (src_ip) (count_over_time({k} | status >= 400 [$__range])))',
            w=10, h=7, value_name="errors")
    b.table("All sources for this key, last 15 minutes", f'sum by (src_ip) (count_over_time({k} [15m]))', w=7, h=7, value_name="requests")

    b.step(3, "What were they after?",
           "endpoints and outcomes for this key.",
           "a wall of 404s on `/vehicles/{vin}/...` (guessing VINs), or any `/remote/` command (unlock, start).",
           "remote command attempts escalate to the vehicle security team right away.",
           "normal endpoints and status codes.")
    b.table("Endpoints and outcomes", f'sum by (method, endpoint, status) (count_over_time({k} [$__range]))', w=10, h=6, value_name="requests")
    b.stat("Remote command attempts", f'sum(count_over_time({k} | endpoint=~".*/remote/.*" [$__range]))', w=7, h=6)

    b.step(4, "Did they get any customer data?",
           "successful responses to addresses outside the partner range.",
           "any 200. Each one is a real vehicle's status or location returned to the abuser.",
           "this is a privacy incident. Privacy and legal need the count and the time range.",
           "zero successes. Enumeration failed. Still revoke the key.")
    b.stat("Successful responses to unregistered addresses",
           f'sum(count_over_time({k} | status=200 | src_ip!~"198[.]18[.].*" [$__range]))', w=6, h=5)
    b.table("What was returned", f'sum by (endpoint, src_ip) (count_over_time({k} | status=200 | src_ip!~"198[.]18[.].*" [$__range]))',
            w=11, h=5, value_name="responses")

    b.row("Decide")
    b.text("### Decide\n"
           "**Abuse** if Step 1 is red and Step 2 shows an unregistered source.\n\n"
           "**Do these now:**\n"
           "1. Revoke the key and issue the partner a new one through their account manager.\n"
           "2. Block the source address at the API gateway.\n"
           "3. If Step 4 is above zero: open a privacy incident with the count of exposed vehicles.\n"
           "4. If Step 3 shows remote commands: notify the vehicle security team.\n\n"
           f"**Then:** {mdlink('Case timeline for the source address', 'case', entity='203.0.113.199')}", h=8)
    return b


# --------------------------------------------------------------------------- case timeline

def case_timeline():
    b = Board(WF["case"], "Halvorsen SOC / Case timeline",
              "Every source for one entity, in time order. Use it to write the case narrative.")
    b.textbox("entity", "Entity (user, host, IP, asset, hash)", "jakub.kowalski")
    b.text("**How to use:** put one value in the Entity box (a user, host, IP, asset or file hash). Read the log **oldest first** and "
           "write one line per event in the case: time, source, what happened. Do this for every entity on your containment list. "
           "The first event across all of them is your initial access time.", h=3)
    b.ts("Events by source", f'sum by (service_name) (count_over_time({ALL} |= "$entity" [$__interval]))',
         w=24, h=6, legend="{{service_name}}", stack=True, bars=True)
    b.logs("Timeline, oldest first", f'{ALL} |= "$entity"', w=24, h=20)
    return b


BOARDS = [triage, wf1, wf2, wf3, wf4, wf5, wf6, case_timeline]


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    boards = [f().json() for f in BOARDS]
    for d in boards:
        (OUT / f"{d['uid']}.json").write_text(json.dumps(d, indent=2))
    print(f"wrote {len(boards)} dashboards to {OUT}")


if __name__ == "__main__":
    main()
