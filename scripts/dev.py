"""Start the current backend and frontend together for development.

    python scripts/dev.py            # from the repository root

Why this exists: on Windows a server bound to 0.0.0.0:8000 and another bound to 127.0.0.1:8000 can coexist, so an old
backend can silently answer requests meant for a new one. This script refuses to start if either port is already in
use, tells you how to find the owner, and then launches both servers from this checkout with the documented settings
(backend on 127.0.0.1:8000 with --reload, frontend dev server on 5174). It never kills any process.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"
API_PORT, WEB_PORT = 8000, 5174


def in_use(port: int) -> bool:
    """True if anything accepts connections on the port (on loopback), whatever address it bound to."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def owner_hint(port: int) -> str:
    if os.name == "nt":
        return f'netstat -ano | findstr ":{port} "   then   tasklist /FI "PID eq <pid>"'
    return f"lsof -i :{port}"


def backend_python() -> str:
    candidates = [BACKEND / ".venv" / "Scripts" / "python.exe", BACKEND / ".venv" / "bin" / "python"]
    return str(next((c for c in candidates if c.is_file()), Path(sys.executable)))


def main() -> int:
    busy = [(name, port) for name, port in (("backend", API_PORT), ("frontend", WEB_PORT)) if in_use(port)]
    if busy:
        for name, port in busy:
            print(f"Port {port} ({name}) is already in use. It may be an old server running outdated code.", file=sys.stderr)
            print(f"  Find the owner:  {owner_hint(port)}", file=sys.stderr)
        print("Stop the old process yourself, then run this script again. Nothing was started or killed.", file=sys.stderr)
        return 1

    npm = "npm.cmd" if os.name == "nt" else "npm"
    procs = [
        subprocess.Popen([backend_python(), "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", str(API_PORT)], cwd=BACKEND),
        subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND),
    ]
    try:
        for _ in range(60):
            time.sleep(1)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/api/health", timeout=2) as r:
                    health = json.load(r)
                print(f"Backend ready from {BACKEND}: {health['datasets_loaded']} dataset(s) loaded.")
                break
            except OSError:
                if procs[0].poll() is not None:
                    print("Backend exited during start-up; see its output above.", file=sys.stderr)
                    return 1
        print(f"Web app: http://localhost:{WEB_PORT}   API docs: http://127.0.0.1:{API_PORT}/docs   (Ctrl+C stops both)")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
