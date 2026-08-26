#!/bin/bash
# Instalación en Raspberry Pi (ejecutar UNA vez dentro de esta carpeta)
set -euo pipefail
cd "$(dirname "$0")"

echo "== Madame Zara — setup Raspberry Pi =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Instala Python 3: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ""
  echo "IMPORTANTE: edita .env antes de arrancar:"
  echo "  nano .env"
  echo ""
fi

CARD_COUNT=$(find assets/cards -maxdepth 1 -name '*.jpg' 2>/dev/null | wc -l || true)
if [[ "${CARD_COUNT:-0}" -lt 78 ]]; then
  echo "Descargando imágenes del mazo (78 cartas)..."
  python scripts/download_cards.py
else
  echo "Cartas OK (${CARD_COUNT} imágenes en assets/cards/)"
fi

echo ""
echo "Listo. Para arrancar el bot:"
echo "  cd $(pwd)"
echo "  source .venv/bin/activate"
echo "  python bot.py"
echo ""
echo "NO arranques aquí si el bot sigue activo en Windows (mismo TELEGRAM_TOKEN)."
