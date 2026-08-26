#!/usr/bin/env python3
"""Limpia duplicados maestro en Pi: sube codigo, mata procesos, arranca uno solo."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        import paramiko
    except ImportError:
        print("[ERROR] pip install paramiko", file=sys.stderr)
        return 1

    host = os.environ.get("PI_HOST", "raspberrypi.local")
    user = os.environ.get("PI_USER", "admin")
    password = os.environ.get("PI_PASS", "1234")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] Conectando a {user}@{host} ...")
    client.connect(
        host, username=user, password=password, timeout=30,
        allow_agent=False, look_for_keys=False,
    )

    sftp = client.open_sftp()
    uploads = (
        "maestro.py", "maestro.service", "reiniciar_maestro_pi.sh",
        "patch_maestro_on_pi.sh",
        "fix_maestro_servicios_comma.py", "setup_maestro_sudo.sh",
        "limpiar_maestro_pi.sh",
    )
    for name in uploads:
        local = ROOT / "deploy" / name
        if local.is_file():
            print(f"[*] Subiendo {name} ...")
            sftp.put(str(local), f"/home/{user}/{name}")
    sftp.close()

    cmd = (
        f"sed -i 's/\\r$//' /home/{user}/*.sh /home/{user}/maestro.py 2>/dev/null; "
        f"chmod +x /home/{user}/limpiar_maestro_pi.sh; "
        f"printf '%s\\n' '{password}' | sudo -S bash /home/{user}/setup_maestro_sudo.sh {user}; "
        f"bash /home/{user}/limpiar_maestro_pi.sh"
    )
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
    for line in stdout:
        text = line.rstrip()
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            ))
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        try:
            print(err, file=sys.stderr)
        except UnicodeEncodeError:
            print(err.encode("ascii", errors="replace").decode("ascii"), file=sys.stderr)
    code = stdout.channel.recv_exit_status()
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
