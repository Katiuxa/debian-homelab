import logging
import os
import re
import subprocess
import threading
import time
import traceback
from pathlib import Path

import psutil
import telebot
import telebot.apihelper
from telebot import types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("maestro")

telebot.apihelper.CONNECT_TIMEOUT = 60
telebot.apihelper.READ_TIMEOUT = 60

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN en el entorno.")
bot = telebot.TeleBot(TOKEN)
LOG = os.environ.get("MAESTRO_LOG", "/home/admin/maestro.log")
SUDO_PASSWORD = os.environ.get("MAESTRO_SUDO_PASS", "")

# Nombre visible -> unidad systemd (estado + menú)
# Nota: telegram_bot.service ejecuta el MISMO mi_bot.py que OnlyNews; no va en reinicios.
SERVICIOS = {
    "Conversor Archivos": "botconversor.service",
    "Meta Downloader": "botdescargador.service",
    "BibliotecaSecreta": "bot_ebooks.service",
    "Meta Mail": "botmail.service",
    "OnlyNews": "mi_bot.service",
    "File Browser": "filebrowser.service",
    "MetavideoToText": "metavideototext-bot.service",
    "X Downloader": "videodownloader-bot.service",
}

# IDs cortos para callback_data (sin espacios; max 64 bytes Telegram)
RESTART_IDS = {
    "conv": "Conversor Archivos",
    "mdl": "Meta Downloader",
    "desc": "Meta Downloader",  # alias menús antiguos
    "ebooks": "BibliotecaSecreta",
    "mail": "Meta Mail",
    "news": "OnlyNews",
    "fb": "File Browser",
    "meta": "MetavideoToText",
    "xdl": "X Downloader",
}

# Carpetas de trabajo/temp por unidad: usadas para no romper envíos en curso
WORK_PATHS: dict[str, list[str]] = {
    "botconversor.service": [
        "/home/admin/temp_conversor",
        "/home/admin/BotConversor",
    ],
    "botdescargador.service": [
        "/home/admin/BotDescargador/temp",
        "/home/admin/BotDescargador",
    ],
    "bot_ebooks.service": [
        "/home/admin/Desktop",
    ],
    "botmail.service": [
        "/home/admin/BotMail",
    ],
    "mi_bot.service": [
        "/home/admin/bots",
    ],
    "filebrowser.service": [],
    "metavideototext-bot.service": [
        "/home/admin/MetavideoToText_bot/temp",
    ],
    "videodownloader-bot.service": [
        "/home/admin/VideoDownloader_bot/temp",
        "/home/admin/VideoDownloader_bot/deploy/temp",
    ],
}

# Temps que LIMPIEZA puede vaciar solo si el archivo NO está en uso y es antiguo
TEMP_CLEAN_DIRS = [
    "/home/admin/MetavideoToText_bot/temp",
    "/home/admin/VideoDownloader_bot/temp",
    "/home/admin/VideoDownloader_bot/deploy/temp",
    "/home/admin/BotDescargador/temp",
    "/home/admin/temp_conversor",
]

TEMP_MIN_AGE_MIN = 20
BUSY_RECENT_MIN = 3
DUPLICATE_ONLYNEWS_UNIT = "telegram_bot.service"

BOTONES_MENU = (
    "📊 ESTADO COMPLETO",
    "🛠 ACTUALIZAR SISTEMA",
    "🧹 LIMPIEZA MAGICA",
    "🔄 MENU REINICIOS",
    "⚡ ENERGIA",
)

INTERVALO_BARRA = 2
APT_ENV = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

_esperando_clave: set[int] = set()
_actualizando = threading.Lock()
_limpiando = threading.Lock()
_reiniciando = threading.Lock()


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def es_boton_menu(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip()
    if t in BOTONES_MENU:
        return True
    up = re.sub(r"[^\w\s]", "", t, flags=re.UNICODE).upper()
    return any(
        k.replace(" ", "") in up.replace(" ", "")
        for k in (
            "ESTADO COMPLETO",
            "ACTUALIZAR SISTEMA",
            "LIMPIEZA MAGICA",
            "MENU REINICIOS",
            "ENERGIA",
        )
    )


def id_por_nombre(bot_name: str) -> str | None:
    for rid, nombre in RESTART_IDS.items():
        if nombre == bot_name:
            return rid
    return None


def dispatch_boton(chat_id: int, text: str) -> None:
    t = text.strip()
    up = t.upper()
    log(f"boton chat={chat_id} text={t!r}")

    if t == "📊 ESTADO COMPLETO" or "ESTADO COMPLETO" in up:
        enviar_estado_completo(chat_id)
    elif t == "🛠 ACTUALIZAR SISTEMA" or "ACTUALIZAR SISTEMA" in up:
        iniciar_actualizacion_con_progreso(chat_id)
    elif t == "🧹 LIMPIEZA MAGICA" or "LIMPIEZA" in up:
        limpieza_magica(chat_id)
    elif t == "🔄 MENU REINICIOS" or "REINICIOS" in up:
        markup = types.InlineKeyboardMarkup(row_width=2)
        for rid, nombre in RESTART_IDS.items():
            markup.add(
                types.InlineKeyboardButton(
                    f"🔄 {nombre}", callback_data=f"res:{rid}"
                )
            )
        bot.send_message(
            chat_id,
            "⚙️ **REINICIAR SERVICIO:**\n"
            "_Si un bot está enviando un archivo, te pediré confirmación._",
            reply_markup=markup,
            parse_mode="Markdown",
        )
    elif t == "⚡ ENERGIA" or up == "ENERGIA" or "ENERGIA" in up:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔄 REBOOT PI", callback_data="reboot_pi"),
            types.InlineKeyboardButton("🛑 SHUTDOWN PI", callback_data="shutdown_pi"),
        )
        bot.send_message(
            chat_id,
            "⚠️ **CONTROL DE ENERGIA**",
            reply_markup=markup,
            parse_mode="Markdown",
        )


