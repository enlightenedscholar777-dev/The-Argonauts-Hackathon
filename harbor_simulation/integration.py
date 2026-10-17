"""Pako sensors -> authenticated HTTP -> durable engine. No local decision logic.

One controller per Streamlit server, shared by browser sessions. The worker owns
scenario time; page refreshes and additional viewers never advance the simulator.
"""

from __future__ import annotations

import copy
import math
import random
import threading
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from harbor_engine.settings import Settings
from harbor_simulation.traffic import HarborTraffic
from simulator.data_models.observation import BearingRange
from simulator.sensors.sensors import (
    AISSensor,
    ContactSpec,
    CooperativeTelemetrySensor,
    EnvironmentalSensor,
    SonarSensor,
)

SCENARIOS = {
    "Harbor approach": "Unknown contact approaches a restricted zone alongside a confirmed research vehicle.",
    "Normal operations": "Confirmed research vehicle follows its permitted route.",
    "Research route deviation": "The confirmed research vehicle turns off its route after 15 seconds.",
    "Unverified underwater report": "An unverified sonar contact approaches the restricted area; verify identity before any clearance.",
    "Conflicting reports": "Inconsistent sonar positions are injected at 10–13s; the engine rejects outliers and reports the conflict.",
    "Sensor outage": "Sonar drops out at 10s and returns at 30s. Telemetry and surface traffic continue.",
    "Port operations disruption": "A quarter of surface traffic holds at 10s while an unknown contact approaches the demo zone.",
    "Busy harbor": "Eight simultaneous engine contacts and dataset-seeded surface traffic exercise the existing CPU pipeline.",
}


class DemoError(RuntimeError):
    pass


class EngineAPI:
    def __init__(self, base_url: str, settings: Settings, http=None):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise DemoError("The local demo requires an HTTP loopback engine URL.")
        self.base_url = base_url
        self.settings = settings
        self.http = http or httpx.Client(
            base_url=base_url, timeout=httpx.Timeout(12, connect=0.5), trust_env=False
        )

    def request(self, method, path, body=None, role="operator"):
        # Same command/event ID and body on every retry, including uncertain commits.
        headers = {
            "Authorization": "Bearer " + getattr(self.settings, f"engine_{role}_token").get_secret_value()
        }
        attempts = 1 if method == "GET" else 3
        for attempt in range(attempts):
            try:
                response = self.http.request(
                    method,
                    path,
                    json=body,
                    headers=headers,
                    timeout=httpx.Timeout(2 if method == "GET" else 12, connect=0.5),
                )
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    raise DemoError(
                        "Engine connection lost. Simulation paused; start the engine and retry."
                    ) from None
            else:
                try:
                    result = response.json()
                except ValueError:
                    raise DemoError("Engine returned an unexpected response. Check the engine URL.") from None
                if response.is_success:
                    return result
                error = result.get("error", {})
                if not error.get("retryable") or attempt == attempts - 1:
                    raise DemoError(
                        f"{error.get('code', response.status_code)}: {error.get('message', 'Request failed')}"
                    )
            time.sleep(0.15 * (attempt + 1))
        raise DemoError("Engine unavailable")

    def command(self, path, **body):
        return self.request("POST", path, {"command_id": "cmd_" + uuid.uuid4().hex, **body})

    def status(self):
        return self.request("GET", "/v1/status", role="viewer")

    def snapshot(self, session_id):
        return self.request("GET", f"/v1/sessions/{session_id}/snapshot", role="viewer")

    def close(self):
        self.http.close()


