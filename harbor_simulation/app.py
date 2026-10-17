"""Streamlit console for the live Pako -> decision engine integration."""

import atexit
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from harbor_engine.settings import Settings
from harbor_simulation.integration import SCENARIOS, DemoController, DemoError, EngineAPI
from harbor_simulation.views import TERMINALS, empty_map, geographic_map, harbor_layout, local_map

st.set_page_config(page_title="Harbor Watch | Live demo", page_icon="⚓", layout="wide")
st.markdown(
    """<style>
.stApp{background:#071422;color:#e9f3fc}.block-container{padding-top:1.4rem;max-width:1600px}
[data-testid="stSidebar"]{background:#0c2034;border-right:1px solid #204263}
h1,h2,h3{color:#eaf6ff!important}h1{letter-spacing:-.035em}
[data-testid="stMetric"]{background:#10263b;border:1px solid #21445f;border-radius:12px;padding:12px}
[data-testid="stMetricValue"]{font-size:1.45rem}.stButton button{border-radius:9px}
</style>""",
    unsafe_allow_html=True,
)


@st.cache_resource
def controller(base_url):
    instance = DemoController(EngineAPI(base_url, Settings()))
    atexit.register(instance.close)
    return instance


try:
    demo = controller(os.environ.get("HARBOR_ENGINE_URL", "http://127.0.0.1:8000"))
except (ValueError, DemoError):
    st.error("Local configuration is incomplete. Run python -m scripts.init_env, then restart the demo.")
    st.stop()

st.title("⚓ Harbor watch")
st.caption("ARGONAUTS / LIVE HARBOR RESILIENCE DEMO · SYNTHETIC DATA · HUMAN DECISION SUPPORT")


