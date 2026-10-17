# Harbor Decision Engine implementation report

Implemented on branch `feature/harbor-decision-engine-demo`. The original build spec and existing architectural notes were preserved. No commit, push, publication, vehicle control, or external messaging was performed.

## Result and startup

The repository now contains a working standalone CPU decision server, durable SQLite audit/recovery, a read-only local diagnostic page, eight HTTP simulator scenarios, local procedure retrieval, optional bounded AI assistance, focused tests, and measured HTTP workloads. Default operation needs no API key or network. No local learned model weights were installed.

A Python 3.12 virtual environment and private `.env` were prepared in this workspace. The environment has the base/development dependencies and optional Groq SDK; `AI_PROVIDER` remains **off** in local configuration. Temporary verification servers were stopped after measurement. To run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn harbor_engine.main:app --host 127.0.0.1 --port 8000 --workers 1
```

In a second terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo --scenario unknown_approach --clock realtime --duration 45
```

Open `http://127.0.0.1:8000`, paste the local viewer token, and observe the structured assessments and map. Stop the printed session explicitly before starting another scenario. Fresh installations and POSIX equivalents are in [README](README.md) and [setup instructions](docs/SETUP_AND_MODELS.md).

## Architecture and ownership

| Concern | Implementation |
|---|---|
| Packaging/configuration | `pyproject.toml`, `.env.example`, `settings.py`, validated `config/demo_policy.yaml` |
| Public boundary | `schemas.py`, `api.py`, `main.py`; strict request fields, UTC times, bearer roles, body limit, error envelope, OpenAPI |
| Mutation and time | `coordinator.py`, `clock.py`; one bounded serialized queue, monotonic realtime clock, authenticated manual steps, coalesced ticks |
| Numerical tracking | `tracking.py`; 4-state Kalman filter, linear solves, Joseph covariance, innovation gating, measurement-anchored state |
| Prediction/geometry | `forecast.py`, `geometry.py`; covariance propagation, continuous polygon crossings, boundary covers, route distance, seeded trajectory ensemble |
| Decisions | `policy.py`; explicit permission binding, independent risk/freshness/authorization, temporal route hysteresis, advisory action precedence and heuristic next evidence |
| Human workflow | `incidents.py`; one open incident per track, latched handoff, historical evidence, revision-checked acknowledgment and closure |
| Durability | `storage.py`; local SQLite WAL/FULL, transaction-before-publish, finite JSON checkpoints, normalized audit tables, ownership lock and recovery |
| Retrieval | `retrieval.py`, `data/procedures.json`; 11 versioned demo-authored records, reason/action filter then BM25, up to three passages |
| Optional AI | `ai/base.py`, `fake_provider.py`, `groq_provider.py`, `worker.py`; one async request, bounded/coalesced jobs, budgets, cooldown/circuit, structured/reference validation and semantic revalidation |
| Diagnostic page | `static/index.html`, `style.css`, `app.js`; local SVG, 1Hz polling, memory-only viewer token, `textContent` for untrusted text |
| Teammate tools | `scripts/run_demo.py`, `verify_http.py`, `benchmark.py`, `init_env.py`, `check_groq.py` |

The critical path never awaits a provider. Successful event receipts are issued only after the deterministic transaction commits. Optional AI can explain supplied evidence and choose an eligible information request; it cannot change authorization, primary action, risk, filter or incident ownership.

## Public endpoints and interaction

The exact [API contract](docs/API_CONTRACT.md) documents every request, response field, role, error, clock rule and retry behavior. Generated `/docs` includes bearer authorization; `/openapi.json` includes the reusable Assessment model.

- Public: `GET /health/live`, `GET /health/ready`, `GET /`, local `/static/*`.
- Read domain: `GET /v1/status`, `/v1/metrics`, `/v1/sessions/{session_id}`, `/snapshot`, `/tracks/{track_id}`, `/history`, `/events/{event_id}` under the session path as documented.
- Control: `POST /v1/sessions`; session `/stop`, `/clock/advance`, `/identity-bindings`, `/incidents/{incident_id}/ack`, `/incidents/{incident_id}/close`, `/tracks/{track_id}/enrichment`.
- Sensor/note input: `POST /v1/sessions/{session_id}/events`.
- Controlled demo faults: `POST /v1/demo/faults`.

Example simulator interaction: create a realtime session using the operator token, publish `sim_sonar_01` local-meter observations using the sensor token, poll `/tracks/track_01` or `/snapshot`, and submit any identity or acknowledgment action separately using the displayed core revision. Events contain no scenario names or expected answers. Retry ambiguous outcomes with the same identifier; query the receipt endpoint if needed.

