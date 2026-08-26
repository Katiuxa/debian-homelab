#!/usr/bin/env bash
# zRAM en Raspberry Pi 3B (1 GB RAM).
# Swap en la MicroSD es lenta y desgasta la tarjeta. zRAM comprime páginas
# en RAM (lz4): en 1 GB da margen cuando corren a la vez bots, Calibre,
# File Browser y tmpfs.
# Uso: sudo bash zram-enable.sh
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Ejecutar como root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y zram-tools

# 50% de 1 GB ≈ 512 MB de dispositivo zRAM (el dato comprimido ocupa menos).
cat >/etc/default/zramswap <<'EOF'
ALGO=lz4
PERCENT=50
PRIORITY=100
EOF

systemctl enable --now zramswap.service || systemctl restart zramswap.service || true
if systemctl list-unit-files | grep -q zramswap; then
  systemctl restart zramswap.service
fi

echo "swapon:"
swapon --show
echo
echo "zram0:"
if [[ -e /sys/block/zram0/disksize ]]; then
  awk '{printf "disksize=%sM\n", $1/1024/1024}' /sys/block/zram0/disksize
fi
free -h
