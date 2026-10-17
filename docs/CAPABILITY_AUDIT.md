# Harbor-maester: capability audit and validation

## What problem is actually solved

Harbor-maester is a CPU-first, synthetic decision-support prototype for a harbor watch officer. It turns position reports and mission context into an explainable next action, keeps uncertainty and lost data visible, and records human review. It now also analyzes surface voyages across the harbor instead of treating surface vessels as decoration.

It is not a production VTS, a hostile-intent detector, a real AIS service, or an autonomous emergency-response system. Acknowledgment is an audited human handoff, not dispatch, navigation clearance, or execution of a recommendation.

## Crisis Mitigation criteria

| Criterion | Demonstrated behavior | Evidence and boundary |
|---|---|---|
| Detect | Estimates motion; rejects outliers; detects projected zone entry, route deviation, overdue communications, lost positions, surface close approaches and schedule delay. | Numerical models and scenario tests. Input contacts are pre-associated; there is no raw camera/sonar detection or identity recognition. |
| Warn | Produces reason codes, position freshness, uncertainty, prioritized recommendations, map colors and traffic advisories. | In the seeded harbor-approach evaluation, high concern appeared at second 36 and estimated zone occupancy at second 51: 15 scenario seconds of lead time. This is one synthetic scenario, not a measured field warning guarantee. |
| Respond | Suggests evidence requests, permission verification, operator contact or human review. Revision-checked acknowledgment is persisted in SQLite; surface reviews now have the same durable audit boundary. | The original objective ends at human handoff. No radio, external messaging, vessel control, incident dispatch, evacuation or real-world response is implemented. |
| Feasibility | Laptop CPU, bounded queues and inputs, authenticated API roles, deterministic fallback, startup recovery, local atlas and separate optional AI worker. | Suitable for a demonstration and controlled user study. Production identity management, validated charts/policies, real sensor contracts, availability engineering and responder acceptance testing remain open. |
| Impact | Can measure warning lead time, freshness transitions, observation processing and completed review workflows. | People made safer and time saved versus existing tools are **not measured**. Do not invent lives saved or percentages faster. |
| Dual-use | Ordinary-day route adherence, berth queues, transit coordination and research-mission oversight; disrupted-day movement delays, lost sensors and emerging zone incidents. | Wildfire/flood modeling is **not implemented**. Harbor traffic consequences of an externally supplied incident could be integrated later; this is not evidence that the app detects fire or predicts flooding. |

