# Administración de la Raspberry Pi 3B

Hostname/usuario típicos: Debian, usuario `admin`. IP de LAN por DHCP (no publicar la IP pública).

## Acceso

```bash
ssh admin@raspberrypi.local
```

Escritorio: **TigerVNC** (servidor en la Pi, visor en el PC). SSH cubre consola y copias; VNC cuando hace falta GUI (File Browser, comprobaciones puntuales).

Claves SSH en el PC (`id_ed25519_*`). La contraseña no va en los scripts del repo: `PI_SSH_PASSWORD` / `PI_HOST` en el entorno.

## Unidades systemd (todas a la vez)

| Unidad | Función |
|---|---|
| `maestro.service` | Panel Telegram: restart de servicios |
| `metavideototext-bot.service` | Meta Media to Text |
| `botconversor.service` | Calibre (EPUB/PDF/…) |
| `botdescargador.service` | Descarga de vídeo |
| `bot_ebooks.service` | Catálogo SQLite en USB |
| `botmail.service` | Cuentas mail.tm |
| `mi_bot.service` | OnlyNoticias |
| `videodownloader-bot.service` | X / vídeo |
| `filebrowser.service` | Disco en red (HTTP) |

```bash
systemctl status metavideototext-bot
journalctl -u bot_ebooks -n 80 --no-pager
```

El maestro no reinicia a ciegas: evita cortar un envío si hay trabajo en el directorio temp del servicio.

## Discos

```text
/          MicroSD 128 GB (antes 8 GB)
/tmp       tmpfs (RAM) — peligroso en 1 GB si Calibre deja basura
/media/admin/KINGSTON   USB 128 GB — epubs + biblioteca.db
```

Comprobar montaje del USB antes de dar por bueno el bot de biblioteca:

```bash
findmnt /media/admin/KINGSTON
df -h /media/admin/KINGSTON
```

## File Browser

Sirve el USB y/o `/home/admin` en la LAN. Es el “disco duro online” de esta Pi: copiar, borrar y ver logs sin SSH. En 1 GB conviene no indexar árboles enormes a la vez que ffmpeg.

## zRAM

Fichero `/etc/default/zramswap`:

```text
ALGO=lz4
PERCENT=50
PRIORITY=100
```

Comprobar: `swapon --show` y `cat /sys/block/zram0/mm_stat`.

## Lo que no corre aquí

- Ollama / Whisper local: no caben.
- Imagen completa de la SD: se hacía desde el PC (ficheros `.img`), no con un timer en la Pi.
