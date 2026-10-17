# Small-object motion detection

Harbor-maester now ingests a separate small-object observation stream and displays **Detection** below **Activity**. It is a behavior-classification prototype, not a material detector or an operational object-recognition system.

## What the operator sees

- Choose the next exercise location in **Simulation**: West Basin, Inner Harbor, Back Channel, Middle Harbor, East Basin, Southeast Basin, Queensway Bay or Outer Harbor. The metric sonar policy frame, routes, forecasts and uncertainty overlays move together. The atlas identifies the active location and keeps a separate detailed inset.
- Choose **All eight harbor areas** (32 objects) or **Selected area only** (four objects). Surface voyages continue on their scheduled Long Beach routes. Small-object measurements arrive every two scenario seconds and appear as purple trails on both maps. Gray markers mean stale reports.
- Open **Detection**, filter by area and review an object. After at least 16 observations spanning 30 seconds, the engine may show drift-like, directed, swimming-like or near-stationary movement. The selected object is ringed and labeled in the atlas.
- Each result includes measured motion features, synthetic model scores, alternative interpretations, and a suggested verification step. **Material remains Unknown.** A drifting bag, vegetation, debris, an unpowered craft, turbulent water or an animal can have overlapping motion. Registration, hostility, species and human identity cannot be established from these positions.
- The table and object detail show **Possible objects (unconfirmed)**, derived from the predicted movement category. These are explanatory candidate lists, not an additional learned object classifier or a ranked identity prediction. The API exposes them as `possible_objects`; uncertain, collecting, stale and unavailable results return an empty list. The internal `HYPOTHESIS` status appears as **Needs confirmation** in the table.
- Stale reports (>4 seconds), high reported measurement uncertainty (>1 m), insufficient history, feature values outside the training envelope or an ambiguous model result withhold a hypothesis. The feature envelope is a simple guard, not a validated out-of-distribution detector.

Other ports need geographic anchors, mapped waterways, validated routes and local policy. This release supplies eight Long Beach areas; it does not invent a worldwide port map or surveyed restrictions. Moving a demo frame does not establish navigability or sensor coverage.

## Model selection and implementation

We reviewed [Time Series Forest](https://arxiv.org/abs/1302.2277), which builds forests over temporal interval statistics; the [scikit-learn random forest](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html); and [TrashCan](https://arxiv.org/abs/2007.08097), a labeled underwater-image dataset for visual marine-debris detection. TrashCan requires imagery: this repository has no connected camera/imaging-sonar feed or suitable labeled object images. It cannot be applied honestly to position-only reports.

The implementation is a 48-tree random forest trained with scikit-learn 1.6.1, maximum depth seven and minimum five examples per leaf. It is **not** an implementation of the Time Series Forest interval-sampling algorithm or a pretrained marine classifier. Seven interpretable temporal features are used: mean speed, relative speed variation, mean heading change, path straightness, mean acceleration, slow-motion fraction and 90th-percentile speed. Time, position origin, object ID, area ID and simulator class labels are excluded from the feature vector.

Observations are resampled at two-second intervals and smoothed over three points. Up to 32 observations (62 seconds) per object are retained. The forest artifact is checked-in JSON arrays, not executable pickle. Runtime uses existing NumPy and local tree traversal: no scikit-learn, network, GPU, Groq key, startup training or downloaded weights are required. A missing artifact returns `UNAVAILABLE`; other engine assessments continue.

Training is a separate reproducible command:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-motion-training.txt
.\.venv\Scripts\python.exe -m scripts.train_motion
```

The exporter checks numerical agreement with scikit-learn probabilities before writing the artifact. Model scores are **not calibrated real-world probabilities**. Hypotheses require a top score of at least 0.65 and a top-two margin of at least 0.20, plus the input quality and feature-envelope checks.

## Evaluation and limits

[Machine-readable evaluation](motion-evaluation.json) records 2,000 synthetic training trajectories and 800 test trajectories with disjoint seeds. Each trajectory contributes one window; overlapping train/test windows are not used. Four balanced behavioral classes give a 25% majority baseline; the forest reached **96.5% synthetic test accuracy before abstention**. The report includes abstention coverage, accuracy on accepted hypotheses and a confusion matrix. In particular, 24 of 200 directed test trajectories were classified as drift, illustrating the ambiguity of slow steady movement.

Train and test trajectories come from the same hand-designed generator. This is a software demonstration and a learning experiment, **not evidence of real-world debris/fish detection accuracy**, incident detection performance, people made safer or faster responder decisions. Synthetic score thresholds are engineering defaults. No confidence calibration against real sensors has been performed. Drift is not compared to a measured current field. There is no size, shape, texture, acoustic signature, raw-image detection, multi-object association or multi-sensor fusion in this stream. Input IDs are supplied by the simulator.

The simulator includes noisy stationary motion, slowly turning passive drift, steady directed motion, and changing-speed/turning motion. Each small-object observation window ends after 126 seconds; subsequent windows use **new IDs**, not teleported existing tracks. Omitted objects remain visibly stale and retire from the active set after 60 seconds when subsequent batches arrive. This bounds memory and keeps generated tracks near the selected waterway anchors; it is not a persistent harbor object-lifecycle simulation. Small objects are observations, not scheduled vessels, and do not participate in vessel spacing control.

## Engine connection and safety boundary

`POST /v1/sessions/{id}/detections` accepts authenticated sensor/operator batches with UTC time, unique object IDs, a configured area, local positions and positional uncertainty. It rejects extra fields (including generator labels), duplicate object IDs, future/out-of-order times and batches over 64 objects. Retries with the same command ID are idempotent. Histories/results commit to SQLite through the existing coordinator and recover with the session. At most 64 active/retiring objects and 32 observations per object are retained.

The snapshot's `detection` section is the dashboard's inference source. Detection does not alter sonar risk, identity binding, mission permission, incident acknowledgment, or surface encounter calculations. Suggestions ask an operator to verify imagery and obstruction; they do not automatically dispatch responders, clear a channel or control a vessel. A real deployment needs labeled recordings, track association, current/size/imagery evidence, calibration, false-alert/missed-object evaluation and responder validation.

## Running the demo

Validation: all **93 tests** passed (`python -m pytest tests simulator/tests -q`), including a full 900-second bounded object-stream run and persistence/outage/API checks. Headless Edge verified area selection, live hypotheses, maps and navigation; page screenshots were inspected. The new feature also passed Streamlit tests with the explanation provider off, fake and Groq unavailable. No paid Groq inference was used.

Restart both services after updating files:

```powershell
Set-Location D:\The-Argonauts-Hackathon
.\.venv\Scripts\python.exe -m scripts.launch_demo --ai off
```

Open http://127.0.0.1:8501. Motion ML runs with `--ai off`; that flag controls only optional language-model explanations. `--ai fake` still produces clearly labeled mock explanations while the local motion classifier remains real. If an older session was recovered, use **Simulation → Stop active exercise**, choose location/coverage, then start a new exercise. The new stream is not injected into a preserved external session.
