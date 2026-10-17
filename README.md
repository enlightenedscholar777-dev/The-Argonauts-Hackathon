# Harbor Decision Engine

A working CPU-only, single-host harbor watch demonstration. Synthetic observations flow through a NumPy Kalman filter, geometric forecasts, explicit mission permissions, policy rules, and a durable human-handoff workflow. Optional AI summarizes evidence; deterministic assessments work without a key or network.

**Synthetic data and demo policy only. All actions are advisory. No vehicle control or external messages.**

## Run on Windows PowerShell

From the repository root, with Python 3.12 (3.11 also supported):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m scripts.init_env
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn harbor_engine.main:app --host 127.0.0.1 --port 8000 --workers 1
```

If `py` is unavailable, invoke the installed Python 3.12 executable directly for the first command. No activation-policy changes are needed. A virtual environment and local `.env` may already exist after the implementation run; reuse them.

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo --scenario unknown_approach --clock realtime --duration 45
```

Open **http://127.0.0.1:8000** and paste the `ENGINE_VIEWER_TOKEN` from your local `.env`. The page keeps it in memory only. The simulator prints its session ID and an explicit stop command. Stop that session before starting another scenario.

## Run on macOS/Linux

Use Python 3.11/3.12 as `python3`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m scripts.init_env
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn harbor_engine.main:app --host 127.0.0.1 --port 8000 --workers 1
# Second terminal:
.venv/bin/python -m scripts.run_demo --scenario normal --clock realtime --duration 45
```

## Handoff

- [Setup, configuration, and optional Groq](docs/SETUP_AND_MODELS.md)
- [Versioned API contract](docs/API_CONTRACT.md); generated `/docs` and `/openapi.json`
- [Presentation and recovery runbook](docs/DEMO_RUNBOOK.md)
- [Implementation report and measured limitations](IMPLEMENTATION_REPORT.md)
- [Measured baseline](docs/benchmark-results.json)

No GPU, CUDA, local LLM weights, Hugging Face login, Node build, or external UI assets are required. Keep `AI_PROVIDER=off` for the first run. Exactly **one worker**, no presentation `--reload`, and a local SQLite disk are required. Earlier architectural notes under `docs/decision_engine` describe broader ideas; the supplied build spec and current code define this implementation.
