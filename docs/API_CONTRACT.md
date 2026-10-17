# Harbor API contract 1.0

All domain records contain `schema_version: "1.0"`. The data and policy are synthetic demonstration assumptions. Positions are horizontal local meters, X east and Y north. Authorization, operational risk, data freshness and AI capability are independent fields. The engine never classifies hostile intent or performs an external action.

Use `/openapi.json` for the exact generated request schemas and the reusable `Assessment` response model. `/docs` is the local interactive API reference. Bodies reject unknown fields, NaN/Infinity, invalid IDs, naive timestamps and unsupported measurements. IDs match `[A-Za-z0-9_-]{1,64}`. Event timestamps require a timezone and are normalized to UTC `Z` in stored/returned event representations. Scenario timestamps serialize as UTC `Z`; internal filter time and transport diagnostic ages use numeric seconds.

## Endpoints and roles

All paths below are exact; `{sid}`, `{tid}`, `{iid}`, `{eid}` stand for valid IDs.

| Method | Path | Role |
|---|---|---|
| GET | `/health/live` | public, minimal coordinator progress |
| GET | `/health/ready` | public, minimal critical capability readiness |
| GET | `/v1/status` | viewer/operator |
| POST | `/v1/sessions` | operator |
| GET | `/v1/sessions/{sid}` | viewer/operator |
| POST | `/v1/sessions/{sid}/stop` | operator |
| POST | `/v1/sessions/{sid}/events` | sensor for sensors; operator for notes |
| GET | `/v1/sessions/{sid}/events/{eid}` | sensor/viewer/operator; committed receipt only |
| GET | `/v1/sessions/{sid}/snapshot` | viewer/operator |
| GET | `/v1/sessions/{sid}/tracks/{tid}` | viewer/operator |
| GET | `/v1/sessions/{sid}/history?after=0&limit=100` | viewer/operator |
| POST | `/v1/sessions/{sid}/clock/advance` | operator, manual demo sessions only |
| POST | `/v1/sessions/{sid}/identity-bindings` | operator |
| POST | `/v1/sessions/{sid}/incidents/{iid}/ack` | operator |
| POST | `/v1/sessions/{sid}/incidents/{iid}/close` | operator |
| POST | `/v1/sessions/{sid}/tracks/{tid}/enrichment` | operator |
| POST | `/v1/demo/faults` | operator, explicitly enabled demo faults |
| GET | `/v1/metrics` | viewer/operator |
| GET | `/`, `/static/*` | public page/assets, no embedded credentials |

Use `Authorization: Bearer TOKEN`. Maximum request body: 65,536 bytes. History has default 100, maximum 500, with increasing integer `cursor` and `next_cursor`. GETs never generate new decisions. Source token ownership is configured by policy role: `sim_sonar_01` owns position input, `sim_telemetry_01` owns cooperative heartbeats, and `operator_console` owns notes. The first accepted position associates one source with one track; cross-source fusion is rejected.

## Create and control a session

```json
{"command_id":"create_demo_001","name":"Harbor Night","clock_mode":"realtime","start_time":null,"seed":42}
```

Manual creation uses `"clock_mode":"manual","start_time":"2026-10-17T07:00:00Z"`. The server assigns `session_id`. The response includes `current_time`, pinned policy/registry/procedure versions, expanded mission windows, seed and stopped state. Realtime timestamps use monotonic elapsed time from UTC start; manual observations never advance time. Session creation conflicts while another is active.

Every control body includes a globally unique `command_id`. Same ID and canonical content (including route/session) returns the original result; changed content returns 409 `COMMAND_ID_CONFLICT`. Reuse identifiers after an ambiguous outcome. Event IDs are scoped to the session. Control examples:

```json
{"command_id":"advance_1","delta_seconds":1}
```

Advance requires `0 < delta_seconds <= 5`; call repeatedly for larger gaps. Stop and enrichment requests use only `{"command_id":"unique_id"}`. Stopping prevents further ingestion, ticking and AI attachment; history remains readable. Repeating stop is harmless. A stopped session never resumes.

Identity binding:

```json
{"command_id":"bind_1","track_id":"track_01","mission_id":"research_mission","operation":"confirm","expected_core_revision":1,"justification":"Officer checked the synthetic mission record"}
```

`operation` is `confirm` or `revoke`. `mission_id` is required but may be null for revocation. A confirmed mission must exist. Actor identity comes from server configuration. Confirmation is a demo human assertion, not physical or cryptographic proof. The returned Assessment immediately reflects binding/permission changes.

Acknowledgment body:

```json
{"command_id":"ack_1","expected_core_revision":3,"note":"Watch officer accepts review"}
```

