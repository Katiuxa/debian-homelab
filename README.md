# Home Lab y administración de servidor (Raspberry Pi)

Configuración, administración y mantenimiento de un servidor doméstico 24/7 sobre una Raspberry Pi 3 Model B (Debian).

El objetivo es mantener servicios continuos (bots de automatización y servidor de archivos) en hardware muy limitado (1 GB de RAM): optimización de memoria, monitorización y acceso remoto.

## Hardware y stack

- Hardware: Raspberry Pi 3 Model B (1 GB RAM), reciclada de un DreamPi.
- Sistema: Debian (Linux), usuario `admin`.
- Almacenamiento: MicroSD 128 GB (sistema; antes 8 GB) y USB Kingston 128 GB (datos, montado en `/media/admin/KINGSTON`).
- Acceso remoto: SSH, TigerVNC y Tailscale.
- Servicios: systemd y scripts en Bash.
- Disco en red: File Browser por HTTP en la LAN.

Todos los bots y File Browser están activos a la vez en esa RAM.

## Arquitectura y recursos

La limitación principal es correr a la vez varios procesos Python, conversiones con `ebook-convert` (Calibre) y ffmpeg en 1 GB. No hay modelo de lenguaje local: 1 GB no da. Lo pesado de texto se manda a la API de Groq (repo [Telegram-Bots-Suite](https://github.com/Katiuxa/Telegram-Bots-Suite)).

### Memoria (zRAM)

El swap en la MicroSD desgastaba la tarjeta y era lento, sobre todo con la SD de 8 GB. Se sustituyó por zRAM (compresión en RAM, algoritmo lz4, hasta ~50 % de la RAM). Sigue teniendo sentido con 1 GB aunque la SD sea ahora de 128 GB: el cuello es la memoria, no el tamaño del disco.

```bash
sudo bash scripts-mantenimiento/zram-enable.sh
bash scripts-mantenimiento/zram-status.sh
```

### Almacenamiento

- **tmpfs / `/tmp`:** las conversiones pesadas no se dejan en la MicroSD. Con 1 GB hay que vigilar que Calibre no deje basura en RAM.
- **USB y catálogo:** la colección de epubs no cabía en 128 GB. Se recortó el árbol de ficheros y se regeneró `biblioteca.db` solo con lo que quedó (`ajustar_biblioteca_usb.py` en Telegram-Bots-Suite).
- **Umbral de disco:**

```bash
bash scripts-mantenimiento/control-espacio.sh 85
```

## Servicios y operación

Los bots y File Browser van como unidades systemd. Detalle de montajes, VNC y unidades: [debian-raspberry/ADMINISTRACION.md](debian-raspberry/ADMINISTRACION.md).

### Panel maestro

`debian-raspberry/panel-maestro/maestro.py` es un bot de Telegram para incidencias sin SSH constante: estado, arranque y reinicio de unidades systemd desde un chat autorizado. Token y sudo por variables de entorno (`TELEGRAM_BOT_TOKEN`, `MAESTRO_SUDO_PASS`). No van en el código.

### Mantenimiento y copias

```bash
bash scripts-mantenimiento/healthcheck-servicios.sh
sudo bash scripts-mantenimiento/rotar-logs.sh
bash scripts-mantenimiento/backup-rsync.sh /media/admin/KINGSTON/backups
```

- `healthcheck-servicios.sh` — estado UP/DOWN de los procesos críticos.
- `rotar-logs.sh` — recorte de logs para no saturar disco.
- `backup-rsync.sh` — copia incremental de código y config (sin `.env` ni bases) al USB.

No hay un cron de imagen de la SD que se ejecute solo. En el PC Windows hay copias `.img` hechas a mano.

## Qué cubre

Diagnóstico en hardware justo, systemd, zRAM, espacio en SD/USB/tmpfs, SSH/VNC, y no fingir capacidad que 1 GB no tiene.
