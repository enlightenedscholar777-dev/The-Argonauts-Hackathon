import hashlib

import numpy as np
from shapely.geometry import LineString

from .clock import stamp
from .geometry import first_entry
from .tracking import matrices, project


def forecast(track, now, seed, track_id, zones, settings, thresholds):
    age = max(0, now - track["last_time"])
    s, p = project(track["state"], track["covariance"], age, thresholds.acceleration_sigma)
    radius = float(2 * np.sqrt(max(0, np.linalg.eigvalsh(p[:2, :2]).max())))
    result = {
        "horizon_seconds": settings.forecast_horizon_seconds,
        "assumption": "Synthetic constant velocity with Gaussian acceleration; uncalibrated",
        "calibrated": False,
        "computed_at": stamp(now),
        "points": [],
        "zone_entries": {},
        "current_uncertainty_radius_m": radius,
        "uncertainty_definition": "2 standard deviation major-axis radius; not 95% joint coverage",
        "sampled_zone_hit_fraction": None,
    }
    if age > thresholds.max_forecast_age or not track["velocity_established"]:
        return s, p, result
    times = list(range(0, settings.forecast_horizon_seconds + 1, settings.forecast_step_seconds))
    if times[-1] != settings.forecast_horizon_seconds:
        times.append(settings.forecast_horizon_seconds)
    path = []
    mean, cov, previous_time = s.copy(), p.copy(), 0
    for t in times:
        mean, cov = project(mean, cov, t - previous_time, thresholds.acceleration_sigma)
        previous_time = t
        path.append(mean[:2].tolist())
        result["points"].append(
            {
                "seconds_ahead": t,
                "x_m": float(mean[0]),
                "y_m": float(mean[1]),
                "position_covariance": cov[:2, :2].tolist(),
                "uncertainty_radius_m": float(2 * np.sqrt(np.linalg.eigvalsh(cov[:2, :2]).max())),
            }
        )
    result["zone_entries"] = {z: first_entry(path, times, poly) for z, poly in zones.items()}
    digest = hashlib.sha256(f"{seed}:{track_id}:{track['last_time']}:{now}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    ensemble = rng.multivariate_normal(s, p, settings.forecast_samples)
    paths = [ensemble[:, :2].copy()]
    for before, after in zip(times, times[1:]):
        f, q = matrices(after - before, thresholds.acceleration_sigma)
        ensemble = ensemble @ f.T + rng.multivariate_normal(np.zeros(4), q, len(ensemble))
        paths.append(ensemble[:, :2].copy())
    lines = [LineString(v) for v in np.stack(paths, axis=1)]
    result["sampled_zone_hit_fraction"] = {
        z: sum(poly.intersects(line) for line in lines) / len(lines) for z, poly in zones.items()
    }
    return s, p, result
