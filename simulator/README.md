# Harbour Decision-Engine Simulator

Prototype simulator for the three-level maritime harbour security architecture
described in [`docs/decision_engine/structure.md`](../docs/decision_engine/structure.md).

---

## Architecture overview

```
simulator/
├── data_models/          Level 1 — typed evidence records
│   ├── observation.py    Observation, Position, BearingRange, enums
│   └── records.py        Mission, Zone, EnvironmentRecord, Report
│
├── sensors/              Level 1 — simulated sensor adapters
│   └── sensors.py        SonarSensor, CooperativeTelemetrySensor,
│                         AISSensor, EnvironmentalSensor, OperatorNoteInjector
│
├── ingestion/            Level 1 — decode → validate → normalise → provenance
│   └── pipeline.py       IngestionPipeline, ObservationValidator,
│                         CoordinateNormalizer
│
├── journal/              Level 1 — append-only event store
│   └── journal.py        InMemoryJournal (swap for JetStream in production)
│
├── engine/               Level 2 — hybrid decision engine
│   ├── tracker/          KalmanTracker (6-state CV KF; EKF placeholder)
│   ├── predictor/        TrajectoryPredictor (MC rollouts, zone hits)
│   ├── policy/           PolicyEngine (typed rules, authorization verdict)
│   ├── incident/         IncidentManager (FSM: watching → handoff → resolved)
│   ├── ai_branch/        AIBranch (hybrid retrieval + LLM stub)
│   ├── planner/          ActionPlanner (catalog + VoI estimate)
│   ├── verifier/         ActionVerifier (schema, freshness, prerequisite checks)
│   └── decision_engine.py  Facade — orchestrates all components
│
├── output/               Level 3 — versioned decision package
│   └── decision_package.py  DecisionPackage, CourseOfActionCard, builder
│
├── orchestrator/         Scenario clock, runner, fault-injection panel
│   └── runner.py         SimulatorRunner, ScenarioConfig, FaultPanel
│
├── tests/
│   └── test_smoke.py     End-to-end and unit smoke tests
│
└── main.py               CLI entry point
```

---

## Quick start

```bash
# Install dependencies
pip install numpy

# Run the demo scenario (60 ticks × 5 s = 5 simulated minutes)
python -m simulator.main

# Fault-injection demos  (see inference.md §11)
python -m simulator.main --fault drop_sonar
python -m simulator.main --fault disable_ai
python -m simulator.main --fault clock_jump
python -m simulator.main --fault event_flood
python -m simulator.main --fault replay_old_data

# Verbose output
python -m simulator.main --verbose
```

### Running the tests

```bash
pip install pytest
pytest simulator/tests/
```

---

## Demo scenario

Matches the end-to-end example in `structure.md`:

| Entity | Description |
|---|---|
| **T-001** | Unknown contact approaching the restricted dock from the west |
| **AUV-01** | Cooperative research AUV; deviates from permitted area at t=90 s |
| **SV-SUPPORT** | Surface support vessel (AIS) |
| **Z-DOCK** | Restricted dock zone — triggers HANDOFF_TO_OFFICER when trajectories intersect |
| **Z-RESEARCH** | AUV operating zone (awareness level) |
| **Operator note** | Injected at t=90 s (AUV deviation) and t=180 s (visual report) |

---

## Fault-injection panel (`FaultPanel`)

| Fault | Effect | inference.md scenario |
|---|---|---|
| `drop_sensor(source_id)` | Sensor produces no observations | "Disconnect sonar" |
| `disable_ai()` | AI branch skipped; deterministic explanations only | "Kill the model process" |
| `set_clock_jump(s)` | Observations arrive with a future timestamp → pipeline rejects | "Introduce a clock jump" |
| `enable_event_flood()` | Each observation is duplicated → pipeline deduplicates | "Flood the system with events" |
| `enable_replay_old_data()` | Observations backdated by 2 h → freshness check fails | "Replay old telemetry" |

---

## Integration TODOs

| Component | Stub location | What to replace with |
|---|---|---|
| LLM inference | `engine/ai_branch/ai_branch.py` `LLMClient.complete` | vLLM OpenAI-compatible endpoint (Granite 4.2 3B or Qwen3.5 4B) |
| Dense retrieval | `AIBranch._retriever` | BGE-small-en-v1.5 embeddings + real BM25 index |
| EKF bearing-only update | `KalmanTracker._update_bearing` | Full EKF Jacobian or Stone Soup `BearingRangeCartesian2DUpdater` |
| Coordinate projection | `CoordinateNormalizer.normalise` | pyproj WGS-84 → local ENU |
| Durable event journal | `InMemoryJournal` | NATS JetStream consumer |
| Anomaly detection | _(not yet present)_ | Isolation Forest on track features |
| Dashboard | _(not yet present)_ | Map + evidence panel + acknowledgment UI |

---

## Decision boundary

> The engine receives structured observations and records, then returns a versioned
> `DecisionPackage` containing estimates, predictions, evidence, uncertainty, and
> recommended actions.  The simulator and dashboard can be built independently
> against this interface.
