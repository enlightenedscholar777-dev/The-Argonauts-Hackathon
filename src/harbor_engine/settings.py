from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    host: str = "127.0.0.1"
    port: int = 8000
    demo_mode: bool = True
    demo_faults_enabled: bool = False
    database_path: str = "runtime/harbor_demo.sqlite3"
    policy_path: str = "config/demo_policy.yaml"
    procedures_path: str = "data/procedures.json"
    engine_sensor_token: SecretStr = SecretStr("")
    engine_operator_token: SecretStr = SecretStr("")
    engine_viewer_token: SecretStr = SecretStr("")
    operator_label: str = "demo_watch_officer"
    ai_provider: Literal["off", "fake", "groq"] = "off"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = Field(6, gt=0, le=30)
    groq_max_completion_tokens: int = Field(1024, ge=64, le=2048)
    groq_max_calls_per_minute: int = Field(3, ge=1, le=60)
    groq_soft_token_budget_per_minute: int = Field(6000, ge=1000, le=100000)
    groq_max_calls_per_session: int = Field(20, ge=1, le=1000)
    ai_min_track_interval_seconds: float = Field(30, ge=0, le=3600)
    ai_queue_capacity: int = Field(8, ge=1, le=8)
    core_queue_capacity: int = Field(256, ge=1, le=256)
    max_tracks: int = Field(20, ge=1, le=20)
    max_session_events: int = Field(100000, ge=100, le=1000000)
    max_session_commands: int = Field(100000, ge=100, le=1000000)
    max_session_seconds: int = Field(7200, ge=60, le=86400)
    command_timeout_seconds: float = Field(10, gt=0, le=60)
    forecast_horizon_seconds: int = Field(30, ge=2, le=30)
    forecast_step_seconds: int = Field(2, ge=1, le=5)
    forecast_samples: int = Field(32, ge=1, le=32)
    allowed_origins: str = "http://127.0.0.1:8000,http://localhost:8000"

    @model_validator(mode="after")
    def tokens(self):
        values = [
            getattr(self, f"engine_{role}_token").get_secret_value()
            for role in ("sensor", "operator", "viewer")
        ]
        if any(len(v) < 24 for v in values) or len(set(values)) != 3:
            raise ValueError("Configure three distinct tokens (24+ characters): python -m scripts.init_env")
        return self
