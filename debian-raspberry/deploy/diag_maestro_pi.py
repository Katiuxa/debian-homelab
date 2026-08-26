#!/usr/bin/env python3
import os
import sys

import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("raspberrypi.local", username="admin", password=os.environ.get("PI_SSH_PASSWORD", ""), timeout=20)
cmd = (
    "tail -100 /home/admin/maestro.log 2>/dev/null; "
    "echo '---PROC---'; pgrep -af 'python3 /home/admin/maestro.py'; "
    "echo '---SYSTEMD---'; systemctl is-enabled maestro.service 2>/dev/null; "
    "systemctl is-active maestro.service 2>/dev/null; "
    "echo '---APTLOCK---'; "
    "fuser /var/lib/dpkg/lock-frontend 2>/dev/null || echo libre; "
    "echo '---APTTEST---'; "
    "timeout 15 bash -lc 'apt list --upgradable 2>/dev/null | tail -n +2 | wc -l' || echo TIMEOUT"
)
_, o, e = c.exec_command(cmd)
sys.stdout.buffer.write(o.read())
err = e.read().decode("utf-8", errors="replace").strip()
if err:
    print("STDERR:", err, file=sys.stderr)
c.close()
