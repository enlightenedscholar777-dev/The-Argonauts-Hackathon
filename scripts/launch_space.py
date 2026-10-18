"""One public Streamlit port, one private engine, no host Groq credentials."""

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from scripts.launch_demo import wait_ready

ROOT = Path(__file__).resolve().parents[1]


def space_environment(source=None):
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
        PYTHONPATH=os.pathsep.join(
            (str(ROOT / "src"), str(ROOT), environment.get("PYTHONPATH", ""))
        ),
    )
    for role in ("SENSOR", "OPERATOR", "VIEWER"):
        environment[f"ENGINE_{role}_TOKEN"] = secrets.token_urlsafe(32)
    return environment


def main():
    os.chdir(ROOT)
    Path("runtime").mkdir(exist_ok=True)
    children = []
    environment = space_environment()

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    commands = [
        (["-m", "uvicorn", "harbor_engine.main:app", "--host", "127.0.0.1", "--port", "8000",
          "--workers", "1", "--no-access-log"], "http://127.0.0.1:8000/health/ready"),
        (["-m", "streamlit", "run", "harbor_simulation/app.py", "--server.address", "0.0.0.0",
          "--server.port", "7860", "--server.headless", "true", "--server.fileWatcherType", "none",
          "--browser.gatherUsageStats", "false", "--theme.base", "dark"],
         "http://127.0.0.1:7860/_stcore/health"),
    ]
    try:
        for command, health in commands:
            process = subprocess.Popen([sys.executable, *command], cwd=ROOT, env=environment)
            children.append(process)
            wait_ready(process, health, "container logs")
        print("Harbor-maester is ready on port 7860. Visitor-provided keys only.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("A service exited; restarting the container is required.")
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
