"""Hugging Face Gradio Space entry point for Harbor-maester.

This module is the `app.py` that Hugging Face Spaces (Gradio SDK) looks for at
startup.  It launches the FastAPI decision engine as a background process on the
loopback interface and then hands control to Streamlit, which is served on port
7860 by the `gradio` CLI wrapper that HF injects automatically.

Because Gradio Spaces forward port 7860 to the public URL we bind Streamlit
there.  The engine always stays on loopback 8000 and is never publicly reachable.
"""

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent


def space_environment(source=None):
    """Build the subprocess environment for a public Spaces launch."""
    environment = dict(os.environ if source is None else source)
    environment.update(
        AI_PROVIDER="off",
        GROQ_API_KEY="",
        HARBOR_PUBLIC_DEMO="true",
        HARBOR_AUTOSTART="true",
        HARBOR_ENGINE_URL="http://127.0.0.1:8000",
        DATABASE_PATH="runtime/space.sqlite3",
        DEMO_MODE="true",
        DEMO_FAULTS_ENABLED="true",
        WEB_CONCURRENCY="1",
        PYTHONUNBUFFERED="1",
        PYTHONPATH=str(ROOT) + os.pathsep + environment.get("PYTHONPATH", ""),
    )
    for role in ("SENSOR", "OPERATOR", "VIEWER"):
        environment[f"ENGINE_{role}_TOKEN"] = secrets.token_urlsafe(32)
    return environment


def wait_ready(process, url, label, timeout=60):
    """Poll *url* until the service responds with a 2xx status."""
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2, trust_env=False) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"{label} exited before becoming ready.")
            try:
                if http.get(url).is_success:
                    print(f"{label} is ready.", flush=True)
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise RuntimeError(f"{label} readiness timed out after {timeout}s.")


def main():
    os.chdir(ROOT)
    Path("runtime").mkdir(exist_ok=True)

    environment = space_environment()
    children = []

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)

    commands = [
        (
            "Engine",
            [sys.executable, "-m", "uvicorn", "harbor_engine.main:app",
             "--host", "127.0.0.1", "--port", "8000",
             "--workers", "1", "--no-access-log"],
            "http://127.0.0.1:8000/health/ready",
        ),
        (
            "Dashboard",
            [sys.executable, "-m", "streamlit", "run", "harbor_simulation/app.py",
             "--server.address", "0.0.0.0",
             "--server.port", "7860",
             "--server.headless", "true",
             "--server.fileWatcherType", "none",
             "--browser.gatherUsageStats", "false",
             "--theme.base", "dark"],
            "http://127.0.0.1:7860/_stcore/health",
        ),
    ]

    try:
        for label, command, health_url in commands:
            process = subprocess.Popen(command, cwd=ROOT, env=environment)
            children.append(process)
            wait_ready(process, health_url, label)

        print("Harbor-maester is ready on port 7860. Visitor-provided keys only.", flush=True)

        # Keep alive — restart policy is handled by the Space runtime.
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError("A service exited unexpectedly.")

    except KeyboardInterrupt:
        print("Stopping Harbor-maester.", flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == "__main__":
    main()
