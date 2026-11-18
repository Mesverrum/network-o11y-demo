#!/usr/bin/env python3
"""Turn the built workflow dashboards into the data file for a Grafana Assistant page.

  python3 build_dashboards.py && python3 build_page_kit.py

Writes page-kit/attach/02-workflows.json. The dashboards stay the single source for
queries, card text and the links between workflows, so the page and the dashboards
cannot drift apart.
"""
import json
import pathlib
import re
from urllib.parse import parse_qsl

HERE = pathlib.Path(__file__).resolve().parent
DASH = HERE / "dashboards"
OUT = HERE / "page-kit" / "attach" / "02-workflows.json"

WF_IDS = {
    "hm-00-triage": "triage",
    "hm-wf1-signin": "wf1",
    "hm-wf2-endpoint": "wf2",
    "hm-wf3-lateral": "wf3",
    "hm-wf4-exfil": "wf4",
    "hm-wf5-ot": "wf5",
    "hm-wf6-api": "wf6",
    "hm-case-timeline": "case",
}
ORDER = list(WF_IDS)

DECIDE_RULES = {
    "wf1": {"verdict": "Account compromised", "when": "(s1 or s3) and (s2 or s4)",
            "next_if_true": ["wf2", "wf4"], "close_if_false": "Not compromised. Close the lead with the step that cleared it."},
    "wf2": {"verdict": "Contain this host", "when": "s1 and (s2 or s5)",
            "also": {"when": "s6", "say": "Movement off this host. Run WF3 from here."},
            "next_if_true": ["wf3", "wf1", "wf4"], "close_if_false": "No containment needed. Close the lead."},
    "wf3": {"verdict": "End of trail on this hop", "when": "not s4",
            "next_if_true": ["wf5", "case"], "close_if_false": "Step 4 found another hop. Follow it before deciding."},
    "wf4": {"verdict": "Confirmed exfiltration", "when": "s1 and (s2 or s3)",
            "also": {"when": "s4", "say": "Session was not the user. Treat as attacker, run WF1."},
            "next_if_true": ["wf1", "case"], "close_if_false": "Not exfiltration. Close the lead."},
    "wf5": {"verdict": "Attack on the plant floor", "when": "s1 and (s3 or s4)",
            "next_if_true": ["wf2", "wf3", "case"], "close_if_false": "Ticketed or explained change. Close the lead."},
    "wf6": {"verdict": "API key abuse", "when": "s1 and s2",
            "also": {"when": "s4", "say": "Customer vehicle data was returned. Open a privacy incident."},
            "next_if_true": ["case"], "close_if_false": "Key behaves like the others. Close the lead."},
}

CARD_RE = re.compile(
    r"### (?P<n>\d+)\. (?P<title>.+?)\n\n\*\*Look at:\*\* (?P<look>.+?)\n\n\*\*Suspicious if:\*\* (?P<bad>.+?)\n\n"
    r"\*\*If suspicious:\*\* (?P<if_bad>.+?)\n\n\*\*If clean:\*\* (?P<if_clean>.+)", re.S)
MDLINK_RE = re.compile(r"\[([^\]]+)\]\(/d/([a-z0-9-]+)\?([^)]*)\)")


def param_source(v):
    if v == "${__value.raw}":
        return "cell"
    m = re.fullmatch(r"\$\{__data\.fields\.([A-Za-z_]+)\}", v)
    if m:
        return "row." + m.group(1)
    m = re.fullmatch(r"\$\{?([A-Za-z_]+)\}?", v)
    if m:
        return "var." + m.group(1)
    return "literal:" + v


def parse_url(url):
    path, _, q = url.partition("?")
    uid = path.rsplit("/", 1)[-1]
    params = {}
    for k, v in parse_qsl(q, keep_blank_values=True):
        if k.startswith("var-"):
            params[k[4:]] = param_source(v)
    return {"workflow": WF_IDS.get(uid, uid), "params": params}


def md_links(md):
    """Replace Grafana dashboard links in markdown with page-native link tokens."""
    links = []

    def sub(m):
        label, uid, q = m.groups()
        params = {k[4:]: param_source(v) for k, v in parse_qsl(q) if k.startswith("var-")}
        links.append({"label": label, "workflow": WF_IDS.get(uid, uid), "params": params})
        return f"[[{label}]]"

    return MDLINK_RE.sub(sub, md), links


def thresholds(p):
    steps = p.get("fieldConfig", {}).get("defaults", {}).get("thresholds", {}).get("steps", [])
    return [{"from": s["value"], "color": s["color"]} for s in steps]


def evidence(p):
    t = p["type"]
    tgt = p["targets"][0]
    ev = {"kind": t, "title": p.get("title", ""), "expr": [x["expr"] for x in p["targets"]] if len(p["targets"]) > 1 else tgt["expr"],
          "query": "instant" if tgt.get("instant") else "range"}
    if p.get("description"):
        ev["help"] = p["description"]
    defaults = p.get("fieldConfig", {}).get("defaults", {})
    if defaults.get("unit") and defaults["unit"] != "short":
        ev["unit"] = defaults["unit"]
    if t == "stat":
        ev["thresholds"] = thresholds(p)
    if t == "timeseries":
        ev["legend"] = tgt.get("legendFormat", "")
        ev["style"] = defaults.get("custom", {}).get("drawStyle", "line")
    if t == "table":
        org = next(x for x in p["transformations"] if x["id"] == "organize")
        ev["value_column"] = org["options"]["renameByName"]["Value"]
        links = []
        for o in p["fieldConfig"]["overrides"]:
            col = o["matcher"]["options"]
            for prop in o["properties"]:
                if prop["id"] == "links":
                    for l in prop["value"]:
                        links.append({"column": col, "label": l["title"], **parse_url(l["url"])})
                if prop["id"] == "unit" and prop["value"] != "short":
                    ev["unit"] = prop["value"]
        if links:
            ev["links"] = links
    return ev


