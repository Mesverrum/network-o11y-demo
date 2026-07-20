#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("/tmp/gnmic-otlp.go")
if not p.exists():
    import urllib.request
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/openconfig/gnmic/main/pkg/outputs/otlp_output/otlp_output.go",
        p,
    )
text = p.read_text(errors="replace")
keys = ("StringsAs", "strings-as", "stringVal", "value", "uint64", "ParseFloat", "strconv", "json.Number", "TypedValue")
for i, line in enumerate(text.splitlines(), 1):
    if any(k.lower() in line.lower() for k in keys):
        print(f"{i}: {line.rstrip()[:160]}")
