"""Presentation landmarks, never engine policy or surveyed boundaries.

Names/relative geography: City of Long Beach Mobility Element, Map 10 (2013).
https://www.longbeach.gov/globalassets/lbcd/media-library/documents/planning/advance/general-plan/mobility-element/320615_lbds_mobility_element_web
Coordinates are approximate display anchors. `outline`/`anchor` are deliberately
schematic drawing coordinates, not geographic polygons or operating boundaries.
"""

AREA_COLORS = {
    "Cargo": "#e8b86d",
    "Logistics": "#70d4ce",
    "Port facilities": "#b1a4d8",
    "Waterfront": "#8dc78b",
}


def area(code, name, kind, lon, lat, anchor, outline):
    return dict(
        code=code,
        label=f"Pier {code}",
        name=name,
        kind=kind,
        lon=lon,
        lat=lat,
        anchor=anchor,
        outline=outline,
        color=AREA_COLORS[kind],
    )


TERMINALS = [
    area(
        "A",
        "Pier A · cargo area",
        "Cargo",
        -118.229,
        33.778,
        (245, 197),
        [(100, 155), (390, 155), (390, 260), (320, 260), (320, 286), (100, 286)],
    ),
    area(
        "B",
        "Pier B · rail / logistics",
        "Logistics",
        -118.214,
        33.787,
        (665, 126),
        [(420, 98), (960, 98), (960, 151), (420, 151)],
    ),
    area(
        "C",
        "Pier C · cargo area",
        "Cargo",
        -118.211,
        33.780,
        (700, 204),
        [(620, 165), (805, 165), (805, 251), (670, 251), (620, 224)],
    ),
    area(
        "D",
        "Pier D · port facilities",
        "Port facilities",
        -118.211,
        33.770,
        (659, 310),
        [(588, 276), (780, 276), (780, 356), (588, 356)],
    ),
    area(
        "E",
        "Pier E · Middle Harbor cargo",
        "Cargo",
        -118.215,
        33.763,
        (619, 403),
        [(550, 368), (764, 368), (764, 464), (550, 464)],
    ),
    area(
        "F",
        "Pier F · port facilities",
        "Port facilities",
        -118.213,
        33.751,
        (577, 521),
        [(550, 464), (631, 464), (631, 574), (574, 602), (550, 561)],
    ),
    area(
        "G",
        "Pier G · cargo area",
        "Cargo",
        -118.201,
        33.752,
        (744, 507),
        [(651, 464), (796, 464), (828, 532), (797, 558), (651, 536)],
    ),
    area(
        "H",
        "Pier H · cruise / waterfront",
        "Waterfront",
        -118.190,
        33.753,
        (945, 432),
        [(884, 330), (951, 330), (951, 379), (1005, 414), (1005, 468), (884, 468)],
    ),
    area(
        "J",
        "Pier J · cargo area",
        "Cargo",
        -118.194,
        33.739,
        (821, 636),
        [(797, 558), (836, 547), (942, 624), (920, 702), (708, 702), (708, 650)],
    ),
    area(
        "S",
        "Pier S · port facilities",
        "Port facilities",
        -118.241,
        33.770,
        (186, 342),
        [(74, 315), (310, 315), (310, 384), (74, 384)],
    ),
    area(
        "T",
        "Pier T · cargo area",
        "Cargo",
        -118.238,
        33.755,
        (241, 462),
        [(74, 399), (362, 399), (416, 440), (416, 491), (355, 551), (74, 551)],
    ),
]

WATERWAYS = [
    dict(name="Inner Harbor", lon=-118.222, lat=33.776, anchor=(489, 214)),
    dict(name="Back Channel", lon=-118.224, lat=33.763, anchor=(446, 364)),
    dict(name="West Basin", lon=-118.231, lat=33.748, anchor=(245, 588)),
    dict(name="Middle Harbor", lon=-118.220, lat=33.751, anchor=(478, 480)),
    dict(name="East Basin", lon=-118.196, lat=33.750, anchor=(884, 504)),
    dict(name="Southeast Basin", lon=-118.184, lat=33.741, anchor=(999, 581)),
    dict(name="Queensway Bay", lon=-118.181, lat=33.759, anchor=(998, 298)),
    dict(name="Outer Harbor", lon=-118.207, lat=33.734, anchor=(528, 738)),
]

# Curated, stationary fictional traffic in water, rather than random points on land.
# Separate coordinates keep the intentionally schematic view independent of WGS84.
CONTEXT_LANES = [
    ((-118.225, 33.773), (-118.224, 33.762), (466, 250), (466, 322), 4),
    ((-118.224, 33.759), (-118.222, 33.752), (480, 397), (480, 439), 3),
    ((-118.220, 33.747), (-118.208, 33.735), (540, 630), (635, 704), 5),
    ((-118.241, 33.745), (-118.231, 33.744), (112, 621), (325, 621), 4),
    ((-118.188, 33.747), (-118.180, 33.743), (953, 515), (1036, 555), 3),
    ((-118.186, 33.763), (-118.178, 33.761), (954, 337), (1043, 367), 3),
]


def context_vessels():
    vessels = []
    for start, end, drawing_start, drawing_end, count in CONTEXT_LANES:
        for i in range(count):
            fraction = (i + 0.5) / count
            lon, lat = [a + (b - a) * fraction for a, b in zip(start, end)]
            anchor = [a + (b - a) * fraction for a, b in zip(drawing_start, drawing_end)]
            vessels.append(
                dict(
                    name=f"SIM-V{len(vessels) + 1:02d} · static context only", lon=lon, lat=lat, anchor=anchor
                )
            )
    return vessels
