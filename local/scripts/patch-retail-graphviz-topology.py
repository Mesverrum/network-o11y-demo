#!/usr/bin/env python3
"""Replace Retail location nodeGraph topology with Graphviz DOT panel."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

UID = "ma28zlf"
VIZ_VER = "13.2.0-29854286369"

STORE_TOPOLOGY_DOT = r"""digraph store_network {
  rankdir=LR;
  splines=true;
  bgcolor="transparent";
  node [
    shape=box
    style="filled,rounded"
    fontname="Helvetica"
    fontsize=11
    fontcolor="#111827"
    fillcolor="#ffffff"
    color="#334155"
    penwidth=1.6
    margin="0.2,0.14"
  ];
  edge [fontname="Helvetica" fontsize=9 fontcolor="#1f2937" color="#64748b"];

  subgraph cluster_corp {
    label="Corporate";
    style=dashed;
    color="#64748b";
    fontsize=12;
    fontcolor="#111827";

    corp [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Corporate Mothership</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">Data Center</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT></TD></TR>
        </TABLE>
      >
      color="#1e40af"
    ];
  }

  subgraph cluster_store {
    label="Retail store #1427";
    style=rounded;
    color="#475569";
    fontsize=12;
    fontcolor="#111827";

    fw [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Firewall</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">Edge Security</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT> <FONT COLOR="#374151">• 2% CPU</FONT></TD></TR>
        </TABLE>
      >
    ];

    rtr [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Router</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">WAN / LAN</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT> <FONT COLOR="#374151">• 12 Mbps</FONT></TD></TR>
        </TABLE>
      >
    ];

    ap [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Wireless AP</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">Store Wi-Fi</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT> <FONT COLOR="#374151">• 8 clients</FONT></TD></TR>
        </TABLE>
      >
    ];

    srv [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Local Server</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">DB + POS Controller</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT> <FONT COLOR="#374151">• 34% CPU</FONT></TD></TR>
        </TABLE>
      >
    ];

    reg1 [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Register 1</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">POS</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT></TD></TR>
        </TABLE>
      >
    ];

    reg2 [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Register 2</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">POS</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT></TD></TR>
        </TABLE>
      >
    ];

    scan1 [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Scanner 1</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">Handheld</FONT></TD></TR>
          <TR><TD><FONT COLOR="#047857"><B>● Online</B></FONT></TD></TR>
        </TABLE>
      >
    ];

    scan2 [
      label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5" COLOR="#111827">
          <TR><TD><FONT COLOR="#111827"><B>Scanner 2</B></FONT></TD></TR>
          <TR><TD><FONT COLOR="#374151">Handheld</FONT></TD></TR>
          <TR><TD><FONT COLOR="#b91c1c"><B>● Offline</B></FONT></TD></TR>
        </TABLE>
      >
      color="#b91c1c"
      penwidth=2.2
    ];
  }

  corp -> fw [label=" WAN " penwidth=1.6 fontcolor="#111827"];
  fw -> rtr;
  rtr -> ap;
  rtr -> srv [label=" LAN " fontcolor="#111827"];
  ap -> reg1 [label=" Wi-Fi "];
  ap -> reg2 [label=" Wi-Fi "];
  ap -> scan1 [label=" Wi-Fi "];
  ap -> scan2 [label=" Wi-Fi " color="#b91c1c" fontcolor="#b91c1c"];
  srv -> reg1 [style=dashed color="#94a3b8"];
  srv -> reg2 [style=dashed color="#94a3b8"];
}
"""


def gcx_get() -> dict:
    raw = subprocess.check_output(
        ["gcx", "--context", "marcnetterfield1", "dashboards", "get", UID, "-o", "json"],
        stderr=subprocess.DEVNULL,
    ).decode("utf-8", errors="replace")
    return json.loads(raw[raw.find("{") :])


def gcx_update(dash: dict) -> None:
    out = Path("/tmp/retail-location-graphviz.json")
    out.write_text(json.dumps(dash, indent=2), encoding="utf-8")
    subprocess.run(
        ["gcx", "--context", "marcnetterfield1", "dashboards", "update", UID, "-f", str(out)],
        check=True,
    )


def graphviz_panel(pid: int, title: str, dot: str) -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": "Retail store WAN/LAN topology rendered with Graphviz DOT (demo).",
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": [], "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "grafana-graphviz-panel",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {"defaults": {}, "overrides": []},
                    "options": {
                        "inputMode": "code",
                        "dotDiagram": dot,
                        "layoutEngine": "dot",
                        "rankDirection": "LR",
                        "splineType": "true",
                        "namedThresholds": [],
                        "edgeOverrides": [],
                        "nodeOverrides": [],
                    },
                },
            },
        },
    }


def main() -> None:
    dash = gcx_get()
    old = dash["spec"]["elements"].get("panel-2", {})
    panel = graphviz_panel(
        old.get("spec", {}).get("id", 2),
        old.get("spec", {}).get("title", "Store Network Topology"),
        STORE_TOPOLOGY_DOT,
    )
    dash["spec"]["elements"]["panel-2"] = panel
    ann = dash.setdefault("metadata", {}).setdefault("annotations", {})
    ann["grafana.app/message"] = "Graphviz topology — high-contrast white cards"
    gcx_update(dash)
    print(f"Updated https://marcnetterfield1.grafana.net/d/{UID}/retail-location")


if __name__ == "__main__":
    main()
