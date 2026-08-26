#!/usr/bin/env bash
# Añade bots al diccionario SERVICIOS de /home/admin/maestro.py
set -eu

MAESTRO="/home/admin/maestro.py"

if [ ! -f "$MAESTRO" ]; then
  echo "[ERROR] No existe $MAESTRO"
  exit 1
fi

python3 <<'PY'
from pathlib import Path

path = Path("/home/admin/maestro.py")
text = path.read_text(encoding="utf-8")
lines = text.splitlines()

ENTRIES = {
    "MetavideoToText": "metavideototext-bot.service",
    "X Downloader": "videodownloader-bot.service",
    "Meta Downloader": "botdescargador.service",
}

missing = {k: v for k, v in ENTRIES.items() if v not in text}
if not missing:
    print("[OK] MetavideoToText y X Downloader ya están en maestro.py")
    raise SystemExit(0)

in_servicios = False
added: list[str] = []
out: list[str] = []
for i, line in enumerate(lines):
    if "SERVICIOS" in line and "=" in line:
        in_servicios = True
    if in_servicios and line.strip() == "}":
        for name, unit in missing.items():
            if unit in "\n".join(out):
                continue
            if out and out[-1].strip().startswith('"') and not out[-1].rstrip().endswith(","):
                out[-1] = out[-1].rstrip() + ","
            out.append(f'    "{name}": "{unit}",')
            added.append(name)
        in_servicios = False
    out.append(line)

if not added:
    raise SystemExit(
        "[ERROR] No encontré SERVICIOS = { ... }. Añade a mano en maestro.py:\n"
        + "\n".join(f'    "{k}": "{v}",' for k, v in missing.items())
    )

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("[OK] Añadido al maestro:", ", ".join(added))
PY

echo ""
echo "=== Bloque SERVICIOS en maestro.py ==="
python3 <<'PY'
from pathlib import Path
text = Path("/home/admin/maestro.py").read_text(encoding="utf-8")
start = text.find("SERVICIOS")
if start < 0:
    print("(no hay SERVICIOS)")
else:
    chunk = text[start : start + 900]
    print(chunk.split("}", 1)[0] + "}")
PY