def perform(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
        st.session_state.pop("action_error", None)
    except DemoError as error:
        st.session_state["action_error"] = str(error)
    st.rerun()


requested_scenario = st.session_state.pop("requested_scenario", None)
if requested_scenario:
    st.session_state["scenario"] = requested_scenario

with st.sidebar:
    st.title("Exercise controls")
    scenario = st.selectbox("Scenario", list(SCENARIOS), key="scenario")
    st.caption(SCENARIOS[scenario])
    seed = st.number_input("Noise seed", min_value=0, max_value=2**32 - 1, value=42)
    autoplay = st.checkbox("Run automatically", value=True, key="autoplay")
    traffic_count = st.slider("Surface traffic for next exercise", 12, 60, 32, 4, key="traffic_count")
    st.select_slider(
        "Playback speed",
        options=[1, 2, 4],
        value=int(1 / demo.period),
        format_func=lambda n: f"{n}×",
        key="playback_speed",
        on_change=lambda: demo.set_speed(st.session_state["playback_speed"]),
    )
    if st.button("Start exercise", type="primary", key="start"):
        perform(demo.start, scenario, int(seed), autoplay, traffic_count)
    st.caption(
        "Starting explicitly confirms the synthetic research mission. Other contacts remain unverified."
    )
    a, b, c = st.columns(3)
    if a.button("Pause", key="pause"):
        perform(demo.pause)
    if b.button("Resume", key="resume"):
        perform(demo.resume)
    if c.button("Step +1s", key="step"):
        perform(demo.step)
    st.caption(
        "Pause freezes all movement and evidence age. Playback speed advances the same scenario clock for traffic and engine contacts; each exercise pauses at 90s."
    )
    st.divider()
    st.subheader("Map")
    online_map = st.checkbox("Show online Long Beach basemap", value=True, key="online_map")
    focus = st.selectbox(
        "Focus area", ["Whole harbor", "Exercise area"] + [t["label"] for t in TERMINALS], key="map_focus"
    )
    with st.expander("Map layers", expanded=False):
        show_labels = st.checkbox("Area and waterway labels", value=True, key="map_labels")
        show_context = st.checkbox("Fictional vessel context", value=True, key="map_context")
        show_forecasts = st.checkbox("Conditional forecasts", value=True, key="map_forecasts")
        show_uncertainty = st.checkbox("Position uncertainty rings", value=True, key="map_uncertainty")
    st.caption(
        "The Harbor atlas and Exercise detail work offline. The Geographic map adds pan, zoom and hover details."
    )
    st.info(
        "The engine runs on your CPU. Groq is optional; provider failures never replace the deterministic assessment."
    )


with st.expander("Scenario presets · click to run", expanded=True):
    st.caption(
        "Each button starts its scenario and archives your current exercise. An externally started session must be stopped explicitly."
    )
    presets = st.columns(4)
    for index, name in enumerate(SCENARIOS):
        if presets[index % 4].button(name, key="preset_" + name, help=SCENARIOS[name], width="stretch"):
            st.session_state["requested_scenario"] = name
            perform(demo.start, name, int(seed), autoplay, traffic_count, replace_owned=True)


def render_maps(snapshot=None, context=None):
    """Keep harbor context visible before startup and during engine outages."""
    harbor, geography, detail = st.tabs(["Harbor atlas", "Geographic map", "Exercise detail"])
    with harbor:
        st.subheader("Long Beach Harbor | Area atlas")
        # Streamlit's image path retains SVG; st.html strips it with its sanitizer.
        st.image(
            harbor_layout(
                snapshot,
                context,
                area_focus=focus,
                show_context=show_context,
                show_labels=show_labels,
                show_forecasts=show_forecasts,
            ),
            width="stretch",
            alt="Detailed Long Beach harbor schematic: 11 pier areas, waterways, directory and live exercise inset",
        )
        st.caption(
            "Surface vessels move on the exercise clock; trails show recent motion. Amber vessels are holding. Live engine assessments update in the inset and right panel. The atlas is schematic, not to scale."
        )
    with geography:
        st.subheader("Long Beach Harbor | Geographic context")
        if online_map:
            st.pydeck_chart(
                geographic_map(
                    snapshot,
                    context,
                    focus=focus == "Exercise area",
                    area_focus=focus,
                    show_context=show_context,
                    show_labels=show_labels,
                    show_forecasts=show_forecasts,
                    show_uncertainty=show_uncertainty,
                ),
                height=620,
                key="harbor_overview_" + focus,
            )
            st.caption(
                "Drag to pan / scroll to zoom. If map tiles do not load, turn off the online basemap in the sidebar."
            )
        else:
            st.info(
                "Online basemap disabled. Use the Harbor atlas and Exercise detail tabs, or enable the basemap in the sidebar."
            )
        st.caption(
            "Amber: cargo · Teal: rail / logistics · Lavender: port facilities · Green: waterfront · Blue: fictional vessels · Cyan outline: synthetic exercise area"
        )
    with detail:
        st.subheader("Live exercise detail")
        st.image(
            local_map(
                snapshot or empty_map(),
                context if show_context else None,
                show_forecasts=show_forecasts,
                show_uncertainty=show_uncertainty,
            ),
            width="stretch",
            alt="Live engine estimates, zones and conditional forecasts in local metres",
        )
        st.caption(
            "Local metres · Dots: engine estimates · Dashed lines: conditional forecasts · Red/amber: demo policy zones"
        )
        if not snapshot or not snapshot["tracks"]:
            st.caption("No live observations yet. Start an exercise to see tracks and forecasts here.")
    with st.expander("Area directory & map reference"):
        st.dataframe(pd.DataFrame(TERMINALS)[["label", "name", "kind"]], hide_index=True, width="stretch")
        st.caption(
            "Public pier and waterway names follow the [City of Long Beach harbor map (Map 10)]"
            "(https://www.longbeach.gov/globalassets/lbcd/media-library/documents/planning/advance/general-plan/mobility-element/320615_lbds_mobility_element_web). "
            "Facility anchors and schematic shapes are approximate. Internal assets are illustrative; no current berth assignments are claimed. "
            "The exercise uses synthetic local policy, not real port restrictions."
        )
    if context and context.get("traffic"):
        with st.expander("Surface traffic & dataset"):
            source = context["dataset"]
            st.caption(
                f"{source['source']} · {source['records']} records / {source['identities']} vessel identities. Generated paths use CSV profiles, not recorded AIS coordinates. Surface vessels are context; engine contacts are assessed separately."
            )
            st.dataframe(
                pd.DataFrame(context["traffic"])[
                    ["vessel_id", "vessel_type", "sector", "source_status", "status", "speed_mps"]
                ],
                hide_index=True,
                width="stretch",
            )


@st.fragment(run_every=1.0)
def live_panel():
    state = demo.view()
    try:
        status = demo.api.status()
        session_id = status["active_session_id"] or state["session_id"]
        snapshot = demo.api.snapshot(session_id) if session_id else None
    except DemoError as error:
        st.error(str(error))
        st.warning("Live data is unavailable. No current assessment is displayed.")
        render_maps()
        return
    if st.session_state.get("action_error"):
        st.error(st.session_state["action_error"])
    if state["error"]:
        st.error(state["error"])
    ai = status["ai"]
    tracks = snapshot["tracks"] if snapshot else []
    metrics = st.columns(6)
    metrics[0].metric("CPU decision core", status["core"])
    metrics[1].metric("Storage", status["storage"])
    metrics[2].metric("AI provider / status", f"{ai['provider']} / {ai['status']}")
    metrics[3].metric("Live tracks", len(tracks))
    metrics[4].metric(
        "Human handoffs", sum(bool(t["incident"] and t["incident"].get("handoff_required")) for t in tracks)
    )
    metrics[5].metric(
        "Surface traffic",
        len(state["context"].get("traffic", [])) if session_id == state["session_id"] else 0,
    )
    if not snapshot:
        st.info(
            "Ready. Choose an exercise and press Start exercise to send Pako sensor observations to the decision engine."
        )
        render_maps()
        return
    owned = session_id == state["session_id"]
    active = not snapshot["session"]["stopped"]
    phase = (
        "RUNNING"
        if owned and state["running"]
        else "PAUSED"
        if owned and active
        else "STOPPED"
        if not active
        else "EXTERNAL SESSION"
    )
    st.caption(
        f"{phase} · {snapshot['session']['name']} · Scenario time {snapshot['session']['current_time']} · {session_id}"
    )
    if active and st.button("Stop active exercise", key="stop"):
        perform(demo.stop, session_id)
    if not owned and active:
        st.warning(
            "An existing session was recovered or started elsewhere. It is displayed without taking over its simulator. Stop it explicitly to start a new exercise."
        )

    render_maps(snapshot, state["context"] if owned else {})
    with st.expander("Live fault controls", expanded=True):
        if owned and active:
            if st.button(
                "Restore sonar" if state["sensor_loss"] else "Lose sonar coverage", key="sensor_fault"
            ):
                perform(demo.set_fault, "sensor_loss", not state["sensor_loss"])
            if st.button(
                "Stop replaying duplicates" if state["replay"] else "Replay duplicate observations",
                key="replay_fault",
            ):
                perform(demo.set_fault, "replay", not state["replay"])
            st.caption(
                "During sonar loss, scenario time and telemetry continue. Position freshness must degrade."
            )
        ai_fault = "AI_UNAVAILABLE" in snapshot["simulated_faults"]
        if active and ai["provider"] != "off":
            if st.button("Clear AI outage" if ai_fault else "Simulate AI unavailable", key="ai_fault"):
                perform(demo.ai_fault, not ai_fault, session_id)
        st.write(
            "Sonar:",
            "DISCONNECTED"
            if owned and state["sensor_loss"]
            else snapshot["sources"].get("sim_sonar_01", {}).get("health", "UNKNOWN"),
        )
        st.write("AI outage injection:", "ACTIVE (expires after 5 min)" if ai_fault else "inactive")
        st.caption(
            "AI faults apply on the next eligible request. Rate limits and circuit cooldowns still apply."
        )
        st.metric("Engine-accepted events", state["counts"].get("APPLIED", 0) if owned else "—")
        st.metric("Duplicates rejected", state["counts"].get("DUPLICATE", 0) if owned else "—")
        if owned and state["context"].get("current_mps") is not None:
            st.caption(f"Synthetic current: {state['context']['current_mps']:.2f} m/s (context only)")

    assessments, evidence, continuity = st.tabs(
        ["Assessments & recommendations", "Evidence & delivery", "Continuity context"]
    )
    with assessments:
        for track in tracks:
            with st.container(border=True):
                st.subheader(f"{track['track_id']} · {track['risk']['current_band']}")
                cols = st.columns(3)
                cols[0].metric(
                    "Recommended action", track["recommendation"]["primary_action"].replace("_", " ")
                )
                cols[1].metric("Authorization", track["authorization"]["status"])
                cols[2].metric("Position evidence", track["capability"]["data_quality"])
                st.write(track["recommendation"]["deterministic_explanation"])
                st.caption(
                    f"Observation age {track['source']['observation_age_seconds']:.1f}s · Speed {track['estimate']['speed_mps']:.1f} m/s · Revision {track['core_revision']} · {track['assessment_id']}"
                )
                st.write("Reason codes:", ", ".join(track["risk"]["reason_codes"]))
                st.write(
                    "Next useful evidence:", ", ".join(track["recommendation"]["eligible_next_evidence"])
                )
                incident = track["incident"]
                if incident:
                    st.write("Incident:", incident["state"], "·", incident["incident_id"])
                    if (
                        active
                        and incident["state"] != "CLOSED"
                        and (incident["state"] != "HUMAN_OWNED" or incident.get("handoff_required"))
                    ):
                        if st.button("Acknowledge human handoff", key=f"ack_{track['track_id']}"):
                            perform(demo.acknowledge, session_id, track["track_id"])
                enrichment = track["ai_enrichment"]
                if active and ai["provider"] != "off":
                    if st.button("Request AI explanation", key=f"enrich_{track['track_id']}"):
                        perform(demo.enrich, session_id, track["track_id"])
                if enrichment:
                    st.info(
                        f"Optional AI explanation · {enrichment['provider']} / {enrichment['model']} · basis revision {enrichment['basis_revision']}: {enrichment['response']['summary']}"
                    )
                else:
                    st.caption(
                        f"No AI explanation attached ({ai['status']}). The recommendation above is the CPU engine's result."
                    )
                with st.expander("Assessment packet"):
                    st.json(track)
    with evidence:
        st.write("Engine source health")
        st.dataframe(pd.DataFrame.from_dict(snapshot["sources"], orient="index"), width="stretch")
        if owned:
            st.write("HTTP delivery receipts")
            st.dataframe(pd.DataFrame(state["receipts"]), hide_index=True, width="stretch")
            if state["trend"]:
                trend = pd.DataFrame(state["trend"]).pivot_table(
                    index="second", columns="track", values="age_seconds", aggfunc="last"
                )
                st.line_chart(trend, height=200)
                st.caption(
                    "Position observation age in scenario seconds; transport heartbeats do not reset it."
                )
        if st.button("Load committed audit history", key="history"):
            try:
                history = demo.api.request(
                    "GET", f"/v1/sessions/{session_id}/history?limit=100", role="viewer"
                )
                st.session_state["audit_history"] = (session_id, history)
            except DemoError as error:
                st.error(str(error))
        saved_history = st.session_state.get("audit_history")
        if saved_history and saved_history[0] == session_id:
            st.json(saved_history[1])
    with continuity:
        st.caption(
            "Preserved Dashboard synthetic traffic dataset and scenario arithmetic. These do not drive live assessments."
        )
        traffic = pd.read_csv(Path(__file__).parent / "data" / "synthetic_surface_vessels.csv")
        traffic["day"] = pd.to_datetime(traffic["timestamp"]).dt.date
        st.line_chart(traffic.groupby("day").size().rename("Synthetic vessel records"), height=180)
        c1, c2, c3 = st.columns(3)
        vessels = c1.slider("Scheduled fictional vessels", 5, 60, 20)
        affected = c2.slider("Affected vessels", 0, vessels, min(6, vessels))
        delay = c3.slider("Assumed delay (hours)", 1, 24, 6)
        c1.metric("Full suspension: vessel-hours", vessels * delay)
        c2.metric("Illustrative partial restriction", affected * delay)
        st.caption(
            "Illustrative arithmetic only. Operating restrictions require independent authorized assessment."
        )


live_panel()
st.divider()
st.caption(
    "Synthetic exercise / local demo policy / advisory recommendations / no vessel control. LOW is not a safety guarantee. Live assessment data comes only from the decision engine API."
)
