"""Illustrative Long Beach exercise locations, not surveyed safety boundaries."""

import math

AREAS = {
    "west_basin": {"name": "West Basin", "lon": -118.231, "lat": 33.748, "anchor": [245, 588]},
    "inner_harbor": {"name": "Inner Harbor", "lon": -118.222, "lat": 33.776, "anchor": [489, 214]},
    "back_channel": {"name": "Back Channel", "lon": -118.224, "lat": 33.763, "anchor": [446, 364]},
    "middle_harbor": {"name": "Middle Harbor", "lon": -118.220, "lat": 33.751, "anchor": [478, 480]},
    "east_basin": {"name": "East Basin", "lon": -118.196, "lat": 33.750, "anchor": [884, 504]},
    "southeast_basin": {"name": "Southeast Basin", "lon": -118.184, "lat": 33.741, "anchor": [999, 581]},
    "queensway_bay": {"name": "Queensway Bay", "lon": -118.181, "lat": 33.759, "anchor": [998, 298]},
    "outer_harbor": {"name": "Outer Harbor", "lon": -118.207, "lat": 33.734, "anchor": [528, 738]},
}


def project_area(x, y, area_id="west_basin"):
    """Center the unchanged metric policy frame on a selected geographic location."""
    area = AREAS[area_id]
    return [
        area["lon"] + (x - 500) / (111320 * math.cos(math.radians(area["lat"]))),
        area["lat"] + (y - 350) / 111320,
    ]
