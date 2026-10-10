"""Run the isolated, loopback-only demo. Stops both children on exit."""
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]


def main():
    node = shutil.which("node")
    if not node or not (ROOT / ".next/BUILD_ID").is_file():
        raise SystemExit("Install Node and run npm ci, then npm run build first.")
    if not (ROOT / "node_modules/next").is_dir():
        raise SystemExit("Run npm ci first.")
    for port in (5180, 8780):
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is occupied. Stop that service first; this demo will not reuse it.")
    children = []
    try:
        backend = subprocess.Popen([sys.executable, "-u", "backend/server.py"], cwd=ROOT)
        children.append(backend)
        opener = build_opener(ProxyHandler({}))
        for _ in range(50):
            if backend.poll() is not None:
                raise RuntimeError("Backend failed to start")
            try:
                with opener.open("http://127.0.0.1:8780/api/health", timeout=1) as response:
                    if json.load(response).get("release") != "laya-jev-public-v1":
                        raise RuntimeError("Unexpected backend identity")
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Backend startup timed out")
        frontend = subprocess.Popen([node, "scripts/next.cjs", "start", "--hostname", "127.0.0.1", "--port", "5180"], cwd=ROOT)
        children.append(frontend)
        print("Open http://127.0.0.1:5180/laya-ft — Ctrl+C stops this demo.", flush=True)
        while all(p.poll() is None for p in children):
            time.sleep(.5)
        raise RuntimeError("A demo service stopped; both services will now close")
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
