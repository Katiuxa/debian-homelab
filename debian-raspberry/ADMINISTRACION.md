# Raspberry Pi 3B administration

Typical hostname and user: Debian, user `admin`. LAN address comes from DHCP (do not publish the public IP).

## Access

```bash
ssh admin@raspberrypi.local
```

Desktop: **TigerVNC** (server on the Pi, viewer on the PC). SSH covers the console and file copies. VNC is for when a GUI is needed (File Browser, one-off checks).

SSH keys live on the PC (`id_ed25519_*`). The password is not in the repo scripts: `PI_SSH_PASSWORD` / `PI_HOST` come from the environment.

## systemd units (all at once)

| Unit | Role |
|---|---|
| `maestro.service` | Telegram panel: restart services |
| `metavideototext-bot.service` | Meta Media to Text |
| `botconversor.service` | Calibre (EPUB/PDF/…) |
| `botdescargador.service` | Video download |
| `bot_ebooks.service` | SQLite catalog on the USB drive |
| `botmail.service` | mail.tm accounts |
| `mi_bot.service` | OnlyNews |
| `videodownloader-bot.service` | X / video |
| `filebrowser.service` | Network disk (HTTP) |

```bash
systemctl status metavideototext-bot
journalctl -u bot_ebooks -n 80 --no-pager
```

The master panel does not restart blindly: it avoids cutting off a send while there is work in that service's temp directory.

## Disks

```text
/          128 GB MicroSD (previously 8 GB)
/tmp       tmpfs (RAM) — risky on 1 GB if Calibre leaves junk behind
/media/admin/KINGSTON   128 GB USB — EPUBs + biblioteca.db
```

Check that the USB drive is mounted before trusting the library bot:

```bash
findmnt /media/admin/KINGSTON
df -h /media/admin/KINGSTON
```

## File Browser

Serves the USB drive and/or `/home/admin` on the LAN. It is this Pi's online disk: copy, delete, and read logs without SSH. On 1 GB, do not index huge trees at the same time as ffmpeg.

## zRAM

File `/etc/default/zramswap`:

```text
ALGO=lz4
PERCENT=50
PRIORITY=100
```

Check with `swapon --show` and `cat /sys/block/zram0/mm_stat`.

## What does not run here

- Local Ollama or Whisper: they do not fit.
- A full SD card image: that was made from the PC (`.img` files), not by a timer on the Pi.
