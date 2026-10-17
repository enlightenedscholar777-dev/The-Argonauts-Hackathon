"""Advisory motion inference. No material, identity, permission or risk decisions.

The bundled forest is trained offline on synthetic trajectories. Its JSON trees
need only NumPy at inference time; there is no pickle loading or remote service.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

FEATURES = [
    "mean_speed",
    "speed_variation",
    "mean_turn",
    "straightness",
    "mean_acceleration",
    "slow_fraction",
    "speed_p90",
]
LABELS = {
    "drift": "Drift-like movement",
    "directed": "Directed movement",
    "swimming": "Swimming-like movement",
    "stationary": "Stationary / near-stationary",
    "unknown": "Unresolved movement",
}
INTERPRETATIONS = {
    "drift": "Possible floating debris, vegetation or an unpowered object; material unknown.",
    "directed": "Possible propelled object, vessel or animal travelling steadily; identity unknown.",
    "swimming": "Possible animal-like movement, turbulent debris or a manoeuvring object; species unknown.",
    "stationary": "Possible fixed, grounded or slowly drifting object; identity unknown.",
    "unknown": "Insufficient or ambiguous motion evidence; do not infer an object type.",
}
# Explanatory candidates derived from motion, not additional model classes.
POSSIBLE_OBJECTS = {
    "drift": ["Floating debris / garbage", "Vegetation", "Unpowered object"],
    "directed": ["Powered craft / device", "Steadily moving animal"],
    "swimming": ["Aquatic animal", "Turbulent debris", "Manoeuvring object"],
    "stationary": ["Fixed / anchored object", "Grounded debris", "Slowly drifting object"],
    "unknown": [],
}
NEXT_STEPS = {
    "drift": "Review camera or imaging sonar evidence; check size and proximity to navigation routes before arranging inspection.",
    "directed": "Correlate with cooperative reports and imaging; movement alone cannot establish registration or permission.",
    "swimming": "Request visual or imaging sonar confirmation; do not label this as a fish or a person from motion alone.",
    "stationary": "Check whether the object is charted and whether it obstructs a route; request another observation.",
    "unknown": "Collect fresh observations and review camera or imaging sonar evidence.",
}


def features(samples):
    """Resample a 30–62 second window to 2 s; remove positional jitter by smoothing."""
    points = np.asarray(samples, dtype=float)
    if len(points) < 16 or points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("At least 16 finite time/x/y observations are required")
    if np.any(np.diff(points[:, 0]) <= 0) or np.max(np.diff(points[:, 0])) > 4:
        raise ValueError("Observations must be ordered, with gaps no larger than 4 seconds")
    duration = points[-1, 0] - points[0, 0]
    if duration < 30:
        raise ValueError("Collect at least 30 seconds of motion")
    times = np.arange(max(points[0, 0], points[-1, 0] - 62), points[-1, 0] + 0.01, 2)
    xy = np.column_stack([np.interp(times, points[:, 0], points[:, i]) for i in (1, 2)])
    xy = (xy[:-2] + xy[1:-1] + xy[2:]) / 3
    velocity = np.diff(xy, axis=0) / 2
    speed = np.linalg.norm(velocity, axis=1)
    headings = np.unwrap(np.arctan2(velocity[:, 1], velocity[:, 0]))
    length = float(speed.sum() * 2)
    return np.array(
        [
            speed.mean(),
            speed.std() / max(0.05, speed.mean()),
            np.abs(np.diff(headings)).mean(),
            np.linalg.norm(xy[-1] - xy[0]) / max(0.01, length),
            np.linalg.norm(np.diff(velocity, axis=0), axis=1).mean() / 2,
            np.mean(speed < 0.08),
            np.percentile(speed, 90),
        ],
        dtype=float,
    )


@lru_cache(maxsize=1)
def load_model():
    return json.loads((Path(__file__).parent / "models" / "motion_forest.json").read_text())


def probabilities(vector, model):
    scores = np.zeros(len(model["classes"]))
    for tree in model["trees"]:
        node = 0
        while tree["left"][node] != -1:
            node = (
                tree["left"][node]
                if vector[tree["feature"][node]] <= tree["threshold"][node]
                else tree["right"][node]
            )
        scores += tree["value"][node]
    return scores / len(model["trees"])


def classify(samples, age=0, sigma=0.3):
    result = {
        "behavior": "unknown",
        "label": LABELS["unknown"],
        "scores": {},
        "features": {},
        "model": "motion_forest_v1",
        "synthetic_training": True,
        "calibrated": False,
        "material": "Unknown",
        "status": "COLLECTING",
        "reason": "Collect at least 16 observations over 30 seconds.",
    }
    if age > 4:
        result.update(status="STALE", reason="Position reports are stale; request fresh observations.")
    elif sigma > 1:
        result.update(status="UNRESOLVED", reason="Measurement uncertainty is too large for this prototype.")
    else:
        try:
            vector = features(samples)
            model = load_model()
            scores = probabilities(vector, model)
            result["features"] = dict(zip(FEATURES, vector.tolist()))
            result["scores"] = dict(zip(model["classes"], scores.tolist()))
            best = int(np.argmax(scores))
            ordered = sorted(scores)
            outside = np.any(vector < np.array(model["minimum"]) - 0.05) or np.any(
                vector > np.array(model["maximum"]) * 1.3 + 0.05
            )
            if outside or scores[best] < 0.65 or ordered[-1] - ordered[-2] < 0.2:
                result.update(status="UNRESOLVED", reason="Ambiguous or outside synthetic training support.")
            else:
                behavior = model["classes"][best]
                result.update(
                    behavior=behavior,
                    label=LABELS[behavior],
                    status="HYPOTHESIS",
                    reason="Motion pattern matches synthetic training examples; confirmation required.",
                )
        except ValueError as error:
            result["reason"] = str(error)
        except (OSError, KeyError, TypeError):
            result.update(
                status="UNAVAILABLE", reason="Motion model unavailable; position monitoring continues."
            )
    result["interpretation"] = INTERPRETATIONS[result["behavior"]]
    result["possible_objects"] = list(POSSIBLE_OBJECTS[result["behavior"]])
    result["next_step"] = NEXT_STEPS[result["behavior"]]
    return result


def ingest_detection(state, body, observed):
    """Bounded histories, no simulator labels in the inference input contract."""
    histories = state.setdefault("detection_histories", {})
    # Retain omitted tracks for stale display, but expire them after one minute.
    histories = {key: value for key, value in histories.items() if observed - value["samples"][-1][0] <= 60}
    if len(set(histories) | {o["object_id"] for o in body["objects"]}) > 64:
        raise ValueError("At most 64 active detection objects are supported")
    for observation in body["objects"]:
        key = observation["object_id"]
        old = histories.get(key)
        samples = old["samples"] if old else []
        if old and old["area_id"] != observation["area_id"]:
            raise ValueError("An object cannot change its coordinate area")
        if samples and observed - samples[-1][0] > 4:
            samples = []
        samples = (samples + [[observed, observation["x_m"], observation["y_m"]]])[-32:]
        histories[key] = {**observation, "samples": samples}
    state["detection_histories"] = histories
    state["detection_observed"] = observed
    reassess_detection(state)


def reassess_detection(state):
    if "detection_histories" not in state:
        return
    from harbor_engine.geography import AREAS, project_area

    rows = []
    for key, item in state["detection_histories"].items():
        age = max(0, state["now"] - item["samples"][-1][0])
        lon, lat = project_area(item["x_m"], item["y_m"], item["area_id"])
        rows.append(
            {
                "object_id": key,
                "area_id": item["area_id"],
                "area": AREAS[item["area_id"]]["name"],
                "x_m": item["x_m"],
                "y_m": item["y_m"],
                "lon": lon,
                "lat": lat,
                "age_seconds": age,
                "sample_count": len(item["samples"]),
                "trail": [p[1:] for p in item["samples"]],
                **classify(item["samples"], age, item["position_sigma_m"]),
            }
        )
    state["detection"] = {
        "model": "motion_forest_v1",
        "objects": rows,
        "synthetic_data": True,
        "calibrated": False,
    }
