# Harbor Resilience Simulator — hackathon MVP

This is an **offline-capable, non-operational, fictionalized** Long Beach-inspired harbor incident and continuity simulation. It does not identify, track, or engage submarines. No real military sensor locations, real threats, or defense response logic are included.

## Quick start

Install Python 3.10+ and run in a terminal:

```bash
python -m pip install -r requirements.txt
python generate_data.py
python -m streamlit run app.py
```

The app opens at http://localhost:8501. After installing dependencies it runs locally without internet access.

## Demo script

1. Show baseline observation log and health indicators.
2. Toggle **AI service unavailable**: deterministic assessment continues.
3. Toggle **Disconnect internet**: local console and assessment continue.
4. Toggle **Sensor coverage lost**: output changes to INSUFFICIENT CURRENT EVIDENCE, not ALL CLEAR.
5. Toggle **Policy snapshot unavailable**: human review is required.
6. Toggle **Replay old/duplicate observations**: duplicate IDs are removed.
7. Compare vessel-delay hours for two hypothetical operational scenarios and acknowledge a handoff.

## Dataset manifest

- `synthetic_observations.csv`: 3,000 synthetic observations
- `synthetic_ground_truth.csv`: 3,000 hidden labels for offline evaluation; NOT loaded into assessment
- `synthetic_environment.csv`: 800 environmental records
- `synthetic_surface_vessels.csv`: 1,400 fictional civilian vessel records, NOT AIS
- `synthetic_missions.csv`: 180 fictional missions
- `synthetic_incidents.csv`: 100 fictional incidents

All records are dated Jan 1–Oct 16, 2026 and are marked synthetic. Real NOAA AIS can be added later only as a separate, provenance-tagged civilian context source.

## Architecture and limitations

- Layer 1: CSV ingestion and simple deduplication.
- Layer 2: Independent local deterministic assessment, optional simulated AI explanation, explicit failure states.
- Layer 3: Streamlit operator console, incident acknowledgment, disruption estimates.

This MVP does **not** implement EKF, real sensor fusion, real LLM/RAG, distributed failover, persistent incident approval, or a validated operational safety policy. It is a demonstration of failure modes and separation of concerns, not a production maritime security system.

## Long Beach Harbor dashboard upgrade
The updated `app.py` features a dark maritime dashboard, interactive Long Beach
Harbor basemap, four illustrative public-facing cargo/logistics facility markers,
fictional vessel and incident markers, trend charts, evidence views, and fault
injection controls. Existing `core.py`, `generate_data.py`, and all six synthetic
CSV datasets are preserved.

Run from this folder:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The background map requires internet access to load. The internet toggle is a
simulated fault, not a real network disconnect. Marker positions are approximate
or entirely synthetic and are not suitable for navigation or security operations.
