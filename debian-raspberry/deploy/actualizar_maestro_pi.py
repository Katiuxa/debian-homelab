#!/usr/bin/env python3
"""Sube maestro.py actualizado a la Pi, valida y reinicia el panel."""

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
        host,
        username=user,
        password=password,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = client.open_sftp()
    uploads = (
        "maestro.py",
        "maestro.service",
        "patch_maestro_on_pi.sh",
        "reiniciar_maestro_pi.sh",
        "fix_maestro_servicios_comma.py",
        "setup_maestro_sudo.sh",
    )
    for name in uploads:
        local = ROOT / "deploy" / name
        if not local.is_file():
            print(f"[AVISO] No existe {local}, omitido")
            continue
        remote = f"/home/{user}/{name}"
        print(f"[*] Subiendo {name} ...")
        sftp.put(str(local), remote)
    sftp.close()

    cmd = (
        f"sed -i 's/\\r$//' /home/{user}/maestro.py "
        f"/home/{user}/patch_maestro_on_pi.sh "
        f"/home/{user}/reiniciar_maestro_pi.sh "
        f"/home/{user}/fix_maestro_servicios_comma.py "
        f"/home/{user}/setup_maestro_sudo.sh 2>/dev/null; "
        f"printf '%s\\n' '{password}' | sudo -S bash /home/{user}/setup_maestro_sudo.sh {user}; "
        f"python3 /home/{user}/fix_maestro_servicios_comma.py; "
        f"python3 -m py_compile /home/{user}/maestro.py && "
        f"bash /home/{user}/patch_maestro_on_pi.sh; "
        f"bash /home/{user}/reiniciar_maestro_pi.sh"
    )
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
    for line in stdout:
        print(line.rstrip())
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        print(err, file=sys.stderr)
    code = stdout.channel.recv_exit_status()
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
