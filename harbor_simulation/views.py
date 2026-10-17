"""Harbor presentation only: live positions, risks and policy come from the API."""

import html
import math

from harbor_simulation.map_catalog import TERMINALS, WATERWAYS, context_vessels

COLORS = {"LOW": "#43d9b5", "ELEVATED": "#ffc66d", "HIGH": "#ff6b7a", "UNKNOWN": "#a7b5cb"}
INK = "#e9f3fc"
MUTED = "#9ab6c9"


def project(x, y):
    """Display placement only; the numerical engine continues to use local metres."""
    return [-118.23 + x / (111320 * math.cos(math.radians(33.744))), 33.744 + y / 111320]


def empty_map():
    return {"bounds": [0, 0, 1000, 700], "zones": {}, "routes": {}, "tracks": []}


def rgb(color, alpha=255):
    return [int(color[i : i + 2], 16) for i in (1, 3, 5)] + [alpha]


def zone_color(zone):
    return "#ff6b7a" if zone["kind"] == "restricted" else "#ffc66d"


def words(value):
    return value.replace("_", " ").title()


class Drawing:
    """SVG writer with escaped labels and no browser or network dependencies."""

    def __init__(self, title):
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="860" viewBox="0 0 1440 860" font-family="Segoe UI, sans-serif">',
            f"<title>{html.escape(title)}</title>",
            '<rect width="1440" height="860" rx="18" fill="#091e30"/>',
            '<defs><pattern id="water" width="40" height="40" patternUnits="userSpaceOnUse">'
            '<path d="M 0 40 L 40 40 40 0" fill="none" stroke="#153347" stroke-width="0.6"/>'
            '</pattern><pattern id="hatch" width="9" height="9" patternUnits="userSpaceOnUse" '
            'patternTransform="rotate(45)"><path d="M 0 0 V 9" stroke="#ffc66d" '
            'stroke-opacity=".25" stroke-width="3"/></pattern></defs>',
        ]

    def add(self, value):
        self.parts.append(value)

    def text(self, x, y, value, size=16, color=INK, weight=400, anchor="start", halo=False):
        stroke = (
            ' stroke="#091e30" stroke-width="5" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        )
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" '
            f'font-weight="{weight}" text-anchor="{anchor}"{stroke}>{html.escape(str(value))}</text>'
        )

    def rect(self, x, y, w, h, fill, stroke="none", radius=0):
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{radius}" fill="{fill}" stroke="{stroke}"/>'
        )

    def path(self, vertices, color, width=2, dash=None, closed=False, fill="none"):
        pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in vertices)
        pattern = f' stroke-dasharray="{dash}"' if dash else ""
        tag = "polygon" if closed else "polyline"
        self.add(
            f'<{tag} points="{pts}" fill="{fill}" stroke="{color}" '
            f'stroke-width="{width}" stroke-linejoin="round"{pattern}/>'
        )

    def circle(self, x, y, r, fill, stroke="none", width=1):
        self.add(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"/>'
        )

    def finish(self):
        return "".join(self.parts) + "</svg>"


def compass(d, x, y):
    d.path([(x, y + 21), (x, y - 17)], MUTED)
    d.path([(x - 6, y - 7), (x, y - 20), (x + 6, y - 7)], INK, closed=True, fill=INK)
    d.text(x, y - 30, "N", 15, weight=700, anchor="middle")
    d.text(x + 13, y + 6, "E", 11, MUTED)


