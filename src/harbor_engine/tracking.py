"""Measurement-anchored constant velocity Kalman filter; demo noise model."""

import numpy as np


def matrices(dt, acceleration):
    f = np.eye(4)
    f[0, 2] = f[1, 3] = dt
    g = np.array([[dt * dt / 2, 0], [0, dt * dt / 2], [dt, 0], [0, dt]])
    return f, acceleration**2 * g @ g.T


def project(state, covariance, dt, acceleration):
    f, q = matrices(max(0, dt), acceleration)
    return f @ np.asarray(state), f @ np.asarray(covariance) @ f.T + q


def initialize(x, y, sigma, now, velocity_sigma):
    return {
        "state": [x, y, 0.0, 0.0],
        "covariance": np.diag([sigma**2, sigma**2, velocity_sigma**2, velocity_sigma**2]).tolist(),
        "last_time": now,
        "first_time": now,
        "accepted_count": 1,
        "outliers": 0,
        "consecutive_outliers": 0,
        "velocity_established": False,
    }


def update(track, x, y, sigma, now, acceleration, gate):
    s, p = project(track["state"], track["covariance"], now - track["last_time"], acceleration)
    h = np.eye(2, 4)
    r = np.eye(2) * sigma**2
    innovation = np.array([x, y]) - h @ s
    innovation_cov = h @ p @ h.T + r
    distance = float(innovation @ np.linalg.solve(innovation_cov, innovation))
    if distance > gate:
        track["outliers"] += 1
        track["consecutive_outliers"] += 1
        return False
    k = np.linalg.solve(innovation_cov, h @ p).T
    s = s + k @ innovation
    residual = np.eye(4) - k @ h
    p = residual @ p @ residual.T + k @ r @ k.T
    p = (p + p.T) / 2
    if not np.isfinite(s).all() or not np.isfinite(p).all() or np.linalg.eigvalsh(p).min() < -1e-8:
        raise ArithmeticError("Unusable filter covariance")
    track.update(
        state=s.tolist(),
        covariance=p.tolist(),
        last_time=now,
        accepted_count=track["accepted_count"] + 1,
        consecutive_outliers=0,
    )
    track["velocity_established"] = track["accepted_count"] >= 3 and now - track["first_time"] >= 2
    return True
