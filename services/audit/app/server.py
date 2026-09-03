"""INTENTLOCK Multi-Service Demo Supervisor.

Brings up the complete four-process INTENTLOCK platform on loopback interfaces:
  - Service A: Signal Intelligence (:8001)
  - Service B: Core Risk Fusion    (:8002)
  - Service C: Audit Chain & SSE   (:8003)
  - Frontend:  Verification Console(:5173)

Usage:
  python3 services/audit/app/server.py
  python3 services/audit/app/server.py --no-browser
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

SERVICES = [
    {
        "name": "Service A (Signal Intelligence)",
        "port": 8001,
        "health_url": "http://127.0.0.1:8001/healthz",
        "cmd": [sys.executable, "-m", "uvicorn", "packages.signal_intel.service:app",
                "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
        "cwd": str(REPO_ROOT),
    },
    {
        "name": "Service B (Core Risk Fusion)",
        "port": 8002,
        "health_url": "http://127.0.0.1:8002/healthz",
        "cmd": [sys.executable, "-m", "packages.core.service"],
        "cwd": str(REPO_ROOT),
    },
    {
        "name": "Service C (Audit Chain & SSE)",
        "port": 8003,
        "health_url": "http://127.0.0.1:8003/healthz",
        "cmd": [sys.executable, "-m", "uvicorn", "services.audit.app.main:app",
                "--host", "127.0.0.1", "--port", "8003", "--log-level", "warning"],
        "cwd": str(REPO_ROOT),
    },
    {
        "name": "Console (Verification Dashboard)",
        "port": 5173,
        "health_url": "http://127.0.0.1:5173",
        "cmd": ["npm", "--prefix", "apps/console", "run", "dev"],
        "cwd": str(REPO_ROOT),
    },
]


def check_health(url: str, timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IntentlockSupervisor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def wait_for_services(services: list[dict], timeout_s: float = 30.0) -> bool:
    start_time = time.time()
    pending = list(services)
    while pending and (time.time() - start_time) < timeout_s:
        for s in list(pending):
            if check_health(s["health_url"]):
                print(f"  \033[32m✔\033[0m {s['name']:<36} on :{s['port']} is healthy")
                pending.remove(s)
        if pending:
            time.sleep(0.5)
    return len(pending) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the INTENTLOCK demo environment.")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the browser.")
    parser.add_argument("--check-only", action="store_true", help="Poll health and exit immediately.")
    args = parser.parse_args()

    if args.check_only:
        all_ok = all(check_health(s["health_url"]) for s in SERVICES)
        sys.exit(0 if all_ok else 1)

    print("\n" + "=" * 64)
    print("  INTENTLOCK — Deepfake-Resistant Transaction Authorization")
    print("=" * 64 + "\n")
    print("Starting services on 127.0.0.1...")

    processes: list[subprocess.Popen] = []

    def shutdown(signum=None, frame=None):
        print("\n\nShutting down INTENTLOCK services...")
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        for p in processes:
            try:
                p.wait(timeout=2.0)
            except Exception:
                p.kill()
        print("All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    if "INTENTLOCK_DEMO_ENDPOINTS" not in env:
        env["INTENTLOCK_DEMO_ENDPOINTS"] = "1"

    for s in SERVICES:
        proc = subprocess.Popen(
            s["cmd"],
            cwd=s["cwd"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(proc)

    print("Waiting for health checks on all ports...")
    healthy = wait_for_services(SERVICES, timeout_s=30.0)

    if not healthy:
        print("\n\033[31mError: Some services failed to start.\033[0m")
        shutdown()

    console_url = "http://localhost:5173"
    print("\n" + "—" * 64)
    print(f"\033[1;32mAll services running!\033[0m")
    print(f"  • Verification Dashboard : \033[1;36m{console_url}\033[0m")
    print(f"  • Signal Intelligence API : http://127.0.0.1:8001/v1/samples")
    print(f"  • Risk Fusion Core API    : http://127.0.0.1:8002/v1/policy")
    print(f"  • Tamper-Evident Audit DB : http://127.0.0.1:8003/v1/audit/head")
    print("—" * 64)
    print("Press Ctrl+C to terminate all services.\n")

    if not args.no_browser:
        try:
            webbrowser.open(console_url)
        except Exception:
            pass

    try:
        while True:
            for p in processes:
                if p.poll() is not None:
                    print(f"\n\033[31mProcess {p.args} exited unexpectedly (code {p.returncode}).\033[0m")
                    shutdown()
            time.sleep(1.0)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
