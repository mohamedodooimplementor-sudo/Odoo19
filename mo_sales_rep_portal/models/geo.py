from math import asin, cos, radians, sin, sqrt


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(radians, (lat1, lng1, lat2, lng2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def nearest_neighbour_order(points, start=None):
    """points: list of (key, lat, lng). Returns keys ordered greedily by distance.

    start: optional (lat, lng) origin; when missing the first point is the origin.
    """
    remaining = list(points)
    ordered = []
    if not remaining:
        return ordered
    if start is None:
        first = remaining.pop(0)
        ordered.append(first[0])
        cur = (first[1], first[2])
    else:
        cur = start
    while remaining:
        nxt = min(remaining, key=lambda p: haversine_km(cur[0], cur[1], p[1], p[2]))
        remaining.remove(nxt)
        ordered.append(nxt[0])
        cur = (nxt[1], nxt[2])
    return ordered
