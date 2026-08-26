#!/usr/bin/env bash
# Instalacion en Raspberry Pi (ejecutar: bash deploy/install_on_pi.sh)
set -eu

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

for f in deploy/*.sh LANZAR_BOT.sh DETENER_BOT.sh; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || true
  fi
done

SERVICE_NAME="metavideototext-bot"
RUN_USER="${SUDO_USER:-$USER}"
RUN_GROUP="$(id -gn "$RUN_USER" 2>/dev/null || echo "$RUN_USER")"

echo ""
echo "=== MetavideoToText_bot - instalacion en Pi ==="
echo "Directorio: $PROJECT_DIR"
echo "Usuario:    $RUN_USER"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Falta python3."
  echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[*] Instalando FFmpeg..."
  sudo apt-get update -qq
  sudo apt-get install -y ffmpeg
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "[AVISO] Creado .env - edita TELEGRAM_BOT_TOKEN y GROQ_API_KEY"
  else
    echo "[ERROR] No hay .env ni .env.example"
    exit 1
  fi
fi

if [ ! -d .venv ]; then
  echo "[*] Entorno virtual..."
  python3 -m venv .venv
fi

echo "[*] Dependencias en .venv (no usar pip del sistema)..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
.venv/bin/python -c "import telegram; print('OK telegram')"

chmod +x LANZAR_BOT.sh DETENER_BOT.sh 2>/dev/null || true

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
echo "[*] Creando servicio systemd: $UNIT_PATH"

sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=MetavideoToText Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/home/admin/.deno/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/run.py
Restart=on-failure
RestartSec=20

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"

if grep -q 'TELEGRAM_BOT_TOKEN=tu_token' .env 2>/dev/null; then
  echo ""
  echo "[AVISO] Edita .env: nano $PROJECT_DIR/.env"
  echo "        sudo systemctl start ${SERVICE_NAME}"
  exit 0
fi

echo "[*] Iniciando servicio..."
sudo systemctl restart "${SERVICE_NAME}.service"
sleep 2
sudo systemctl status "${SERVICE_NAME}.service" --no-pager || true

echo ""
echo "=== Listo ==="
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo ""