def local_map(snapshot, context=None, *, show_forecasts=True, show_uncertainty=True):
    """Equal-scale metre plot plus a readable contact and policy key."""
    x0, y0, x1, y1 = snapshot["bounds"]
    scale = min(920 / (x1 - x0), 640 / (y1 - y0))
    plot_w, plot_h = (x1 - x0) * scale, (y1 - y0) * scale
    left, top = 90 + (920 - plot_w) / 2, 110 + (640 - plot_h) / 2

    def xy(x, y):
        return left + (x - x0) * scale, top + (y1 - y) * scale

    d = Drawing("Live exercise: measured axes, policy zones, routes and engine estimates")
    d.text(32, 39, "EXERCISE / LOCAL OPERATING PICTURE", 24, weight=700)
    d.text(32, 68, "Engine estimates · equal-scale metres · synthetic policy", 15, MUTED)
    compass(d, 1026, 59)
    d.rect(left, top, plot_w, plot_h, "url(#water)", "#3c6076", 2)
    d.add(
        f'<defs><clipPath id="plot"><rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/></clipPath></defs>'
    )
    span = max(x1 - x0, y1 - y0)
    step = 10 ** math.floor(math.log10(span / 7))
    if span / step > 14:
        step *= 5
    for axis, lo, hi in (("x", x0, x1), ("y", y0, y1)):
        for i in range(math.ceil(lo / step), math.floor(hi / step) + 1):
            value = i * step
            if axis == "x":
                a, b = xy(value, y0), xy(value, y1)
                d.text(a[0], top + plot_h + 26, f"{value:g}", 14, MUTED, anchor="middle")
            else:
                a, b = xy(x0, value), xy(x1, value)
                d.text(left - 13, a[1] + 5, f"{value:g}", 14, MUTED, anchor="end")
            d.path([a, b], "#254357", 0.8)
    d.text(left, top - 14, "NORTHING (m)", 12, MUTED)
    d.text(left + plot_w, top + plot_h + 49, "EASTING (m) →", 12, MUTED, anchor="end")
    d.add('<g clip-path="url(#plot)">')
    for name, vertices in snapshot.get("routes", {}).items():
        d.path([xy(*v) for v in vertices], "#80a8cb", 2, "12 5 2 5")
        x, y = xy(*vertices[-1])
        d.text(min(x, left + plot_w - 8), y + 22, words(name), 14, "#a7c5df", anchor="end", halo=True)
    for name, zone in snapshot["zones"].items():
        color = zone_color(zone)
        vertices = [xy(*v) for v in zone["vertices"]]
        d.path(vertices, color, 2, closed=True, fill=color + "20")
        if zone["kind"] != "restricted":
            d.path(vertices, color, 1, closed=True, fill="url(#hatch)")
        zx = sum(p[0] for p in vertices) / len(vertices)
        zy = min(p[1] for p in vertices)
        d.text(zx, zy - 24, words(name), 15, color, 600, "middle", halo=True)
        d.text(zx, zy - 7, zone["kind"].upper() + " · DEMO", 10, color, anchor="middle", halo=True)
    for vessel in (context or {}).get("surface", []):
        x, y = xy(vessel["x_m"], vessel["y_m"])
        d.path(
            [(x - 10, y - 5), (x + 6, y - 5), (x + 13, y), (x + 6, y + 5), (x - 10, y + 5)],
            "#72a9e3",
            closed=True,
            fill="#72a9e3",
        )
        d.text(x + 20, y + 5, "SIM-SUPPORT · context", 14, "#72a9e3", halo=True)
    for index, track in enumerate(snapshot["tracks"], 1):
        color = COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"])
        estimate, forecast = track["estimate"], track["forecast"]
        x, y = xy(estimate["x_m"], estimate["y_m"])
        if show_uncertainty:
            d.circle(x, y, forecast.get("current_uncertainty_radius_m", 0) * scale, color + "18", color)
        if show_forecasts:
            d.path([xy(p["x_m"], p["y_m"]) for p in forecast["points"]], color, 2.5, "7 6")
            for p in forecast["points"]:
                seconds = p["seconds_ahead"]
                if seconds and (seconds % 20 == 0 or p is forecast["points"][-1]):
                    px, py = xy(p["x_m"], p["y_m"])
                    d.circle(px, py, 3, "#091e30", color)
                    last = forecast["points"][-1]
                    end = xy(last["x_m"], last["y_m"])
                    if p is last or math.dist((px, py), end) > 55:
                        d.text(px, py - 10, f"+{seconds:g}s", 11, color, anchor="middle", halo=True)
        if estimate["velocity_established"] and estimate["speed_mps"] > 0.05:
            angle = math.atan2(-estimate["vy_mps"], estimate["vx_mps"])
            dx, dy = math.cos(angle), math.sin(angle)
            tip = (x + 32 * dx, y + 32 * dy)
            d.path([(x, y), tip], color, 2)
            d.path(
                [
                    (tip[0] - 9 * dx + 4 * dy, tip[1] - 9 * dy - 4 * dx),
                    tip,
                    (tip[0] - 9 * dx - 4 * dy, tip[1] - 9 * dy + 4 * dx),
                ],
                color,
                2,
            )
        d.circle(x, y, 11, color, INK, 2)
        d.text(x, y + 4, index, 12, "#091e30", 700, "middle")
        tx = max(left + 8, min(x - 15, left + plot_w - 190))
        d.text(tx, max(top + 20, y - 25), f"{index:02d} / {track['track_id']}", 14, color, 600, halo=True)
    d.add("</g>")
    d.rect(1080, 94, 332, 708, "#102a3e", "#284b63", 12)
    d.text(1102, 126, "TRACK REGISTER", 15, weight=700)
    if not snapshot["tracks"]:
        d.text(1102, 165, "Awaiting observations", 18, MUTED)
        d.text(1102, 192, "Start an exercise to populate", 14, MUTED)
        d.text(1102, 213, "live tracks, zones and routes.", 14, MUTED)
    for index, track in enumerate(snapshot["tracks"][:3], 1):
        color = COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"])
        y = 160 + (index - 1) * 133
        d.text(1102, y, f"{index:02d}  {track['track_id']}", 16, color, 700)
        d.text(
            1102,
            y + 24,
            f"{track['risk']['current_band']} / {track['capability']['data_quality']}",
            13,
            color,
        )
        est = track["estimate"]
        d.text(1102, y + 47, f"E {est['x_m']:.0f} m · N {est['y_m']:.0f} m", 13, MUTED)
        d.text(
            1102,
            y + 68,
            f"{est['speed_mps']:.1f} m/s · age {track['source']['observation_age_seconds']:.1f}s",
            13,
            MUTED,
        )
        d.text(1102, y + 91, words(track["recommendation"]["primary_action"]), 14)
    if len(snapshot["tracks"]) > 3:
        d.text(1102, 547, f"+ {len(snapshot['tracks']) - 3} tracks in assessments below", 12, MUTED)
    d.text(1102, 582, "READING THE MAP", 14, weight=700)
    d.path([(1102, 606), (1130, 606)], "#a7c5df", 2, "10 4 2 4")
    d.text(1142, 611, "Mission reference route", 13, MUTED)
    d.path([(1102, 634), (1130, 634)], "#43d9b5", 2, "7 5")
    d.text(1142, 639, "Conditional forecast", 13, MUTED)
    d.circle(1115, 662, 10, "none", "#43d9b5")
    d.text(1142, 667, "Uncertainty radius (2σ)", 13, MUTED)
    d.text(1102, 696, "Uncalibrated; not a confidence boundary.", 12, MUTED)
    for i, (label, color) in enumerate(list(COLORS.items())[:3]):
        d.circle(1107 + i * 100, 726, 5, color)
        d.text(1118 + i * 100, 730, label, 11, color)
    d.text(1102, 765, "Risk is advisory · human decision", 13, MUTED)
    d.path([(left, 803), (left + step * scale, 803)], INK, 4)
    d.text(left, 827, f"{step:g} m", 12, MUTED)
    d.text(325, 827, "Rings = current position uncertainty · Arrows = estimated heading", 13, MUTED)
    return d.finish()


