"""Presentation of engine snapshots; no risk classification or policy decisions."""

import html
import math

COLORS = {"LOW": "#43d9b5", "MEDIUM": "#ffc66d", "HIGH": "#ff6b7a", "UNKNOWN": "#a7b5cb"}


def local_map(snapshot, context=None):
    x0, y0, x1, y1 = snapshot["bounds"]
    width, height = x1 - x0, y1 - y0

    def flip(y):
        return y1 - y + y0

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {width} {height}" '
        'role="img" aria-label="Live synthetic harbor tracks, restricted zones and forecasts" '
        'style="width:100%;max-height:510px;background:#091e30;border-radius:16px">',
        '<defs><pattern id="grid" width="100" height="100" patternUnits="userSpaceOnUse">'
        '<path d="M 100 0 L 0 0 0 100" fill="none" stroke="#18374d" stroke-width="1"/>'
        "</pattern></defs>",
        f'<rect x="{x0}" y="{y0}" width="{width}" height="{height}" fill="url(#grid)"/>',
        '<g font-family="sans-serif" font-size="17" fill="#a9c8da">'
        '<text x="25" y="35">HARBOR LOCAL FRAME · METRES</text>'
        '<text x="25" y="65">N ↑  /  E →</text></g>',
    ]
    for name, zone in snapshot["zones"].items():
        vertices = zone["vertices"]
        points = " ".join(f"{x},{flip(y)}" for x, y in vertices)
        color = "#ff6b7a" if zone["kind"] == "restricted" else "#ffc66d"
        parts.append(
            f'<polygon points="{points}" fill="{color}" fill-opacity="0.13" stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{vertices[0][0]}" y="{flip(max(v[1] for v in vertices)) - 12}" fill="{color}" font-size="16">{html.escape(name)}</text>'
        )
    for track in snapshot["tracks"]:
        color = COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"])
        points = " ".join(f"{p['x_m']},{flip(p['y_m'])}" for p in track["forecast"]["points"])
        x, y = track["estimate"]["x_m"], flip(track["estimate"]["y_m"])
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" stroke-dasharray="8 6"/>'
        )
        parts.append(f'<circle cx="{x}" cy="{y}" r="10" fill="{color}" stroke="#f3f9ff" stroke-width="2"/>')
        label = html.escape(track["track_id"] + " · " + track["risk"]["current_band"])
        parts.append(f'<text x="{x + 16}" y="{y - 15}" fill="{color}" font-size="17">{label}</text>')
    for vessel in (context or {}).get("surface", []):
        x, y = vessel["x_m"], flip(vessel["y_m"])
        parts.append(f'<rect x="{x - 8}" y="{y - 5}" width="22" height="10" rx="3" fill="#72a9e3"/>')
        parts.append(
            f'<text x="{x + 20}" y="{y}" fill="#72a9e3" font-size="15">SIM-SUPPORT · context only</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def geographic_map(snapshot):
    """Illustrative projection for the optional basemap; never used by the engine."""
    import pydeck as pdk

    def project(x, y):
        return [-118.23 + x / (111320 * math.cos(math.radians(33.744))), 33.744 + y / 111320]

    zones = [
        {"polygon": [project(x, y) for x, y in z["vertices"]], "name": key}
        for key, z in snapshot["zones"].items()
    ]
    tracks = [
        {"position": project(t["estimate"]["x_m"], t["estimate"]["y_m"]), "name": t["track_id"]}
        for t in snapshot["tracks"]
    ]
    return pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        initial_view_state=pdk.ViewState(latitude=33.747, longitude=-118.225, zoom=14.8),
        layers=[
            pdk.Layer(
                "PolygonLayer",
                zones,
                get_polygon="polygon",
                get_fill_color=[255, 100, 110, 65],
                get_line_color=[255, 100, 110],
                stroked=True,
                pickable=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                tracks,
                get_position="position",
                get_fill_color=[67, 217, 181],
                get_radius=15,
                pickable=True,
            ),
        ],
        tooltip={"text": "{name}"},
    )
