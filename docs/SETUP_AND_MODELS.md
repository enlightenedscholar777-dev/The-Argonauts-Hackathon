# Setup and models

## Reference installation

Python **3.12.10 on Windows 11** is the tested interpreter. Python >=3.11 is declared; 3.11 and POSIX were not tested on this machine. Run commands from the repository root because configuration and procedure paths are relative to it. The Python package uses a `src` layout; the scripts are repository modules.

PowerShell, without activation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m scripts.init_env
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m uvicorn harbor_engine.main:app --host 127.0.0.1 --port 8000 --workers 1
```

If the Windows Python launcher is missing, use your installed Python 3.12 executable's full path for `-m venv`. On POSIX:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m scripts.init_env
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m uvicorn harbor_engine.main:app --host 127.0.0.1 --port 8000 --workers 1
```

The exact tested base/development dependencies are in `requirements-lock.txt`. To reproduce them, install that file, then `pip install --no-deps -e .` to install the local package. Optional Groq dependencies are recorded separately if installed during verification; the base lock deliberately does not require Groq. Compatible ranges in `pyproject.toml` are not a claim that every possible resolved version has been tested.

## Local preparation

`scripts.init_env` copies `.env.example` when needed and fills only missing token values using `secrets.token_urlsafe(32)`. It preserves existing values and never prints secrets. Keep `.env` private; it and runtime databases are ignored by Git. Missing, short, or equal role tokens fail startup with a setup message. Local environment variables override `.env`.

The diagnostic page at `/` asks for a viewer token. Read it from your own `.env`; never put tokens in a URL. API clients send `Authorization: Bearer TOKEN`. The three static roles are for a trusted demo, not production account management. The sensor role owns the configured sensor sources; the operator role owns `operator_console`. The actor label is configured by `OPERATOR_LABEL`.

Start with `AI_PROVIDER=off`. No provider request is made at startup, by default tests, or in OFF mode. All required mathematical models execute on the CPU. **No local learned weights, CUDA, GPU, Hugging Face login, embeddings, or inference server are needed.**

## Optional Groq