Closure additionally requires `"reason":"Resolved with fresh evidence"`. Revision mismatches return 409 `STALE_REVISION` with `current_core_revision`. Acknowledgment changes incident ownership, not physical risk. Closure requires fresh LOW assessment and no unresolved handoff. Incident states are WATCHING, VERIFYING, HANDOFF_PENDING, HUMAN_OWNED and CLOSED. One open incident per track; highest historical risk/evidence stays separate from current risk. Lost positions cannot clear a pending handoff.

## Observation events

```json
{
  "schema_version":"1.0",
  "event_id":"evt_000001",
  "source_id":"sim_sonar_01",
  "source_boot_id":"boot_001",
  "source_sequence":1,
  "kind":"observation",
  "observed_at":"2026-10-17T07:00:01Z",
  "payload":{"track_id":"track_01","coordinate_frame":"harbor_local_m","x_m":120,"y_m":85,"position_sigma_m":2,"claimed_vehicle_id":"research_auv_02"}
}
```

The timestamp is illustrative: use current session time in manual mode or fresh UTC aligned with the session in realtime mode. Do not replay this date as current data. `claimed_vehicle_id` may be null and cannot authorize the track. Speed, threat, permission, identity-verification and ground-truth scenario labels are not accepted payload properties. Sigma is a source claim bounded by policy (0.2..20m by default). Bounds are X 0..1000m, Y 0..700m. Only local Cartesian positions are supported.

Other kinds use the same envelope:

| Kind | Source | Payload | Effect |
|---|---|---|---|
| `source_heartbeat` | either configured sensor | `{"status":"online"}` | Transport only |
| `vehicle_heartbeat` | `sim_telemetry_01` | `{"track_id":"track_01"}` | Bound cooperative mission communication only |
| `operator_note` | `operator_console` | `{"track_id":"track_01","text":"Check the mission record"}` | Attributed untrusted text, max 500 chars |

Heartbeats, notes, AI answers and predictions never refresh position time. Keep source heartbeats flowing during intentional position silence. Vehicle heartbeats need a current explicit mission/source binding; unknown tracks have no assumed communication obligation.

HTTP 200 means the event disposition and deterministic state/history committed. Receipt fields: `event_id`, `disposition`, nullable `track_id`, `assessment_id`, `core_revision`, and `ai_status`. AI completion is not part of this acknowledgment.

Dispositions:

- `APPLIED`: updated live deterministic state or accepted heartbeat/note.
- `DUPLICATE`: same event/content; original assessment reference, no second filter update.
- `ARCHIVED_STALE`: older than policy ingestion-age limit (15s default), audit only.
- `ARCHIVED_OUT_OF_ORDER`: position time <= last applied position or old vehicle heartbeat, audit only.
- `REJECTED_OUTLIER`: squared innovation distance exceeds gate (16 default), audit only; accepted filter/measurement time stays unchanged.

The `(sid,source_id,source_boot_id,source_sequence)` tuple is also unique; reuse under another event ID returns `SEQUENCE_CONFLICT`. Sequence gaps are exposed as transport diagnostics. A boot change does not reset measurement age. Events more than 2 scenario seconds ahead return `FUTURE_EVENT`. Out-of-sequence filtering and automatic reacquisition are deferred; create a new associated track ID for a deliberate reacquisition demo.

## Snapshot and assessment

Poll `/snapshot` at 1 Hz. Top-level fields: `session`, `synthetic_data`, `policy_assumptions`, `health`, `ai`, `sources`, `zones`, `routes`, `bounds`, `tracks` (Assessment array), `open_incidents`, `simulated_faults`. `routes` is an additive field mapping route IDs to local-metre vertex arrays from the session's pinned policy; the dashboard uses it for mission reference lines.

| Assessment group | Stable fields / meaning |
|---|---|
| Identity | `assessment_id`, `session_id`, `track_id`, `core_revision`, `assessed_at`, `last_observed_at`, `policy_version`, `registry_version` |
| `source` | `applied_event_id`, `source_id`, `observation_age_seconds`, `accepted_observations`, `rejected_outliers`, `synthetic_data` |
| `estimate` | `x_m`, `y_m`, `vx_mps`, `vy_mps`, `speed_mps`, 4x4 `covariance`, `velocity_established`, `estimated_at` |
| `authorization` | `status` UNKNOWN/AUTHORIZED/NOT_AUTHORIZED, `mission_id`, `claimed_vehicle_id`, `binding_provenance`, `per_zone_permissions` |
| `risk` | `current_band` LOW/ELEVATED/HIGH/UNKNOWN, `reason_codes`, `historical_incident_maximum`, `calibrated:false` |
| `forecast` | `horizon_seconds`, assumption, `computed_at` UTC timestamp, `points`, `zone_entries`, `current_zones`, `relevant_zones`, current uncertainty radius, nearest zone/route distances, sampled diagnostic |
| `recommendation` | `primary_action`, `human_action_required`, `advisory`, deterministic explanation, evidence IDs, `eligible_next_evidence`, `ranking_method:heuristic`, `reassess_by`, optional `outstanding_human_handoff` |
| `evidence` | Stable reason-based IDs, measured feature values, observation timestamp and deterministic origin |
| `incident` | Current packet or null, state, ID, historical evidence, acknowledgment actor/time |
| `capability` | `data_quality`, `source_health`, `core_health`, `storage_health`, `ai_status` |
| `ai_enrichment` | null or separate record: provider/model, basis revision/time/age, validation status, review requirement and response |

