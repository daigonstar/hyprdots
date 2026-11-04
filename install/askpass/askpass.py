#!/usr/bin/env python3
"""sudo runs this for a password (SUDO_ASKPASS). It asks the installer's interface over a private socket and prints the
answer for sudo. Nothing is stored. No answer means cancelled: exit 1, and sudo gives up."""
import os
import socket
import sys

try:
    with socket.socket(socket.AF_UNIX) as link:
        link.connect(os.environ["HYPRINSTALL_ASKPASS_SOCKET"])
        link.sendall((sys.argv[1] if len(sys.argv) > 1 else "").encode() + b"\n")
        answer = b""
        while chunk := link.recv(4096):
            answer += chunk
except (KeyError, OSError):
    sys.exit(1)
if not answer:
    sys.exit(1)
sys.stdout.buffer.write(answer + b"\n")
