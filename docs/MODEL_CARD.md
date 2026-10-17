# Harbor-maester — model and data card

## Model inventory

| System element | Learned? | Training / configuration | Role |
|---|---|---|---|
| Constant-velocity Kalman filter | No | Measurement and acceleration noise in demo policy | Estimate motion and covariance |
| Monte Carlo forecast | No | 32 samples, 30-second horizon, Gaussian acceleration assumption | Conditional zone-entry forecast |
| Surface kinematics | No | Demo CPA, route and delay thresholds | Traffic advisories |
| Motion forest v1 | Yes | Offline synthetic trajectory training | Four-class movement hypothesis |
| Groq explanation | Externally hosted model | Default `openai/gpt-oss-20b`; no project fine-tuning | Optional structured explanation |

Harbor-maester does not implement a trained ensemble of threat-detection neural networks. Its trained ensemble is the random forest. Numerical models and policy compose the broader decision pipeline. Model availability and account permissions for hosted inference depend on Groq.

## Motion forest: input and preprocessing

Each object supplies ordered `(time, x, y)` observations with a reported positional uncertainty. Object identity, area identity, absolute position origin, absolute time and simulator ground-truth labels are excluded from the classifier feature vector.

At least 16 finite observations over 30 seconds are required. Gaps above four seconds invalidate the window; only the most recent 32 observations are retained. Samples are interpolated onto a two-second grid, covering at most 62 seconds, and positions are smoothed with a three-point moving average.

The seven features are mean speed, speed coefficient of variation, mean absolute heading change, displacement/path-length straightness, mean acceleration magnitude, fraction of intervals below 0.08 m/s, and the 90th percentile of speed. See [`motion.py`](../src/harbor_engine/motion.py).

## Training procedure

[`scripts/train_motion.py`](../scripts/train_motion.py) generates 500 trajectories per class for training and 200 per class for testing: 2,000 train and 800 test examples. Training and test use disjoint deterministic seed ranges. Windows vary from 16 to 32 observations. Both datasets use the same hand-designed generator, so this is an in-distribution synthetic evaluation, not external validation.

The estimator is scikit-learn `RandomForestClassifier` with 48 trees, maximum depth 7, minimum leaf size 5, balanced class weights, random state 42 and one CPU job. Each leaf stores class frequencies. Runtime probabilities are the average leaf scores across trees. They are not calibrated probabilities of physical identity.

The exporter writes child indices, split feature indices, thresholds and leaf scores into [`motion_forest.json`](../src/harbor_engine/models/motion_forest.json). It checks exported inference against scikit-learn `predict_proba` with absolute tolerance `1e-12`. No pickle or executable model artifact is loaded. NumPy and ordinary tree traversal provide CPU-only inference.

## Classes and interpretations

| Learned class | Display label | Unconfirmed object examples |
|---|---|---|
| `drift` | Drift-like movement | Floating debris/garbage, vegetation, unpowered object |
| `directed` | Directed movement | Powered craft/device, steadily moving animal |
| `swimming` | Swimming-like movement | Aquatic animal, turbulent debris, manoeuvring object |
| `stationary` | Stationary / near-stationary | Fixed/anchored object, grounded debris, slowly drifting object |

The last column is a hand-authored interpretation mapping. It is not a second model, a ranked identity estimate or material recognition. `material` remains `Unknown`; internal `HYPOTHESIS` appears as **Needs confirmation** in the UI.

## Abstention

A hypothesis requires maximum class score ≥0.65, a top-two score margin ≥0.20, and features within the training-derived envelope. The lower envelope is the training minimum minus 0.05; the upper envelope is 1.3 times the training maximum plus 0.05. This is a simple guard, not a validated out-of-distribution detector.

The classifier withholds candidate objects for insufficient history, stale reports (age >4 s), reported uncertainty >1 m, unsupported features or ambiguous scores. Missing model artifacts return `UNAVAILABLE` while position monitoring continues. These checks prevent a forced object label when the available input does not support one.

## Recorded evaluation

From [`motion-evaluation.json`](motion-evaluation.json):

- Accuracy across 800 test trajectories: **96.5%**; balanced-class majority baseline: **25%**.
- Hypothesis coverage after abstention: **97%**.
- The JSON report contains the confusion matrix, accepted-case accuracy and feature importances.
- Twenty-four of 200 directed trajectories were confused with drift in the recorded evaluation.

These figures measure synthetic behavior recognition only. They do not measure garbage detection, material/species recognition, detection range, real-world false alarms, harbor safety or responder effectiveness. Similar-looking trajectories from debris, animals and powered devices overlap. Camera or imaging-sonar evidence, object size and current estimates would be needed for stronger identification.

## Data provenance and reproducibility

The surface CSV contains synthetic profiles and scheduling states, not geographic AIS positions. The integrated simulator uses the bundled `harbor_simulation/data/synthetic_surface_vessels.csv`; an identical local reference dataset can override it during development. Ground-truth CSVs are excluded from inference and from the deployment bundle. Sonar, surface and small-object exercises use explicit random seeds.

Training dependencies are separate from deployment. For the original pinned training environment, use Python 3.12 and `requirements-motion-training.txt`; scikit-learn 1.6.1 is not installed in the production container:

```powershell
py -3.12 -m venv .venv-training
.\.venv-training\Scripts\python.exe -m pip install -r requirements-motion-training.txt
.\.venv-training\Scripts\python.exe -m pip install -e .
.\.venv-training\Scripts\python.exe -m scripts.train_motion
```

This deliberately regenerates the model and evaluation JSON; review their diff before committing. The bundled artifact is sufficient for ordinary use. The [capability audit](CAPABILITY_AUDIT.md) and [architecture](ARCHITECTURE.md) distinguish implemented behavior from field-validation work.
