# Five-minute demonstration and recovery

Start from the repository root. `AI_PROVIDER=off` is enough for the complete deterministic demonstration. The UI is read-only; use the API or simulator for operator actions. All observations and procedures are synthetic.

## Before presenting

1. Run `python -m scripts.init_env`, then tests, using the virtual environment Python shown in README.
2. Start exactly one server: `python -m uvicorn harbor_engine.main:app --host 127.0.0.1 --port 8000 --workers 1`. No `--reload`.
3. Open `/`, paste the local viewer token, and check core/storage READY/AVAILABLE. OFF is a valid AI state.
4. Check `/health/ready`. Run `python -m scripts.run_demo --scenario normal --clock realtime --duration 45` in a second terminal.
5. Keep the printed session ID. A completed simulator run leaves the session active for inspection; stop it explicitly before another scenario:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo --stop --session-id SESSION_ID
```

The simulator refuses to replace someone else's active session. `--session-id` deliberately attaches to an existing compatible session; no implicit stop/reset occurs.

## Presentation sequence

| Scenario | Command suffix | What to explain |
|---|---|---|
| Normal research | `--scenario normal --clock realtime --duration 45` | Explicit mission binding; LOW/MONITOR after initialization; independent permission and freshness |
| Unknown approach | `--scenario unknown_approach --clock realtime --duration 45` | Unknown identity initially requests verification; the computed trajectory triggers HUMAN_REVIEW before zone entry |
| Authorized deviation | `--scenario authorized_deviation --clock realtime --duration 45` | Permission remains authorized while persistent route deviation requests CONTACT_OPERATOR; no message is sent |
| Sensor loss | `--scenario sensor_loss --clock realtime --duration 30` | Observations stop after five samples; source heartbeats continue; STALE then LOST/UNKNOWN without refreshing position time |
| Identity resolution | `--scenario identity_resolved --clock realtime --duration 45` | An explicit inspection-mission binding resolves permission; audit survives and obsolete AI is discarded |
| Replay/outlier | `--scenario replay_and_outlier --clock manual` | Duplicate, conflicting ID, old position and impossible jump have different durable outcomes |
| Malicious note | `--scenario malicious_note --clock manual` | Untrusted instruction-like text cannot authorize a vehicle or change the protected action |

Prepend `python -m scripts.run_demo` using the environment executable. Stop between rows. Use `--base-url`, `--seed`, `--duration`, and deliberate `--session-id` as needed. Manual scenarios run quickly without sleeps and require demo mode. Realtime uses fresh timestamps; never paste a fixed historical observation as current data.

For a five-minute talk, focus on normal, unknown approach, provider failure, then sensor loss. Point to forecast assumptions and handoff evidence instead of claiming intent detection or disaster prevention. LOW means low under these demo rules.

## AI failure with no account or paid calls

Stop the active session and server. In `.env`, set `AI_PROVIDER=fake` and `DEMO_FAULTS_ENABLED=true`; restart. Keep the MOCK badge visible.

```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo --scenario ai_failure --clock realtime --duration 30
```

This activates a simulated unavailable-provider condition at the provider interface. Core ingestion, forecasts, incidents and explanations continue. Other allowed faults are TIMEOUT, RATE_LIMIT and INVALID_RESPONSE via `/v1/demo/faults` with their `AI_` prefixes. The command records an audit entry and a visible simulated-fault flag. Faults expire after a bounded duration and clear on session stop. Never imply MOCK is a Groq inference.

For live optional enrichment, follow `SETUP_AND_MODELS.md`, run the explicit Groq smoke check, then set `AI_PROVIDER=groq` and restart. If access/Wi-Fi fails, OFF or fake remains usable. No local model weights are involved.

## Human acknowledgment

Read the current assessment's incident ID and `core_revision`. POST `/incidents/{id}/ack` with a unique `command_id` and that revision using the operator token. Stale revisions return 409 so the officer can review new information. HUMAN_OWNED does not change risk. Closure requires fresh LOW evidence and an accepted outstanding handoff, with an explicit reason. The API contract has exact request examples.

## Restart and failure recovery

Leave a manual session active with a few observations. Stop the server process (Ctrl+C), start it again with the same database, and query the same session/track. Manual scenario time and accepted position/filter state remain committed. Retrying the last event ID returns DUPLICATE. Realtime recovery recalculates freshness after downtime; it cannot make an old position fresh. Unfinished AI work is canceled, not resent. Old sessions remain readable.

If storage fails, show NOT_READY/storage unavailable and last committed data; fix disk/permissions and restart. Do not corrupt or fill a user's disk for the presentation. Tests use injected storage failure, including rollback after a partial transaction. A single host still fails if power, disk or process fails; no distributed failover is claimed.

## Reproducible verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m scripts.verify_http
.\.venv\Scripts\python.exe -m scripts.benchmark --output runtime/benchmark.json
```

`verify_http` requires no active session, runs seven deterministic scenarios over real HTTP, checks final structured outcomes, and stops only the sessions it creates. With a fake-provider/fault-enabled server, add `--include-ai` to exercise all eight. `benchmark` requires AI OFF and no active session; defaults are 20 tracks at 1Hz for 60s, followed by 200 observation attempts/s for 5s. It uses fresh timestamps, caps client concurrency/pending work, reports client drops separately, and never silently discards a successful persistence acknowledgment. Burst saturation is expected to show rejection/lag. Server timing windows reset at session creation; counters remain process-wide.

Browser assets are local. If a browser connection fails, the terminal summaries and HTTP contracts can still demonstrate the engine. A real deployment would need validated sensors, operational policies, stronger identity/access controls, independent hardware and deployment-specific safety review.
