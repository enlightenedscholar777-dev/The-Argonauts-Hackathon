import copy
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer

from .clock import stamp, utc_now
from .errors import DomainError
from .schemas import (
    ID,
    Acknowledge,
    Advance,
    Assessment,
    Binding,
    Close,
    Command,
    CreateSession,
    Event,
    Fault,
)


def error_response(error, request_id=None):
    from fastapi.responses import JSONResponse

    headers = {"Retry-After": "1"} if error.retryable else {}
    return JSONResponse(
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": request_id or "request_" + uuid.uuid4().hex,
                "retryable": error.retryable,
                **error.details,
            }
        },
        status_code=error.status,
        headers=headers,
    )


bearer_auth = HTTPBearer(auto_error=False)


def identify(request: Request, credentials=Depends(bearer_auth)):
    supplied = credentials.credentials if credentials else ""
    settings = request.app.state.core.settings
    for role in ("sensor", "operator", "viewer"):
        if secrets.compare_digest(
            supplied.encode(), getattr(settings, f"engine_{role}_token").get_secret_value().encode()
        ):
            return role
    raise DomainError("UNAUTHENTICATED", "Valid bearer token required", 401)


def require(*roles):
    def dependency(role=Depends(identify)):
        if role not in roles:
            raise DomainError("FORBIDDEN", "Token role cannot perform this operation", 403)
        return role

    return dependency


read_access = require("operator", "viewer")
operator_access = require("operator")
sensor_or_operator = require("sensor", "operator")


async def get_session(request, session_id):
    core = request.app.state.core
    state = (
        core.state
        if core.state and core.state["session_id"] == session_id
        else await core.storage.session(session_id)
    )
    if state is None:
        raise DomainError("SESSION_NOT_FOUND", "Session not found", 404)
    return state


def source_status(state):
    result = {}
    for source_id, config in state["policy"]["sources"].items():
        source = state["sources"].get(source_id)
        age = max(0, state["now"] - source["time"]) if source else None
        result[source_id] = {
            "health": "UNKNOWN"
            if age is None
            else "ONLINE"
            if age <= config["interval_seconds"] * config["fresh_intervals"]
            else "OVERDUE",
            "last_event_at": stamp(source["time"]) if source else None,
            "age_seconds": age,
            "source_boot_id": source["boot"] if source else None,
            "last_sequence": source["sequence"] if source else None,
            "sequence_gaps": source["sequence_gaps"] if source else 0,
        }
    return result


def snapshot(core, state):
    result = {
        "schema_version": "1.0",
        "synthetic_data": True,
        "policy_assumptions": state["policy"]["description"],
        "session": core.metadata(state),
        "health": core.health(),
        "ai": core.ai.metrics(),
        "sources": source_status(state),
        "zones": state["policy"]["zones"],
        "routes": state["policy"]["routes"],
        "bounds": state["policy"]["bounds"],
        "tracks": [],
        "open_incidents": [],
        "simulated_faults": [key for key, until in state["faults"].items() if until > utc_now()],
    }
    for track_id, track in state["tracks"].items():
        assessment = copy.deepcopy(track["assessment"])
        assessment["capability"]["storage_health"] = result["health"]["storage"]
        assessment["capability"]["core_health"] = result["health"]["core"]
        assessment["capability"]["ai_status"] = core.ai.status
        source_info = state["sources"].get(track["source_id"])
        source_policy = state["policy"]["sources"][track["source_id"]]
        assessment["capability"]["source_health"] = (
            "UNKNOWN"
            if source_info is None
            else (
                "ONLINE"
                if state["now"] - source_info["time"]
                <= source_policy["interval_seconds"] * source_policy["fresh_intervals"]
                else "OVERDUE"
            )
        )
        enrichment = assessment.get("ai_enrichment")
        if enrichment:
            basis = datetime.fromisoformat(enrichment["basis_assessed_at"].replace("Z", "+00:00")).timestamp()
            enrichment["basis_age_seconds"] = max(0, state["now"] - basis)
        result["tracks"].append(assessment)
        incident = track.get("incident")
        if incident and incident["state"] != "CLOSED":
            result["open_incidents"].append(copy.deepcopy(incident))
    return result


router = APIRouter()


@router.get("/health/live")
async def live(request: Request):
    health = request.app.state.core.health()
    if health["core"] != "READY":
        raise DomainError("CORE_UNAVAILABLE", "Coordinator is not progressing", 503, True)
    return {"live": True}


@router.get("/health/ready")
async def ready(request: Request):
    health = request.app.state.core.health()
    if health != {"core": "READY", "storage": "AVAILABLE"}:
        raise DomainError("NOT_READY", "Critical capability unavailable", 503, True)
    return {"ready": True}


