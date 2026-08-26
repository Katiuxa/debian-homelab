#!/usr/bin/env python3
"""Panel interactivo: estado y logs en tiempo real de servicios en la Raspberry Pi."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).with_name("pi_services.json")

# ANSI (Windows 10+ CMD lo soporta)
R = "\033[0m"
B = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"


def _enable_vt() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        h = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        kernel.GetConsoleMode(h, ctypes.byref(mode))
        kernel.SetConsoleMode(h, mode.value | 4)
    except Exception:
        pass


def _load_config() -> dict:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["host"] = os.environ.get("PI_HOST", data.get("host", "raspberrypi.local"))
    data["user"] = os.environ.get("PI_USER", data.get("user", "admin"))
    data["password"] = os.environ.get("PI_PASS", data.get("password", "1234"))
    data["ssh_alias"] = os.environ.get("PI_SSH_ALIAS", data.get("ssh_alias", "pi-bot"))
    return data


def _services(cfg: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in cfg.get("services", []):
        unit = str(item.get("unit", "")).strip()
        if not unit:
            continue
        label = str(item.get("label", unit)).strip()
        out.append((unit, label))
    return out


class PiSSH:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._mode = "none"
        self._client = None
        self._ssh_bin = shutil.which("ssh") or "ssh"
        self._target = cfg.get("ssh_alias") or f"{cfg['user']}@{cfg['host']}"

    def connect(self) -> None:
        probe = subprocess.run(
            [self._ssh_bin, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self._target, "echo ok"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if probe.returncode == 0 and "ok" in (probe.stdout or ""):
            self._mode = "openssh"
            return
        try:
            import paramiko
        except ImportError as e:
            raise RuntimeError("Sin clave SSH y falta paramiko. Ejecuta: pip install paramiko") from e
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.cfg["host"],
            username=self.cfg["user"],
            password=self.cfg["password"],
            timeout=20,
            allow_agent=False,
            look_for_keys=False,
        )
        self._client = client
        self._mode = "paramiko"

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def run(self, remote_cmd: str, *, timeout: float = 60) -> tuple[int, str, str]:
        if self._mode == "openssh":
            proc = subprocess.run(
                [self._ssh_bin, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", self._target, remote_cmd],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        assert self._client is not None
        _stdin, stdout, stderr = self._client.exec_command(remote_cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return stdout.channel.recv_exit_status(), out, err

    def stream_follow(self, remote_cmd: str) -> int:
        """Muestra salida en tiempo real (journalctl -f). Ctrl+C para volver."""
        print(f"\n{DIM}Conectando a {self._target}…{R}")
        print(f"{YELLOW}Ctrl+C{R} = volver al menú\n")
        if self._mode == "openssh":
            try:
                return subprocess.call(
                    [self._ssh_bin, "-t", self._target, remote_cmd],
                )
            except KeyboardInterrupt:
                return 130
        assert self._client is not None
        _stdin, stdout, stderr = self._client.exec_command(remote_cmd, get_pty=True)
        chan = stdout.channel
        try:
            while not chan.exit_status_ready():
                if chan.recv_ready():
                    data = chan.recv(4096).decode("utf-8", errors="replace")
                    sys.stdout.write(data)
                    sys.stdout.flush()
                elif chan.recv_stderr_ready():
                    data = chan.recv_stderr(4096).decode("utf-8", errors="replace")
                    sys.stderr.write(data)
                    sys.stderr.flush()
                else:
                    time.sleep(0.05)
            while chan.recv_ready():
                sys.stdout.write(chan.recv(4096).decode("utf-8", errors="replace"))
            return chan.recv_exit_status()
        except KeyboardInterrupt:
            try:
                chan.close()
            except Exception:
                pass
            print(f"\n{YELLOW}— Detenido —{R}\n")
            return 130
        finally:
            if self._mode == "paramiko":
                self.close()
                self.connect()


def _unit_arg(unit: str) -> str:
    return unit if unit.endswith(".service") else f"{unit}.service"


def _status_map(ssh: PiSSH, units: list[str]) -> dict[str, str]:
    joined = " ".join(_unit_arg(u) for u in units)
    cmd = (
        f"for u in {joined}; do "
        f"s=$(systemctl is-active \"$u\" 2>/dev/null || echo unknown); "
        f"echo \"$u|$s\"; done"
    )
    _rc, out, _err = ssh.run(cmd, timeout=30)
    result: dict[str, str] = {}
    for line in out.splitlines():
        if "|" not in line:
            continue
        unit, state = line.split("|", 1)
        key = unit.replace(".service", "")
        result[key] = state.strip()
    return result


def _color_state(state: str) -> str:
    s = state.lower()
    if s == "active":
        return f"{GREEN}● activo{R}"
    if s in ("inactive", "dead"):
        return f"{DIM}○ parado{R}"
    if s == "failed":
        return f"{RED}✖ fallo{R}"
    return f"{YELLOW}? {state}{R}"


def _clear() -> None:
    os.system("cls" if sys.platform == "win32" else "clear")


def _pause() -> None:
    try:
        input(f"\n{DIM}Enter para continuar…{R}")
    except (EOFError, KeyboardInterrupt):
        pass


def _journal_follow(units: list[str], lines: int = 0) -> str:
    parts = " ".join(f"-u {_unit_arg(u)}" for u in units)
    tail = f"-n {lines} " if lines else ""
    return f"journalctl {tail}-f {parts} --no-pager -o short-iso"


def _journal_tail(units: list[str], lines: int = 80) -> str:
    parts = " ".join(f"-u {_unit_arg(u)}" for u in units)
    return f"journalctl -n {lines} {parts} --no-pager -o short-iso"


def _draw_menu(cfg: dict, services: list[tuple[str, str]], statuses: dict[str, str]) -> None:
    _clear()
    host = cfg["host"]
    mode = "SSH clave" if True else ""
    print(f"{B}{CYAN}  PANEL RASPBERRY PI — LOGS EN TIEMPO REAL{R}")
    print(f"{DIM}  {cfg['user']}@{host}  |  Ctrl+C dentro de un log = volver{R}\n")
    print(f"  {'#':>2}  {'Estado':<14}  Servicio")
    print(f"  {'—'*2}  {'—'*14}  {'—'*40}")
    for i, (unit, label) in enumerate(services, start=1):
        st = _color_state(statuses.get(unit, "?"))
        print(f"  {B}{i:>2}{R}  {st:<24}  {label}")
        print(f"      {DIM}{unit}.service{R}")
    print()
    print(f"  {B}A{R}  Ver {MAGENTA}TODOS{R} los servicios mezclados (tiempo real)")
    print(f"  {B}V{R}  Abrir {MAGENTA}ventana por servicio{R} (varias consolas)")
    print(f"  {B}D{R}  Tablero en vivo (estado + última línea, refresco 4 s)")
    print(f"  {B}R{R}  Reiniciar un servicio")
    print(f"  {B}0{R}  Salir")
    print()


def _pick_service(services: list[tuple[str, str]], prompt: str) -> tuple[str, str] | None:
    raw = input(prompt).strip()
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(services):
            return services[idx - 1]
    return None


def _open_windows(cfg: dict, services: list[tuple[str, str]]) -> None:
    ssh_bin = shutil.which("ssh") or "ssh"
    target = cfg.get("ssh_alias") or f"{cfg['user']}@{cfg['host']}"
    print("\nAbriendo una ventana CMD por servicio…")
    for unit, label in services:
        title = f"Pi {label[:30]}"
        remote = _journal_follow([unit])
        cmd = f'title {title} & {ssh_bin} -t {target} "{remote}"'
        subprocess.Popen(f'start "{title}" cmd /k "{cmd}"', shell=True)
        time.sleep(0.3)
    print(f"{GREEN}Ventanas lanzadas.{R} Cierra cada una con Ctrl+C o cerrando la ventana.\n")
    _pause()


def _dashboard(ssh: PiSSH, services: list[tuple[str, str]]) -> None:
    print(f"\n{CYAN}Tablero en vivo{R} — refresco cada 4 s — Ctrl+C para salir\n")
    try:
        while True:
            _clear()
            print(f"{B}{CYAN}  TABLERO PI — {time.strftime('%H:%M:%S')}{R}\n")
            statuses = _status_map(ssh, [u for u, _ in services])
            for unit, label in services:
                st = _color_state(statuses.get(unit, "?"))
                _rc, tail, _ = ssh.run(
                    f"journalctl -u {_unit_arg(unit)} -n 1 --no-pager -o cat 2>/dev/null",
                    timeout=12,
                )
                last = (tail.strip().splitlines() or ["(sin líneas recientes)"])[-1]
                if len(last) > 100:
                    last = last[:97] + "…"
                print(f"  {st}  {B}{label}{R}")
                print(f"      {DIM}{last}{R}\n")
            time.sleep(4)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Tablero cerrado.{R}\n")


def main() -> int:
    _enable_vt()
    if not CONFIG_PATH.is_file():
        print(f"No encuentro {CONFIG_PATH}", file=sys.stderr)
        return 1

    cfg = _load_config()
    services = _services(cfg)
    if not services:
        print("Sin servicios en pi_services.json", file=sys.stderr)
        return 1

    ssh = PiSSH(cfg)
    try:
        ssh.connect()
    except Exception as e:
        print(f"{RED}No pude conectar a la Pi: {e}{R}", file=sys.stderr)
        return 1

    # Modo CLI: pi_panel.py follow metavideototext-bot
    if len(sys.argv) >= 2 and sys.argv[1] in ("all", "todos"):
        return ssh.stream_follow(_journal_follow([u for u, _ in services]))

    if len(sys.argv) >= 3 and sys.argv[1] == "follow":
        unit = sys.argv[2].replace(".service", "")
        return ssh.stream_follow(_journal_follow([unit]))

    if len(sys.argv) >= 3 and sys.argv[1] == "tail":
        unit = sys.argv[2].replace(".service", "")
        lines = int(sys.argv[3]) if len(sys.argv) > 3 else 80
        _rc, out, err = ssh.run(_journal_tail([unit], lines))
        print(out or err)
        return _rc

    try:
        while True:
            statuses = _status_map(ssh, [u for u, _ in services])
            _draw_menu(cfg, services, statuses)
            choice = input(f"  {B}Elige{R} [# / A / V / D / R / 0]: ").strip().upper()
            if choice in ("0", "Q", "S", "X"):
                break
            if choice == "A":
                ssh.stream_follow(_journal_follow([u for u, _ in services]))
                continue
            if choice == "V":
                _open_windows(cfg, services)
                continue
            if choice == "D":
                _dashboard(ssh, services)
                continue
            if choice == "R":
                picked = _pick_service(services, "  Nº servicio a reiniciar: ")
                if not picked:
                    continue
                unit, label = picked
                confirm = input(f"  ¿Reiniciar {label}? [s/N]: ").strip().lower()
                if confirm not in ("s", "si", "sí", "y", "yes"):
                    continue
                rc, out, err = ssh.run(f"sudo systemctl restart {_unit_arg(unit)} && systemctl is-active {_unit_arg(unit)}")
                print(out or err)
                print(f"{GREEN if rc == 0 else RED}Código {rc}{R}")
                _pause()
                continue
            if choice.isdigit():
                idx = int(choice)
                if not (1 <= idx <= len(services)):
                    continue
                unit, label = services[idx - 1]
                print(f"\n{B}{label}{R}")
                print(f"  1  Log en tiempo real")
                print(f"  2  Últimas 80 líneas")
                print(f"  0  Volver")
                sub = input("  Opción: ").strip()
                if sub == "1":
                    ssh.stream_follow(_journal_follow([unit]))
                elif sub == "2":
                    _rc, out, err = ssh.run(_journal_tail([unit], 80))
                    print("\n" + (out or err))
                    _pause()
                continue
    finally:
        ssh.close()

    print(f"\n{DIM}Hasta luego.{R}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
