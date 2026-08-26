#!/usr/bin/env python3
"""Añade comas faltantes SOLO en entradas del dict SERVICIOS = { ... }."""
from __future__ import annotations

import re
from pathlib import Path

path = Path("/home/admin/maestro.py")
lines = path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
in_servicios = False
# Entrada típica: "Nombre": "unit.service",
_ENTRY = re.compile(r'^\s*"[^"]+"\s*:\s*"[^"]+"\s*,?\s*$')

for i, line in enumerate(lines):
    if "SERVICIOS" in line and "=" in line and "{" in line:
        in_servicios = True
    if in_servicios:
        stripped = line.strip()
        if _ENTRY.match(line) and not stripped.endswith(","):
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else "}"
            if nxt.startswith('"') or nxt == "}":
                line = line.rstrip() + ","
        if stripped == "}":
            in_servicios = False
    out.append(line)

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("[OK] Comas corregidas en SERVICIOS")
