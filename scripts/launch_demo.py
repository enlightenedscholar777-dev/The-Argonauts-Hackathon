"""Launch the loopback-only engine and integrated Streamlit dashboard together."""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from scripts.init_env import main as init_env

ROOT = Path(__file__).resolve().parents[1]


def unused_port(port):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(
                f"Port {port} is already in use. Stop its owner or choose another port."
            ) from None


def wait_ready(process, url, log_path):
    deadline = time.monotonic() + 40
    with httpx.Client(timeout=1, trust_env=False) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Service exited. Inspect {log_path}")
            try:
                if http.get(url).is_success:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError(f"Service readiness timed out. Inspect {log_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-port", type=int, default=8000)
    parser.add_argument("--dashboard-port", type=int, default=8501)
    parser.add_argument("--database", default="runtime/v1-demo.sqlite3")
    parser.add_argument("--ai", choices=("off", "fake", "groq"), default="off")
    parser.add_argument("--check", action="store_true", help="Check both services, then shut them down")
    args = parser.parse_args()
    if args.engine_port == args.dashboard_port or any(
        not 1024 <= p <= 65535 for p in (args.engine_port, args.dashboard_port)
    ):
        parser.error("Choose two distinct ports in 1024..65535")
    os.chdir(ROOT)
    processes, logs = [], []
    try:
        unused_port(args.engine_port)
        unused_port(args.dashboard_port)
        init_env()
        Path("runtime").mkdir(exist_ok=True)
        engine_url = f"http://127.0.0.1:{args.engine_port}"
        dashboard_url = f"http://127.0.0.1:{args.dashboard_port}"
        environment = {
            **os.environ,
            "AI_PROVIDER": args.ai,
            "DATABASE_PATH": args.database,
            "DEMO_FAULTS_ENABLED": "true",
            "DEMO_MODE": "true",
            "WEB_CONCURRENCY": "1",
            "HARBOR_ENGINE_URL": engine_url,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        }
        if args.ai == "fake":
            # Fast mock-only feedback for the outage button; Groq keeps conservative budgets.
            environment.update(
                AI_MIN_TRACK_INTERVAL_SECONDS="0",
                GROQ_MAX_CALLS_PER_MINUTE="60",
                GROQ_SOFT_TOKEN_BUDGET_PER_MINUTE="100000",
                GROQ_MAX_CALLS_PER_SESSION="1000",
            )
        commands = [
            (
                "engine",
                [
                    "-m",
                    "uvicorn",
                    "harbor_engine.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.engine_port),
                    "--workers",
                    "1",
                    "--no-access-log",
                ],
                engine_url + "/health/ready",
            ),
            (
                "dashboard",
                [
                    "-m",
                    "streamlit",
                    "run",
                    "harbor_simulation/app.py",
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(args.dashboard_port),
                    "--server.headless",
                    "true",
                    "--server.fileWatcherType",
                    "none",
                    "--browser.gatherUsageStats",
                    "false",
                    "--theme.base",
                    "dark",
                ],
                dashboard_url + "/_stcore/health",
            ),
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for name, command, health_url in commands:
            log_path = Path("runtime") / f"v1-demo-{name}.log"
            log = log_path.open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(
                [sys.executable, *command],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=flags,
            )
            processes.append(process)
            wait_ready(process, health_url, log_path)
        print(f"Dashboard: {dashboard_url}\nEngine API: {engine_url}/docs", flush=True)
        print(f"AI mode: {args.ai}. CPU assessments remain available without Groq.", flush=True)
        print(
            "Choose Start exercise in the dashboard. Ctrl+C stops both services; committed data is preserved.",
            flush=True,
        )
        if not args.check:
            while all(p.poll() is None for p in processes):
                time.sleep(0.5)
            raise RuntimeError("A demo service exited. Inspect runtime/v1-demo-*.log")
        print("Both HTTP services are ready. Startup check passed.")
    except KeyboardInterrupt:
        print("\nStopping demo services; database preserved.")
    except (RuntimeError, OSError) as error:
        parser.exit(1, f"Demo failed: {error}\n")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