def board(d):
    out = {"id": WF_IDS[d["uid"]], "uid": d["uid"], "title": d["title"].split(" / ", 1)[-1], "description": d["description"],
           "variables": [{"name": v["name"], "label": v["label"], "default": v["current"]["value"],
                          **({"choices": v["query"].split(",")} if v["type"] == "custom" else {})}
                         for v in d["templating"]["list"] if v["name"] != "ds"],
           "intro": [], "leads": [], "steps": [], "decide": None}
    section = None
    for p in d["panels"]:
        if p["type"] == "row":
            title = p["title"]
            m = re.match(r"Step (\d+)\. (.+)", title)
            if m:
                section = {"n": int(m.group(1)), "title": m.group(2), "evidence": []}
                out["steps"].append(section)
            elif title.startswith("Lead "):
                letter, _, rest = title[5:].partition(". ")
                section = {"letter": letter, "title": rest, "evidence": []}
                out["leads"].append(section)
            elif title == "Decide":
                section = {"evidence": []}
                out["decide"] = section
            continue
        if p["type"] == "text":
            md = p["options"]["content"]
            if section is None:
                out["intro"].append(md)
                continue
            m = CARD_RE.match(md)
            if m and "n" in section:
                card = {k: m.group(k).strip() for k in ("look", "bad", "if_bad", "if_clean")}
                for k, v in list(card.items()):
                    card[k], links = md_links(v)
                    if links:
                        card.setdefault("links", []).extend(links)
                section["card"] = card
            elif "letter" in section:
                why = re.search(r"\*\*Why it matters:\*\* (.+?)\n", md)
                section["why"] = why.group(1) if why else md
                section["work_in"] = re.search(r"\*\*Work it in:\*\* (.+)", md).group(1)
            else:
                section["markdown"], links = md_links(md)
                if links:
                    section["links"] = links
            continue
        if section is None:
            out["intro_evidence"] = out.get("intro_evidence", []) + [evidence(p)]
        else:
            section["evidence"].append(evidence(p))
    for k in ("leads", "steps", "intro"):
        if not out[k]:
            out.pop(k)
    if out["decide"] is None:
        out.pop("decide")
    else:
        out["decide"]["rule"] = DECIDE_RULES[out["id"]]
    return out


def main():
    boards = {json.loads(f.read_text(encoding="utf-8"))["uid"]: json.loads(f.read_text(encoding="utf-8"))
              for f in DASH.glob("*.json")}
    missing = [u for u in ORDER if u not in boards]
    if missing:
        raise SystemExit(f"run build_dashboards.py first, missing {missing}")
    data = {
        "meta": {
            "title": "Halvorsen Motors SOC investigation console",
            "company": "Halvorsen Motors (fictional automaker, synthetic data)",
            "stack": "marcnetterfield1.grafana.net",
            "datasource": {"type": "loki", "uid": "grafanacloud-logs"},
            "source": "Generated by build_page_kit.py from the hm-* dashboards in folder halvorsen-soc. Queries, card text and links match the dashboards.",
            "replay": "A scripted intrusion replays at the top of every UTC hour over about 30 minutes. Victim rotates jakub.kowalski, aisha.nguyen, carlos.ortega by hour.",
            "query_notes": [
                "LogQL. $__range is the selected range as a duration, $__interval the step. Variables appear as $name or ${name}.",
                "instant queries return a vector: one row per label set, value in the last element.",
                "Severity label is detected_level, not severity_text.",
                "Keep each query under 500 series; the expressions here already are.",
            ],
        },
        "link_params": {
            "cell": "the clicked cell value",
            "row.<col>": "another column of the same row",
            "var.<name>": "the current workflow variable",
            "literal:<x>": "fixed value",
        },
        "workflows": [board(boards[u]) for u in ORDER],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    split = OUT.parent / "send"
    split.mkdir(exist_ok=True)
    for old in split.glob("*.json"):
        old.unlink()
    wfs = {w["id"]: w for w in data["workflows"]}
    parts = [("02a-meta-triage-case", {"meta": data["meta"], "link_params": data["link_params"],
                                        "workflows": [wfs["triage"], wfs["case"]]})]
    parts += [(f"02{chr(98 + i)}-{k}", {"workflows": [wfs[k]]}) for i, k in enumerate(["wf1", "wf2", "wf3", "wf4", "wf5", "wf6"])]
    for name, body in parts:
        (split / f"{name}.json").write_text(json.dumps(body, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    steps = sum(len(w.get("steps", [])) for w in data["workflows"])
    queries = sum(len(s["evidence"]) for w in data["workflows"] for s in w.get("steps", []) + w.get("leads", []) + ([w["decide"]] if w.get("decide") else []))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB), {len(data['workflows'])} workflows, {steps} steps, {queries} evidence panels")


if __name__ == "__main__":
    main()