1. Create a key in the [Groq console](https://console.groq.com/keys), checking your account's model access and [rate limits](https://console.groq.com/docs/rate-limits).
2. Put it only in your local `.env` as `GROQ_API_KEY`. Leave the engine in OFF mode initially.
3. Install the optional SDK and run the explicit account/schema check:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,groq]"
.\.venv\Scripts\python.exe -m scripts.check_groq
```

POSIX equivalent:

```sh
.venv/bin/python -m pip install -e '.[dev,groq]'
.venv/bin/python -m scripts.check_groq
```

4. Only after a successful completion check, set `AI_PROVIDER=groq` and restart the server. A failed check leaves the offline engine usable. No key was supplied for implementation verification, so live account/model access remains unverified.

The default is `GROQ_MODEL=openai/gpt-oss-20b`. [Groq's structured-output documentation](https://console.groq.com/docs/structured-outputs), consulted during implementation, lists this model for strict JSON schema. The adapter uses the [official async SDK](https://github.com/groq/groq-python), `max_retries=0`, one non-streaming completion, low reasoning effort, and a 1,024-token completion allowance. [Reasoning controls](https://console.groq.com/docs/reasoning) are model-specific. A structured schema constrains format, not factual truth. Listing a model does not prove account permission or compatibility; the single completion in `check_groq` tests the payload. There is no automatic model switching, repair loop, tool calling, or arbitrary provider URL.

The smoke command lists model IDs when possible and makes at most one synthetic completion. It prints category, model, total check latency and reported token usage (null when unavailable); never credentials or hidden reasoning. Each operation has a six-second bound. Without a key it prints SKIPPED and makes no calls.

## Configuration and limits

See `.env.example` for all common settings; `src/harbor_engine/settings.py` defines validation bounds.

| Setting | Default / purpose |
|---|---|
| `DATABASE_PATH` | `runtime/harbor_demo.sqlite3`, local disk only |
| `POLICY_PATH`, `PROCEDURES_PATH` | Validated YAML and 11 demo-authored procedure records |
| `DEMO_MODE` | true; enables manual sessions |
| `DEMO_FAULTS_ENABLED` | false; explicit opt-in for fault commands |
| `AI_PROVIDER` | off, fake, or groq; fake always displays MOCK |
| `CORE_QUEUE_CAPACITY` | 256, hard maximum 256 |
| `MAX_TRACKS` | 20, hard maximum 20 |
| `MAX_SESSION_EVENTS` | 100,000; accepted, archived, and outlier records count |
| `MAX_SESSION_COMMANDS` | 100,000 explicit control commands |
| `MAX_SESSION_SECONDS` | 7,200 scenario seconds; realtime tick auto-stops expired sessions |
| `FORECAST_HORIZON_SECONDS` / step / samples | 30 / 2 / 32 |
| `GROQ_TIMEOUT_SECONDS` | 6 real seconds, outer deadline plus SDK timeout |
| `GROQ_MAX_CALLS_PER_MINUTE` | 3 global calls, including failures |
| `GROQ_SOFT_TOKEN_BUDGET_PER_MINUTE` | 6,000 estimated tokens, reconciled against reported usage |
| `GROQ_MAX_CALLS_PER_SESSION` | 20 persisted attempts |
| `AI_MIN_TRACK_INTERVAL_SECONDS` | 30 real seconds |
| `AI_QUEUE_CAPACITY` | 8 coalesced track jobs; one in flight |
| `COMMAND_TIMEOUT_SECONDS` | 10; a waiter timeout does not cancel admitted work |
| `ALLOWED_ORIGINS` | exact loopback origins, comma-separated |

The local budgets are not Groq allowances. Shared organization usage can consume provider quota. 429 respects a bounded Retry-After (1..3,600s); timeout/connection/server failures cause 30s cooldown. Three consecutive failures open a circuit for at least 60s. Only a later eligible job probes; no autonomous retry loop exists. Bad credentials/model/settings disable provider calls until restart. Cooldown jobs may be dropped and require a later material change or explicit request; there is no delayed replay backlog.

The runtime keeps one active session, <=20 tracks, <=20 sources, bounded metrics deques, <=8 pending AI jobs and bounded calls. Durable session history remains on disk; repeated demos create new sessions. Old sessions are preserved and there is no reset-all endpoint. Session duration/event/command quotas bound each session but do not cap accumulated disk use across sessions. Review/archive old databases offline when no server owns them.

## Runtime and recovery

One FastAPI/Uvicorn process owns the coordinator, ticker and AI worker. The database ownership lock rejects a second process using the same file. `WEB_CONCURRENCY` values other than 1 fail startup. Never use `--workers 2` or `--reload` for the presentation. [FastAPI worker documentation](https://fastapi.tiangolo.com/deployment/server-workers/) explains process replication; this demo has in-memory coordination that must not be replicated.

SQLite uses WAL, foreign keys, busy timeout, explicit transactions and `synchronous=FULL`. State JSON, event disposition, idempotency records, incident changes and history commit together. Readers cannot observe in-progress transactions. State is published only after commit. The full current session is checkpointed as finite JSON; normalized tables also expose tracks, bindings, incidents and AI job audit records. This duplicates some data for simple recovery and costs write bandwidth under burst load. [SQLite WAL](https://www.sqlite.org/wal.html) is not replication or a backup.

Recovery preserves manual time and projects realtime freshness from persisted UTC plus downtime. Backward jumps greater than 2s or downtime/jumps over 24h mark `CLOCK_UNCERTAIN`; begin a new session after reviewing the clock. Pending AI jobs are marked canceled; they are not replayed. A storage failure freezes mutations and readiness, with last committed snapshots still available. Repair the local issue and restart. This is process recovery, not high availability.

## Teammate access

Default binding is loopback. For a trusted LAN only, explicitly use `--host 0.0.0.0`, distribute distinct role tokens only to their owners, restrict the firewall, and configure exact frontend CORS origins. CORS is not authentication. Plain HTTP provides no confidentiality; use a trusted TLS proxy when needed. No public tunnel or public exposure is part of this build.
