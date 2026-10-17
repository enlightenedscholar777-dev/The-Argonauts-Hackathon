"""Harbor-maester: a live harbor operator workspace backed by the decision API."""

import atexit
import os
from html import escape

import pandas as pd
import streamlit as st

from harbor_engine.geography import AREAS
from harbor_engine.settings import Settings
from harbor_simulation.integration import SCENARIOS, DemoController, DemoError, EngineAPI
from harbor_simulation.operator_view import (
    ACTION_DETAILS,
    ACTION_LABELS,
    QUALITY_LABELS,
    RISK_LABELS,
    contact_name,
    explanation,
    needs_attention,
    priority,
    review_state,
)
from harbor_simulation.personal_ai import PersonalAI
from harbor_simulation.views import COLORS, TERMINALS, empty_map, geographic_map, harbor_layout, local_map

st.set_page_config(page_title="Harbor-maester | Harbor operations", page_icon="⚓", layout="wide")
st.markdown(
    """<style>
.stApp{background:#091522;color:#e5edf5}
.block-container{padding:3.6rem 2.5rem 2rem;max-width:1660px}
[data-testid="stSidebar"]{background:#0d2031;border-right:1px solid #223a4c}
[data-testid="stSidebar"] .block-container{padding-top:1rem}
h1,h2,h3{color:#eff6fa!important;letter-spacing:-.025em}
h1{font-size:2.25rem!important}h2{font-size:1.4rem!important}h3{font-size:1.12rem!important}
[data-testid="stMetric"]{background:#102536;border:1px solid #244052;border-radius:12px;padding:15px 18px}
[data-testid="stMetricValue"]{font-size:1.65rem;font-weight:650}[data-testid="stMetricValue"],[data-testid="stMetricValue"]>div{white-space:normal;overflow:visible;text-overflow:clip}[data-testid="stMetricLabel"] p{white-space:normal}
[data-testid="stMetricLabel"]{color:#aebfce}.stButton button{border-radius:8px;min-height:2.55rem}
[data-testid="stTabs"] button{font-size:14px}
.brand{font-size:23px;font-weight:750;letter-spacing:-1px;color:#f1f8fa;margin:8px 0}
.brand span{color:#53d7c0}.eyebrow{font-size:11px;font-weight:700;letter-spacing:1.7px;color:#8da7b8;text-transform:uppercase;margin-bottom:8px}
.situation{background:linear-gradient(110deg,#102b3b,#112333);border:1px solid #2c495c;border-left:4px solid #5bd8bf;border-radius:12px;padding:17px 21px;margin:2px 0 6px}
.situation h2{margin:3px 0 9px;padding:0;font-size:23px!important}.situation p{margin:5px 0;color:#c4d2de;font-size:15px;line-height:1.6}
.situation-grid{display:grid;grid-template-columns:1fr 1fr;gap:25px}.suggestion{margin-top:0!important;padding-left:22px;border-left:1px solid #355064;color:#edf8f8!important}
.pill{display:inline-block;border:1px solid currentColor;border-radius:20px;padding:2px 9px;font-size:11px;font-weight:650;margin:0 6px 5px 0}
.watch-row{border-bottom:1px solid #243d50;padding:13px 0}.watch-row strong{font-size:15px}.watch-row p{color:#b0c1cf;font-size:13px;margin:5px 0 0}
.note{font-size:12px;color:#9cb2c2;line-height:1.6}.stAlert{border-radius:10px}
@media(max-width:1100px){.situation-grid{grid-template-columns:1fr;gap:10px}.suggestion{padding-left:0;border-left:0}.block-container{padding:3.6rem 1.5rem 1.5rem}[data-testid="stHorizontalBlock"]{flex-wrap:wrap}[data-testid="stColumn"]{min-width:180px!important;flex:1 1 180px!important}}@media(max-width:640px){h1{font-size:1.8rem!important}.situation{padding:16px}}
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


def perform(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
        st.session_state.pop("action_error", None)
    except DemoError as error:
        st.session_state["action_error"] = str(error)
    st.rerun()


def open_contact(track_id):
    st.session_state["selected_contact"] = track_id
    st.session_state["navigation"] = "Contacts"


def open_traffic():
    st.session_state["navigation"] = "Traffic"


requested_scenario = st.session_state.pop("requested_scenario", None)
if requested_scenario:
    st.session_state["scenario"] = requested_scenario

with st.sidebar:
    st.markdown(
        '<div class="brand"><span>⚓</span> Harbor-maester</div><div class="eyebrow">Harbor operations workspace</div>',
        unsafe_allow_html=True,
    )
    st.caption("LONG BEACH · SIMULATION")
    if os.environ.get("HARBOR_PUBLIC_DEMO") == "true":
        st.caption("Shared live demo: exercise controls affect all viewers. Your AI key and explanations are private to this browser session.")
    page = st.radio(
        "Workspace",
        ["Overview", "Contacts", "Traffic", "Simulation", "Activity", "Detection"],
        key="navigation",
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("**Your harbor watch**")
    st.caption("Live position reports, assessments and suggested actions in one place.")
    with st.expander("Map settings"):
        online_map = st.checkbox("Show online Long Beach basemap", value=True, key="online_map")
        focus = st.selectbox(
            "Focus area", ["Whole harbor", "Exercise area"] + [t["label"] for t in TERMINALS], key="map_focus"
        )
        show_labels = st.checkbox("Area and waterway labels", value=True, key="map_labels")
        show_context = st.checkbox("Surface vessel context", value=True, key="map_context")
        show_forecasts = st.checkbox("Conditional forecasts", value=True, key="map_forecasts")
        show_uncertainty = st.checkbox("Position uncertainty rings", value=True, key="map_uncertainty")
        st.caption(
            "The atlas and exercise detail work without internet. Geographic tiles require a connection."
        )
    st.divider()
    st.markdown(
        '<div class="eyebrow">Decision support</div><p class="note">Recommendations come from the decision engine. Optional AI can explain them; it does not control vessels or authorize operations.</p>',
        unsafe_allow_html=True,
    )
    st.caption("Synthetic exercise data · Local demo policy")
    with st.expander("Your Groq API key", expanded=False):
        st.caption(
            "Optional. Your key stays in this browser session's server memory; it is not saved to disk "
            "or shared with other viewers. On request, assessment evidence is sent to Groq using your account."
        )
        with st.form("personal_groq_key", clear_on_submit=True):
            entered_key = st.text_input("Groq API key", type="password", key="groq_key_input")
            save_key = st.form_submit_button("Use my key")
        if save_key:
            candidate = entered_key.strip()
            if 20 <= len(candidate) <= 256 and all(c.isascii() and (c.isalnum() or c in "_-") for c in candidate):
                st.session_state["personal_ai"] = PersonalAI(candidate)
                st.session_state.pop("personal_key_error", None)
            else:
                st.session_state["personal_key_error"] = "Enter a valid Groq API key."
        if st.session_state.get("personal_key_error"):
            st.error(st.session_state["personal_key_error"])
        if "personal_ai" in st.session_state:
            st.success("Your key is set. AI runs only when requested.")
            if st.button("Remove my key", key="remove_groq_key"):
                st.session_state.pop("personal_ai", None)
                st.session_state.pop("personal_key_error", None)
                st.rerun()
        st.caption("Use Contacts → Optional AI explanation. Remove your key when finished.")

st.markdown('<div class="eyebrow">LONG BEACH HARBOR / OPERATIONS</div>', unsafe_allow_html=True)
st.title(
    {
        "Overview": "Your harbor, at a glance",
        "Contacts": "Contact review",
        "Simulation": "Simulation control room",
        "Traffic": "Harbor-wide traffic watch",
        "Activity": "Activity & system health",
        "Detection": "Small-object detection watch",
    }[page]
)
st.caption(
    {
        "Overview": "Understand the situation. See what needs attention. Decide the next step.",
        "Contacts": "Review the evidence behind each recommendation and acknowledge a requested review.",
        "Simulation": "Explore harbor situations with live traffic and sensor observations.",
        "Traffic": "Scheduled voyages, predicted encounters, route adherence and berth delays.",
        "Activity": "Check observation delivery, system availability and the committed audit trail.",
        "Detection": "Follow movement patterns, review possible explanations and decide what to verify next.",
    }[page]
)


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
            "Vessels follow scheduled voyages on the exercise clock. Dashed paths show assigned corridors; queued arrivals wait for space. Red marks traffic concern; amber marks a hold or elevated concern. Live engine assessments update in the inset and right panel. The atlas is schematic, not to scale."
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
                f"{source['source']} · {source['records']} records / {source['identities']} vessel identities. Generated paths use CSV profiles, not recorded AIS coordinates. Surface vessels have traffic-model assessments; sonar identity and zone assessments remain separate."
            )
            st.dataframe(
                pd.DataFrame(context["traffic"])[
                    ["vessel_id", "vessel_type", "sector", "source_status", "status", "speed_mps"]
                ],
                hide_index=True,
                width="stretch",
            )


def contact_card(track, snapshot, ai):
    action = track["recommendation"]["primary_action"]
    band = track["risk"]["current_band"]
    quality = track["capability"]["data_quality"]
    st.markdown(
        f'<span class="pill" style="color:{COLORS.get(band, "#a7b5cb")}">{escape(RISK_LABELS.get(band, band))}</span><span class="pill" style="color:#a9c4d6">{escape(review_state(track))}</span>',
        unsafe_allow_html=True,
    )
    st.subheader(contact_name(track["track_id"]))
    st.caption(f"Reference: {track['track_id']} · Assessment at {track['assessed_at']}")
    st.markdown("**What is happening**")
    st.write(explanation(track))
    st.markdown("**Suggested next step**")
    st.info(f"{ACTION_LABELS.get(action, action)}. {ACTION_DETAILS.get(action, '')}")
    a, b = st.columns(2)
    a.metric("Position evidence", QUALITY_LABELS.get(quality, quality))
    authorization = {
        "UNKNOWN": "Unconfirmed",
        "AUTHORIZED": "Confirmed mission",
        "NOT_AUTHORIZED": "Not permitted",
    }.get(track["authorization"]["status"], track["authorization"]["status"])
    b.metric("Operating permission", authorization)
    st.caption(
        f"Last position: {track['source']['observation_age_seconds']:.1f} scenario seconds ago · Estimated speed: {track['estimate']['speed_mps']:.1f} m/s"
    )
    incident = track["incident"]
    active = not snapshot["session"]["stopped"]
    if (
        incident
        and active
        and incident["state"] != "CLOSED"
        and (incident["state"] != "HUMAN_OWNED" or incident.get("handoff_required"))
    ):
        if st.button("Acknowledge review", type="primary", key=f"ack_{track['track_id']}"):
            perform(demo.acknowledge, snapshot["session"]["session_id"], track["track_id"])
        st.caption("Records your acknowledgment. Monitoring continues; no vessel command is sent.")
    elif incident and incident["state"] == "HUMAN_OWNED":
        st.success("Review acknowledged. Continue watching for changes.")
    with st.expander("Optional AI explanation"):
        st.caption("Generated only when you request it. Simulation updates do not call AI.")
        personal = st.session_state.get("personal_ai")
        if personal:
            sid = snapshot["session"]["session_id"]
            tid = track["track_id"]
            wait = personal.wait_seconds(sid, tid)
            st.caption("Using your Groq key. This explanation is visible only in your browser session.")
            if wait > 0:
                st.info(f"Wait {int(wait) + 1} seconds before requesting another explanation.")
            if st.button("Request AI explanation", key=f"personal_enrich_{tid}", disabled=not active or wait > 0):
                with st.spinner("Generating your explanation…"):
                    personal.request(demo.api, sid, tid)
            if personal.error:
                st.warning(personal.error)
            result = personal.results.get((sid, tid))
            if result:
                st.write(result["response"]["summary"])
                st.caption(
                    f"Groq / {result['model']} · Assessment at {result['basis_assessed_at']} · "
                    f"Revision {result['basis_revision']} (current {track['core_revision']}). "
                    "This is a snapshot explanation; use the current CPU recommendation for changes."
                )
        else:
            server_ai_explanation(track, snapshot, ai, active)
    with st.expander("Evidence & assessment details"):
        st.write("Engine explanation:", track["recommendation"]["deterministic_explanation"])
        st.write(
            "Next useful evidence:",
            ", ".join(s.replace("_", " ").lower() for s in track["recommendation"]["eligible_next_evidence"]),
        )
        st.caption(
            "Forecasts assume current motion continues; they are not guaranteed paths. Mission confirmation does not grant permission for every zone."
        )
        st.json(track)


def server_ai_explanation(track, snapshot, ai, active):
    if ai["provider"] == "off":
        st.info("Add your key under Your Groq API key in the sidebar to request an explanation.")
    st.caption(
        f"Provider: {ai['provider']} · Status: {ai['status']}. The engine recommendation remains available if AI is offline."
    )
    if ai["provider"] == "fake":
        st.warning("Mock mode: explanations are simulated, not real AI inference.")
    if active and ai["provider"] != "off":
        cooldown = ai.get("cooldown_seconds", 0)
        busy = ai["status"] == "PENDING" or ai.get("pending", 0) > 0
        if cooldown > 0:
            st.info(f"AI is cooling down. Try again in {int(cooldown) + 1} seconds. CPU assessments continue.")
        elif busy:
            st.info("An AI explanation is being generated. Please wait.")
        if st.button("Request AI explanation", key=f"enrich_{track['track_id']}", disabled=busy or cooldown > 0 or ai["status"] == "MISCONFIGURED"):
            perform(demo.enrich, snapshot["session"]["session_id"], track["track_id"])
    enrichment = track.get("ai_enrichment")
    if enrichment:
        st.write(enrichment["response"]["summary"])
        st.caption(
            f"{enrichment['provider']} / {enrichment['model']} · Based on revision {enrichment['basis_revision']} · Current revision {track['core_revision']}"
        )
    else:
        st.caption("No AI explanation attached to this assessment.")


def simulation_controls(state, snapshot, ai, owned):
    if "scenario" not in st.session_state:
        st.session_state["scenario"] = state["scenario"] or "Harbor approach"
    metadata = (snapshot or {}).get("session", {})
    st.session_state.setdefault("exercise_area", metadata.get("exercise_area", "west_basin"))
    st.session_state.setdefault("detection_scope", metadata.get("detection_scope", "harbor"))
    st.subheader("Choose a situation")
    a, b = st.columns(2)
    area = a.selectbox(
        "Exercise location for next run",
        list(AREAS),
        format_func=lambda key: AREAS[key]["name"],
        key="exercise_area",
    )
    scope = b.selectbox(
        "Small-object detection coverage",
        ["harbor", "area"],
        format_func=lambda key: "All eight harbor areas" if key == "harbor" else "Selected area only",
        key="detection_scope",
    )
    st.caption(
        "Location and coverage apply when a new exercise starts. Zone shapes are illustrative demo policy; vessel routes remain Long Beach routes."
    )
    st.caption(
        "A preset archives this dashboard's current exercise and starts a fresh one. Sessions started elsewhere are preserved."
    )
    cols = st.columns(4)
    for index, name in enumerate(SCENARIOS):
        with cols[index % 4]:
            if st.button(name, key="preset_" + name, help=SCENARIOS[name], width="stretch"):
                st.session_state["requested_scenario"] = name
                perform(
                    demo.start,
                    name,
                    int(st.session_state.get("seed", 42)),
                    st.session_state.get("autoplay", True),
                    st.session_state.get("traffic_count", 48),
                    replace_owned=True,
                    exercise_area=area,
                    detection_scope=scope,
                )
    with st.container(border=True):
        a, b = st.columns(2)
        scenario = a.selectbox("Scenario", list(SCENARIOS), key="scenario")
        a.caption(SCENARIOS[scenario])
        seed = b.number_input("Noise seed", min_value=0, max_value=2**32 - 1, value=42, key="seed")
        traffic_count = a.slider("Surface traffic for next exercise", 12, 100, 48, 4, key="traffic_count")
        autoplay = b.checkbox("Run automatically", value=True, key="autoplay")
        b.select_slider(
            "Playback speed",
            options=[1, 2, 4],
            value=int(1 / demo.period),
            format_func=lambda n: f"{n}×",
            key="playback_speed",
            on_change=lambda: demo.set_speed(st.session_state["playback_speed"]),
        )
        if st.button("Start selected exercise", type="primary", key="start"):
            perform(
                demo.start,
                scenario,
                int(seed),
                autoplay,
                traffic_count,
                replace_owned=True,
                exercise_area=area,
                detection_scope=scope,
            )
        st.caption(
            "Starting confirms the synthetic research mission. Other contacts remain unverified. Harbor-wide operations runs for 15 minutes; focused incident scenarios pause at 90 seconds."
        )
    active = snapshot and not snapshot["session"]["stopped"]
    with st.expander("Test sensor and AI outages"):
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
                "With sonar lost, the clock and vehicle heartbeats continue. Position evidence ages until it is marked lost."
            )
        if active and ai["provider"] != "off":
            ai_fault = "AI_UNAVAILABLE" in snapshot["simulated_faults"]
            if st.button("Clear AI outage" if ai_fault else "Simulate AI unavailable", key="ai_fault"):
                perform(demo.ai_fault, not ai_fault, snapshot["session"]["session_id"])
            st.caption(
                "AI outage applies to eligible requests and expires after five minutes. CPU assessments continue."
            )
    if active and st.button("Stop active exercise", key="stop"):
        perform(demo.stop, snapshot["session"]["session_id"])
    render_maps(snapshot, state["context"] if owned else None)


def detection_watch(snapshot, context):
    report = (snapshot or {}).get("detection") or {}
    rows = report.get("objects", [])
    st.info(
        "Movement is evidence, not object identification. Material, species, identity and registration remain unknown until independently confirmed."
    )
    if not rows:
        st.caption(
            "Start a new exercise in Simulation to enable the object observation stream. Existing sessions are preserved."
        )
        render_maps(snapshot, context)
        return
    a, b, c = st.columns(3)
    a.metric("Objects observed", len(rows))
    b.metric("Movement hypotheses", sum(r["status"] == "HYPOTHESIS" for r in rows))
    c.metric("Areas covered", len({r["area_id"] for r in rows}))
    st.caption(
        "Local trained random forest · synthetic training only · no Groq or GPU needed · initial observation window: 30 seconds · scores are not calibrated real-world probabilities."
    )
    area_filter = st.selectbox(
        "Detection area", ["All areas"] + [v["name"] for v in AREAS.values()], key="detection_area_filter"
    )
    visible = [r for r in rows if area_filter == "All areas" or r["area"] == area_filter]
    evidence_labels = {
        "HYPOTHESIS": "Needs confirmation",
        "COLLECTING": "Collecting observations",
        "UNRESOLVED": "Uncertain movement",
        "STALE": "Stale observations",
        "UNAVAILABLE": "Model unavailable",
    }
    st.caption(
        "Possible objects are unconfirmed examples consistent with the movement category, "
        "not separate object-recognition predictions. Camera or imaging sonar evidence is needed to confirm them."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Object": r["object_id"],
                    "Area": r["area"],
                    "Movement": r["label"],
                    "Possible objects (unconfirmed)": "; ".join(r.get("possible_objects", [])) or "Not enough reliable evidence",
                    "Evidence": evidence_labels.get(r["status"], r["status"]),
                    "Age (s)": r["age_seconds"],
                    "Material": r["material"],
                }
                for r in visible
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    ids = sorted(r["object_id"] for r in visible)
    if not ids:
        st.caption("No reports in this area for the current coverage selection.")
        return
    if st.session_state.get("detection_object") not in ids:
        st.session_state["detection_object"] = ids[0]
    selected = st.selectbox("Review object", ids, key="detection_object")
    row = next(r for r in visible if r["object_id"] == selected)
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader(row["label"])
        st.markdown("**Possible objects — unconfirmed**")
        st.write("; ".join(row.get("possible_objects", [])) or "No object-type suggestion from the available evidence.")
        st.write(row["interpretation"])
        st.warning("Suggested next step: " + row["next_step"])
        st.caption(
            f"{row['reason']} {row['sample_count']} observations retained; report age {row['age_seconds']:.0f} s."
        )
    with right:
        st.subheader("Movement evidence")
        if row["features"]:
            f = row["features"]
            st.write(
                f"Average speed: **{f['mean_speed']:.2f} m/s** · Straightness: **{f['straightness']:.2f} / 1**"
            )
            st.write(
                f"Average turn per interval: **{f['mean_turn']:.2f} rad** · Speed variation: **{f['speed_variation']:.2f}**"
            )
        if row["scores"]:
            st.bar_chart(pd.DataFrame({"Synthetic model score": row["scores"]}), height=190)
        else:
            st.caption("Evidence scores are withheld until the observation window is usable.")
    st.caption(
        "Purple dots and trails on the maps are small-object observations. Gray dots have stale reports. These are separate from vessel traffic and sonar permission assessments."
    )
    render_maps(snapshot, {**(context or {}), "selected_object": selected})


def traffic_watch(snapshot, context, detail=False):
    surface = (snapshot or {}).get("surface")
    if surface is None:
        st.info("Surface assessments will appear when a new simulation sends its first voyage batch.")
        return
    rows = sorted(
        surface["vessels"],
        key=lambda v: ({"HIGH": 0, "UNKNOWN": 1, "ELEVATED": 2, "LOW": 3}[v["concern"]], v["vessel_id"]),
    )
    alerts = [v for v in rows if v["reason_codes"]]
    if not detail:
        st.markdown(
            f"**Harbor-wide traffic watch:** {len(rows)} observed vessels · {len(alerts)} advisories · {surface['pairs_evaluated']} vessel pairs evaluated"
        )
        if alerts:
            first = alerts[0]
            st.warning(f"{first['vessel_id']} → {first['destination']}: {first['recommendation']}.")
        if st.button("Review traffic & schedules →", key="open_traffic", on_click=open_traffic):
            st.rerun()
        return
    a, b, c = st.columns(3)
    a.metric("Observed surface vessels", len(rows))
    b.metric("Traffic advisories", len(alerts))
    c.metric("Vessels holding", sum(v["status"] == "HOLDING" for v in rows))
    st.caption(
        f"Engine model: {surface['model']} · Report time: {surface['observed_at']} · {surface['pairs_evaluated']} pairs checked. These are analytical models, not trained ML."
    )
    if rows:
        table = [
            {
                "Vessel": r["vessel_id"],
                "Destination": r["destination"],
                "Voyage": r["phase"],
                "Status": r["status"],
                "Concern": RISK_LABELS[r["concern"]],
                "Delay (s)": r["delay_s"],
                "ETA (scenario s)": r["eta_s"],
                "Suggested next step": r["recommendation"],
            }
            for r in rows
        ]
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
        identifiers = sorted(r["vessel_id"] for r in rows)
        if st.session_state.get("surface_selection") not in identifiers:
            st.session_state["surface_selection"] = rows[0]["vessel_id"]
        vessel_id = st.selectbox("Review a surface vessel", identifiers, key="surface_selection")
        row = next(r for r in rows if r["vessel_id"] == vessel_id)
        st.subheader(f"{vessel_id} · {row['destination']}")
        st.info(row["recommendation"])
        st.write(
            f"Route deviation: {row['cross_track_m']:.0f} m · Position age: {row['observation_age_seconds']:.1f}s · Schedule delay: {row['delay_s']:.0f}s"
        )
        for encounter in row["encounters"]:
            st.write(
                f"Predicted approach to {encounter['vessel_id']}: {encounter['separation_m']:.0f} m in {encounter['closest_in_s']:.0f}s if current velocities persist."
            )
        if row.get("acknowledgment"):
            st.success("Traffic review acknowledged and saved to the audit history.")
        elif row["reason_codes"] and not snapshot["session"]["stopped"]:
            if st.button("Acknowledge traffic review", key="surface_ack"):
                perform(demo.acknowledge_surface, snapshot["session"]["session_id"], vessel_id)
        st.caption(
            "Acknowledgment records review, not clearance or a vessel command. A new reason or encounter requires another review."
        )
    if context and context.get("traffic"):
        with st.expander("Full voyage schedule, including queued arrivals"):
            st.dataframe(
                pd.DataFrame(context["traffic"])[
                    [
                        "vessel_id",
                        "destination",
                        "phase",
                        "status",
                        "scheduled_arrival_s",
                        "eta_s",
                        "delay_s",
                        "hold_reason",
                    ]
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Times are scenario seconds. Queued arrivals are intentionally off-map until there is room to enter. Completed voyages leave the map. Berth service lasts 60 simulated seconds."
            )
    st.caption(surface["assumptions"])
    render_maps(snapshot, context)


def activity(state, snapshot, status, owned):
    metrics = st.columns(3)
    metrics[0].metric("CPU decision core", status["core"])
    metrics[1].metric("Storage", status["storage"])
    metrics[2].metric("AI provider / status", f"{status['ai']['provider']} / {status['ai']['status']}")
    st.caption(
        "The provider status above is for optional language-model explanations. Local motion ML runs independently, including when the provider is off."
    )
    if not snapshot:
        st.info("No session activity yet.")
        return
    st.subheader("Observation sources")
    detection_rows = (snapshot.get("detection") or {}).get("objects", [])
    st.metric(
        "Local motion ML",
        "Unavailable"
        if any(r["status"] == "UNAVAILABLE" for r in detection_rows)
        else "Running"
        if detection_rows
        else "Awaiting observations",
    )
    st.dataframe(pd.DataFrame.from_dict(snapshot["sources"], orient="index"), width="stretch")
    if owned:
        a, b = st.columns(2)
        a.metric("Engine-accepted events", state["counts"].get("APPLIED", 0))
        b.metric("Duplicates rejected", state["counts"].get("DUPLICATE", 0))
        a.metric("Surface observations accepted", state["counts"].get("SURFACE_OBSERVATIONS", 0))
        a.metric("Small-object observations accepted", state["counts"].get("OBJECT_OBSERVATIONS", 0))
        b.metric("Latest ingestion step (ms)", f"{state['context'].get('step_ms', 0):.0f}")
        if state["trend"]:
            st.subheader("Position report age")
            trend = pd.DataFrame(state["trend"]).pivot_table(
                index="second", columns="track", values="age_seconds", aggfunc="last"
            )
            st.line_chart(trend, height=220)
            st.caption(
                "Seconds since the last accepted position. Heartbeats do not refresh position evidence."
            )
        with st.expander("Delivery receipts"):
            st.dataframe(pd.DataFrame(state["receipts"]), hide_index=True, width="stretch")
    st.subheader("Committed audit history")
    sid = snapshot["session"]["session_id"]
    if st.button("Load committed audit history", key="history"):
        try:
            st.session_state["audit_history"] = (
                sid,
                demo.api.request("GET", f"/v1/sessions/{sid}/history?limit=100", role="viewer"),
            )
        except DemoError as error:
            st.error(str(error))
    history = st.session_state.get("audit_history")
    if history and history[0] == sid:
        st.caption("Loaded audit snapshot. Select Load again to refresh.")
        st.json(history[1])
    st.caption(f"Session reference: {sid}")


@st.fragment(run_every=1.0)
def live_panel():
    try:
        if os.environ.get("HARBOR_AUTOSTART", "true").lower() == "true":
            demo.ensure_started()
        state = demo.view()
        status = demo.api.status()
        session_id = status["active_session_id"] or state["session_id"]
        snapshot = demo.api.snapshot(session_id) if session_id else None
    except DemoError as error:
        st.error("Connection to the decision engine is unavailable.")
        st.warning(
            "Live data is unavailable. No current assessment is displayed. Check the launcher; this page reconnects automatically."
        )
        with st.expander("Connection details"):
            st.write(str(error))
        render_maps()
        return
    for error in (st.session_state.get("action_error"), state["error"]):
        if error:
            st.error(error)
    owned = bool(session_id and session_id == state["session_id"])
    active = bool(snapshot and not snapshot["session"]["stopped"])
    running = owned and active and state["running"]
    phase = (
        "Running"
        if running
        else "Paused"
        if owned and active
        else "Stopped"
        if snapshot and not active
        else "External session"
        if active
        else "Ready"
    )
    a, b, c, d = st.columns([6, 1, 1, 1])
    a.markdown(
        f"**{'●' if running else '○'} Simulation {phase.lower()}** · {escape(state['scenario'] or (snapshot['session']['name'] if snapshot else 'No exercise'))}"
    )
    if snapshot:
        a.caption(
            f"Scenario clock: {max(0, state['elapsed'])} / {state['duration']} seconds"
            if owned
            else f"Session clock: {snapshot['session']['current_time']}"
        )
    if b.button("Pause", key="pause", disabled=not running):
        perform(demo.pause)
    if c.button(
        "Resume",
        key="resume",
        disabled=not owned or not active or running or state["elapsed"] >= state["duration"],
    ):
        perform(demo.resume)
    if d.button(
        "Step +1s", key="step", disabled=not owned or not active or state["elapsed"] >= state["duration"]
    ):
        perform(demo.step)
    if owned and state["elapsed"] >= state["duration"]:
        st.info("Exercise complete. Review the final assessments or start another situation in Simulation.")
    elif owned and active and not running:
        st.caption("Playback is paused. Positions and evidence age are frozen at the scenario clock above.")
    if not active and snapshot:
        st.warning(
            "This exercise has stopped. Showing its final recorded assessments, not current operations."
        )
    if active and not owned:
        st.info(
            "Showing an existing session. Its simulator is controlled elsewhere; it has not been replaced. To start your own, stop it explicitly in Simulation."
        )
    if page == "Simulation":
        simulation_controls(state, snapshot, status["ai"], owned)
        return
    if page == "Activity":
        activity(state, snapshot, status, owned)
        return
    if page == "Detection":
        detection_watch(snapshot, state["context"] if owned else None)
        return
    if page == "Traffic":
        traffic_watch(snapshot, state["context"] if owned else None, detail=True)
        return
    tracks = sorted(snapshot["tracks"], key=priority) if snapshot else []
    attention = [t for t in tracks if needs_attention(t)]
    context = state["context"] if owned else None
    if page == "Contacts":
        if not tracks:
            st.info("No assessed contacts yet. Start a situation in Simulation.")
            return
        search = st.text_input(
            "Find a contact", placeholder="Contact name or reference", key="contact_search"
        )
        filter_mode = st.radio(
            "Show",
            ["All contacts", "Needs attention", "Acknowledged reviews"],
            horizontal=True,
            key="contact_filter",
        )
        filtered = [
            t
            for t in tracks
            if search.casefold() in (contact_name(t["track_id"]) + t["track_id"]).casefold()
            and (
                filter_mode == "All contacts"
                or filter_mode == "Needs attention"
                and needs_attention(t)
                or filter_mode == "Acknowledged reviews"
                and review_state(t) == "Review acknowledged"
            )
        ]
        if not filtered:
            st.info("No contacts match this view. Change the filter or search.")
            return
        ids = [t["track_id"] for t in filtered]
        if st.session_state.get("selected_contact") not in ids:
            st.session_state["selected_contact"] = ids[0]
        selected = st.selectbox("Contact", ids, format_func=contact_name, key="selected_contact")
        track = next(t for t in filtered if t["track_id"] == selected)
        left, right = st.columns([1, 1.3], gap="large")
        with left:
            contact_card(track, snapshot, status["ai"])
        with right:
            st.subheader("Position & nearby policy zones")
            st.image(
                local_map(
                    snapshot,
                    context,
                    show_forecasts=show_forecasts,
                    show_uncertainty=show_uncertainty,
                    selected_track=selected,
                ),
                width="stretch",
                alt="Live engine estimates, zones and conditional forecasts in local metres",
            )
            st.caption(
                "The white selection ring marks the contact under review. Other contacts remain visible for context. Local demo coordinates, not a navigation chart."
            )
        return
    # Overview: lead with the next decision, then situational awareness.
    if attention:
        top = attention[0]
        color = COLORS.get(top["risk"]["current_band"], "#a7b5cb")
        action = ACTION_LABELS.get(top["recommendation"]["primary_action"], "Review assessment")
        st.markdown(
            f'<div class="situation" style="border-left-color:{color}"><div class="eyebrow">PRIORITY CONTACT · {escape(review_state(top))}</div><div class="situation-grid"><div><h2>{escape(contact_name(top["track_id"]))} needs attention</h2><p>{escape(explanation(top))}</p></div><p class="suggestion"><strong>Suggested next step: {escape(action)}</strong><br>{escape(ACTION_DETAILS.get(top["recommendation"]["primary_action"], ""))}</p></div></div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "Review priority contact →", key="review_priority", on_click=open_contact, args=(top["track_id"],)
        ):
            st.rerun()
    else:
        st.markdown(
            '<div class="situation"><div class="eyebrow">HARBOR WATCH</div><h2>'
            + ("Continue monitoring" if tracks else "Waiting for observations")
            + "</h2><p>"
            + (
                "No current sonar recommendation requires action. Check the harbor traffic watch below for surface advisories."
                if tracks
                else "Start a situation in Simulation to populate the harbor watch."
            )
            + "</p></div>",
            unsafe_allow_html=True,
        )
    cols = st.columns(4)
    cols[0].metric("Contacts needing attention", len(attention))
    cols[1].metric("Assessed contacts", len(tracks))
    traffic = context.get("traffic", []) if context else []
    cols[2].metric(
        "Surface vessels moving",
        sum(t["status"] == "UNDERWAY" for t in traffic) if owned else "—",
        help="Scheduled surface voyages are assessed separately for closest approach, route adherence and delay; sonar contacts retain their identity and zone policy.",
    )
    cols[3].metric(
        "Current position reports",
        f"{sum(t['capability']['data_quality'] == 'FRESH' for t in tracks)} / {len(tracks)}",
    )
    degraded = sum(t["capability"]["data_quality"] in ("STALE", "LOST", "CONFLICT") for t in tracks)
    if degraded:
        st.warning(
            f"{degraded} contact(s) have stale, lost or conflicting position evidence. Request fresh observations before relying on their position or forecast."
        )
    st.subheader("Live harbor picture")
    traffic_watch(snapshot, context)
    st.caption(
        f"{len(traffic)} scheduled surface voyages · {len(tracks)} sonar contacts · Both streams are assessed by the CPU engine · Refreshes every second; scenario pace depends on playback and ingestion time"
    )
    render_maps(snapshot, context)
    st.subheader("Attention queue")
    st.caption(
        "Ordered by outstanding review request, engine concern level and recommended action. Unconfirmed identity alone is not a high-risk classification."
    )
    if not attention:
        st.success(
            "No sonar contacts currently require an action beyond monitoring. Surface traffic advisories are shown separately."
        )
    for track in attention:
        left, right = st.columns([5, 1])
        band = track["risk"]["current_band"]
        left.markdown(
            f'<div class="watch-row"><span class="pill" style="color:{COLORS.get(band, "#a7b5cb")}">{escape(RISK_LABELS.get(band, band))}</span> <strong>{escape(contact_name(track["track_id"]))}</strong><p>{escape(ACTION_LABELS.get(track["recommendation"]["primary_action"], "Review assessment"))} · {escape(QUALITY_LABELS.get(track["capability"]["data_quality"], track["capability"]["data_quality"]))} · {escape(review_state(track))}</p></div>',
            unsafe_allow_html=True,
        )
        if right.button(
            "Review contact",
            key="review_" + track["track_id"],
            on_click=open_contact,
            args=(track["track_id"],),
        ):
            st.rerun()


live_panel()
st.divider()
st.caption(
    "Harbor-maester · Synthetic exercise / advisory recommendations / no vessel control. Concern levels are not calibrated probabilities or safety guarantees. Live assessments come from the decision engine API."
)