def geographic_map(
    snapshot=None,
    context=None,
    focus=False,
    *,
    area_focus=None,
    show_context=True,
    show_labels=True,
    show_forecasts=True,
    show_uncertainty=True,
):
    """Geographic context with labeled landmarks and authoritative API overlays."""
    import pydeck as pdk

    snapshot = snapshot or empty_map()
    terminals = [
        {
            **t,
            "color": rgb(t["color"]),
            "name": t["name"] + "\nApproximate public landmark · illustrative anchor",
        }
        for t in TERMINALS
    ]
    zones = [
        dict(
            polygon=[project(x, y) for x, y in z["vertices"]],
            position=project(*z["vertices"][0]),
            label=words(key),
            name=f"{key}\n{z['kind'].upper()} · synthetic session policy",
            color=rgb(zone_color(z), 85),
        )
        for key, z in snapshot["zones"].items()
    ]
    routes = [
        dict(
            path=[project(*p) for p in vertices],
            name=words(name) + "\nMission reference route · synthetic policy",
        )
        for name, vertices in snapshot.get("routes", {}).items()
    ]
    tracks, paths = [], []
    for track in snapshot["tracks"]:
        color = rgb(COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"]))
        est = track["estimate"]
        tracks.append(
            dict(
                position=project(est["x_m"], est["y_m"]),
                label=track["track_id"],
                color=color,
                radius=track["forecast"].get("current_uncertainty_radius_m", 0),
                name=f"{track['track_id']} · {track['risk']['current_band']}\n"
                f"{track['capability']['data_quality']} · {est['speed_mps']:.1f} m/s · observation age {track['source']['observation_age_seconds']:.1f}s\n"
                f"Action: {words(track['recommendation']['primary_action'])}",
            )
        )
        if len(track["forecast"]["points"]) > 1:
            paths.append(
                dict(
                    path=[project(p["x_m"], p["y_m"]) for p in track["forecast"]["points"]],
                    color=color,
                    name=track["track_id"] + " · conditional forecast",
                )
            )
    surface = [
        dict(position=project(v["x_m"], v["y_m"]), name=v["name"] + " · context only")
        for v in (context or {}).get("surface", [])
    ]
    x0, y0, x1, y1 = snapshot["bounds"]
    outline = [project(x, y) for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
    center = project((x0 + x1) / 2, (y0 + y1) / 2)
    selected = next((t for t in TERMINALS if t["label"] == area_focus), None)
    longitude, latitude, zoom = (-118.215, 33.761, 12.65)
    if focus:
        longitude, latitude, zoom = *center, 15
    elif selected:
        longitude, latitude, zoom = selected["lon"], selected["lat"], 14.5
    text_style = dict(outline_width=3, outline_color=[9, 30, 48], font_settings={"sdf": True})
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            terminals,
            id="harbor-terminals",
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius=65,
            radius_min_pixels=5,
            radius_max_pixels=12,
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            terminals,
            id="terminal-labels",
            visible=show_labels,
            get_position="[lon, lat]",
            get_text="label",
            get_size=16,
            get_color=[235, 246, 255],
            get_pixel_offset=[0, -22],
            **text_style,
        ),
        pdk.Layer(
            "TextLayer",
            WATERWAYS,
            id="waterway-labels",
            visible=show_labels and not focus and selected is None,
            get_position="[lon, lat]",
            get_text="name",
            get_size=13,
            get_color=[132, 180, 204],
            **text_style,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            context_vessels(),
            id="context-vessels",
            visible=show_context,
            get_position="[lon, lat]",
            get_fill_color=[58, 157, 255, 170],
            get_radius=30,
            radius_min_pixels=3,
            radius_max_pixels=5,
            pickable=True,
        ),
        pdk.Layer(
            "PathLayer",
            [dict(path=outline, name="Exercise frame · synthetic local metres")],
            id="exercise-boundary",
            get_path="path",
            get_color=[106, 214, 225],
            get_width=2,
            width_units="pixels",
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            [dict(position=project(x0, y1), label="EXERCISE AREA · SYNTHETIC")],
            id="exercise-label",
            get_position="position",
            get_text="label",
            get_size=12,
            get_color=[106, 214, 225],
            get_text_anchor="start",
            get_pixel_offset=[0, -14],
            **text_style,
        ),
        pdk.Layer(
            "PathLayer",
            routes,
            id="engine-routes",
            get_path="path",
            get_color=[128, 168, 203, 150],
            get_width=2,
            width_units="pixels",
            pickable=True,
        ),
        pdk.Layer(
            "PolygonLayer",
            zones,
            id="engine-zones",
            get_polygon="polygon",
            get_fill_color="color",
            get_line_color="color",
            line_width_min_pixels=2,
            stroked=True,
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            zones,
            id="zone-labels",
            get_position="position",
            get_text="label",
            get_size=13,
            get_color=[255, 210, 190],
            get_pixel_offset=[0, 14],
            visible=focus,
            **text_style,
        ),
        pdk.Layer(
            "PathLayer",
            paths,
            id="engine-forecasts",
            visible=show_forecasts,
            get_path="path",
            get_color="color",
            get_width=3,
            width_units="pixels",
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            tracks,
            id="engine-uncertainty",
            visible=show_uncertainty,
            get_position="position",
            get_radius="radius",
            filled=False,
            stroked=True,
            get_line_color="color",
            line_width_min_pixels=1,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            tracks,
            id="engine-tracks",
            get_position="position",
            get_fill_color="color",
            get_radius=12,
            radius_min_pixels=6,
            radius_max_pixels=10,
            get_line_color=[240, 248, 255],
            line_width_min_pixels=2,
            stroked=True,
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            tracks,
            id="track-labels",
            get_position="position",
            get_text="label",
            get_size=13,
            get_color="color",
            get_pixel_offset=[12, -24],
            get_text_anchor="start",
            **text_style,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            surface,
            id="sim-support",
            visible=show_context,
            get_position="position",
            get_fill_color=[114, 169, 227],
            get_radius=12,
            radius_min_pixels=4,
            pickable=True,
        ),
    ]
    return pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        map_provider="carto",
        initial_view_state=pdk.ViewState(latitude=latitude, longitude=longitude, zoom=zoom, pitch=0),
        layers=layers,
        tooltip={"text": "{name}", "style": {"backgroundColor": "#102a3e", "color": "#e9f3fc"}},
    )


