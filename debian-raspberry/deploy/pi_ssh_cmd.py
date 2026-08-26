#!/usr/bin/env python3
"""Ejecuta un comando en la Pi por SSH (paramiko)."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", help="Comando remoto")
    parser.add_argument("--host", default=os.environ.get("PI_HOST", "raspberrypi.local"))
    parser.add_argument("--user", default=os.environ.get("PI_USER", "admin"))
    parser.add_argument("--password", default=os.environ.get("PI_PASS", "1234"))
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print("[ERROR] pip install paramiko", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.user,
        password=args.password,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    stdin, stdout, stderr = client.exec_command(args.command, get_pty=True)
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
