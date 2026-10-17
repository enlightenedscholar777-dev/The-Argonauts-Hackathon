"""Offline reproducible training; sklearn is only required for this command."""

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix

from harbor_engine.motion import FEATURES, features, probabilities
from harbor_simulation.motion_scenarios import trajectory


def dataset(offset, per_class):
    rows, labels = [], []
    for j, kind in enumerate(("directed", "drift", "stationary", "swimming")):
        for i in range(per_class):
            seed = offset + j * 100000 + i
            path = trajectory(kind, seed, count=16 + i % 17)
            rows.append(features(path))
            labels.append(kind)
    return np.array(rows), np.array(labels)


def main():
    x, y = dataset(1000000, 500)
    test_x, test_y = dataset(9000000, 200)
    forest = RandomForestClassifier(
        n_estimators=48, max_depth=7, min_samples_leaf=5, class_weight="balanced", random_state=42, n_jobs=1
    ).fit(x, y)
    trees = []
    for estimator in forest.estimators_:
        t = estimator.tree_
        values = t.value[:, 0, :]
        values = values / values.sum(axis=1, keepdims=True)
        trees.append(
            {
                "left": t.children_left.tolist(),
                "right": t.children_right.tolist(),
                "feature": t.feature.tolist(),
                "threshold": t.threshold.tolist(),
                "value": values.tolist(),
            }
        )
    model = {
        "version": "motion_forest_v1",
        "features": FEATURES,
        "classes": forest.classes_.tolist(),
        "minimum": x.min(axis=0).tolist(),
        "maximum": x.max(axis=0).tolist(),
        "trees": trees,
    }
    scores = np.array([probabilities(row, model) for row in test_x])
    assert np.allclose(scores, forest.predict_proba(test_x), atol=1e-12)
    predicted = forest.classes_[np.argmax(scores, axis=1)]
    ordered = np.sort(scores, axis=1)
    accepted = (ordered[:, -1] >= 0.65) & (ordered[:, -1] - ordered[:, -2] >= 0.2)
    accepted &= np.all(test_x >= x.min(axis=0) - 0.05, axis=1)
    accepted &= np.all(test_x <= x.max(axis=0) * 1.3 + 0.05, axis=1)
    report = {
        "model": model["version"],
        "training_trajectories": len(y),
        "test_trajectories": len(test_y),
        "split": "Disjoint trajectory seeds; no overlapping train/test windows",
        "data": "Synthetic motion only; not real debris, fish or vessel validation",
        "accuracy": accuracy_score(test_y, predicted),
        "majority_baseline": 0.25,
        "hypothesis_coverage": float(accepted.mean()),
        "accuracy_when_hypothesis": accuracy_score(test_y[accepted], predicted[accepted]),
        "classes": model["classes"],
        "confusion_matrix": confusion_matrix(test_y, predicted).tolist(),
        "feature_importance": dict(zip(FEATURES, forest.feature_importances_.tolist())),
        "export_matches_sklearn": True,
    }
    destination = Path("src/harbor_engine/models/motion_forest.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(model, separators=(",", ":")) + "\n")
    Path("docs/motion-evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
