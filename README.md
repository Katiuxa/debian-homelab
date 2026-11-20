# Home lab and server administration (Raspberry Pi)

Configuration, administration, and maintenance of a 24/7 home server on a Raspberry Pi 3 Model B (Debian).

The goal is to keep continuous services (automation bots and a file server) running on very limited hardware (1 GB of RAM): memory tuning, monitoring, and remote access.

## Hardware and stack

- Hardware: Raspberry Pi 3 Model B (1 GB RAM), reused from a DreamPi.
- System: Debian (Linux), user `admin`.
- Storage: 128 GB MicroSD (system; previously 8 GB) and a 128 GB Kingston USB drive (data, mounted at `/media/admin/KINGSTON`).
- Remote access: SSH, TigerVNC, and Tailscale.
- Services: systemd and Bash scripts.
- Network disk: File Browser over HTTP on the LAN.

Every bot and File Browser run at the same time in that RAM.

## Architecture and resources

The main constraint is running several Python processes, `ebook-convert` (Calibre) conversions, and ffmpeg at once inside 1 GB. There is no local language model: 1 GB is not enough. Heavy text work is sent to the Groq API (repo [Telegram-Bots-Suite](https://github.com/Katiuxa/Telegram-Bots-Suite)).

### Memory (zRAM)

Swap on the MicroSD wore the card out and was slow, especially on the 8 GB SD. It was replaced with zRAM (compression in RAM, lz4, up to about 50% of RAM). It still makes sense with 1 GB even though the SD is now 128 GB: the bottleneck is memory, not disk size.

```bash
sudo bash scripts-mantenimiento/zram-enable.sh
bash scripts-mantenimiento/zram-status.sh
```

### Storage

- **tmpfs / `/tmp`:** heavy conversions are not left on the MicroSD. With 1 GB, watch that Calibre does not leave junk in RAM.
- **USB and catalog:** the EPUB collection did not fit in 128 GB. The file tree was trimmed and `biblioteca.db` was regenerated with only what remained (`ajustar_biblioteca_usb.py` in Telegram-Bots-Suite).
- **Disk threshold:**

```bash
bash scripts-mantenimiento/control-espacio.sh 85
```

## Services and operation

The bots and File Browser run as systemd units. Mounts, VNC, and units are detailed in [debian-raspberry/ADMINISTRACION.md](debian-raspberry/ADMINISTRACION.md).

### Master panel

`debian-raspberry/panel-maestro/maestro.py` is a Telegram bot for incidents when you do not want to stay on SSH: status, start, and restart of systemd units from an authorized chat. The token and sudo password come from environment variables (`TELEGRAM_BOT_TOKEN`, `MAESTRO_SUDO_PASS`). They are not in the code.

### Maintenance and backups

```bash
bash scripts-mantenimiento/healthcheck-servicios.sh
sudo bash scripts-mantenimiento/rotar-logs.sh
bash scripts-mantenimiento/backup-rsync.sh /media/admin/KINGSTON/backups
```

- `healthcheck-servicios.sh` — UP/DOWN status of the critical processes.
- `rotar-logs.sh` — trims logs so they do not fill the disk.
- `backup-rsync.sh` — incremental copy of code and config (no `.env` files and no databases) to the USB drive.

There is no cron job that images the SD card by itself. On the Windows PC there are `.img` copies made by hand.

## What this covers

Diagnosis on tight hardware, systemd, zRAM, free space on the SD card, the USB drive, and tmpfs, SSH/VNC, and not pretending that 1 GB can do more than it can.