Real VTS work includes traffic reports and advisory coordination. The local context and distinction between information and navigational responsibility are described in the [Marine Exchange / USCG VTS LA-LB user manual, May 2026](https://mxsocal.org/assets/pdf/vts-user-manual-260504.pdf). This prototype does not implement or claim compliance with that manual's operating procedures.

## Implemented algorithms versus AI/ML claims

| Component | Actual implementation | Status |
|---|---|---|
| Position/velocity estimation | Four-state linear constant-velocity Kalman filter, covariance propagation, Mahalanobis innovation gate and Joseph covariance update (`tracking.py`). | Runs on accepted sonar-derived local position observations. |
| Forecast | Conditional constant-velocity mean trajectory and propagated covariance (`forecast.py`). | Runs on established, sufficiently fresh tracks. |
| Ensemble | 32 seeded Monte Carlo state/acceleration samples and zone-intersection fractions. | A trajectory sample ensemble, **not** an ensemble of trained ML classifiers. Uncalibrated; not a collision probability or threat confidence score. |
| Geometry and temporal policy | Shapely route distances, segment/polygon entry, freshness thresholds, route-deviation hysteresis and exact mission permissions (`policy.py`). | Drives primary sonar recommendations. |
| Procedure retrieval | Reason/action filtering plus BM25 over versioned demo-authored records (`retrieval.py`). | Retrieval support, not an embedding model or learned reasoning system. |
| LLM | Optional configured Groq-hosted `openai/gpt-oss-20b`, asynchronous and validated (`ai/`). | `off` makes no LLM calls; `fake` is a labeled mock. Real Groq mode requires credentials, SDK/network and provider availability. No paid inference was required for this validation. |
| Surface analysis, added here | Relative-velocity closest point of approach over 120 s, cross-track distance to an assigned route, and delay against a synthetic arrival schedule (`surface.py`). | Runs in the decision coordinator for all currently positioned surface vessels. Thresholds are explicit demo assumptions. No vessel identity inference. |
| Voyage scheduling, added here | Seeded route assignment, directional water corridors, channel spacing, berth-basin reservation, 60 s service dwell, departures and queued arrivals (`traffic.py`, `voyages.py`). | Simulation mechanics; not a learned scheduler or operational collision-avoidance controller. |
| Trained motion classifier | 48-tree random forest over seven temporal motion features, trained offline on synthetic trajectories. | Advisory movement hypotheses on the Detection page; not material recognition or a trained safety/anomaly classifier. See [model card and evaluation](MOTION_DETECTION.md). The supplied CSV is not used as labeled motion training data. |

The fast decision path consists of numerical tracking, geometry and explicit policy. The slower optional LLM explains a committed assessment and cannot change permissions, risk or the primary action. The separate local motion classifier now provides synthetic-data-trained behavioral hypotheses without changing those decisions. Real-world anomaly detection still needs evaluation on held-out vessels/days and incident labels with false-alerts-per-hour and missed-event rates.

## Harbor-wide changes

- App name is **Harbor-maester**.
- Default **Harbor-wide operations** exercise lasts 900 scenario seconds and schedules 48 surface voyages alongside eight sonar contacts. Short incident presets remain 90 seconds. Up to 100 unique dataset profiles can be scheduled.
- Ten voyage destinations cover the water-facing areas of the existing 11-area harbor atlas. Pier B remains a rail/logistics area; it is not given a fabricated vessel berth.
- Warm-started voyages occupy separated positions. Additional arrivals wait off-map until there is space. Vessels follow assigned routes, wait for channel/berth separation, berth, dwell, depart and leave the map. They do not bounce between endpoints or wrap through another vessel.
- The scheduler enforces 120 m center separation in the illustrative geographic frame and 18 drawing units on the atlas. These are simulation constraints, not real vessel safety distances. Schematic route and vessel positions are checked against pier polygons. Geographic anchors remain approximate; no hydrographic depth, real hull/draft model, tides, COLREGs or surveyed navigability is claimed.
- Surface position/velocity/schedule batches go through authenticated `/v1/sessions/{id}/surface`, the bounded coordinator and SQLite. They are included in committed snapshots and history. Batches have unique IDs, bounded sizes, clock validation and out-of-order rejection.
- `/v1/sessions/{id}/surface/{vessel_id}/ack` records revision-checked review. Changed reasons or encounter counterparties invalidate the old acknowledgment. Stale positions suppress current encounter predictions.
- The **Traffic** page shows advisories, voyage state, ETA, delay, encounter evidence and acknowledgment. The full schedule includes arrivals not yet admitted. The atlas and geographic view show assigned routes and assessment colors.
- **Activity** shows accepted surface observations and ingestion-step timing. Playback pacing includes ingest time rather than adding processing time after every nominal interval. Slow processing does not trigger unbounded catch-up bursts.

The simulator and assessment model have separate responsibilities: the simulator schedules movement; the engine observes and advises. An engine warning does not silently steer a vessel. Surface reports currently contain generated positions and velocities; this is not raw AIS parsing or surface sensor fusion. Surface close-approach forecasts may be conservative around planned turns and scheduled holds; this false-alert burden remains to be calibrated.

## Measured evaluation

The harbor timing results below were recorded before the small-object stream was added. They remain a historical baseline, not a throughput claim for the expanded system. Motion-model results are recorded separately in [motion-evaluation.json](motion-evaluation.json).

See [machine-readable results](harbor-evaluation.json). Reproduce with:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_harbor --output docs/harbor-evaluation.json
```

The evaluation uses the real engine API with an in-process ASGI test transport and disposable storage, with AI off. It is not a network/end-to-end human-response benchmark. Timing is machine/load dependent.

- Approach: high concern at 36 s; estimated entry at 51 s; **15 s warning lead**.
- Sonar stops at 10 s: stale at 13 s and lost at 20 s; the last accepted position was at 9 s. Telemetry and surface processing continue.
- Harbor-wide sample: **44 visible surface vessels + 8 sonar contacts**, **946 pairs** checked per surface assessment, **1,584 surface observations** accepted over the 36 batches spanning seconds 0–35. Four additional scheduled voyages initially wait for admission; numbers change as space becomes available.
- Harbor-wide ingestion-step median **209 ms**, p95 **280 ms** in the recorded evaluation. This includes simulator sampling, sonar/heartbeat requests, surface analysis/persistence and snapshot acquisition. It is not LLM inference latency or proof of an operational SLA.
- The 100-vessel schedule check spans 900 scenario seconds, verifies pier avoidance and pair separation at sampled times, observes both berthing and departure, and checks deterministic replay. Movement logic applies spacing checks on each 1 s step. Dense traffic can queue; not every scheduled voyage completes within 15 minutes.

Before claiming operational benefit, conduct a tabletop responder study with the same cases and a baseline workflow. Measure detection-to-acknowledgment time, correct next-action selection, missed events and false alerts per watch-hour. Count exposure reduction only from an explicit validated scenario model; do not equate vessels shown with people made safer.

## Verification completed

The full engine, dashboard, integration and preserved Pako suite passed: **93 tests**, including surface models, dense traffic geometry, persistent acknowledgment, motion classification/abstention, bounded 15-minute object streaming, area projection, authorization, duplicate handling and recovery. Headless Edge verified movement/pause, geographic overlays, East Basin location selection, live Detection hypotheses, contact/traffic navigation and audit loading. Detection screenshots were visually inspected. Ruff passed for changed Python files. Existing Starlette/TestClient deprecation warnings remain; they did not fail validation.

## Remaining work for real use

1. A licensed/live AIS or port-feed adapter with provenance, timestamps, coverage gaps and replay protection; surveyed lanes/berths and real dimensions/drafts.
2. Harbor-approved thresholds, procedures and permissions; independent validation of forecast behavior, route plans and alert burden.
3. Role-specific user accounts, responder ownership/escalation, secure deployment, reliable backups and availability/recovery exercises.
4. Labeled incident data and held-out evaluation before adopting trained classifiers or claiming ML accuracy.
5. Dedicated hazard inputs and domain validation before any wildfire/flood detection or evacuation claims.

The current useful claim is: **explainable harbor-watch decision support that keeps working without an LLM, with an integrated, scheduled harbor-wide simulation and measurable warning/review behavior**.
