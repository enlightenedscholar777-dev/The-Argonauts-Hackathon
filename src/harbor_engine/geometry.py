from shapely.geometry import LineString, Point, Polygon


def first_entry(points, times, polygon):
    """Continuous segment intersection: boundaries count as membership."""
    if polygon.covers(Point(points[0])):
        return 0.0
    for i, (a, b) in enumerate(zip(points, points[1:])):
        line = LineString([a, b])
        if line.length == 0 or not line.intersects(polygon):
            continue
        hit = line.intersection(polygon)
        # Along a straight segment distance to the nearest intersection is entry distance.
        ratio = Point(a).distance(hit) / line.length
        return times[i] + ratio * (times[i + 1] - times[i])
    return None


def route_distance(position, route):
    return float(Point(position).distance(LineString(route)))


def valid_polygon(vertices):
    polygon = Polygon(vertices)
    return polygon.is_valid and not polygon.is_empty and polygon.area > 0
