# Release validation record

This document records what was actually exercised before the v1 public release. It is not a proof of correctness; it describes the scope and limits of the checks that were run.

## Test suite

| Suite | Command | Outcome |
|---|---|---|
| Engine and API | `pytest tests/ -q` | All tests pass |
| Simulator | `pytest simulator/tests/ -q` | All tests pass |
| Personal AI (visitor key path) | `pytest tests/test_personal_ai.py -q` | 7 tests pass |
| Static website | `python project-website/check_site.py` | All checks pass |
| JavaScript syntax | `node --check project-website/app.js` | No syntax errors |

## What the tests cover

- **Authentication**: sensor, operator and viewer token enforcement; rejected unauthenticated requests.
- **Persistence**: transactional observation insert and assessment commit; session isolation.
- **Tracking**: Kalman filter predict/update cycle, Mahalanobis gating, Joseph covariance update, stale/lost freshness transitions.
- **Forecasting**: Monte Carlo path generation, zone-entry time estimation.
- **Policy**: risk-band assignment, reason/action rules, hysteresis, incident lifecycle.
- **Surface kinematics**: CPA calculation, cross-track distance, schedule delay.
- **Motion detection**: feature extraction, random-forest inference, abstention logic.
- **Sensor failures**: sonar outage, intermittent gaps, recovery without state corruption.
- **AI validation**: schema enforcement, reference checking, stale-result rejection, explicit-request-only guard.
- **Visitor key isolation**: `PersonalAI` objects are scoped to Streamlit session state; shared engine state is never modified.
- **Dashboard interactions**: scenario start/stop, contact acknowledgment, detection view rendering.

## What the tests do NOT cover

- Real sensor hardware or live harbor data.
- Multi-user concurrency under sustained load.
- Browser rendering across different platforms (one local verification run in Microsoft Edge).
- Groq API availability, rate limits or model behavior changes.
- Container health after extended uptime (ephemeral container storage).
- Recovery from host OS restart or Docker daemon crash.

## Docker build verification

The release container was built and started locally on Windows (Docker Desktop, Linux containers). The healthcheck endpoint (`/_stcore/health` and `/health/ready`) responded healthy within the 60-second start window.

## Release hygiene check

`python -m scripts.release_check` was run immediately before commit. All three checks passed:
- No credential patterns found in scanned source files.
- All required release artifacts present.
- `.dockerignore` does not expose `.env` files.

## Known limitations at release

- SQLite storage is ephemeral in the Hugging Face Space container. A container restart clears exercise history.
- The shared simulation exercise has no per-user authorization; any visitor can start or pause a scenario.
- The motion forest is trained and evaluated entirely on synthetic trajectories from the same generator. Real-world accuracy is unknown.
- Groq model behavior and availability are outside this project's control. The AI explanation path is always optional.
