from pathlib import Path

root = Path(__file__).resolve().parents[1]
patterns = {".sh", ".tmpl"}
names = {"Makefile"}
for p in root.rglob("*"):
    if not p.is_file():
        continue
    if p.suffix not in patterns and p.name not in names and not p.name.endswith(".env") and not p.name.endswith(".env.sample"):
        continue
    data = p.read_bytes()
    if b"\r\n" in data or b"\r" in data:
        p.write_bytes(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        print("fixed", p.relative_to(root))