`core_revision` changes on semantic permission/risk/reason/action/evidence-eligibility/note changes and operator incident actions. `assessment_id` changes when an assessment is computed. GET does neither. Nullable unavailable values are never silently zero. Velocity needs >=3 accepted observations spanning >=2s. A single observation has no ETA. Boundary membership uses polygon `covers`; continuous segment intersection detects thin crossings between forecast vertices. The uncertainty radius is twice the major-axis standard deviation, not certified 95% joint coverage. `sampled_zone_hit_fraction` is a seeded model-conditional diagnostic with `calibrated:false`, not attack or collision probability.

Freshness defaults: <=3s fresh, >3s stale, >10s lost, derived from the source interval. Forecasts end when measurement age exceeds 15s. Data validity gates current geometry assertions. Source health is ONLINE/OVERDUE/UNKNOWN independently. A stale/lost current risk replaces old geometric certainty while preserving historical handoff evidence. Primary-action precedence is HUMAN_REVIEW > CONTACT_OPERATOR > REQUEST_FRESH_OBSERVATION > VERIFY_PERMISSION > MONITOR among valid matched rules. Risk and action are selected independently. Route deviation enters above 20m for three accepted observations spanning 2s and clears below 15m for three accepted observations; ticks do not count.

## Optional AI and faults

AI may summarize supplied evidence and select one eligible next-evidence action; it cannot change the primary action, risk, permissions, filter, policy or incident. Enrichment schema:

```json
{"summary":"Review the current evidence.","suggested_next_evidence_action":"VERIFY_TRACK_IDENTITY","evidence_ids":["ev_identity_unconfirmed"],"procedure_ids":["proc_identity_check"],"uncertainties":["Identity remains unverified."]}
```

All properties required, no extra properties. Summary max 600 chars; <=3 uncertainties of <=160 chars. IDs/actions must belong to the exact supplied snapshot; substantive responses need evidence. Semantic revalidation allows unchanged normal motion while retaining the original basis timestamp; changed identity/reasons/action/note invalidate results. Maximum attachment job age is 10 real seconds; observations must still be usable. Show AI prose separately as **AI explanation — review against evidence**. MOCK output never represents live inference.

Fault request:

```json
{"command_id":"fault_1","fault":"AI_TIMEOUT","enabled":true,"duration_seconds":60}
```

Allowed faults: `AI_UNAVAILABLE`, `AI_TIMEOUT`, `AI_RATE_LIMIT`, `AI_INVALID_RESPONSE`. Duration >0 and <=300s. Requires active session, operator role, `DEMO_MODE=true`, `DEMO_FAULTS_ENABLED=true`. Faults are audited, expire and clear on stop. They intercept the provider interface without paid calls. OFF does not attempt a provider call and therefore demonstrates offline operation, not attempted provider failure.

## Errors, retry and durability

```json
{"error":{"code":"EVENT_ID_CONFLICT","message":"This identifier already belongs to different content","request_id":"request_example","retryable":false}}
```

Common errors: 401 UNAUTHENTICATED; 403 FORBIDDEN/SOURCE_FORBIDDEN/FAULTS_DISABLED; 404 missing records; 409 ID/sequence conflicts, active/stopped session, stale revision, ineligible closure; 413 BODY_TOO_LARGE; 422 INVALID_SCHEMA/FUTURE_EVENT/POSITION_BOUNDS/NOISE_BOUNDS/CLOCK_MODE; 429 QUEUE_FULL/TRACK_LIMIT/SESSION_QUOTA; 503 STORAGE_UNAVAILABLE/CORE_UNAVAILABLE/COMMIT_STATUS_UNKNOWN.

Before queue admission, overload returns 429 with Retry-After 1s. Retry the same identifier. If an admitted waiter times out, 503 `COMMIT_STATUS_UNKNOWN` means it may still commit: query the receipt endpoint or retry the same ID, never issue a replacement event ID. Last committed snapshots remain available on storage failure and visibly show unavailable storage. A 200 acknowledgment is never issued for an uncommitted mutation.

The sensor owner should use stable event IDs across retries, a new boot ID per publisher run, increasing sequences and one source per track. The UI owner should render structured fields, retain unknown/lost coverage, keep tokens in memory, use `textContent` for notes/AI prose, and include the displayed core revision in operator commands. Neither client should infer permissions from a claimed vehicle ID or AI text.
