"""Seeded small-object motion. Ground truth stays here, outside sensor payloads."""

import numpy as np

from harbor_engine.geography import AREAS


def trajectory(kind, seed, count=451, dt=2, noise=None):
    rng = np.random.default_rng(seed)
    noise = rng.uniform(0.05, 0.45) if noise is None else noise
    heading = rng.uniform(-np.pi, np.pi)
    speed = {
        "drift": rng.uniform(0.08, 0.6),
        "directed": rng.uniform(0.4, 3),
        "swimming": rng.uniform(0.2, 1.8),
        "stationary": rng.uniform(0, 0.035),
    }[kind]
    positions = [rng.uniform(-10, 10, 2)]
    for i in range(1, count):
        if kind == "swimming":
            heading += rng.normal(0, 0.35) + 0.3 * np.sin(i / 3)
            velocity = speed * max(0.05, 1 + 0.6 * np.sin(i / 2.3))
        elif kind == "drift":
            heading += rng.normal(0, 0.06)
            velocity = speed * max(0.1, 1 + 0.15 * np.sin(i / 8))
        else:
            heading += rng.normal(0, 0.012)
            velocity = speed * (1 + 0.03 * np.sin(i / 5))
        positions.append(positions[-1] + dt * velocity * np.array([np.cos(heading), np.sin(heading)]))
    xy = np.asarray(positions) + rng.normal(0, noise, (count, 2))
    return np.column_stack([np.arange(count) * dt, xy])


class ObjectExercise:
    def __init__(self, seed, area_id, scope="harbor"):
        self.objects = []
        areas = list(AREAS) if scope == "harbor" else [area_id]
        for a, area in enumerate(areas):
            for k, kind in enumerate(("drift", "directed", "swimming", "stationary")):
                # Short-lived 126 s observations are replenished at planned locations,
                # with new IDs. No track jumps or reuses an identity on respawn.
                self.objects.append((a, area, k, kind, seed + a * 100 + k))

    def sample(self, elapsed):
        epoch, index = divmod(int(elapsed) // 2, 64)
        rows = []
        for a, area, k, kind, seed in self.objects:
            path = trajectory(kind, seed + epoch * 10000, count=64, noise=0.2)
            _, x, y = path[index]
            rows.append(
                {
                    "object_id": f"obj_{a:02d}_{k:02d}_{epoch:03d}",
                    "area_id": area,
                    "x_m": float(420 + k * 45 + x),
                    "y_m": float(310 + (k % 2) * 90 + y),
                    "position_sigma_m": 0.2,
                }
            )
        return rows
