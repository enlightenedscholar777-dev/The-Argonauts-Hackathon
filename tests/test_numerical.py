import copy

import numpy as np
from conftest import configuration
from shapely.geometry import Point, Polygon

from harbor_engine.forecast import forecast
from harbor_engine.geometry import first_entry, route_distance
from harbor_engine.policy import load_policy
from harbor_engine.tracking import initialize, project, update


def test_constant_velocity_and_joseph_covariance():
    track = initialize(20, 30, 1, 0, 10)
    rng = np.random.default_rng(42)
    for t in range(1, 60):
        x, y = np.array([20 + 2 * t, 30 + t]) + rng.normal(0, 0.1, 2)
        assert update(track, x, y, 1, t, 0.25, 16)
        p = np.array(track["covariance"])
        assert np.isfinite(p).all()
        assert np.allclose(p, p.T, atol=1e-10)
        assert np.linalg.eigvalsh(p).min() > -1e-10
    assert np.allclose(track["state"][2:], [2, 1], atol=0.15)
    assert track["velocity_established"]


def test_geometry_continuous_crossing_and_boundary():
    poly = Polygon([(5, -1), (5.1, -1), (5.1, 1), (5, 1)])
    assert first_entry([[0, 0], [10, 0]], [0, 2], poly) == 1
    assert poly.covers(Point(5, 0))
    assert first_entry([[5, 0], [6, 0]], [0, 2], poly) == 0
    assert route_distance([4, 3], [[0, 0], [10, 0]]) == 3


def test_projection_is_copy_and_outlier_preserves_freshness():
    track = initialize(10, 10, 1, 0, 10)
    for t in range(1, 4):
        update(track, 10 + t, 10, 1, t, 0.25, 16)
    before = copy.deepcopy(track)
    one, _ = project(track["state"], track["covariance"], 5, 0.25)
    two, _ = project(track["state"], track["covariance"], 5, 0.25)
    assert np.array_equal(one, two)
    assert before == track
    assert not update(track, 900, 600, 1, 4, 0.25, 16)
    assert track["last_time"] == before["last_time"]
    assert track["state"] == before["state"]
    assert track["covariance"] == before["covariance"]


def test_seeded_forecast_and_insufficient_history(tmp_path):
    config = configuration(tmp_path)
    policy = load_policy(config.policy_path)
    zones = {z: Polygon(v.vertices) for z, v in policy.zones.items()}
    track = initialize(200, 160, 2, 0, 10)
    assert forecast(track, 0, 42, "t", zones, config, policy.thresholds)[2]["zone_entries"] == {}
    for t in range(1, 4):
        update(track, 200 + 5 * t, 160, 2, t, 0.25, 16)
    a = forecast(track, 3, 42, "t", zones, config, policy.thresholds)[2]
    b = forecast(track, 3, 42, "t", zones, config, policy.thresholds)[2]
    assert a == b
    # Forecast covariance uses the same independent acceleration steps as the ensemble.
    mean, covariance = project(track["state"], track["covariance"], 0, 0.25)
    for _ in range(2):
        mean, covariance = project(mean, covariance, config.forecast_step_seconds, 0.25)
    assert np.allclose(a["points"][2]["position_covariance"], covariance[:2, :2])
    assert a["zone_entries"]["restricted_01"] < 30
    assert 0 <= a["sampled_zone_hit_fraction"]["restricted_01"] <= 1
    assert not a["calibrated"]
    assert forecast(track, 25, 42, "t", zones, config, policy.thresholds)[2]["points"] == []
