#!/usr/bin/env bash
# Actualiza codigo ya copiado en la Pi: deps + reinicio del servicio
set -eu

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
SERVICE_NAME="metavideototext-bot"
SUDO_PASS="${PI_SUDO_PASS:-1234}"

sudo_cmd() {
  echo "$SUDO_PASS" | sudo -S "$@" 2>/dev/null
}

echo ""
echo "=== MetavideoToText_bot - actualizar en Pi ==="
echo "Directorio: $PROJECT_DIR"
echo ""

for f in deploy/*.sh LANZAR_BOT.sh DETENER_BOT.sh; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || true
  fi
done

if [ ! -d .venv ]; then
  echo "[ERROR] No hay .venv. Ejecuta primero: bash deploy/install_on_pi.sh"
  exit 1
fi

echo "[*] Fecha de actualizacion en la Pi..."
date "+%Y-%m-%d %H:%M:%S" > BOT_VERSION.txt
MARKER="force_end_v2"
echo "$MARKER" >> BOT_VERSION.txt

echo "[*] .env Pi (YouTube solo audio, timeouts largos)..."
bash deploy/patch_pi_env.sh

echo "[*] Dependencias..."
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt -q
.venv/bin/python -m pip install --force-reinstall --no-deps -U "yt-dlp @ https://github.com/yt-dlp/yt-dlp/archive/refs/heads/master.tar.gz" -q
.venv/bin/python -m pip install -U curl-cffi yt-dlp-ejs -q
.venv/bin/python -c "import telegram; print('OK telegram')"
.venv/bin/python -c "
import importlib.metadata
import yt_dlp
print('yt-dlp', yt_dlp.version.__version__)
try:
    print('yt-dlp-ejs', importlib.metadata.version('yt-dlp-ejs'))
except Exception:
    print('[AVISO] Falta yt-dlp-ejs')
try:
    print('curl_cffi', importlib.metadata.version('curl_cffi'))
except Exception:
    print('[AVISO] Falta curl_cffi (Instagram/Reels)')
"

if systemctl list-unit-files "${SERVICE_NAME}.service" 2>/dev/null | grep -q "${SERVICE_NAME}"; then
  if [ -x /home/admin/.deno/bin/deno ]; then
    echo "[*] deno en PATH del servicio systemd..."
    sudo_cmd mkdir -p "/etc/systemd/system/${SERVICE_NAME}.service.d"
    sudo_cmd tee "/etc/systemd/system/${SERVICE_NAME}.service.d/deno.conf" >/dev/null <<'EOF'
[Service]
Environment="PATH=/home/admin/.deno/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EOF
    sudo_cmd systemctl daemon-reload
  fi
  echo "[*] Reiniciando ${SERVICE_NAME}..."
  sudo_cmd systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  sudo_cmd systemctl status "${SERVICE_NAME}.service" --no-pager || true
else
  echo "[AVISO] Sin servicio systemd. Detén instancias viejas y: bash LANZAR_BOT.sh"
fi

echo "[*] Comprobando codigo desplegado..."
if grep -q "force_end_heavy_job" bot/services/user_busy.py && grep -q "_JOB_INVALID" bot/services/user_busy.py; then
  echo "[OK] Cancelar/ ocupado: parche force_end_v2 presente"
else
  echo "[ERROR] El codigo en la Pi NO tiene el parche de cancelar. Vuelve a copiar desde el PC."
  exit 1
fi

echo ""
echo "=== Actualizado ==="
echo "  Fecha: $(head -1 BOT_VERSION.txt)"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo ""