def harbor_layout(
    snapshot=None, context=None, *, area_focus=None, show_context=True, show_labels=True, show_forecasts=True
):
    """Detailed offline schematic; deliberately not surveyed navigation geometry."""
    snapshot = snapshot or empty_map()
    d = Drawing("Long Beach Harbor: all pier areas, waterways and synthetic exercise inset")
    d.rect(24, 88, 1085, 690, "url(#water)", "#284b63", 12)
    d.text(32, 39, "LONG BEACH / HARBOR ATLAS", 26, weight=700)
    d.text(32, 66, "Public landmarks · illustrative facilities · live synthetic exercise inset", 15, MUTED)
    d.path(
        [
            (70, 155),
            (70, 98),
            (407, 98),
            (407, 150),
            (980, 150),
            (1085, 215),
            (1085, 255),
            (876, 255),
            (876, 322),
            (806, 322),
            (806, 160),
        ],
        "#365366",
        2,
        closed=True,
        fill="#172f3e",
    )
    d.path([(75, 301), (412, 301), (562, 264), (814, 264)], "#637c89", 7)
    d.path([(75, 301), (412, 301), (562, 264), (814, 264)], "#253d4b", 3)
    d.text(139, 309, "OCEAN BLVD · BRIDGE CONNECTION", 10, INK, halo=True)
    d.path([(840, 174), (840, 325), (855, 489), (875, 570), (939, 622)], "#526d7c", 5)
    d.text(866, 197, "LANDSIDE ACCESS", 11, MUTED)
    for t in TERMINALS:
        color = t["color"]
        selected = area_focus == t["label"]
        d.path(
            t["outline"],
            color if selected else "#58717b",
            3 if selected else 1.5,
            closed=True,
            fill="#1c3846",
        )
        d.path(t["outline"], color, 1, closed=True, fill=color + "16")
        x, y = t["anchor"]
        if t["kind"] == "Cargo":
            for row in range(2):
                for col in range(5):
                    d.rect(x - 56 + col * 24, y + 17 + row * 12, 19, 7, color + "70", radius=1)
            for col in range(3):
                cx = x - 38 + col * 38
                d.path([(cx - 6, y - 25), (cx - 6, y - 43), (cx + 12, y - 43), (cx + 17, y - 36)], color, 1.4)
        elif t["kind"] == "Logistics":
            for row in (-12, 12):
                d.path([(442, y + row), (938, y + row)], color, 1.5)
                for rx in range(448, 939, 12):
                    d.path([(rx, y + row - 3), (rx, y + row + 3)], color, 0.8)
        elif t["kind"] == "Port facilities":
            for col in range(3):
                d.circle(x - 25 + col * 25, y + 24, 8, "#1b3345", color)
        else:
            d.path(
                [(x - 32, y + 20), (x + 28, y + 20), (x + 38, y + 29), (x - 27, y + 29)],
                color,
                closed=True,
                fill=color + "60",
            )
        if show_labels:
            d.text(x, y + 5, t["label"], 19, color, 700, "middle", halo=True)
    if show_labels:
        for water in WATERWAYS:
            x, y = water["anchor"]
            lines = (
                water["name"].split()
                if water["name"] in {"Middle Harbor", "Back Channel", "Southeast Basin"}
                else [water["name"]]
            )
            for i, line in enumerate(lines):
                d.text(x, y + i * 18, line.upper(), 12, "#91b6cb", anchor="middle", halo=True)
        d.text(960, 241, "LONG BEACH WATERFRONT", 11, MUTED, anchor="middle")
        d.text(193, 570, "TERMINAL ISLAND", 11, MUTED, anchor="middle")
    if show_context:
        for vessel in context_vessels():
            x, y = vessel["anchor"]
            d.path(
                [(x - 9, y - 3), (x + 5, y - 3), (x + 11, y), (x + 5, y + 3), (x - 9, y + 3)],
                "#539bd0",
                1,
                closed=True,
                fill="#397eaf",
            )
    # Clearly labeled inset prevents confusing schematic geometry with geography.
    x0, y0, x1, y1 = snapshot["bounds"]
    ex, ey, ew, eh = 88, 659, 255, 93
    d.rect(ex, ey, ew, eh, "#16465a" if area_focus == "Exercise area" else "#0c293b", "#6ad6e1", 4)
    d.text(ex, ey - 10, "EXERCISE INSET · SYNTHETIC", 12, "#6ad6e1", 700)

    def xy(x, y):
        return ex + (x - x0) / (x1 - x0) * ew, ey + (y1 - y) / (y1 - y0) * eh

    d.add(
        f'<defs><clipPath id="inset"><rect x="{ex}" y="{ey}" width="{ew}" height="{eh}"/></clipPath></defs><g clip-path="url(#inset)">'
    )
    for vertices in snapshot.get("routes", {}).values():
        d.path([xy(*v) for v in vertices], "#80a8cb", 1, "5 3")
    for zone in snapshot["zones"].values():
        color = zone_color(zone)
        d.path([xy(*v) for v in zone["vertices"]], color, 1, closed=True, fill=color + "30")
    for track in snapshot["tracks"]:
        color = COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"])
        if show_forecasts:
            d.path([xy(p["x_m"], p["y_m"]) for p in track["forecast"]["points"]], color, 2, "5 3")
        x, y = xy(track["estimate"]["x_m"], track["estimate"]["y_m"])
        d.circle(x, y, 4, color, INK)
    if not snapshot["tracks"]:
        d.text(ex + ew / 2, ey + eh / 2 + 4, "Awaiting exercise", 14, MUTED, anchor="middle")
    d.add("</g>")
    compass(d, 1057, 718)
    d.rect(1130, 88, 282, 690, "#102a3e", "#284b63", 12)
    d.text(1150, 121, "AREA DIRECTORY", 15, weight=700)
    for i, t in enumerate(TERMINALS):
        y = 155 + i * 36
        d.circle(1160, y - 5, 11, "#193a4d", t["color"])
        d.text(1160, y - 1, t["code"], 12, t["color"], 700, "middle")
        d.text(1180, y, t["label"] + " / " + t["kind"], 14, t["color"])
    d.text(1150, 571, "MAP KEY", 14, weight=700)
    for i, (label, color) in enumerate(
        [
            ("Cargo / container area", "#e8b86d"),
            ("Rail / logistics", "#70d4ce"),
            ("Other port facilities", "#b1a4d8"),
            ("Cruise / waterfront", "#8dc78b"),
            ("Static fictional vessel", "#539bd0"),
        ]
    ):
        y = 600 + i * 26
        d.rect(1150, y - 10, 12, 12, color, radius=2)
        d.text(1175, y, label, 13, MUTED)
    d.text(1150, 747, "11 areas · 8 named waterways", 13, MUTED)
    d.text(32, 813, "SCHEMATIC · NOT TO SCALE", 13, "#6ad6e1", 600)
    d.text(
        32,
        838,
        "Facility shapes, internal assets and vessel positions are illustrative. See Exercise detail for measured tracks and policy geometry.",
        14,
        MUTED,
    )
    return d.finish()