def position_payload(observation):
    """Convert range+bearing (north=0, east=90) to local metres with conservative sigma.

    A bearing without a measured range cannot establish a Cartesian position.
    Depth is intentionally excluded from this 2D engine's contract.
    """
    measurement = observation.value
    if not isinstance(measurement, BearingRange) or measurement.range_m is None:
        raise DemoError("Only measured range+bearing is supported by the sonar bridge.")
    if measurement.source_x is None or measurement.source_y is None or measurement.range_m < 0:
        raise DemoError("Sonar origin and a nonnegative range are required.")
    radians = math.radians(measurement.bearing_deg)
    # Upper bound on either axis' variance, including radial and tangential error.
    sigma = math.hypot(
        measurement.sigma_range_m or 1,
        measurement.range_m * math.radians(measurement.sigma_bearing_deg or 0),
    )
    return {
        "track_id": observation.track_id,
        "coordinate_frame": "harbor_local_m",
        "x_m": measurement.source_x + measurement.range_m * math.sin(radians),
        "y_m": measurement.source_y + measurement.range_m * math.cos(radians),
        "position_sigma_m": max(0.5, sigma),
        "claimed_vehicle_id": None,
    }


class PakoScenario:
    def __init__(self, name, seed, traffic_count=32):
        if name not in SCENARIOS:
            raise DemoError("Choose a supported scenario.")
        self.name = name
        self.traffic = HarborTraffic(seed, traffic_count, name)
        rng = random.Random(seed)
        self.research = ContactSpec("research_auv_02", x0=60, y0=50, vx=2, vy=0)
        contacts = [self.research]
        if name in {
            "Harbor approach",
            "Unverified underwater report",
            "Port operations disruption",
            "Busy harbor",
        }:
            contacts.insert(0, ContactSpec("unknown_01", x0=100, y0=160, vx=5, vy=0))
        if name == "Busy harbor":
            for i in range(6):
                contacts.append(
                    ContactSpec(
                        f"contact_{i + 1:02d}",
                        x0=80 + (i % 3) * 260,
                        y0=300 + (i // 3) * 280,
                        vx=1.2 + i * 0.12,
                        vy=0,
                    )
                )
        self.sonar = SonarSensor(
            "sim_sonar_01",
            x=0,
            y=0,
            contacts=contacts,
            detection_range_m=1500,
            bearing_sigma_deg=0.15,
            range_sigma_m=0.7,
            rng=rng,
        )
        self.telemetry = CooperativeTelemetrySensor(
            "sim_telemetry_01",
            "research_auv_02",
            x0=60,
            y0=50,
            depth0=-8,
            vx=2,
            vy=0,
            report_interval_s=5,
            rng=rng,
        )
        self.surface = AISSensor(
            "context_ais",
            "123456789",
            "SIM-SUPPORT",
            x0=100,
            y0=340,
            course_deg=90,
            speed_kts=3,
            report_interval_s=1,
            rng=rng,
        )
        self.environment = EnvironmentalSensor(
            "context_environment",
            "SIM-CURRENT",
            x=0,
            y=0,
            report_interval_s=1,
            rng=rng,
        )

    def sample(self, when, elapsed):
        if self.name == "Research route deviation" and elapsed >= 15:
            self.research.y0, self.research.vy = 20, 2
        observations = self.sonar.generate(when)
        telemetry = self.telemetry.generate(when)
        surface = self.surface.generate(when)
        environment = self.environment.generate(when)
        context = {
            "surface": [{"name": "SIM-SUPPORT", "x_m": o.value.x, "y_m": o.value.y} for o in surface],
            "current_mps": environment[0].value["value"] if environment else None,
            "traffic": self.traffic.sample(elapsed),
            "dataset": self.traffic.metadata,
            "elapsed": elapsed,
            "scenario": self.name,
        }
        return observations, telemetry, context


class DemoController:
    """Serialize simulator controls and operator actions; expose copied display state."""

    def __init__(self, api: EngineAPI, background=True, period=1.0):
        self.api = api
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.session_id = None
        self.scenario = None
        self.running = False
        self.elapsed = -1
        self.sensor_loss = False
        self.replay = False
        self.last_error = ""
        self.context = {}
        self.counts = Counter()
        self.receipts = deque(maxlen=40)
        self.trend = deque(maxlen=120)
        self.sequence = Counter()
        self.boot = "boot_" + uuid.uuid4().hex
        self.period = period
        self.thread = None
        if background:
            self.thread = threading.Thread(target=self._worker, daemon=True, name="pako-http-feeder")
            self.thread.start()

    def _worker(self):
        while not self.closed.wait(self.period):
            with self.lock:
                if self.running:
                    try:
                        self._step()
                    except Exception as error:
                        self.running = False
                        self.last_error = (
                            str(error)
                            if isinstance(error, DemoError)
                            else "Simulator paused after an internal error. Restart the exercise."
                        )

    def view(self):
        with self.lock:
            return copy.deepcopy(
                {
                    "session_id": self.session_id,
                    "running": self.running,
                    "elapsed": self.elapsed,
                    "scenario": self.scenario.name if self.scenario else None,
                    "sensor_loss": self.sensor_loss,
                    "replay": self.replay,
                    "error": self.last_error,
                    "context": {**self.context, "running": self.running},
                    "counts": dict(self.counts),
                    "receipts": list(self.receipts),
                    "trend": list(self.trend),
                }
            )

    def start(
        self, scenario="Harbor approach", seed=42, autoplay=True, traffic_count=32, replace_owned=False
    ):
        with self.lock:
            active = self.api.status()["active_session_id"]
            if active and not (replace_owned and active == self.session_id):
                raise DemoError(
                    "An exercise is already active. Stop it explicitly before starting a new one."
                )
            self.running = False
            candidate = PakoScenario(scenario, seed, traffic_count)
            if active:
                self.api.command(f"/v1/sessions/{active}/stop")
            session = self.api.command(
                "/v1/sessions",
                name=f"v1-demo / {scenario}",
                clock_mode="manual",
                start_time=datetime.now(timezone.utc).isoformat(),
                seed=seed,
            )
            self.session_id, self.scenario = session["session_id"], candidate
            self.boot = "boot_" + uuid.uuid4().hex
            self.sequence.clear()
            self.receipts.clear()
            self.counts.clear()
            self.trend.clear()
            self.elapsed = -1
            self.sensor_loss = self.replay = False
            self.last_error = ""
            self._step()
            self.running = autoplay

    def stop(self, session_id):
        with self.lock:
            self.running = False
            self.api.command(f"/v1/sessions/{session_id}/stop")

    def pause(self):
        with self.lock:
            self.running = False

    def resume(self):
        with self.lock:
            if not self.scenario or self.elapsed >= 90:
                raise DemoError("Start a new exercise to run the simulator.")
            metadata = self.api.request("GET", f"/v1/sessions/{self.session_id}")
            if metadata["stopped"]:
                raise DemoError("This exercise has stopped. Start a new exercise.")
            self.last_error = ""
            self.running = True

    def set_fault(self, name, enabled):
        with self.lock:
            if name not in {"sensor_loss", "replay"}:
                raise DemoError("Unknown simulator fault")
            setattr(self, name, enabled)

    def set_speed(self, speed):
        with self.lock:
            if speed not in (1, 2, 4):
                raise DemoError("Playback speed must be 1, 2 or 4.")
            self.period = 1 / speed

    def _event(self, kind, payload, when, source="sim_sonar_01"):
        self.sequence[source] += 1
        return {
            "schema_version": "1.0",
            "event_id": "evt_" + uuid.uuid4().hex,
            "source_id": source,
            "source_boot_id": self.boot,
            "source_sequence": self.sequence[source],
            "kind": kind,
            "observed_at": when,
            "payload": payload,
        }

    def _send(self, event):
        result = self.api.request("POST", f"/v1/sessions/{self.session_id}/events", event, role="sensor")
        self.counts[result["disposition"]] += 1
        self.receipts.append(
            {
                "time": event["observed_at"],
                "source": event["source_id"],
                "track": event["payload"].get("track_id", "—"),
                "event_id": event["event_id"],
                "result": result["disposition"],
            }
        )
        return result

    def step(self):
        with self.lock:
            self.running = False
            try:
                self._step()
                self.last_error = ""
            except DemoError as error:
                self.last_error = str(error)
                raise

    def _step(self):
        if not self.scenario or self.elapsed >= 90:
            self.running = False
            return
        root = f"/v1/sessions/{self.session_id}"
        metadata = self.api.request("GET", root)
        if metadata["stopped"]:
            raise DemoError("Exercise stopped. Start a new exercise.")
        if self.elapsed >= 0:
            metadata = self.api.command(root + "/clock/advance", delta_seconds=1)
        self.elapsed = round(
            (
                datetime.fromisoformat(metadata["current_time"].replace("Z", "+00:00"))
                - datetime.fromisoformat(metadata["start_time"].replace("Z", "+00:00"))
            ).total_seconds()
        )
        when = metadata["current_time"]
        raw, telemetry, self.context = self.scenario.sample(
            datetime.fromisoformat(when.replace("Z", "+00:00")), self.elapsed
        )
        if self.scenario.name == "Sensor outage":
            if self.elapsed == 10:
                self.sensor_loss = True
            elif self.elapsed == 30:
                self.sensor_loss = False
        if not self.sensor_loss:
            for observation in raw:
                payload = position_payload(observation)
                if self.scenario.name == "Conflicting reports" and 10 <= self.elapsed <= 13:
                    payload.update(x_m=990, y_m=690)
                event = self._event("observation", payload, when)
                self._send(event)
                if self.replay:
                    self._send(event)  # Exact same ID, sequence, and timestamp: engine owns deduplication.
        if self.elapsed == 0:
            self.bind("research_auv_02", "research_mission")
        for observation in telemetry:
            self._send(
                self._event("vehicle_heartbeat", {"track_id": observation.track_id}, when, "sim_telemetry_01")
            )
        snapshot = self.api.snapshot(self.session_id)
        for track in snapshot["tracks"]:
            self.trend.append(
                {
                    "second": self.elapsed,
                    "track": track["track_id"],
                    "risk": track["risk"]["current_band"],
                    "age_seconds": track["source"]["observation_age_seconds"],
                }
            )
        if self.elapsed >= 90:
            self.running = False

    def bind(self, track_id, mission_id):
        with self.lock:
            root = f"/v1/sessions/{self.session_id}"
            track = self.api.request("GET", root + f"/tracks/{track_id}")
            return self.api.command(
                root + "/identity-bindings",
                track_id=track_id,
                mission_id=mission_id,
                operation="confirm",
                expected_core_revision=track["core_revision"],
                justification="Operator-confirmed synthetic exercise mission association",
            )

    def acknowledge(self, session_id, track_id):
        with self.lock:
            root = f"/v1/sessions/{session_id}"
            track = self.api.request("GET", root + f"/tracks/{track_id}")
            if not track["incident"]:
                raise DemoError("This track has no incident to acknowledge.")
            return self.api.command(
                root + f"/incidents/{track['incident']['incident_id']}/ack",
                expected_core_revision=track["core_revision"],
                note="Acknowledged from integrated dashboard",
            )

    def ai_fault(self, enabled, session_id=None):
        with self.lock:
            result = self.api.command(
                "/v1/demo/faults", fault="AI_UNAVAILABLE", enabled=enabled, duration_seconds=300
            )
            target = session_id or self.session_id
            if target:
                for track in self.api.snapshot(target)["tracks"]:
                    self.enrich(target, track["track_id"])
            return result

    def enrich(self, session_id, track_id):
        with self.lock:
            return self.api.command(f"/v1/sessions/{session_id}/tracks/{track_id}/enrichment")

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=40)
        self.api.close()
