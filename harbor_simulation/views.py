"""Presentation of engine snapshots; no risk classification or policy decisions."""

import hashlib
import html
import math

COLORS = {"LOW": "#43d9b5", "ELEVATED": "#ffc66d", "HIGH": "#ff6b7a", "UNKNOWN": "#a7b5cb"}

# Original Dashboard branch's illustrative public facility anchors.
TERMINALS = [
    {"name": "Pier T Container Terminal", "label": "Pier T", "kind": "Cargo", "lat": 33.752, "lon": -118.223},
    {"name": "Pier J Container Terminal", "label": "Pier J", "kind": "Cargo", "lat": 33.744, "lon": -118.194},
    {"name": "Pier G Container Terminal", "label": "Pier G", "kind": "Cargo", "lat": 33.757, "lon": -118.205},
    {
        "name": "Pier B Rail Support Area",
        "label": "Pier B",
        "kind": "Logistics",
        "lat": 33.774,
        "lon": -118.218,
    },
]


def context_vessels():
    """Preserve the 22 original fictional markers without treating them as tracks."""
    vessels = []
    for i in range(22):
        value = int(hashlib.sha256(f"vessel-{i}".encode()).hexdigest()[:8], 16)
        vessels.append(
            {
                "name": f"SIM-V{i + 1:02d} · context only",
                "lat": 33.735 + (value % 3600) / 100000,
                "lon": -118.248 + ((value // 3600) % 6500) / 100000,
            }
        )
    return vessels


def project(x, y):
    """Display-only placement; the numerical engine continues to use local metres."""
    return [-118.23 + x / (111320 * math.cos(math.radians(33.744))), 33.744 + y / 111320]


def empty_map():
    # An idle illustration has no fabricated observations, zones, or assessments.
    return {"bounds": [0, 0, 1000, 700], "zones": {}, "tracks": []}


def local_map(snapshot, context=None):
    x0, y0, x1, y1 = snapshot["bounds"]
    width, height = x1 - x0, y1 - y0

    def flip(y):
        return y1 - y + y0

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {width} {height}" '
        'role="img" aria-label="Live synthetic harbor tracks, restricted zones and forecasts" '
        'font-family="sans-serif" style="width:100%;max-height:510px;border-radius:16px">',
        f'<rect x="{x0}" y="{y0}" width="{width}" height="{height}" rx="16" fill="#091e30"/>',
        '<defs><pattern id="grid" width="100" height="100" patternUnits="userSpaceOnUse">'
        '<path d="M 100 0 L 0 0 0 100" fill="none" stroke="#18374d" stroke-width="1"/>'
        "</pattern></defs>",
        f'<rect x="{x0}" y="{y0}" width="{width}" height="{height}" fill="url(#grid)"/>',
        '<g font-size="22" fill="#a9c8da">'
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
            f'<text x="{vertices[0][0]}" y="{flip(max(v[1] for v in vertices)) - 12}" fill="{color}" font-size="22">{html.escape(name)}</text>'
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
        parts.append(f'<text x="{x + 16}" y="{y - 20}" fill="{color}" font-size="24">{label}</text>')
    for vessel in (context or {}).get("surface", []):
        x, y = vessel["x_m"], flip(vessel["y_m"])
        parts.append(f'<rect x="{x - 8}" y="{y - 5}" width="22" height="10" rx="3" fill="#72a9e3"/>')
        parts.append(
            f'<text x="{x + 20}" y="{y}" fill="#72a9e3" font-size="22">SIM-SUPPORT · context only</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def geographic_map(snapshot=None, context=None, focus=False):
    """Restore the Dashboard's harbor view and overlay actual API tracks/forecasts."""
    import pydeck as pdk

    snapshot = snapshot or empty_map()
    terminals = [
        {**t, "color": [255, 171, 65, 230] if t["kind"] == "Cargo" else [52, 210, 224, 230]}
        for t in TERMINALS
    ]
    zones = [
        {
            "polygon": [project(x, y) for x, y in z["vertices"]],
            "name": key,
            "color": [255, 107, 122, 80] if z["kind"] == "restricted" else [255, 198, 109, 80],
        }
        for key, z in snapshot["zones"].items()
    ]
    tracks, paths = [], []
    for track in snapshot["tracks"]:
        color = COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"])
        rgb = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
        tracks.append(
            {
                "position": project(track["estimate"]["x_m"], track["estimate"]["y_m"]),
                "name": f"{track['track_id']} · {track['risk']['current_band']} · {track['capability']['data_quality']}",
                "color": rgb,
            }
        )
        if len(track["forecast"]["points"]) > 1:
            paths.append(
                {
                    "path": [project(p["x_m"], p["y_m"]) for p in track["forecast"]["points"]],
                    "color": rgb,
                    "name": track["track_id"] + " · conditional forecast",
                }
            )
    surface = [
        {"position": project(v["x_m"], v["y_m"]), "name": v["name"] + " · context only"}
        for v in (context or {}).get("surface", [])
    ]
    return pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        map_provider="carto",
        initial_view_state=pdk.ViewState(
            latitude=33.747 if focus else 33.754,
            longitude=-118.225 if focus else -118.218,
            zoom=14.8 if focus else 12.3,
            pitch=0,
        ),
        layers=[
            pdk.Layer(
                "ScatterplotLayer",
                terminals,
                id="harbor-terminals",
                get_position="[lon, lat]",
                get_fill_color="color",
                get_radius=180,
                radius_min_pixels=8,
                radius_max_pixels=18,
                pickable=True,
            ),
            pdk.Layer(
                "TextLayer",
                terminals,
                id="terminal-labels",
                get_position="[lon, lat]",
                get_text="label",
                get_size=14,
                get_color=[235, 246, 255],
                get_pixel_offset=[0, -24],
            ),
            pdk.Layer(
                "ScatterplotLayer",
                context_vessels(),
                id="context-vessels",
                get_position="[lon, lat]",
                get_fill_color=[58, 157, 255, 180],
                get_radius=85,
                radius_min_pixels=3,
                radius_max_pixels=6,
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
                "PathLayer",
                paths,
                id="engine-forecasts",
                get_path="path",
                get_color="color",
                get_width=3,
                width_units="pixels",
                pickable=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                tracks,
                id="engine-tracks",
                get_position="position",
                get_fill_color="color",
                get_radius=15,
                radius_min_pixels=7,
                radius_max_pixels=12,
                get_line_color=[240, 248, 255],
                line_width_min_pixels=2,
                stroked=True,
                pickable=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                surface,
                id="sim-support",
                get_position="position",
                get_fill_color=[114, 169, 227],
                get_radius=12,
                radius_min_pixels=4,
                pickable=True,
            ),
        ],
        tooltip={"text": "{name}"},
    )


def harbor_layout(snapshot=None, context=None):
    """Self-contained schematic fallback: no tile server, WebGL, or external assets.

    Facility anchors and vessel positions match the original Dashboard. Shoreline
    shapes are deliberately illustrative, not surveyed harbor geometry.
    """
    snapshot = snapshot or empty_map()

    def xy(lon, lat):
        return (lon + 118.253) / 0.077 * 1100, (33.783 - lat) / 0.054 * 650

    def points(vertices):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in [xy(*v) for v in vertices])

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="650" viewBox="0 0 1100 650">',
        "<title>Long Beach Harbor illustrative layout with terminals, context vessels and live exercise tracks</title>",
        '<rect width="1100" height="650" rx="16" fill="#091e30"/>',
        '<defs><pattern id="water" width="45" height="45" patternUnits="userSpaceOnUse">'
        '<path d="M 0 45 L 45 45 45 0" fill="none" stroke="#163448" stroke-width="0.7"/>'
        '</pattern></defs><rect width="1100" height="650" fill="url(#water)"/>',
    ]
    land = [
        [
            (-118.253, 33.783),
            (-118.176, 33.783),
            (-118.176, 33.767),
            (-118.198, 33.767),
            (-118.209, 33.772),
            (-118.237, 33.772),
            (-118.253, 33.767),
        ],
        [(-118.232, 33.772), (-118.221, 33.772), (-118.221, 33.747), (-118.232, 33.747)],
        [(-118.215, 33.772), (-118.199, 33.772), (-118.199, 33.753), (-118.215, 33.753)],
        [
            (-118.198, 33.768),
            (-118.192, 33.768),
            (-118.192, 33.751),
            (-118.183, 33.748),
            (-118.187, 33.740),
            (-118.198, 33.742),
        ],
    ]
    for polygon in land:
        parts.append(
            f'<polygon points="{points(polygon)}" fill="#203c4a" stroke="#497180" stroke-width="2"/>'
        )
    # Container stacks make the cargo/logistics layout recognizable without map tiles.
    for terminal in TERMINALS:
        x, y = xy(terminal["lon"], terminal["lat"])
        color = "#ffab41" if terminal["kind"] == "Cargo" else "#34d2e0"
        for row in range(3):
            for col in range(4):
                parts.append(
                    f'<rect x="{x - 46 + col * 24:.1f}" y="{y - 55 + row * 13:.1f}" width="19" height="8" rx="1" fill="{color}" opacity="0.35"/>'
                )
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{color}"/>')
        parts.append(
            f'<text x="{x + 14:.1f}" y="{y + 6:.1f}" fill="{color}" font-family="sans-serif" font-size="20" font-weight="600">{terminal["label"]}</text>'
        )
    for vessel in context_vessels():
        x, y = xy(vessel["lon"], vessel["lat"])
        parts.append(
            f'<path d="M -10 -4 L 8 -4 14 0 8 4 -10 4 Z" transform="translate({x:.1f},{y:.1f})" fill="#3a9dff" opacity="0.65"><title>{html.escape(vessel["name"])}</title></path>'
        )
    for name, zone in snapshot["zones"].items():
        color = "#ff6b7a" if zone["kind"] == "restricted" else "#ffc66d"
        parts.append(
            f'<polygon points="{points([project(x, y) for x, y in zone["vertices"]])}" fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="2"><title>{html.escape(name)}</title></polygon>'
        )
    for track in snapshot["tracks"]:
        color = COLORS.get(track["risk"]["current_band"], COLORS["UNKNOWN"])
        path = points([project(p["x_m"], p["y_m"]) for p in track["forecast"]["points"]])
        x, y = xy(*project(track["estimate"]["x_m"], track["estimate"]["y_m"]))
        parts.append(f'<polyline points="{path}" stroke="{color}" stroke-width="3" fill="none"/>')
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{color}" stroke="#fff" stroke-width="1.5"><title>{html.escape(track["track_id"])}</title></circle>'
        )
    for vessel in (context or {}).get("surface", []):
        x, y = xy(*project(vessel["x_m"], vessel["y_m"]))
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="10" height="5" fill="#72a9e3"/>')
    parts.extend(
        [
            '<g font-family="sans-serif"><text x="28" y="38" fill="#e9f3fc" font-size="23" font-weight="600">LONG BEACH HARBOR</text>',
            '<text x="28" y="63" fill="#a9c8da" font-size="14">Illustrative layout · Synthetic vessel context</text>',
            '<text x="510" y="535" fill="#48738c" font-size="22" letter-spacing="4">HARBOR APPROACH</text>',
            '<text x="1040" y="570" fill="#a9c8da" font-size="22">N ↑</text>',
            '<text x="28" y="622" fill="#a9c8da" font-size="15">Amber: cargo · Cyan: logistics · Blue: context vessels · Live detail shown alongside</text></g></svg>',
        ]
    )
    return "".join(parts)