@router.get("/v1/status", dependencies=[Depends(read_access)])
async def status(request: Request):
    core = request.app.state.core
    return {
        "schema_version": "1.0",
        "synthetic_data": True,
        **core.health(),
        "ai": core.ai.metrics(),
        "active_session_id": core.state["session_id"] if core.state and not core.state["stopped"] else None,
        "limits": {
            "tracks": core.settings.max_tracks,
            "body_bytes": 65536,
            "queue": core.settings.core_queue_capacity,
            "session_events": core.settings.max_session_events,
            "session_commands": core.settings.max_session_commands,
            "session_seconds": core.settings.max_session_seconds,
            "workers": 1,
        },
        "sources": source_status(core.state) if core.state else {},
        "policy_assumptions": core.policy.description,
    }


@router.post("/v1/sessions", dependencies=[Depends(operator_access)])
async def create(request: Request, body: CreateSession):
    return await request.app.state.core.submit("create", body=body.model_dump(mode="json"))


@router.get("/v1/sessions/{session_id}", dependencies=[Depends(read_access)])
async def session(request: Request, session_id: ID):
    return request.app.state.core.metadata(await get_session(request, session_id))


@router.post("/v1/sessions/{session_id}/stop", dependencies=[Depends(operator_access)])
async def stop(request: Request, session_id: ID, body: Command):
    return await request.app.state.core.submit("stop", session_id, body.model_dump(mode="json"))


@router.post("/v1/sessions/{session_id}/events")
async def event(request: Request, session_id: ID, body: Event, role=Depends(sensor_or_operator)):
    if (body.kind == "operator_note") != (role == "operator"):
        raise DomainError(
            "FORBIDDEN", "Use sensor credentials for sensors and operator credentials for notes", 403
        )
    return await request.app.state.core.submit("event", session_id, body.model_dump(mode="json"), role)


@router.get(
    "/v1/sessions/{session_id}/events/{event_id}",
    dependencies=[Depends(require("sensor", "operator", "viewer"))],
)
async def event_result(request: Request, session_id: ID, event_id: ID):
    result = await request.app.state.core.storage.duplicate("event", session_id, event_id)
    if not result:
        raise DomainError("EVENT_NOT_FOUND", "No committed event with that ID", 404)
    return result[1]


@router.get("/v1/sessions/{session_id}/snapshot", dependencies=[Depends(read_access)])
async def get_snapshot(request: Request, session_id: ID):
    return snapshot(request.app.state.core, await get_session(request, session_id))


@router.get(
    "/v1/sessions/{session_id}/tracks/{track_id}",
    dependencies=[Depends(read_access)],
    response_model=Assessment,
)
async def get_track(request: Request, session_id: ID, track_id: ID):
    state = await get_session(request, session_id)
    request.app.state.core.find_track(state, track_id)
    return next(a for a in snapshot(request.app.state.core, state)["tracks"] if a["track_id"] == track_id)


@router.get("/v1/sessions/{session_id}/history", dependencies=[Depends(read_access)])
async def history(
    request: Request,
    session_id: ID,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    await get_session(request, session_id)
    items = await request.app.state.core.storage.history(session_id, after, limit)
    return {"schema_version": "1.0", "items": items, "next_cursor": items[-1]["cursor"] if items else after}


@router.post("/v1/sessions/{session_id}/clock/advance", dependencies=[Depends(operator_access)])
async def advance(request: Request, session_id: ID, body: Advance):
    return await request.app.state.core.submit("advance", session_id, body.model_dump(mode="json"))


@router.post("/v1/sessions/{session_id}/identity-bindings", dependencies=[Depends(operator_access)])
async def binding(request: Request, session_id: ID, body: Binding):
    return await request.app.state.core.submit("binding", session_id, body.model_dump(mode="json"))


@router.post("/v1/sessions/{session_id}/incidents/{incident_id}/ack", dependencies=[Depends(operator_access)])
async def ack(request: Request, session_id: ID, incident_id: ID, body: Acknowledge):
    return await request.app.state.core.submit(
        "ack", session_id, {**body.model_dump(mode="json"), "incident_id": incident_id}
    )


@router.post(
    "/v1/sessions/{session_id}/incidents/{incident_id}/close", dependencies=[Depends(operator_access)]
)
async def close_incident(request: Request, session_id: ID, incident_id: ID, body: Close):
    return await request.app.state.core.submit(
        "close", session_id, {**body.model_dump(mode="json"), "incident_id": incident_id}
    )


@router.post(
    "/v1/sessions/{session_id}/tracks/{track_id}/enrichment", dependencies=[Depends(operator_access)]
)
async def enrichment(request: Request, session_id: ID, track_id: ID, body: Command):
    return await request.app.state.core.submit(
        "enrichment", session_id, {**body.model_dump(mode="json"), "track_id": track_id}
    )


@router.post("/v1/demo/faults", dependencies=[Depends(operator_access)])
async def fault(request: Request, body: Fault):
    return await request.app.state.core.submit("fault", body=body.model_dump(mode="json"))


@router.get("/v1/metrics", dependencies=[Depends(read_access)])
async def metrics(request: Request):
    return request.app.state.core.metrics()


@router.get("/", include_in_schema=False)
async def page():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
