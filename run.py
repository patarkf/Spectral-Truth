#!/usr/bin/env python3
"""Start the Audio Analyzer server and optionally open the browser."""
import sys
import webbrowser
from threading import Timer

from backend.config import HOST, PORT


def free_port():
    """If port is in use, try to kill the process so we can bind. Returns True if port is free."""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((HOST, PORT))
            return True
    except OSError:
        pass
    # Port in use: try to kill the process (macOS/Linux)
    try:
        import subprocess
        result = subprocess.run(
            ["lsof", "-t", "-i", ":%d" % PORT],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                pid = pid.strip()
                if pid.isdigit():
                    subprocess.run(["kill", pid], capture_output=True, timeout=2)
                    print(f"Killed previous process (PID {pid}) on port {PORT}.", file=sys.stderr)
            return True
    except Exception as e:
        print(f"Could not free port {PORT}: {e}", file=sys.stderr)
    return False


def open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    if not free_port():
        print(
            f"\nPort {PORT} is in use. Stop the other process first, e.g.:\n"
            f"  kill $(lsof -t -i :{PORT})\n\n"
            f"Then run: python run.py\n",
            file=sys.stderr,
        )
        sys.exit(1)

    Timer(1.2, open_browser).start()

    import uvicorn
    from backend.main import app
    uvicorn.run(app, host=HOST, port=PORT)
