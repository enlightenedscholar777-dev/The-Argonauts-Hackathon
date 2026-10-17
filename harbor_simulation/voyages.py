"""Illustrative water-route plans, not navigation charts or berth assignments.

Geographic anchors and schematic anchors deliberately have separate geometry.
Pier B is a rail/logistics area, so it has no invented vessel berth.
"""

import math


def node(lon, lat, x, y):
    return ((lon, lat), (x, y))


WEST_GATE = node(-118.220, 33.729, 600, 750)
WEST_JOIN = node(-118.224, 33.745, 500, 610)
BACK = node(-118.224, 33.755, 480, 550)
INNER = node(-118.225, 33.766, 470, 360)
EAST_GATE = node(-118.176, 33.730, 1050, 750)
EAST_JOIN = node(-118.179, 33.743, 1060, 590)
EAST_BASIN = node(-118.194, 33.749, 850, 520)


def route(code, *nodes):
    return {
        "route_id": f"pier_{code.lower()}",
        "destination": f"Pier {code}",
        "geo": [p[0] for p in nodes],
        "atlas": [p[1] for p in nodes],
    }


VOYAGE_ROUTES = [
    route(
        "A",
        WEST_GATE,
        WEST_JOIN,
        BACK,
        INNER,
        node(-118.226, 33.775, 470, 240),
        node(-118.228, 33.776, 405, 230),
    ),
    route("S", WEST_GATE, WEST_JOIN, BACK, INNER, node(-118.234, 33.767, 335, 350)),
    route("T", WEST_GATE, WEST_JOIN, BACK, node(-118.228, 33.755, 440, 480)),
    route(
        "C",
        EAST_GATE,
        EAST_JOIN,
        EAST_BASIN,
        node(-118.203, 33.771, 850, 260),
        node(-118.206, 33.776, 825, 235),
    ),
    route(
        "D",
        EAST_GATE,
        EAST_JOIN,
        EAST_BASIN,
        node(-118.205, 33.767, 850, 330),
        node(-118.207, 33.770, 805, 310),
    ),
    route(
        "E",
        EAST_GATE,
        EAST_JOIN,
        EAST_BASIN,
        node(-118.204, 33.759, 850, 430),
        node(-118.209, 33.760, 790, 410),
    ),
    route(
        "F",
        WEST_GATE,
        node(-118.213, 33.736, 670, 730),
        node(-118.214, 33.743, 670, 610),
        node(-118.216, 33.747, 640, 580),
    ),
    route("G", EAST_GATE, EAST_JOIN, EAST_BASIN, node(-118.198, 33.748, 825, 540)),
    route("H", EAST_GATE, EAST_JOIN, node(-118.178, 33.754, 1070, 470), node(-118.182, 33.756, 1030, 435)),
    route("J", EAST_GATE, node(-118.183, 33.736, 1040, 705), node(-118.187, 33.739, 980, 655)),
]


def metres(a, b):
    return math.hypot((b[0] - a[0]) * 92500, (b[1] - a[1]) * 111320)


def locate(plan, distance):
    """Interpolate both views by physical distance on the same voyage."""
    lengths = [metres(a, b) for a, b in zip(plan["geo"], plan["geo"][1:])]
    distance = max(0, min(sum(lengths), distance))
    for i, length in enumerate(lengths):
        if distance <= length or i == len(lengths) - 1:
            fraction = distance / length
            geo, atlas = [
                [a + (b - a) * fraction for a, b in zip(points[i], points[i + 1])]
                for points in (plan["geo"], plan["atlas"])
            ]
            return geo, atlas
        distance -= length


def route_length(plan):
    return sum(metres(a, b) for a, b in zip(plan["geo"], plan["geo"][1:]))
