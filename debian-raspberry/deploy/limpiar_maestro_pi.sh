#!/usr/bin/env bash
# Mata TODAS las instancias de maestro y arranca UNA sola con el codigo de /home/admin/maestro.py
set -eu

MAESTRO="/home/admin/maestro.py"
LOG="/home/admin/maestro.log"
PY="/usr/bin/python3"

echo "[1] Codigo en disco:"
if grep -q 'Usa los botones' "$MAESTRO" 2>/dev/null; then
  echo "    ERROR: maestro.py tiene texto viejo en disco"
  exit 1
fi
echo "    OK (sin mensaje basura)"

echo "[2] Copias de maestro.py en la Pi:"
find /home/admin -name 'maestro.py' 2>/dev/null || true

echo "[3] Procesos ANTES (cualquier maestro.py):"
ps aux | grep '[p]ython.*maestro.py' || echo "    (ninguno)"

echo "[4] Parar systemd temporalmente (se re-habilita al final):"
for svc in maestro.service admin-maestro.service; do
  if systemctl list-unit-files "$svc" 2>/dev/null | grep -q "$svc"; then
    sudo systemctl stop "$svc" 2>/dev/null || true
    echo "    stop $svc"
  fi
done

echo "[5] Matar procesos maestro (cualquier ruta):"
while read -r pid; do
  [ -n "$pid" ] || continue
  echo "    kill $pid"
  kill -9 "$pid" 2>/dev/null || true
done < <(pgrep -f '[p]ython.*maestro.py' || true)
sleep 2

REMAINING=$(pgrep -f '[p]ython.*maestro.py' 2>/dev/null | wc -l)
REMAINING=${REMAINING// /}
if [ "$REMAINING" != "0" ]; then
  echo "    ERROR: siguen $REMAINING proceso(s):"
  pgrep -af '[p]ython.*maestro.py' || true
  exit 1
fi
echo "    OK cero procesos"

echo "[6] Sincronizar copia en MetavideoToText_bot/deploy/:"
if [ -d /home/admin/MetavideoToText_bot/deploy ]; then
  cp "$MAESTRO" /home/admin/MetavideoToText_bot/deploy/maestro.py
  grep -q 'Usa los botones' /home/admin/MetavideoToText_bot/deploy/maestro.py \
    && echo "    ERROR: copia deploy sigue con codigo viejo" && exit 1 \
    || echo "    OK copiado"
fi

echo "[7] Validar y arrancar:"
python3 /home/admin/fix_maestro_servicios_comma.py
python3 -m py_compile "$MAESTRO"
bash /home/admin/patch_maestro_on_pi.sh
bash /home/admin/reiniciar_maestro_pi.sh

echo "[8] Procesos DESPUES:"
ps aux | grep '[p]ython3 /home/admin/maestro.py'
echo "[9] Log:"
tail -3 "$LOG" 2>/dev/null || true
echo "[OK] Maestro unico. Pulsa /start en Telegram."
