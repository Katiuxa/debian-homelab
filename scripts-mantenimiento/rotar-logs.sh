#!/usr/bin/env bash
# Rota y comprime logs de bots / journal. Pensado para no hinchar la SD.
# Uso: sudo bash rotar-logs.sh
set -euo pipefail

LOG_DIR="${LOG_DIR:-/home/admin}"
KEEP_DAYS="${KEEP_DAYS:-7}"

journalctl --vacuum-time="${KEEP_DAYS}d" || true
journalctl --vacuum-size=80M || true

shopt -s nullglob
for f in \
  "$LOG_DIR"/maestro.log \
  "$LOG_DIR"/*.log \
  /var/log/*.log
do
  [[ -f "$f" ]] || continue
  [[ -s "$f" ]] || continue
  tam=$(stat -c%s "$f")
  if (( tam > 1048576 )); then
    gzip -c "$f" > "${f}.$(date +%Y%m%d).gz"
    : > "$f"
    echo "rotado $f ($tam bytes)"
  fi
done

find "$LOG_DIR" -name '*.log.*.gz' -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true
echo "ok"
