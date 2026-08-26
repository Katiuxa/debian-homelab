#!/usr/bin/env bash
# Comprueba unidades systemd de los bots y File Browser.
# Uso: bash healthcheck-servicios.sh
set -euo pipefail

UNITS=(
  maestro.service
  metavideototext-bot.service
  botconversor.service
  botdescargador.service
  bot_ebooks.service
  botmail.service
  mi_bot.service
  videodownloader-bot.service
  filebrowser.service
)

fallos=0
printf '%-32s %-10s %-10s %s\n' "UNIDAD" "ACTIVO" "HABILITADO" "MEMORIA"
for u in "${UNITS[@]}"; do
  if ! systemctl list-unit-files "$u" >/dev/null 2>&1; then
    printf '%-32s %-10s\n' "$u" "AUSENTE"
    continue
  fi
  activo=$(systemctl is-active "$u" 2>/dev/null || true)
  hab=$(systemctl is-enabled "$u" 2>/dev/null || true)
  mem=$(systemctl show "$u" -p MemoryCurrent --value 2>/dev/null || echo "")
  if [[ "$mem" =~ ^[0-9]+$ ]] && [[ "$mem" != "18446744073709551615" ]]; then
    mem_h="$((mem / 1024 / 1024))M"
  else
    mem_h="-"
  fi
  printf '%-32s %-10s %-10s %s\n' "$u" "$activo" "$hab" "$mem_h"
  if [[ "$activo" != "active" ]]; then
    fallos=$((fallos + 1))
    journalctl -u "$u" -n 15 --no-pager >&2 || true
  fi
done

echo
echo "loadavg: $(cut -d' ' -f1-3 /proc/loadavg)"
echo "mem:     $(free -h | awk '/Mem:/ {print $3 "/" $2}')"
if [[ -d /sys/block/zram0 ]]; then
  echo "zram:    $(awk '{printf "%.0fM comprimido / %.0fM original\n", $3/1024/1024, $4/1024/1024}' /sys/block/zram0/mm_stat 2>/dev/null || echo presente)"
else
  echo "zram:    no"
fi

exit "$fallos"
