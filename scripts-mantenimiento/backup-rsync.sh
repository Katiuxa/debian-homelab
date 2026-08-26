#!/usr/bin/env bash
# Copia rsync de configs y código de bots a un USB o carpeta destino.
# No clona la SD entera (eso se hacía a mano desde el PC con imágenes .img).
# Uso: bash backup-rsync.sh /media/admin/KINGSTON/backups
set -euo pipefail

DEST="${1:-}"
if [[ -z "$DEST" ]]; then
  echo "Uso: $0 /ruta/destino" >&2
  exit 1
fi
mkdir -p "$DEST"

HOST="$(hostname)"
STAMP="$(date +%Y%m%d-%H%M)"
OUT="$DEST/${HOST}-${STAMP}"
mkdir -p "$OUT"

rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'temp' \
  --exclude '*.db' \
  --exclude '.env' \
  /home/admin/ "$OUT/home-admin/" \
  --include '*/' \
  --include '*.py' \
  --include '*.sh' \
  --include '*.service' \
  --include '*.example' \
  --include 'requirements.txt' \
  --exclude '*' || true

# Lista de unidades y montajes, sin secretos.
systemctl list-units --type=service --state=running > "$OUT/services-running.txt"
df -hT > "$OUT/df.txt"
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,UUID > "$OUT/lsblk.txt"
find /etc/systemd/system -name '*.service' -exec cp {} "$OUT/systemd/" \; 2>/dev/null || mkdir -p "$OUT/systemd"

# Conservar 5 copias
ls -1dt "$DEST/${HOST}-"* 2>/dev/null | tail -n +6 | xargs -r rm -rf
echo "backup en $OUT"
