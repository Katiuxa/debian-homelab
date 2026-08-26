#!/usr/bin/env bash
# Configura Instagram en la Pi: deps, impersonate, cookies si existen, reinicio.
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
SERVICE_NAME="metavideototext-bot"
SUDO_PASS="${PI_SUDO_PASS:-1234}"

sudo_cmd() {
  echo "$SUDO_PASS" | sudo -S "$@" 2>/dev/null
}

echo "=== Instagram / Reels en Pi ==="

.venv/bin/python -m pip install -U curl-cffi yt-dlp-ejs instaloader -q
.venv/bin/python -m pip install --force-reinstall --no-deps -U \
  "yt-dlp @ https://github.com/yt-dlp/yt-dlp/archive/refs/heads/master.tar.gz" -q

echo "[*] yt-dlp $(.venv/bin/python -m yt_dlp --version)"
.venv/bin/python -m yt_dlp --list-impersonate-targets 2>&1 | head -3

if [ -f cookies.txt ] && [ "$(wc -c < cookies.txt)" -gt 50 ]; then
  echo "[OK] cookies.txt presente ($(wc -c < cookies.txt | tr -d ' ') bytes)"
else
  echo "[AVISO] Sin cookies.txt — Reels privados o con login fallaran."
fi

if systemctl list-unit-files "${SERVICE_NAME}.service" 2>/dev/null | grep -q "${SERVICE_NAME}"; then
  sudo_cmd systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  systemctl is-active "${SERVICE_NAME}.service"
fi

echo "=== Listo ==="
