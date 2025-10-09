import math
from typing import Dict, List, Optional

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Earth's radius in meters
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def point_in_circle(lat: float, lon: float, circle: Dict) -> bool:
    # Check if a point is inside a circle
    if not circle:
        return False
    c_lat = circle.get("latitude")
    c_lon = circle.get("longitude")
    r = circle.get("radius")
    if c_lat is None or c_lon is None or r is None:
        return False
    return haversine_m(lat, lon, c_lat, c_lon) <= float(r)

def point_in_polygon(lat: float, lon: float, polygon_coords: List[List[List[float]]]) -> bool:
    """Ray casting on first ring; coords are [[lon, lat], ...]."""
    # Check if a point is inside a polygon (first ring only)
    if not polygon_coords or not polygon_coords[0]:
        return False
    ring = polygon_coords[0]
    x, y = lon, lat
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        intersects = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1)
        if intersects:
            inside = not inside
    return inside

def geozones_for_point(lat: Optional[float], lon: Optional[float], geozones: List[Dict]) -> List[str]:
    """Return geozone names that contain the point."""
    # Iterate through geozones and collect those containing the point
    if lat is None or lon is None:
        return []
    names: List[str] = []
    for g in geozones:
        gtype = g.get("type")
        if gtype == "POINT":
            if point_in_circle(lat, lon, g.get("circle")):
                names.append(g.get("name"))
        elif gtype == "POLYGON":
            geom = (g.get("feature") or {}).get("geometry") or {}
            coords = geom.get("coordinates")
            if coords and point_in_polygon(lat, lon, coords):
                names.append(g.get("name"))
    return names
