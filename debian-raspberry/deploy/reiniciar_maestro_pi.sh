#!/usr/bin/env bash
# Una sola instancia de maestro.py vía systemd (arranque automático tras reboot)
set -eu

MAESTRO="/home/admin/maestro.py"
LOG="/home/admin/maestro.log"
UNIT="maestro.service"
UNIT_PATH="/etc/systemd/system/${UNIT}"

count_maestro() {
  pgrep -cf '[p]ython3.*/home/admin/maestro.py' 2>/dev/null || echo 0
}

list_maestro() {
  pgrep -af '[p]ython3.*/home/admin/maestro.py' || true
}

echo "[*] Matando procesos sueltos (nohup antiguos)..."
while read -r pid; do
  [ -n "$pid" ] || continue
  kill -9 "$pid" 2>/dev/null || true
done < <(pgrep -f 'python3.*/home/admin/maestro.py' || true)
sleep 1

if [ -f "/home/admin/maestro.service" ]; then
  echo "[*] Instalando unidad systemd..."
  sudo cp /home/admin/maestro.service "$UNIT_PATH"
  sudo chmod 644 "$UNIT_PATH"
  sudo systemctl daemon-reload
fi

if systemctl list-unit-files "$UNIT" 2>/dev/null | grep -q "$UNIT"; then
  echo "[*] Habilitando arranque automatico + reinicio servicio..."
  sudo systemctl enable "$UNIT"
  sudo systemctl restart "$UNIT"
  sleep 3
  sudo systemctl is-active "$UNIT" || true
else
  echo "[AVISO] Sin $UNIT — arranque manual nohup"
  cd /home/admin
  nohup /usr/bin/python3 "$MAESTRO" >> "$LOG" 2>&1 &
  sleep 2
fi

N="$(count_maestro)"
list_maestro
if [ "$N" -eq 0 ]; then
  echo "[ERROR] maestro.py no arranco"
  tail -20 "$LOG" 2>/dev/null || true
  journalctl -u "$UNIT" -n 15 --no-pager 2>/dev/null || true
  exit 1
fi
if [ "$N" -gt 1 ]; then
  echo "[ERROR] Hay $N procesos maestro (debe ser 1)"
  exit 1
fi

echo "[OK] Maestro unico activo (autostart tras reboot). Pulsa /start en Telegram."
