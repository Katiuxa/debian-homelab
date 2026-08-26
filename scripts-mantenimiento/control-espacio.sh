#!/usr/bin/env bash
# Alerta si la SD, el USB o /tmp (tmpfs) superan el umbral.
# Uso: bash control-espacio.sh [porcentaje]
set -euo pipefail

UMBRAL="${1:-85}"
PUNTOS=("/" "/tmp" "/media/admin/KINGSTON" "/home")

aviso=0
df -hT | awk 'NR==1 || /ext4|vfat|tmpfs|exfat|ntfs/'
echo
for p in "${PUNTOS[@]}"; do
  [[ -d "$p" ]] || continue
  uso=$(df -P "$p" | awk 'NR==2 {gsub("%","",$5); print $5}')
  avail=$(df -hP "$p" | awk 'NR==2 {print $4}')
  fstype=$(df -PT "$p" | awk 'NR==2 {print $2}')
  printf '%-28s %3s%% usado  libre=%-8s tipo=%s\n' "$p" "$uso" "$avail" "$fstype"
  if [[ "$uso" -ge "$UMBRAL" ]]; then
    echo "  -> por encima del umbral ${UMBRAL}%"
    du -xh "$p" --max-depth=2 2>/dev/null | sort -h | tail -n 12
    aviso=1
  fi
done

# Inodos: una SD pequeña se llena de ficheros vacíos/temp sin llenar bytes.
echo
df -i / /home 2>/dev/null | awk 'NR==1 || NR>1 {print}'

exit "$aviso"
