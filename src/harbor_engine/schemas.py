from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

ID = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value.astimezone(timezone.utc)


UTC = Annotated[
    datetime,
    AfterValidator(utc),
    PlainSerializer(lambda v: v.isoformat().replace("+00:00", "Z"), return_type=str, when_used="json"),
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Command(Strict):
    command_id: ID


class CreateSession(Command):
    name: str = Field(min_length=1, max_length=80)
    clock_mode: Literal["realtime", "manual"] = "realtime"
    start_time: UTC | None = None
    seed: int = Field(42, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def start(self):
        if (self.clock_mode == "manual") != (self.start_time is not None):
            raise ValueError("Manual sessions require start_time; realtime sessions assign it")
        return self


class Observation(Strict):
    track_id: ID
    coordinate_frame: Literal["harbor_local_m"]
    x_m: float
    y_m: float
    position_sigma_m: float = Field(gt=0)
    claimed_vehicle_id: ID | None = None


class SourceHeartbeat(Strict):
    status: Literal["online"]


class VehicleHeartbeat(Strict):
    track_id: ID


class OperatorNote(Strict):
    track_id: ID
    text: str = Field(min_length=1, max_length=500)


class Event(Strict):
    schema_version: Literal["1.0"] = "1.0"
    event_id: ID
    source_id: ID
    source_boot_id: ID
    source_sequence: int = Field(ge=0, le=2**53 - 1)
    kind: Literal["observation", "source_heartbeat", "vehicle_heartbeat", "operator_note"]
    observed_at: UTC
    payload: Observation | SourceHeartbeat | VehicleHeartbeat | OperatorNote

    @model_validator(mode="after")
    def matching_payload(self):
        expected = {
            "observation": Observation,
            "source_heartbeat": SourceHeartbeat,
            "vehicle_heartbeat": VehicleHeartbeat,
            "operator_note": OperatorNote,
        }
        if not isinstance(self.payload, expected[self.kind]):
            raise ValueError("Payload does not match event kind; only local position measurements supported")
        return self


class Advance(Command):
    delta_seconds: float = Field(gt=0, le=5)


class Binding(Command):
    track_id: ID
    mission_id: ID | None
    operation: Literal["confirm", "revoke"]
    expected_core_revision: int = Field(ge=1)
    justification: str = Field(min_length=1, max_length=300)


class Acknowledge(Command):
    expected_core_revision: int = Field(ge=1)
    note: str = Field("", max_length=300)


class Close(Acknowledge):
    reason: str = Field(min_length=1, max_length=300)


class Fault(Command):
    fault: Literal["AI_UNAVAILABLE", "AI_TIMEOUT", "AI_RATE_LIMIT", "AI_INVALID_RESPONSE"]
    enabled: bool
    duration_seconds: float = Field(60, gt=0, le=300)


class AIResponse(Strict):
    summary: str = Field(min_length=1, max_length=600)
    suggested_next_evidence_action: ID | None
    evidence_ids: list[ID] = Field(max_length=20)
    procedure_ids: list[ID] = Field(max_length=3)
    uncertainties: list[Annotated[str, Field(max_length=160)]] = Field(max_length=3)


class Assessment(Strict):
    schema_version: Literal["1.0"] = "1.0"
    assessment_id: ID
    session_id: ID
    track_id: ID
    core_revision: int
    assessed_at: UTC
    last_observed_at: UTC
    policy_version: str
    registry_version: str
    source: dict[str, Any]
    estimate: dict[str, Any]
    authorization: dict[str, Any]
    risk: dict[str, Any]
    forecast: dict[str, Any]
    recommendation: dict[str, Any]
    evidence: list[dict[str, Any]]
    incident: dict[str, Any] | None
    capability: dict[str, Any]
    ai_enrichment: dict[str, Any] | None
