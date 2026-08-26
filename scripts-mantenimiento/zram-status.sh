#!/usr/bin/env bash
# Estado de zRAM / swap. Sin argumentos.
set -euo pipefail
echo "=== mem ==="
free -h
echo
echo "=== swap ==="
swapon --show || true
echo
if [[ -d /sys/block/zram0 ]]; then
  echo "=== zram0 mm_stat (orig_data, compr_data, mem_used) ==="
  cat /sys/block/zram0/mm_stat
  echo
  echo "comp_algorithm: $(cat /sys/block/zram0/comp_algorithm 2>/dev/null || true)"
else
  echo "zram0 no está activo"
fi
