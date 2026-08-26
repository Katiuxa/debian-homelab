#!/usr/bin/env bash
# Permite que maestro.py use apt/systemctl/reboot sin TTY ni contraseña.
set -eu

USER="${1:-admin}"
SUDOERS="/etc/sudoers.d/maestro-${USER}"

if [ "$(id -u)" -ne 0 ]; then
  echo "[*] Instalando reglas sudo (pide contraseña una vez)..."
  exec sudo bash "$0" "$USER"
fi

TMP="$(mktemp)"
cat >"$TMP" <<EOF
# Bot maestro.py — panel Telegram (${USER})
${USER} ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt
${USER} ALL=(ALL) NOPASSWD: /usr/bin/apt-get *, /usr/bin/apt *
${USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl *
${USER} ALL=(ALL) NOPASSWD: /usr/bin/journalctl *
${USER} ALL=(ALL) NOPASSWD: /usr/sbin/reboot, /sbin/reboot
${USER} ALL=(ALL) NOPASSWD: /usr/sbin/shutdown, /sbin/shutdown
${USER} ALL=(ALL) NOPASSWD: /usr/sbin/poweroff, /sbin/poweroff
EOF

install -m 440 "$TMP" "$SUDOERS"
rm -f "$TMP"

if ! visudo -cf "$SUDOERS" >/dev/null; then
  echo "[ERROR] sudoers invalido: $SUDOERS"
  exit 1
fi

if sudo -u "$USER" sudo -n true 2>/dev/null; then
  echo "[OK] sudo sin contraseña para ${USER}"
else
  echo "[AVISO] Reglas instaladas; prueba: sudo -n apt-get update"
fi