def barra_progreso(porcentaje, ancho=14):
    p = max(0, min(100, int(porcentaje)))
    lleno = round(ancho * p / 100)
    vacio = ancho - lleno
    return f"{'█' * lleno}{'░' * vacio}  {p}%"


def mensaje_progreso(
    titulo: str,
    pct: int,
    *,
    fase: str = "",
    pie: str = "",
) -> str:
    """Formato común: título → fase → (línea en blanco) → barra → pie."""
    partes = [titulo.rstrip()]
    if fase:
        partes.append(fase.rstrip())
    partes.append("")  # aire antes de la barra
    partes.append(barra_progreso(pct))
    if pie:
        partes.append(pie.rstrip())
    return "\n".join(partes)


def teclado_principal():
    """Teclado junto al 📎 (ReplyKeyboard): menú en PC y móvil."""
    markup = types.ReplyKeyboardMarkup(
        row_width=2,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Elige una opción…",
    )
    markup.row(BOTONES_MENU[0], BOTONES_MENU[1])
    markup.row(BOTONES_MENU[2], BOTONES_MENU[3])
    markup.row(BOTONES_MENU[4])
    return markup


def boton_actualizar_pendiente():
    """Único botón bajo ESTADO cuando hay actualizaciones."""
    mk = types.InlineKeyboardMarkup()
    mk.add(
        types.InlineKeyboardButton(
            "🛠 Actualizar",
            callback_data="update_system",
        )
    )
    return mk