## Tested environment and installation

Python **3.12.10**, Windows 11 build **10.0.26300**. Hardware reported **Intel64 Family 6 Model 197 Stepping 2, GenuineIntel**, **16 logical CPUs**. No GPU was required or used.

| Package | Tested version |
|---|---|
| FastAPI / Uvicorn | 0.143.3 / 0.54.0 |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.0 |
| NumPy / Shapely | 2.5.4 / 2.2.0 |
| aiosqlite / HTTPX | 0.22.1 / 0.28.1 |
| PyYAML / rank-bm25 | 6.0.3 / 0.2.2 |
| python-dotenv | 1.2.4 |
| pytest / pytest-asyncio / Ruff | 9.1.1 / 1.4.0 / 0.17.1 |
| Optional Groq SDK | 0.37.1, tested with local mock HTTP |

Exact transitive base/development versions are in `requirements-lock.txt`; optional additions are in `requirements-groq-lock.txt`. The initial base environment was installed and tested without Groq. The final suite also deliberately blocks Groq imports while starting and exercising the offline app. `pip check` reported no broken requirements. Python 3.11 and other operating systems are supported by metadata/instructions but were not executed here.

For optional Groq, install `.[groq]`, configure a key privately, run `python -m scripts.check_groq`, and only then set `AI_PROVIDER=groq`. The official hosted model defaults to `openai/gpt-oss-20b`; account/model availability still needs a live functional check. No automatic alternate model is selected.

## Verification executed

**64 tests passed, zero failures** in the final regression run. Ruff passed, and dependency consistency passed. Tests cover:

- Constant velocity within 0.15m/s tolerance, finite/symmetric positive semidefinite covariance, matching stepped forecast covariance, continuous thin-zone intersections, boundary membership, analytic route distance, insufficient-history ETA suppression, repeatable ensembles and outlier freshness preservation.
- Unknown claims versus explicit authorization, independent zone permission and mission validity, projected handoff before entry, persistent deviation, source/vehicle heartbeat distinctions, loss of coverage, historical handoff retention, incident reuse, revision checks, idempotent acknowledgment/stop, eligibility for closure and stopped-session rejection.
- Invalid schemas/IDs/frame/nonfinite values/future times, body and role boundaries, duplicate event and sequence conflicts, archival, bounded overload, ambiguous commit completion, storage failure and actual mid-transaction rollback, committed-only publication, single database owner, manual/realtime recovery and clock uncertainty.
- An **actual server OS process termination and restart**, restoring committed filter/incident state and duplicate detection using a disposable database.
- Blocked fake-provider noninterference, timeout/429/5xx/credentials/missing-model/refusal/truncation/malformed/invalid-action/unknown-reference failures, all four controlled faults, bounded jobs and session budget, circuit/cooldown, semantic invalidation on identity change, valid attachment during unchanged normal motion, cancellation after stop and prompt-injection containment.
- Five official Groq SDK transport tests intercepted with `httpx.MockTransport`; real request schema/options and retry disabling are checked without network or a real key.

The HTTP simulator was also run against actual local Uvicorn servers:

| Scenario | Verified final behavior |
|---|---|
| normal | AUTHORIZED, MONITOR |
| unknown_approach | UNKNOWN permission, HUMAN_REVIEW |
| authorized_deviation | AUTHORIZED, CONTACT_OPERATOR |
| sensor_loss | LOST/UNKNOWN, REQUEST_FRESH_OBSERVATION, source ONLINE |
| identity_resolved | AUTHORIZED, MONITOR, explicit operator binding |
| replay_and_outlier | DUPLICATE, ID conflict, archived late position, rejected jump; permission remains UNKNOWN |
| malicious_note | UNKNOWN, VERIFY_PERMISSION despite instruction-like/HTML text |
| ai_failure | MOCK adapter unavailable; deterministic HUMAN_REVIEW remains available |

Seven scenarios passed with AI OFF; all eight passed with the explicit fake provider/fault configuration. Presentation-speed realtime ingestion was exercised by the real HTTP benchmark. The scenario verification runs used manual clocks for reproducibility.

**Not performed:** live Groq/account verification. The explicit smoke command printed `SKIPPED: no GROQ_API_KEY configured` and made no provider call. Visual browser QA was also unavailable because the connected browser inventory was empty. The page/assets, DOM-safe rendering code, API contract and CSP were checked; this is not a claim of a completed visual browser review.

