"""One mutation owner. Copy, compute, commit, publish, then schedule enrichment."""

import asyncio
import copy
import hashlib
import sqlite3
import time
import uuid
from collections import Counter, deque
from contextlib import suppress
from datetime import datetime

from .clock import SessionClock, stamp, utc_now
from .errors import DomainError
from .incidents import reconcile
from .motion import ingest_detection, reassess_detection
from .policy import Policy, assess
from .storage import encode
from .surface import assess_surface
from .tracking import initialize, update


class Coordinator:
    def __init__(self, settings, policy, storage, procedures):
        self.settings, self.policy, self.storage = settings, policy, storage
        self.configured_policy = policy
        self.procedures = procedures
        self.state = None
        self.clock = None
        self.queue = asyncio.Queue(settings.core_queue_capacity)
        self.task = self.ticker = self.ai = None
        self.ready = False
        self.storage_available = True
        self.progress = time.monotonic()
        self.processing = False
        self.tick_pending = False
        self.counts = Counter()
        self.timings = {
            name: deque(maxlen=4096) for name in ("core_ms", "queue_ms", "tick_lag_ms", "http_ms")
        }

    async def start(self):
        await self.storage.open()
        self.state = await self.storage.recover()
        if self.state:
            self.policy = Policy.model_validate(self.state["policy"])
            if self.state["clock_mode"] == "realtime":
                current = utc_now()
                gap = current - self.state["saved_utc"]
                self.state["clock_uncertain"] = gap < -2 or gap > 86400
                self.state["now"] += max(0, gap)
                self.clock = SessionClock(self.state["now"])
            self.state["faults"] = {}
            for track in self.state["tracks"].values():
                track["assessment"]["ai_enrichment"] = None
            for track_id in self.state["tracks"]:
                self.reassess(self.state, track_id)
            self.reassess_surface(self.state)
            reassess_detection(self.state)
            self.state["saved_utc"] = utc_now()
            await self.storage.commit(
                self.state,
                "recovery",
                {"schema_version": "1.0", "status": "RECOVERED"},
                changed=list(self.state["tracks"]),
            )
        self.task = asyncio.create_task(self.run(), name="decision-coordinator")
        self.ticker = asyncio.create_task(self.tick_loop(), name="assessment-ticker")
        self.ready = True

    async def stop(self):
        self.ready = False
        for task in (self.ticker, self.task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        while not self.queue.empty():
            _, _, _, _, future, _ = self.queue.get_nowait()
            if not future.done():
                future.set_exception(DomainError("SHUTTING_DOWN", "Server is stopping", 503, True))
            self.queue.task_done()
        await self.storage.close()

    async def submit(self, kind, session_id=None, body=None, role="operator"):
        if not self.ready or not self.task or self.task.done():
            raise DomainError("CORE_UNAVAILABLE", "Coordinator is not ready", 503, True)
        if not self.storage_available:
            raise DomainError("STORAGE_UNAVAILABLE", "Storage unavailable; restart after repair", 503, True)
        future = asyncio.get_running_loop().create_future()
        try:
            self.queue.put_nowait((kind, session_id, body or {}, role, future, time.monotonic()))
        except asyncio.QueueFull:
            self.counts["QUEUE_FULL"] += 1
            raise DomainError("QUEUE_FULL", "Retry the same identifier after 1 second", 429, True) from None
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.settings.command_timeout_seconds)
        except TimeoutError:
            # Consume any later exception while preserving the admitted work.
            future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
            raise DomainError(
                "COMMIT_STATUS_UNKNOWN", "Query the event or retry the same identifier", 503, True
            ) from None

    async def tick_loop(self):
        due = time.monotonic() + 1
        while True:
            await asyncio.sleep(max(0, due - time.monotonic()))
            self.timings["tick_lag_ms"].append(max(0, time.monotonic() - due) * 1000)
            due = time.monotonic() + 1
            if (
                self.state
                and not self.state["stopped"]
                and self.state["clock_mode"] == "realtime"
                and not self.tick_pending
            ):
                self.tick_pending = True
                try:
                    await self.submit("tick")
                except DomainError as error:
                    if error.code != "COMMIT_STATUS_UNKNOWN":
                        self.tick_pending = False

    async def run(self):
        while True:
            kind, session_id, body, role, future, queued = await self.queue.get()
            self.progress = time.monotonic()
            self.processing = True
            self.timings["queue_ms"].append((self.progress - queued) * 1000)
            try:
                result = await self.execute(kind, session_id, body, role)
            except DomainError as error:
                self.counts[error.code] += 1
                if not future.done():
                    future.set_exception(error)
            except (sqlite3.Error, OSError):
                self.storage_available = False
                if not future.done():
                    future.set_exception(
                        DomainError("STORAGE_UNAVAILABLE", "Storage access failed", 503, True)
                    )
            except Exception:
                self.ready = False
                if not future.done():
                    future.set_exception(
                        DomainError("CORE_FAILED", "Coordinator failed; restart required", 503)
                    )
                raise
            else:
                if not future.done():
                    future.set_result(result)
            finally:
                self.progress = time.monotonic()
                self.processing = False
                if kind == "tick":
                    self.tick_pending = False
                self.queue.task_done()

    def reassess(self, state, track_id, accepted=False):
        start = time.perf_counter()
        assess(state, track_id, self.policy, self.settings, accepted)
        reconcile(state, track_id)
        self.timings["core_ms"].append((time.perf_counter() - start) * 1000)

    def check_revision(self, track, expected):
        current = track["assessment"]["core_revision"]
        if current != expected:
            raise DomainError(
                "STALE_REVISION", "Review the current assessment before acting", current_core_revision=current
            )

    def reassess_surface(self, state):
        if "surface_input" not in state:
            return
        previous = {r["vessel_id"]: r for r in state.get("surface", {}).get("vessels", [])}
        batch = state["surface_input"]
        observed = datetime.fromisoformat(batch["observed_at"].replace("Z", "+00:00")).timestamp()
        result = assess_surface(batch["vessels"], max(0, state["now"] - observed))
        result["revision"] = state.get("surface", {}).get("revision", 0) + 1
        result["observed_at"] = batch["observed_at"]
        for row in result["vessels"]:
            old = previous.get(row["vessel_id"], {})
            signature = (row["reason_codes"], sorted(e["vessel_id"] for e in row["encounters"]))
            old_signature = (
                old.get("reason_codes"),
                sorted(e["vessel_id"] for e in old.get("encounters", [])),
            )
            row["acknowledgment"] = old.get("acknowledgment") if signature == old_signature else None
        state["surface"] = result

    def find_track(self, state, track_id):
        if track_id not in state["tracks"]:
            raise DomainError("TRACK_NOT_FOUND", "Track not found", 404)
        return state["tracks"][track_id]

    async def execute(self, kind, session_id, body, role):
        digest = hashlib.sha256(
            encode({"kind": kind, "session_id": session_id, "body": body}).encode()
        ).hexdigest()
        command = None
        event = None
        changed = []
        ai_job = None
        if "command_id" in body or kind == "event":
            identifier = body["event_id"] if kind == "event" else body["command_id"]
            duplicate = await self.storage.duplicate(kind, session_id, identifier)
            if duplicate:
                if duplicate[0] != digest:
                    raise DomainError(
                        "EVENT_ID_CONFLICT" if kind == "event" else "COMMAND_ID_CONFLICT",
                        "This identifier already belongs to different content",
                    )
                response = duplicate[1]
                if kind == "event":
                    response["disposition"] = "DUPLICATE"
                self.counts["DUPLICATE"] += 1
                return response
            if kind != "event":
                command = (identifier, digest)
        if kind == "create":
            if self.state and not self.state["stopped"]:
                raise DomainError("ACTIVE_SESSION_EXISTS", "Stop the active session explicitly first")
            if body["clock_mode"] == "manual" and not self.settings.demo_mode:
                raise DomainError("DEMO_DISABLED", "Manual sessions require demo mode", 403)
            self.policy = self.configured_policy
            start = (
                datetime.fromisoformat(body["start_time"].replace("Z", "+00:00")).timestamp()
                if body.get("start_time")
                else utc_now()
            )
            state = {
                "schema_version": "1.0",
                "state_version": 1,
                "session_id": "session_" + uuid.uuid4().hex,
                "name": body["name"],
                "clock_mode": body["clock_mode"],
                "start": start,
                "now": start,
                "seed": body["seed"],
                "exercise_area": body.get("exercise_area", "west_basin"),
                "detection_scope": body.get("detection_scope", "harbor"),
                "generation": uuid.uuid4().hex,
                "stopped": False,
                "clock_uncertain": False,
                "tracks": {},
                "sources": {},
                "faults": {},
                "event_count": 0,
                "command_count": 0,
                "ai_calls": 0,
                "policy": self.policy.model_dump(mode="json"),
                "procedures": copy.deepcopy(self.procedures),
                "saved_utc": utc_now(),
            }
            response = self.metadata(state)
        else:
            if not self.state or (session_id and self.state["session_id"] != session_id):
                raise DomainError("SESSION_NOT_ACTIVE", "Requested session is not active", 409)
            if self.state["stopped"]:
                if kind != "stop":
                    raise DomainError("SESSION_STOPPED", "Stopped sessions are read-only")
                if self.state["command_count"] > self.settings.max_session_commands:
                    raise DomainError("SESSION_QUOTA", "Stopped-session command quota reached", 429)
            state = copy.deepcopy(self.state)
            if state["clock_mode"] == "realtime" and not state["stopped"]:
                state["now"] = self.clock.now()
            if state["now"] - state["start"] > self.settings.max_session_seconds and kind not in (
                "stop",
                "tick",
            ):
                raise DomainError(
                    "SESSION_QUOTA", "Session duration exceeded; stop and create a new session", 429
                )
            if state["command_count"] >= self.settings.max_session_commands and kind not in ("stop", "tick"):
                raise DomainError(
                    "SESSION_QUOTA", "Command quota exceeded; stop and create a new session", 429
                )
            response = {"schema_version": "1.0"}
            if kind == "event":
                event, changed, response = await self.apply_event(state, body, digest, role)
            elif kind == "detection_batch":
                observed = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00")).timestamp()
                if observed > state["now"] or state["now"] - observed > 4:
                    raise DomainError(
                        "DETECTION_TIMESTAMP", "Detection batch must match the session clock", 422
                    )
                if observed <= state.get("detection_observed", float("-inf")):
                    raise DomainError("DETECTION_OUT_OF_ORDER", "Detection times must increase", 409)
                try:
                    ingest_detection(state, body, observed)
                except ValueError as error:
                    raise DomainError("DETECTION_INPUT", str(error), 422) from None
                response = state["detection"]
            elif kind == "surface_batch":
                observed = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00")).timestamp()
                if observed > state["now"] + 1 or state["now"] - observed > 30:
                    raise DomainError(
                        "SURFACE_TIMESTAMP", "Surface batch must match the current scenario clock", 422
                    )
                old = state.get("surface_input")
                if (
                    old
                    and observed
                    <= datetime.fromisoformat(old["observed_at"].replace("Z", "+00:00")).timestamp()
                ):
                    raise DomainError(
                        "SURFACE_OUT_OF_ORDER", "Surface batches must advance observation time", 409
                    )
                state["surface_input"] = body
                self.reassess_surface(state)
                response = state["surface"]
            elif kind == "surface_ack":
                surface = state.get("surface", {})
                if surface.get("revision") != body["expected_revision"]:
                    raise DomainError("STALE_REVISION", "Review the current surface assessment before acting")
                row = next(
                    (v for v in surface.get("vessels", []) if v["vessel_id"] == body["vessel_id"]), None
                )
                if not row or not row["reason_codes"]:
                    raise DomainError("SURFACE_ALERT_NOT_FOUND", "No current alert for this vessel", 404)
                row["acknowledgment"] = {
                    "actor": self.settings.operator_label,
                    "time": stamp(state["now"]),
                    "note": body["note"],
                }
                response = {
                    "vessel_id": row["vessel_id"],
                    "acknowledgment": row["acknowledgment"],
                    "revision": surface["revision"],
                }
            elif kind in ("tick", "advance"):
                if kind == "advance":
                    if state["clock_mode"] != "manual" or not self.settings.demo_mode:
                        raise DomainError("CLOCK_MODE", "Only demo manual sessions can advance", 422)
                    state["now"] += body["delta_seconds"]
                if state["now"] - state["start"] > self.settings.max_session_seconds:
                    state["stopped"] = True
                    state["faults"] = {}
                changed = list(state["tracks"])
                for track_id in changed:
                    self.reassess(state, track_id)
                self.reassess_surface(state)
                response = self.metadata(state)
                reassess_detection(state)
            elif kind == "stop":
                state["stopped"] = True
                state["faults"] = {}
                response = self.metadata(state)
            elif kind == "binding":
                track_id = body["track_id"]
                track = self.find_track(state, track_id)
                self.check_revision(track, body["expected_core_revision"])
                mission_id = body["mission_id"]
                if body["operation"] == "confirm" and mission_id not in self.policy.missions:
                    raise DomainError("MISSION_NOT_FOUND", "Mission must exist for confirmation", 422)
                track["binding"] = {
                    "mission_id": mission_id,
                    "operation": body["operation"],
                    "actor": self.settings.operator_label,
                    "time": state["now"],
                    "justification": body["justification"],
                    "registry_version": self.policy.registry_version,
                }
                track.pop("deviation", None)
                self.reassess(state, track_id)
                changed = [track_id]
                response = track["assessment"]
            elif kind in ("ack", "close"):
                track = next(
                    (
                        t
                        for t in state["tracks"].values()
                        if t.get("incident", {}).get("incident_id") == body["incident_id"]
                    ),
                    None,
                )
                if not track:
                    raise DomainError("INCIDENT_NOT_FOUND", "Incident not found", 404)
                self.check_revision(track, body["expected_core_revision"])
                incident = track["incident"]
                if kind == "ack":
                    if incident["state"] == "CLOSED":
                        raise DomainError("INCIDENT_CLOSED", "Incident is closed")
                    incident["state"] = "HUMAN_OWNED"
                    incident["handoff_required"] = False
                    incident["acknowledgment"] = {
                        "actor": self.settings.operator_label,
                        "time": stamp(state["now"]),
                        "note": body["note"],
                    }
                else:
                    a = track["assessment"]
                    if (
                        a["risk"]["current_band"] != "LOW"
                        or a["capability"]["data_quality"] != "FRESH"
                        or incident["handoff_required"]
                    ):
                        raise DomainError(
                            "CLOSE_INELIGIBLE", "Closure requires fresh LOW data and accepted handoff"
                        )
                    incident.update(
                        state="CLOSED",
                        closed_by=self.settings.operator_label,
                        reason=body["reason"],
                        closed_at=stamp(state["now"]),
                    )
                track["assessment"]["core_revision"] += 1
                track["assessment"]["incident"] = copy.deepcopy(incident)
                track["assessment"]["recommendation"]["outstanding_human_handoff"] = incident[
                    "handoff_required"
                ]
                response = copy.deepcopy(incident)
                response["core_revision"] = track["assessment"]["core_revision"]
                changed = [incident["track_id"]]
            elif kind == "fault":
                if not self.settings.demo_mode or not self.settings.demo_faults_enabled:
                    raise DomainError("FAULTS_DISABLED", "Demo fault injection is disabled", 403)
                state["faults"][body["fault"]] = (
                    utc_now() + body["duration_seconds"] if body["enabled"] else 0
                )
                response.update(fault=body["fault"], enabled=body["enabled"], simulated=True)
            elif kind == "enrichment":
                self.find_track(state, body["track_id"])
                response.update(status="OFF" if self.settings.ai_provider == "off" else "REQUESTED")
            elif kind == "ai_start":
                track = self.find_track(state, body["track_id"])
                if track["digest"] != body["digest"] or state["generation"] != body["generation"]:
                    raise DomainError("AI_OBSOLETE", "AI input is no longer relevant")
                if state["ai_calls"] >= self.settings.groq_max_calls_per_session:
                    raise DomainError("AI_SESSION_CAP", "AI request cap reached", 429)
                state["ai_calls"] += 1
                ai_job = {**body, "state": "PENDING"}
                response.update(status="PENDING")
            elif kind == "ai_result":
                track = self.find_track(state, body["track_id"])
                accepted = (
                    state["generation"] == body["generation"]
                    and track["digest"] == body["digest"]
                    and time.monotonic() - body["started_mono"] <= 10
                    and state["now"] - track["last_time"]
                    <= self.policy.sources[track["source_id"]].interval_seconds
                    * self.policy.sources[track["source_id"]].fresh_intervals
                    and track["assessment"]["capability"]["data_quality"] in ("FRESH", "INSUFFICIENT_HISTORY")
                )
                if accepted and body.get("enrichment"):
                    track["assessment"]["ai_enrichment"] = body["enrichment"]
                    changed = [body["track_id"]]
                ai_job = {
                    "job_id": body["job_id"],
                    "state": "ATTACHED" if accepted and body.get("enrichment") else "DISCARDED",
                    "status": body["status"],
                    "track_id": body["track_id"],
                    "usage": body.get("usage"),
                }
                response.update(status=ai_job["state"])
            else:
                raise DomainError("UNKNOWN_COMMAND", "Unsupported command", 422)
        if command:
            state["command_count"] += 1
        state["saved_utc"] = utc_now()
        try:
            await self.storage.commit(state, kind, response, command, event, changed, ai_job)
        except Exception:
            self.storage_available = False
            raise DomainError(
                "STORAGE_UNAVAILABLE", "Transaction failed; no new state published", 503, True
            ) from None
        self.state = state
        if kind == "create":
            self.clock = SessionClock(state["now"])
            for values in self.timings.values():
                values.clear()
        if kind == "event":
            self.counts[response["disposition"]] += 1
        if kind == "surface_batch":
            self.counts["surface_observations"] += len(body["vessels"])
        if kind == "detection_batch":
            self.counts["object_observations"] += len(body["objects"])
        self.counts["committed_commands"] += 1
        if self.ai:
            if state["stopped"]:
                self.ai.cancel_session()
            elif kind == "create":
                self.ai.new_session()
            elif kind == "enrichment":
                # External inference is opt-in per operator request, never per observation.
                self.ai.schedule(state, body["track_id"])
        return response

    async def apply_event(self, state, body, digest, role):
        source_id = body["source_id"]
        source = self.policy.sources.get(source_id)
        if not source or source.role != role:
            raise DomainError("SOURCE_FORBIDDEN", "Source is not owned by this token role", 403)
        kinds = {
            "position": {"observation", "source_heartbeat"},
            "telemetry": {"vehicle_heartbeat", "source_heartbeat"},
            "operator": {"operator_note"},
        }
        if body["kind"] not in kinds[source.kind]:
            raise DomainError("SOURCE_KIND", "Source does not support this event kind", 422)
        if state["event_count"] >= self.settings.max_session_events:
            raise DomainError("SESSION_QUOTA", "Event quota reached; create a new session", 429)
        sequence = await self.storage.one(
            "SELECT id FROM events WHERE session_id=? AND source=? AND boot=? AND sequence=?",
            (state["session_id"], source_id, body["source_boot_id"], body["source_sequence"]),
        )
        if sequence:
            raise DomainError("SEQUENCE_CONFLICT", "Source sequence already belongs to an event")
        observed = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00")).timestamp()
        if observed > state["now"] + 2:
            raise DomainError("FUTURE_EVENT", "Event is more than two scenario seconds in the future", 422)
        payload = body["payload"]
        track_id = payload.get("track_id")
        track = state["tracks"].get(track_id)
        disposition = "APPLIED"
        changed = []
        if body["kind"] == "observation":
            x0, y0, x1, y1 = self.policy.bounds
            if not (x0 <= payload["x_m"] <= x1 and y0 <= payload["y_m"] <= y1):
                raise DomainError("POSITION_BOUNDS", "Position outside simulation bounds", 422)
            if (
                not self.policy.thresholds.sigma_min
                <= payload["position_sigma_m"]
                <= self.policy.thresholds.sigma_max
            ):
                raise DomainError("NOISE_BOUNDS", "Position sigma outside configured bounds", 422)
            if track and track["source_id"] != source_id:
                raise DomainError("CROSS_SOURCE_UNSUPPORTED", "Each track has one position source", 422)
        elif track_id and not track:
            raise DomainError("TRACK_NOT_FOUND", "Track not found", 404)
        if state["now"] - observed > self.policy.thresholds.ingestion_age:
            disposition = "ARCHIVED_STALE"
        elif body["kind"] == "observation" and track and observed <= track["last_time"]:
            disposition = "ARCHIVED_OUT_OF_ORDER"
        elif body["kind"] == "observation":
            if track is None:
                if len(state["tracks"]) >= self.settings.max_tracks:
                    raise DomainError("TRACK_LIMIT", "Maximum tracks reached", 429)
                track = initialize(
                    payload["x_m"],
                    payload["y_m"],
                    payload["position_sigma_m"],
                    observed,
                    self.policy.thresholds.initial_velocity_sigma,
                )
                track.update(source_id=source_id, event_id=body["event_id"])
                state["tracks"][track_id] = track
                accepted = True
            else:
                try:
                    accepted = update(
                        track,
                        payload["x_m"],
                        payload["y_m"],
                        payload["position_sigma_m"],
                        observed,
                        self.policy.thresholds.acceleration_sigma,
                        self.policy.thresholds.innovation_gate,
                    )
                except (ArithmeticError, ValueError):
                    track["filter_failed"] = True
                    accepted = False
            if accepted:
                track["event_id"] = body["event_id"]
                track["claimed_vehicle_id"] = payload.get("claimed_vehicle_id")
            else:
                disposition = "REJECTED_OUTLIER"
            self.reassess(state, track_id, accepted)
            changed = [track_id]
        elif body["kind"] == "vehicle_heartbeat":
            binding = track.get("binding") or {}
            mission = (
                self.policy.missions.get(binding.get("mission_id"))
                if binding.get("operation") == "confirm"
                else None
            )
            if not mission or mission.telemetry_source != source_id:
                raise DomainError(
                    "TELEMETRY_UNBOUND", "Heartbeat requires a bound cooperative mission/source", 403
                )
            if observed <= track.get("heartbeat_time", float("-inf")):
                disposition = "ARCHIVED_OUT_OF_ORDER"
            else:
                track["heartbeat_time"] = observed
                self.reassess(state, track_id)
                changed = [track_id]
        elif body["kind"] == "operator_note":
            track["note"] = {
                "text": payload["text"],
                "actor": self.settings.operator_label,
                "observed_at": body["observed_at"],
                "untrusted": True,
            }
            track["note_revision"] = track.get("note_revision", 0) + 1
            self.reassess(state, track_id)
            changed = [track_id]
        # Transport receipt is separate from observation freshness; archived input does not refresh either.
        if disposition in ("APPLIED", "REJECTED_OUTLIER"):
            previous = state["sources"].get(source_id, {})
            gaps = previous.get("sequence_gaps", 0)
            if previous.get("boot") == body["source_boot_id"]:
                gaps += max(0, body["source_sequence"] - previous.get("sequence", 0) - 1)
            state["sources"][source_id] = {
                "time": max(previous.get("time", observed), observed),
                "boot": body["source_boot_id"],
                "sequence": body["source_sequence"],
                "sequence_gaps": gaps,
            }
            for changed_id in changed:
                current = state["tracks"][changed_id]
                if current["source_id"] == source_id:
                    current["assessment"]["capability"]["source_health"] = (
                        "ONLINE"
                        if (
                            state["now"] - state["sources"][source_id]["time"]
                            <= source.interval_seconds * source.fresh_intervals
                        )
                        else "OVERDUE"
                    )
        state["event_count"] += 1
        assessment = track.get("assessment") if track else None
        response = {
            "schema_version": "1.0",
            "event_id": body["event_id"],
            "disposition": disposition,
            "track_id": track_id,
            "assessment_id": assessment["assessment_id"] if assessment else None,
            "core_revision": assessment["core_revision"] if assessment else None,
            "ai_status": self.ai.status if self.ai else "OFF",
            "synthetic_data": True,
        }
        return (body, digest, stamp(utc_now())), changed, response

    def metadata(self, state):
        return {
            "schema_version": "1.0",
            "session_id": state["session_id"],
            "name": state["name"],
            "clock_mode": state["clock_mode"],
            "start_time": stamp(state["start"]),
            "current_time": stamp(state["now"]),
            "stopped": state["stopped"],
            "seed": state["seed"],
            "exercise_area": state.get("exercise_area", "west_basin"),
            "detection_scope": state.get("detection_scope", "harbor"),
            "synthetic_data": True,
            "clock_uncertain": state["clock_uncertain"],
            "policy_version": state["policy"]["version"],
            "registry_version": state["policy"]["registry_version"],
            "procedure_version": state["policy"]["procedure_version"],
            "mission_windows": {
                key: {
                    "starts_at": stamp(state["start"] + m["start_offset"]),
                    "ends_at": stamp(state["start"] + m["end_offset"]),
                    "registry_starts_at": stamp(state["start"] + m["registry_start_offset"]),
                    "registry_ends_at": stamp(state["start"] + m["registry_end_offset"]),
                }
                for key, m in state["policy"]["missions"].items()
            },
        }

    def health(self):
        alive = self.task is not None and not self.task.done()
        advancing = (not self.processing and self.queue.empty()) or time.monotonic() - self.progress < 15
        return {
            "core": "READY" if self.ready and alive and advancing else "FAILED",
            "storage": "AVAILABLE" if self.storage_available else "UNAVAILABLE",
        }

    def metrics(self):
        import numpy as np

        return {
            "schema_version": "1.0",
            "counters": dict(self.counts),
            "queue_depth": self.queue.qsize(),
            "latencies": {
                key: {
                    "count": len(values),
                    "p50": float(np.percentile(values, 50)),
                    "p95": float(np.percentile(values, 95)),
                    "max": max(values),
                }
                if values
                else {"count": 0}
                for key, values in self.timings.items()
            },
            "ai": self.ai.metrics() if self.ai else {"status": "OFF"},
        }