def count_pending_updates(timeout: int = 12) -> int:
    """Cuenta pendientes del cache apt local (rápido; sin apt update)."""
    try:
        out = subprocess.run(
            ["bash", "-lc", "apt list --upgradable 2>/dev/null | tail -n +2 | wc -l"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return max(0, int((out.stdout or "0").strip() or 0))
    except subprocess.TimeoutExpired:
        log("count_pending_updates: timeout apt")
        return -1
    except Exception as exc:
        log(f"count_pending_updates: {exc}")
        return -1


def _run_short(cmd: list[str], timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        log(f"timeout: {' '.join(cmd)}")
        return "timeout"
    except Exception as exc:
        log(f"cmd error {cmd}: {exc}")
        return "error"


def _texto_progreso_estado(pct: int, fase: str = "Consultando Pi…") -> str:
    return mensaje_progreso(f"⏳ {fase}", pct)


def _unit_main_pids(unit: str) -> list[int]:
    out = _run_short(
        ["systemctl", "show", unit, "-p", "MainPID", "-p", "ControlPID", "--value"],
        timeout=8,
    )
    pids: list[int] = []
    for line in (out or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pid = int(line)
            if pid > 0:
                pids.append(pid)
    # Hijos del proceso principal
    extra: list[int] = []
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            extra.extend(c.pid for c in proc.children(recursive=True))
        except (psutil.Error, ValueError):
            pass
    return sorted(set(pids + extra))


def _normalize_path(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return os.path.abspath(p)


def _fd_targets(pids: list[int]) -> set[str]:
    targets: set[str] = set()
    for pid in pids:
        fd_dir = Path(f"/proc/{pid}/fd")
        if not fd_dir.is_dir():
            continue
        try:
            for entry in fd_dir.iterdir():
                try:
                    target = os.readlink(entry)
                except OSError:
                    continue
                if target.startswith("/") and not target.startswith("/dev/"):
                    targets.add(_normalize_path(target))
        except OSError:
            continue
    return targets


def _under_any(path: str, roots: list[str]) -> bool:
    np = _normalize_path(path)
    for root in roots:
        nr = _normalize_path(root)
        if np == nr or np.startswith(nr + os.sep):
            return True
    return False


def archivos_abiertos_en(roots: list[str], pids: list[int] | None = None) -> list[str]:
    if not roots:
        return []
    if pids is None:
        pids = [p.pid for p in psutil.process_iter(["pid"]) if p.pid > 1]
    abiertos: list[str] = []
    for target in _fd_targets(pids):
        if _under_any(target, roots):
            abiertos.append(target)
    return sorted(set(abiertos))


def archivos_recientes_en(roots: list[str], minutos: int = BUSY_RECENT_MIN) -> list[str]:
    cutoff = time.time() - minutos * 60
    recientes: list[str] = []
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        try:
            iterator = base.rglob("*") if base.is_dir() else []
        except OSError:
            continue
        for path in iterator:
            try:
                if path.is_file() and path.stat().st_mtime >= cutoff:
                    recientes.append(str(path))
            except OSError:
                continue
    return recientes[:20]


def servicio_ocupado(unit: str) -> tuple[bool, str]:
    """True si el servicio parece estar enviando/procesando archivos."""
    roots = WORK_PATHS.get(unit, [])
    media_roots = [r for r in roots if "temp" in r.lower() or r.endswith("temp_conversor")]
    check_roots = media_roots or roots
    pids = _unit_main_pids(unit)
    if not pids and not check_roots:
        return False, ""

    abiertos = archivos_abiertos_en(check_roots, pids=pids or None)
    if abiertos:
        sample = ", ".join(Path(p).name for p in abiertos[:3])
        return True, f"archivos abiertos ({sample})"

    # Señal suave: escritura reciente en temp del bot (descarga/encode en curso)
    if media_roots:
        recientes = archivos_recientes_en(media_roots, BUSY_RECENT_MIN)
        if recientes and pids:
            # Solo si el proceso del bot sigue vivo
            sample = ", ".join(Path(p).name for p in recientes[:3])
            return True, f"actividad reciente en temp ({sample})"
    return False, ""


def bots_ocupados() -> list[tuple[str, str, str]]:
    """Lista (nombre, unit, motivo) de bots con trabajo en curso."""
    ocupados = []
    for nombre, unit in SERVICIOS.items():
        busy, motivo = servicio_ocupado(unit)
        if busy:
            ocupados.append((nombre, unit, motivo))
    return ocupados


def _todos_fds_abiertos() -> set[str]:
    pids = [p.pid for p in psutil.process_iter(["pid"]) if p.pid > 1]
    return _fd_targets(pids)


def limpiar_temps_seguros(min_age_min: int = TEMP_MIN_AGE_MIN) -> tuple[int, int]:
    """Borra solo ficheros viejos y sin fd abierto. Devuelve (borrados, omitidos)."""
    cutoff = time.time() - min_age_min * 60
    abiertos = _todos_fds_abiertos()
    borrados = 0
    omitidos = 0
    for root in TEMP_CLEAN_DIRS:
        base = Path(root)
        if not base.is_dir():
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.name in {".gitkeep", ".git"}:
                continue
            try:
                if not path.is_file():
                    # En temp_conversor puede haber subdirs (libros); no borramos árboles enteros
                    continue
                if path.stat().st_mtime >= cutoff:
                    omitidos += 1
                    continue
                if _normalize_path(str(path)) in abiertos:
                    omitidos += 1
                    log(f"limpieza: omito abierto {path}")
                    continue
                path.unlink()
                borrados += 1
            except OSError as exc:
                omitidos += 1
                log(f"limpieza: no borré {path}: {exc}")
    return borrados, omitidos


def get_status(updates: int | None = None, on_progress=None):
    if on_progress:
        on_progress(20, "Midiendo temperatura, CPU y RAM…")

    temp_raw = _run_short(["vcgencmd", "measure_temp"], timeout=5)
    if temp_raw and temp_raw not in ("timeout", "error"):
        temp = temp_raw.replace("temp=", "").replace("'C", "C")
    else:
        temp = "N/D"

    ram = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent(interval=0.1)
    disk = psutil.disk_usage("/")
    free_sd = round(disk.free / (1024**3), 2)

    if on_progress:
        on_progress(40, "Comprobando actualizaciones…")
    if updates is None:
        updates = count_pending_updates()

    if updates < 0:
        updates_txt = "N/D (apt ocupado o lento tras reinicio)"
    else:
        updates_txt = f"{updates} pendientes"

    reporte = (
        f"🌡 TEMP: {temp} | 🧠 CPU: {cpu}%\n"
        f"📊 RAM: {ram}%\n"
        f"💾 LIBRE SD: {free_sd} GB\n"
        f"📦 ACTUALIZACIONES: {updates_txt}\n\n"
        f"🤖 ESTADO SERVICIOS:\n"
    )

    if on_progress:
        on_progress(65, "Consultando servicios…")

    units = list(SERVICIOS.values())
    svc_list = " ".join(units)
    batch = _run_short(
        [
            "bash",
            "-lc",
            f"for s in {svc_list}; do "
            f"printf '%s:%s\\n' \"$s\" \"$(systemctl is-active \"$s\" 2>/dev/null || echo unknown)\"; "
            f"done",
        ],
        timeout=20,
    )
    status_map: dict[str, str] = {}
    if batch not in ("timeout", "error"):
        for line in batch.splitlines():
            if ":" in line:
                svc, st = line.split(":", 1)
                status_map[svc.strip()] = st.strip()

    for nombre, servicio in SERVICIOS.items():
        status = status_map.get(servicio, "unknown")
        emoji = "🟢" if status == "active" else "🔴"
        reporte += f"{emoji} {nombre}: {status.upper()}\n"

    if on_progress:
        on_progress(90, "Preparando informe…")
    return reporte, max(0, updates)


def mensaje_actualizacion(pct, fase, detalle=""):
    pie = f"_{detalle[:120]}_" if detalle else ""
    return mensaje_progreso(
        "⏳ **Actualizando Raspberry Pi**",
        pct,
        fase=f"**{fase}**",
        pie=pie,
    )


def probar_sudo(password: str) -> tuple[bool, str]:
    r = subprocess.run(
        ["sudo", "-S", "-k", "true"],
        input=f"{password}\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or r.stdout or "Contraseña incorrecta").strip()[:300]
    return False, err


def sudo_cmd(password: str, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-S", *args],
        input=f"{password}\n",
        capture_output=True,
        text=True,
        env=APT_ENV,
        timeout=timeout,
    )


def run_system_update(chat_id: int, msg_id: int, password: str) -> None:
    if not _actualizando.acquire(blocking=False):
        bot.send_message(chat_id, "⏳ Ya hay una actualización en curso.")
        return

    last_edit = 0.0

    def edit(pct, fase, detalle="", force=False):
        nonlocal last_edit
        now = time.time()
        if not force and now - last_edit < INTERVALO_BARRA:
            return
        last_edit = now
        try:
            bot.edit_message_text(
                mensaje_actualizacion(pct, fase, detalle),
                chat_id,
                msg_id,
                parse_mode="Markdown",
            )
        except Exception:
            pass

    try:
        edit(5, "Comprobando contraseña", force=True)
        ok, err = probar_sudo(password)
        if not ok:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            bot.send_message(
                chat_id,
                f"❌ **Contraseña sudo incorrecta**\n`{err}`",
                parse_mode="Markdown",
                reply_markup=teclado_principal(),
            )
            return

        edit(10, "Sincronizando repositorios", "apt update...", force=True)
        r = sudo_cmd(password, ["apt-get", "update", "-qq"], timeout=600)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "error desconocido")[:500]
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            bot.send_message(
                chat_id,
                f"❌ **Error en apt update**\n`{err}`",
                parse_mode="Markdown",
                reply_markup=teclado_principal(),
            )
            return

        edit(20, "Comprobando paquetes pendientes", force=True)
        pending = count_pending_updates()
        if pending <= 0:
            edit(100, "Sistema al día", force=True)
            # Ya hicimos apt update: no volver a sincronizar
            reporte, _ = get_status(updates=0)
            bot.send_message(
                chat_id,
                f"✅ **Ya estaba actualizado**\n\n{reporte}",
                parse_mode="Markdown",
                reply_markup=teclado_principal(),
            )
            return

        edit(30, f"Instalando {pending} paquete(s)", "apt dist-upgrade...", force=True)
        proc = subprocess.Popen(
            [
                "sudo",
                "-S",
                "apt-get",
                "dist-upgrade",
                "-y",
                "-o",
                "Dpkg::Options::=--force-confdef",
                "-o",
                "Dpkg::Options::=--force-confold",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=APT_ENV,
        )
        assert proc.stdin is not None
        proc.stdin.write(f"{password}\n")
        proc.stdin.close()

        done_pkgs = 0
        last_pct = 30
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            m = re.search(r"Progress:\s*\[\s*(\d+)%\]", line)
            if m:
                dpkg_pct = int(m.group(1))
                pct = 30 + int(dpkg_pct * 0.55)
                edit(pct, "Instalando paquetes", line)
                last_pct = max(last_pct, pct)
            elif "Setting up" in line or "Unpacking" in line:
                done_pkgs += 1
                pct = 30 + min(55, int(done_pkgs / max(pending, 1) * 55))
                if pct > last_pct:
                    last_pct = pct
                    edit(pct, "Instalando paquetes", line)

        proc.wait()
        if proc.returncode != 0:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            bot.send_message(
                chat_id,
                "❌ **Error** durante dist-upgrade. Revisa `/home/admin/maestro.log`",
                parse_mode="Markdown",
                reply_markup=teclado_principal(),
            )
            return

        edit(88, "Limpiando paquetes obsoletos", "apt autoremove...", force=True)
        sudo_cmd(password, ["apt-get", "autoremove", "-y", "-qq"], timeout=300)
        edit(95, "Finalizando", force=True)

        edit(100, "Completado", "Sistema actualizado", force=True)
        reporte, _ = get_status(updates=0)
        bot.send_message(
            chat_id,
            f"✅ Actualización OK\n\n{reporte}",
            reply_markup=teclado_principal(),
        )
    finally:
        _actualizando.release()


def pedir_contrasena(chat_id: int) -> None:
    """Arranca la actualización con la contraseña fija (sin pedirla por chat)."""
    _esperando_clave.discard(chat_id)
    # No decidir aquí: run_system_update hace apt update y luego cuenta de verdad
    arrancar_actualizacion(chat_id, SUDO_PASSWORD, None)


def arrancar_actualizacion(chat_id: int, password: str, pwd_msg_id: int | None) -> None:
    if pwd_msg_id:
        try:
            bot.delete_message(chat_id, pwd_msg_id)
        except Exception:
            pass
    msg = bot.send_message(
        chat_id,
        mensaje_actualizacion(0, "Preparando…", "No cierres el bot"),
        parse_mode="Markdown",
    )
    threading.Thread(
        target=run_system_update,
        args=(chat_id, msg.message_id, password),
        daemon=True,
    ).start()


def borrar_mensaje(chat_id: int, msg_id: int) -> None:
    try:
        bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


def mostrar_estado_completo(chat_id: int, msg_id: int | None = None) -> None:
    log(f"estado_completo chat={chat_id} msg_id={msg_id}")
    try:
        if msg_id is None:
            wait = bot.send_message(chat_id, _texto_progreso_estado(15))
            msg_id = wait.message_id
        else:
            bot.edit_message_text(_texto_progreso_estado(15), chat_id, msg_id)
    except Exception as exc:
        log(f"estado_completo send error: {exc}")
        return

    def on_progress(pct: int, fase: str) -> None:
        try:
            bot.edit_message_text(_texto_progreso_estado(pct, fase), chat_id, msg_id)
        except Exception:
            pass

    def _worker():
        try:
            reporte, updates = get_status(on_progress=on_progress)
            # Solo un botón bajo el estado si hay pendientes (sin menú inline)
            if updates > 0:
                reply_markup = boton_actualizar_pendiente()
            else:
                reply_markup = types.InlineKeyboardMarkup()  # quita botones previos
            bot.edit_message_text(
                reporte,
                chat_id,
                msg_id,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            log(f"estado_completo worker: {exc}\n{traceback.format_exc()}")
            try:
                bot.edit_message_text(
                    f"❌ Error al leer estado: {exc}",
                    chat_id,
                    msg_id,
                )
            except Exception:
                bot.send_message(
                    chat_id,
                    f"❌ Error al leer estado: {exc}",
                    reply_markup=teclado_principal(),
                )

    threading.Thread(target=_worker, daemon=True).start()


def enviar_estado_completo(chat_id: int) -> None:
    mostrar_estado_completo(chat_id)


def iniciar_actualizacion_con_progreso(chat_id: int) -> None:
    """Siempre arranca el flujo real (apt update → contar → instalar si hay)."""
    _esperando_clave.discard(chat_id)
    arrancar_actualizacion(chat_id, SUDO_PASSWORD, None)


def _systemctl(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-n", "systemctl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _esperar_activo(servicio: str, segundos: int = 45) -> str:
    status = "unknown"
    deadline = time.time() + segundos
    while time.time() < deadline:
        status = subprocess.run(
            ["systemctl", "is-active", servicio],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if status == "active":
            return status
        time.sleep(1)
    return status


def _parar_duplicado_onlynews() -> str:
    """Si telegram_bot (mismo mi_bot.py) está activo, lo para para evitar conflicto."""
    st = subprocess.run(
        ["systemctl", "is-active", DUPLICATE_ONLYNEWS_UNIT],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if st != "active":
        return ""
    r = _systemctl(["stop", DUPLICATE_ONLYNEWS_UNIT], timeout=60)
    if r.returncode == 0:
        return f"\n🔇 Detenido duplicado `{DUPLICATE_ONLYNEWS_UNIT}` (mismo OnlyNews)."
    err = (r.stderr or r.stdout or "").strip()[:200]
    return f"\n⚠️ No pude parar `{DUPLICATE_ONLYNEWS_UNIT}`: {err}"


def reiniciar_servicio_con_progreso(
    chat_id: int, bot_name: str, forzar: bool = False
) -> None:
    servicio = SERVICIOS.get(bot_name)
    if not servicio:
        bot.send_message(chat_id, f"❌ Servicio desconocido: {bot_name}")
        return

    rid = id_por_nombre(bot_name) or "?"
    if not forzar:
        busy, motivo = servicio_ocupado(servicio)
        if busy:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "⚠️ Forzar reinicio", callback_data=f"force:{rid}"
                )
            )
            markup.add(
                types.InlineKeyboardButton("❌ Cancelar", callback_data="res_cancel")
            )
            bot.send_message(
                chat_id,
                f"⏳ **{bot_name}** parece ocupado: _{motivo}_\n\n"
                "Reiniciar ahora puede cortar un envío de vídeo/archivo.\n"
                "Espera a que termine o fuerza el reinicio.",
                parse_mode="Markdown",
                reply_markup=markup,
            )
            return

    msg = bot.send_message(
        chat_id,
        mensaje_progreso(
            f"🔄 **Reiniciando {bot_name}**",
            10,
            pie=f"`{servicio}`",
        ),
        parse_mode="Markdown",
    )

    def _worker():
        if not _reiniciando.acquire(blocking=False):
            try:
                bot.edit_message_text(
                    "⏳ Ya hay un reinicio en curso. Espera un momento.",
                    chat_id,
                    msg.message_id,
                )
            except Exception:
                pass
            return
        try:
            fases = (
                (20, "Comprobando unidad…"),
                (40, "Reiniciando servicio…"),
                (75, "Esperando active…"),
            )
            for pct, txt in fases[:2]:
                try:
                    bot.edit_message_text(
                        mensaje_progreso(
                            f"🔄 **Reiniciando {bot_name}**",
                            pct,
                            fase=txt,
                            pie=f"`{servicio}`",
                        ),
                        chat_id,
                        msg.message_id,
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            # Verificar que la unidad existe
            show = _systemctl(["cat", servicio], timeout=20)
            if show.returncode != 0:
                err = (show.stderr or show.stdout or "unidad no encontrada").strip()[:300]
                bot.edit_message_text(
                    f"❌ **{bot_name}**: unidad inexistente o inaccesible\n`{err}`",
                    chat_id,
                    msg.message_id,
                    parse_mode="Markdown",
                )
                return

            r = _systemctl(["restart", servicio], timeout=120)
            extra = ""
            if bot_name == "OnlyNews":
                extra = _parar_duplicado_onlynews()

            try:
                bot.edit_message_text(
                    mensaje_progreso(
                        f"🔄 **Reiniciando {bot_name}**",
                        75,
                        fase="Esperando active…",
                        pie=f"`{servicio}`",
                    ),
                    chat_id,
                    msg.message_id,
                    parse_mode="Markdown",
                )
            except Exception:
                pass

            status = _esperar_activo(servicio, segundos=45)
            ok = r.returncode == 0 and status == "active"
            if not ok and r.returncode == 0:
                # Intento stop+start si restart dejó el servicio raro
                _systemctl(["reset-failed", servicio], timeout=30)
                r2 = _systemctl(["start", servicio], timeout=120)
                status = _esperar_activo(servicio, segundos=30)
                ok = r2.returncode == 0 and status == "active"
                if not ok:
                    r = r2

            emoji = "✅" if ok else "❌"
            detail = ""
            if not ok:
                err = (r.stderr or r.stdout or "").strip()[:280]
                if err:
                    detail = f"`{err}`"
                journal = _run_short(
                    [
                        "bash",
                        "-lc",
                        f"journalctl -u {servicio} -n 5 --no-pager -q 2>/dev/null",
                    ],
                    timeout=15,
                )
                if journal and journal not in ("timeout", "error"):
                    block = f"```\n{journal[-400:]}\n```"
                    detail = f"{detail}\n{block}" if detail else block

            pie_final = ""
            if extra:
                pie_final = extra.strip()
            if detail:
                pie_final = f"{pie_final}\n{detail}".strip() if pie_final else detail

            bot.edit_message_text(
                mensaje_progreso(
                    f"{emoji} **{bot_name}** → `{status.upper()}`",
                    100,
                    pie=pie_final,
                ),
                chat_id,
                msg.message_id,
                parse_mode="Markdown",
            )
            log(f"reinicio {bot_name} ({servicio}) -> {status} ok={ok} force={forzar}")
        except Exception as exc:
            log(f"reinicio error {bot_name}: {exc}\n{traceback.format_exc()}")
            try:
                bot.edit_message_text(
                    f"❌ Error reiniciando **{bot_name}**: `{exc}`",
                    chat_id,
                    msg.message_id,
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        finally:
            _reiniciando.release()

    threading.Thread(target=_worker, daemon=True).start()


def limpieza_magica(chat_id: int) -> None:
    if not _limpiando.acquire(blocking=False):
        bot.send_message(chat_id, "⏳ Ya hay una limpieza en curso.")
        return

    msg = bot.send_message(
        chat_id,
        mensaje_progreso("🧼 **Limpieza del sistema**", 5, fase="Iniciando…"),
        parse_mode="Markdown",
    )

    def _worker():
        try:
            ocupados = bots_ocupados()
            aviso_fase = ""
            if ocupados:
                lista = ", ".join(n for n, _, _ in ocupados)
                aviso_fase = f"Bots ocupados (no toco sus archivos): {lista}"
                try:
                    bot.edit_message_text(
                        mensaje_progreso(
                            "🧼 **Limpieza segura**",
                            5,
                            fase=aviso_fase,
                        ),
                        chat_id,
                        msg.message_id,
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            steps: list[tuple[str, list[str] | None, str]] = [
                ("Borrando caché apt (.deb)…", ["sudo", "-n", "apt-get", "clean"], "apt"),
                (
                    "Vaciando logs journal…",
                    ["sudo", "-n", "journalctl", "--vacuum-size=30M"],
                    "journal",
                ),
                (
                    "Limpiando caché pip…",
                    ["rm", "-rf", os.path.expanduser("~/.cache/pip")],
                    "pip",
                ),
            ]

            # autoremove sin --purge y solo si nadie está enviando
            if not ocupados:
                steps.insert(
                    1,
                    (
                        "Eliminando paquetes huérfanos…",
                        ["sudo", "-n", "apt-get", "autoremove", "-y", "-qq"],
                        "autoremove",
                    ),
                )
            else:
                log("limpieza: skip autoremove porque hay bots ocupados")

            total = len(steps) + 1  # + temps
            notas: list[str] = []
            titulo_limpieza = "🧼 **Limpieza segura**" if ocupados else "🧼 **Limpieza**"
            for i, (txt, cmd, tag) in enumerate(steps, 1):
                pct = int(i / total * 90)
                fase = txt if not aviso_fase else f"{txt}\n_{aviso_fase}_"
                try:
                    bot.edit_message_text(
                        mensaje_progreso(titulo_limpieza, pct, fase=fase),
                        chat_id,
                        msg.message_id,
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if r.returncode != 0:
                        err = (r.stderr or r.stdout or "error").strip()[:160]
                        notas.append(f"· {tag}: {err}")
                        log(f"limpieza {tag} rc={r.returncode}: {err}")
                except subprocess.TimeoutExpired:
                    notas.append(f"· {tag}: timeout")
                except Exception as exc:
                    notas.append(f"· {tag}: {exc}")
                time.sleep(0.2)

            try:
                fase_temps = "Temps de bots (solo viejos y no abiertos)…"
                if aviso_fase:
                    fase_temps = f"{fase_temps}\n_{aviso_fase}_"
                bot.edit_message_text(
                    mensaje_progreso(titulo_limpieza, 95, fase=fase_temps),
                    chat_id,
                    msg.message_id,
                    parse_mode="Markdown",
                )
            except Exception:
                pass

            # Nunca borrar temps de bots con fds abiertos / recientes en uso
            borrados, omitidos = limpiar_temps_seguros()
            notas.append(f"· temps: {borrados} borrados, {omitidos} omitidos (en uso/recientes)")

            reporte, _ = get_status()
            extra = ""
            if notas:
                extra = "\n\n📋 Detalle:\n" + "\n".join(notas)
            if ocupados:
                extra += (
                    "\n\n✅ No se interrumpió ningún envío: "
                    "archivos abiertos/recientes se dejaron intactos."
                )
            final = (
                mensaje_progreso("✨ **Limpieza OK**", 100)
                + extra
                + "\n\n"
                + reporte
            )
            try:
                bot.edit_message_text(
                    final[:4000],
                    chat_id,
                    msg.message_id,
                    parse_mode="Markdown",
                )
            except Exception:
                bot.send_message(
                    chat_id,
                    final[:4000],
                    reply_markup=teclado_principal(),
                )
        except Exception as exc:
            log(f"limpieza error: {exc}\n{traceback.format_exc()}")
            try:
                bot.edit_message_text(
                    f"❌ Error en limpieza: `{exc}`",
                    chat_id,
                    msg.message_id,
                    parse_mode="Markdown",
                )
            except Exception:
                bot.send_message(chat_id, f"❌ Error en limpieza: {exc}")
        finally:
            _limpiando.release()

    threading.Thread(target=_worker, daemon=True).start()


# Un solo handler de texto: sin catch-all que bloquee los botones.
@bot.message_handler(content_types=["text"])
def on_text(message):
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    cid = message.chat.id

    if cid in _esperando_clave:
        if es_boton_menu(text):
            _esperando_clave.discard(cid)
            dispatch_boton(cid, text)
            return
        _esperando_clave.discard(cid)
        password = text
        if not password:
            bot.send_message(
                cid,
                "❌ Contraseña vacía. Pulsa 🛠 ACTUALIZAR SISTEMA otra vez.",
                reply_markup=teclado_principal(),
            )
            return
        arrancar_actualizacion(cid, password, message.message_id)
        return

    if es_boton_menu(text):
        dispatch_boton(cid, text)


@bot.message_handler(commands=["start", "menu", "teclado"])
def send_welcome(message):
    _esperando_clave.discard(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🛰 **ADMINISTRACIÓN RASPBERRY**\n"
        "Panel de Control Maestro\n\n"
        "El menú está en el **teclado junto al 📎** (clip).\n"
        "En el PC: icono de teclado/cuadrito al lado del clip si no lo ves abierto.",
        reply_markup=teclado_principal(),
        parse_mode="Markdown",
    )
    enviar_estado_completo(message.chat.id)


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data or ""

    if data == "res_cancel":
        bot.answer_callback_query(call.id, "Cancelado")
        try:
            bot.edit_message_text(
                "❎ Reinicio cancelado.",
                call.message.chat.id,
                call.message.message_id,
            )
        except Exception:
            pass
        return

    if data.startswith("res:") or data.startswith("force:"):
        forzar = data.startswith("force:")
        rid = data.split(":", 1)[1]
        bot_name = RESTART_IDS.get(rid)
        if not bot_name:
            # Compatibilidad con menú antiguo res_Nombre
            bot.answer_callback_query(call.id, "Botón antiguo; abre MENU REINICIOS otra vez")
            return
        bot.answer_callback_query(
            call.id, f"{'Forzando' if forzar else 'Reiniciando'} {bot_name}..."
        )
        reiniciar_servicio_con_progreso(call.message.chat.id, bot_name, forzar=forzar)
        return

    # Compat menú antiguo: res_Conversor Archivos
    if data.startswith("res_"):
        bot_name = data[4:]
        if bot_name in SERVICIOS:
            bot.answer_callback_query(call.id, f"Reiniciando {bot_name}...")
            reiniciar_servicio_con_progreso(call.message.chat.id, bot_name)
        else:
            bot.answer_callback_query(call.id, "Abre MENU REINICIOS otra vez")
        return

    if data == "update_system":
        bot.answer_callback_query(call.id)
        iniciar_actualizacion_con_progreso(call.message.chat.id)

    elif data == "reboot_pi":
        ocupados = bots_ocupados()
        if ocupados:
            bot.answer_callback_query(call.id, "Hay bots ocupados")
            lista = ", ".join(n for n, _, _ in ocupados)
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "⚠️ Forzar reboot", callback_data="reboot_force"
                )
            )
            bot.send_message(
                call.message.chat.id,
                f"⏳ Bots ocupados: {lista}\n"
                "Un reboot cortará envíos en curso. ¿Forzar?",
                reply_markup=markup,
            )
            return
        bot.answer_callback_query(call.id, "Reiniciando Pi…")
        _do_reboot(call.message.chat.id)

    elif data == "reboot_force":
        bot.answer_callback_query(call.id, "Reboot forzado…")
        _do_reboot(call.message.chat.id)

    elif data == "shutdown_pi":
        ocupados = bots_ocupados()
        if ocupados:
            bot.answer_callback_query(call.id, "Hay bots ocupados")
            lista = ", ".join(n for n, _, _ in ocupados)
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "⚠️ Forzar apagado", callback_data="shutdown_force"
                )
            )
            bot.send_message(
                call.message.chat.id,
                f"⏳ Bots ocupados: {lista}\n"
                "El apagado cortará envíos en curso. ¿Forzar?",
                reply_markup=markup,
            )
            return
        bot.answer_callback_query(call.id, "Apagando Pi…")
        _do_shutdown(call.message.chat.id)

    elif data == "shutdown_force":
        bot.answer_callback_query(call.id, "Apagado forzado…")
        _do_shutdown(call.message.chat.id)


def _do_reboot(chat_id: int) -> None:
    bot.send_message(
        chat_id,
        "🚀 **Reiniciando Raspberry Pi…**\n\n"
        "El maestro volverá solo en ~2 min (servicio `maestro.service`).\n"
        "Luego pulsa /start o 📊 ESTADO COMPLETO.",
        parse_mode="Markdown",
    )
    time.sleep(1.5)
    subprocess.Popen(["sudo", "-n", "reboot"])


def _do_shutdown(chat_id: int) -> None:
    bot.send_message(
        chat_id,
        "🔌 **Apagando sistema…**\n\n"
        "Para volver a usar el panel tendrás que encender la Pi manualmente.",
        parse_mode="Markdown",
    )
    time.sleep(1.5)
    subprocess.Popen(["sudo", "-n", "shutdown", "-h", "now"])


def monitor_temp():
    while True:
        try:
            temp_file = os.popen("vcgencmd measure_temp").readline()
            temp_val = float(temp_file.replace("temp=", "").replace("'C\n", ""))
            if temp_val > 75:
                print(f"ALERTA: Temperatura critica {temp_val}C")
        except Exception:
            pass
        time.sleep(300)


def main() -> None:
    threading.Thread(target=monitor_temp, daemon=True).start()
    log("Maestro arrancando...")
    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True,
            )
        except KeyboardInterrupt:
            log("Maestro detenido por teclado")
            break
        except Exception as exc:
            log(f"Polling caido ({exc!r}), reintento en 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