## Measured performance

Recorded output: [docs/benchmark-results.json](docs/benchmark-results.json). AI OFF, one Uvicorn worker, local SQLite with WAL and FULL synchronization, 20 tracks, default 30s/2s/32-sample forecasts. Each phase creates a new session; timing deques reset per session, while counters are process-wide. The burst client is bounded to 320 in-flight and 512 pending requests.

| Measurement | Normal: 20 observations/s for 60s | Burst: 200 attempts/s for 5s |
|---|---:|---:|
| HTTP attempts | 1,200 | 1,000 |
| Committed APPLIED | 1,200 | 396 |
| Queue-full HTTP 429 | 0 | 604 |
| Archived / client dropped / unexpected failures | 0 / 0 / 0 | 0 / 0 / 0 |
| HTTP p50 | 19.21ms | See JSON (mixed successes/rejections) |
| HTTP p95 | **121.15ms** | 4,866.55ms |
| HTTP p99 | 191.96ms | See JSON |
| Per-track core compute p95 | 6.05ms | 5.38ms |
| Coordinator queue wait p95 | 47.00ms | 4,937.00ms |
| Maximum reported tick scheduling lag | 0ms at platform timer resolution | 3,109ms |
| Burst including queue drain | — | 8.06s |

The normal-load p95 target is 150ms. **This run met the target with no unexpected normal-load failures.** This is one local measured run, not a real-time guarantee. The burst intentionally saturates the bounded coordinator and reports 429 rejections instead of silently losing accepted events. Burst HTTP percentiles include both successful and rejected attempts; the normal phase contains only committed successful ingestion. No AI latency/throughput claim is made from this offline experiment.

PowerShell `Get-Process` sampled the server after this workload: working set **97.1 MiB**, process-lifetime peak working set **119.0 MiB**. This is an OS observation, not a long-duration memory-leak study. The raw byte counts are preserved in the benchmark JSON. Windows monotonic timer granularity can quantize queue/tick timings, including reported zero lag; it does not imply a hard real-time tick guarantee.

## Limitations and deviations

- Live provider access and visual browser review remain unverified as described above. The installed SDK and mock output are not represented as live model execution.
- To keep recovery reviewable, each transaction checkpoints the bounded current session as versioned JSON as well as updating normalized audit tables. This duplication limits burst throughput. Measurements expose the lag/rejections; successful receipts retain their commit semantics.
- Local token budgets use conservative character-based estimates plus completion allowance and reconcile reported usage. Retry-After is honored when numeric (bounded to 1..3,600s); malformed/unrecognized values use a 30s cooldown. Other provider rate-limit header variants are not used to infer additional quota. Account limits remain authoritative.
- AI jobs rejected by cooldown/budget do not accumulate a delayed retry backlog. A later eligible change or explicit request can try again. Runtime rate windows reset on process restart; the per-session attempt cap is durable.
- Numerical checks and seeded synthetic cases establish implementation behavior, not calibrated prediction accuracy, intent identification, operational harbor validation, safety certification or disaster prevention.
- This is one host/process with process recovery, not high availability. There is no automatic reacquisition, cross-source fusion, raw sonar processing, geographic conversion, roles/accounts service, vehicle actuation, automatic external messaging, WebSocket service, trained anomaly model or distributed infrastructure.
- Per-session quotas and bounded memory do not cap accumulated disk usage across preserved sessions. Old databases require deliberate offline archival/cleanup outside the MVP.
- Operator identity binding is a human assertion in the demo. Static tokens and trusted-LAN HTTP are not production identity or transport security.

## Teammate next steps

**Simulator owner:** use the versioned Event envelope, local meters, configured source IDs, stable retry IDs, boot/sequence metadata and fresh session-aligned timestamps. Publish source heartbeats during position silence. Use operator credentials only for session/time/identity/workflow commands. Start from `scripts/run_demo.py`; do not send ground-truth labels into observations.

**Interface owner:** poll `/snapshot` at 1Hz; render authorization, risk, data quality, source health and AI independently. Preserve LOST/UNKNOWN and outstanding handoffs. Use deterministic numeric fields instead of parsing prose. Include displayed core revisions in acknowledgment/binding/close requests. Render notes and AI text as text and show MOCK/provider/basis age. See [API contract](docs/API_CONTRACT.md) and [runbook](docs/DEMO_RUNBOOK.md).

**Presenter:** run the offline path first, then optional fake failures. A live Groq key is optional. Use the documented one-worker command and stop the previous session between scenarios.
