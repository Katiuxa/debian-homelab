"""Analiza logs de la Pi: actividad real, sin spam de polling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("pi_services.json")

IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

# Solo spam puro (polling cada 10 s)
POLL_SPAM = re.compile(r"getUpdates.*HTTP/1\.1 200", re.I)

STARTUP_SPAM = re.compile(
    r"^(Descripción del bot actualizada|No `JobQueue`|setMyDescription|"
    r"setMyShortDescription|deleteWebhook|getMe )",
    re.I,
)

SSH_LINE = re.compile(
    r"(Accepted|Failed|Invalid user|Connection closed by|Disconnected from|Received disconnect)",
    re.I,
)

# SSH rutinario del propio panel / tu PC — no aporta
OWNER_SSH_ROUTINE = re.compile(
    r"(Accepted publickey for admin|Disconnected from user admin|"
    r"Received disconnect from|Connection closed by authenticating user admin)",
    re.I,
)

TG_API = re.compile(
    r"/bot[^/]+/(sendMessage|sendAudio|sendDocument|editMessageText|"
    r"answerCallbackQuery|sendPhoto|sendVideo|getFile|sendVoice)",
    re.I,
)

MAESTRO_CHAT = re.compile(r"chat=(\d+).*text=(.+)", re.I)


@dataclass
class LogHit:
    service: str
    label: str
    ts: str
    kind: str
    origin: str  # owner | other | foreign | unknown
    ips: list[str]
    summary: str
    full: str
    foreign_ips: list[str] = field(default_factory=list)
    owner_ips: list[str] = field(default_factory=list)
    audit: dict | None = None
    tg_uid: int | None = None
    tg_user: str = ""


AUDIT_RE = re.compile(r"\[AUDIT\]\s*(\{.*\})")


def load_config() -> dict:
    import os

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["host"] = os.environ.get("PI_HOST", data.get("host", "raspberrypi.local"))
    data["user"] = os.environ.get("PI_USER", data.get("user", "admin"))
    data["password"] = os.environ.get("PI_PASS", data.get("password", "1234"))
    data["ssh_alias"] = os.environ.get("PI_SSH_ALIAS", data.get("ssh_alias", "pi-bot"))
    if os.environ.get("PI_LOG_HOURS", "").strip().isdigit():
        data["log_since_hours"] = int(os.environ["PI_LOG_HOURS"])
    extra = os.environ.get("PI_OWNER_IPS", "")
    if extra.strip():
        data["owner_ips"] = [x.strip() for x in extra.split(",") if x.strip()]
    extra_tg = os.environ.get("PI_OWNER_TELEGRAM_IDS", "")
    if extra_tg.strip():
        data["owner_telegram_ids"] = [
            int(x.strip()) for x in extra_tg.split(",") if x.strip().isdigit()
        ]
    return data


def owner_telegram_ids(cfg: dict) -> set[int]:
    out: set[int] = set()
    for x in cfg.get("owner_telegram_ids") or []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            pass
    return out


def owner_ips(cfg: dict) -> set[str]:
    base = set(cfg.get("owner_ips") or [])
    base.update({"127.0.0.1", "::1", "localhost"})
    return base


def _unit_arg(unit: str) -> str:
    return unit if unit.endswith(".service") else f"{unit}.service"


def _extract_ts(line: str) -> str:
    m = re.match(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    if m:
        return m.group(1).replace("T", " ")
    m = re.match(r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)
    return m.group(1) if m else ""


def _short(text: str, n: int = 140) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _ips_in_line(line: str) -> list[str]:
    return IPV4.findall(line)


def _is_ssh_noise(line: str, owners: set[str]) -> bool:
    if not SSH_LINE.search(line):
        return False
    if re.search(r"Failed|Invalid user|authentication failure", line, re.I):
        return False
    ips = _ips_in_line(line)
    if ips and all(ip in owners for ip in ips) and OWNER_SSH_ROUTINE.search(line):
        return True
    return False


def _is_spam(line: str) -> bool:
    if POLL_SPAM.search(line):
        return True
    if STARTUP_SPAM.search(line.strip()):
        return True
    if "Application started" in line or "Application.stop() complete" in line:
        return True
    return False


def _tg_origin(owners_tg: set[int], uid: int | None = None, who: str = "") -> str:
    if who == "OTHER":
        return "other"
    if who == "OWNER" or (uid is not None and uid in owners_tg):
        return "owner"
    return "owner"  # sin AUDIT: actividad bot = tú (único admin)


def _parse_audit_line(
    line: str,
    *,
    service: str,
    label: str,
    owners_tg: set[int],
) -> LogHit | None:
    m = AUDIT_RE.search(line)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    uid = data.get("uid")
    try:
        uid_int = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_int = None

    who = str(data.get("who") or "").upper()
    phase = str(data.get("phase") or "")
    action = str(data.get("action") or "?")
    detail_in = str(data.get("in") or "")
    detail_out = str(data.get("out") or "")
    uname = str(data.get("user") or "")
    origin = _tg_origin(owners_tg, uid_int, who)

    if phase == "in":
        summary = f"⬇️ Pidió · {action}: {detail_in or detail_out}"
    elif phase == "out":
        summary = f"⬆️ Bot respondió · {action}: {detail_out or detail_in}"
    elif phase == "err":
        summary = f"❌ Error · {action}: {detail_out or detail_in}"
    else:
        summary = f"{action}: {detail_in or detail_out}"

    return LogHit(
        service=service,
        label=label,
        ts=_extract_ts(line),
        kind="audit",
        origin=origin,
        ips=[],
        summary=_short(summary),
        full=line,
        audit=data,
        tg_uid=uid_int,
        tg_user=uname,
    )


def _parse_maestro(line: str, owners_tg: set[int]) -> LogHit | None:
    m = MAESTRO_CHAT.search(line)
    if not m:
        return None
    chat_id = int(m.group(1))
    text = m.group(2).strip()
    origin = "owner" if chat_id in owners_tg else "other"
    return LogHit(
        service="maestro",
        label="Maestro",
        ts=_extract_ts(line),
        kind="maestro",
        origin=origin,
        ips=[],
        summary=_short(f"Maestro chat={chat_id}: {text}"),
        full=line,
        tg_uid=chat_id,
    )


def _summarize_tg_api(line: str) -> str | None:
    m = TG_API.search(line)
    if not m:
        return None
    action = m.group(1).lower()
    labels = {
        "sendmessage": "📤 Bot envió mensaje",
        "sendaudio": "🎵 Bot envió audio/MP3",
        "senddocument": "📎 Bot envió archivo",
        "editmessagetext": "✏️ Bot actualizó mensaje/progreso",
        "answercallbackquery": "👆 Bot respondió botón",
        "sendphoto": "🖼 Bot envió imagen",
        "sendvideo": "🎬 Bot envió vídeo",
        "sendvoice": "🎤 Bot envió nota de voz",
        "getfile": "⬇️ Bot descargó de Telegram",
    }
    code = re.search(r"HTTP/1\.1 (\d+)", line)
    st = code.group(1) if code else "?"
    return f"{labels.get(action, action)} [HTTP {st}]"


def classify_line(
    line: str,
    *,
    service: str,
    label: str,
    owners: set[str],
    owners_tg: set[int],
) -> LogHit | None:
    line = line.rstrip()
    if not line.strip() or _is_spam(line) or _is_ssh_noise(line, owners):
        return None

    ips = _ips_in_line(line)
    mine = [ip for ip in ips if ip in owners]
    foreign = [ip for ip in ips if ip not in owners]
    ts = _extract_ts(line)

    maestro = _parse_maestro(line, owners_tg)
    if maestro:
        return maestro

    if SSH_LINE.search(line) and ips:
        return LogHit(
            service=service,
            label=label,
            ts=ts,
            kind="ssh",
            origin="foreign" if foreign and not mine else "owner",
            ips=ips,
            owner_ips=mine,
            foreign_ips=foreign,
            summary=_short(line),
            full=line,
        )

    tg_sum = _summarize_tg_api(line)
    if tg_sum:
        # Progreso UI: muchos editMessageText 400 — ruido si no hay error real
        if "editmessagetext" in line.lower() and "HTTP 400" in tg_sum:
            return None
        return LogHit(
            service=service,
            label=label,
            ts=ts,
            kind="telegram",
            origin="owner",
            ips=ips,
            summary=tg_sum,
            full=line,
        )

    if foreign and not re.search(r"bot\.|httpx|YouTube", line, re.I):
        return LogHit(
            service=service,
            label=label,
            ts=ts,
            kind="foreign_ip",
            origin="foreign",
            ips=ips,
            foreign_ips=foreign,
            summary=_short(line),
            full=line,
        )

    if re.search(
        r"bot\.(services|handlers)|YouTube|yt-dlp|ytdlp|MP3|transcri|"
        r"RuntimeError|ERROR|WARNING|Exception|Traceback|"
        r"Bad Request|falló|Started|Stopped|Restart|Deactivated|"
        r"sendAudio|sendMessage|link_mode|download",
        line,
        re.I,
    ):
        return LogHit(
            service=service,
            label=label,
            ts=ts,
            kind="activity",
            origin="owner",
            ips=ips,
            summary=_short(line),
            full=line,
        )

    if mine:
        return LogHit(
            service=service,
            label=label,
            ts=ts,
            kind="mine_ip",
            origin="owner",
            ips=ips,
            owner_ips=mine,
            summary=_short(line),
            full=line,
        )

    return None


def fetch_service_logs(ssh, unit: str, *, since_hours: int, max_lines: int) -> list[str]:
    cmd = (
        f"journalctl -u {_unit_arg(unit)} --since '{since_hours} hours ago' "
        f"-n {max_lines} --no-pager -o short-iso 2>/dev/null"
    )
    _rc, out, _err = ssh.run(cmd, timeout=120)
    return [ln for ln in out.splitlines() if ln.strip()]


def fetch_ssh_logs(ssh, *, since_hours: int, max_lines: int) -> list[str]:
    cmd = (
        f"journalctl -t ssh -t sshd -t sshd-session --since '{since_hours} hours ago' "
        f"-n {max_lines} --no-pager -o short-iso 2>/dev/null"
    )
    _rc, out, _err = ssh.run(cmd, timeout=60)
    return [ln for ln in out.splitlines() if ln.strip()]


def collect_hits(
    ssh,
    cfg: dict,
    *,
    service_filter: str | None = None,
    foreign_only: bool = False,
    mine_only: bool = False,
    others_only: bool = False,
    audit_only: bool = False,
    hours: int | None = None,
) -> list[LogHit]:
    from deploy.pi_panel import _services

    since = hours or int(cfg.get("log_since_hours", 6))
    max_lines = int(cfg.get("log_lines_per_service", 1000))
    services = _services(cfg)
    hits: list[LogHit] = []
    owners = owner_ips(cfg)
    owners_tg = owner_telegram_ids(cfg)

    units = services
    if service_filter and service_filter not in ("all", "*"):
        units = [(u, l) for u, l in services if u == service_filter]

    for unit, label in units:
        for line in fetch_service_logs(ssh, unit, since_hours=since, max_lines=max_lines):
            hit = _parse_audit_line(line, service=unit, label=label, owners_tg=owners_tg)
            if not hit:
                hit = classify_line(
                    line,
                    service=unit,
                    label=label,
                    owners=owners,
                    owners_tg=owners_tg,
                )
            if hit:
                hits.append(hit)

    if not service_filter or service_filter in ("all", "*", "ssh"):
        for line in fetch_ssh_logs(ssh, since_hours=since, max_lines=max_lines):
            hit = classify_line(
                line,
                service="ssh",
                label="SSH / acceso",
                owners=owners,
                owners_tg=owners_tg,
            )
            if hit:
                hits.append(hit)

    if others_only:
        hits = [h for h in hits if h.origin == "other" or (h.origin == "foreign" and h.kind == "foreign_ip")]
    elif foreign_only:
        hits = [h for h in hits if h.origin == "foreign"]
    elif mine_only:
        hits = [h for h in hits if h.origin == "owner"]
    if audit_only:
        hits = [h for h in hits if h.kind == "audit"]

    hits.sort(key=lambda h: h.ts, reverse=True)
    return hits
