# geom_extra.py
from __future__ import annotations
from typing import List, Tuple

def polygon_centroid_lonlat(first_ring: List[List[float]]) -> Tuple[float, float]:
    """
    Centroid GeoJSON-gyűrűre (első gyűrű), ami [ [lon,lat], ... ] koordinátákat tartalmaz.
    Visszatérés: (lat, lon)
    """
    ring = first_ring
    n = len(ring)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        lon, lat = ring[0]
        return (lat, lon)

    # Ha a gyűrű nincs lezárva, zárjuk le
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
        n += 1

    A = 0.0
    Cx = 0.0
    Cy = 0.0
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        cross = x1 * y2 - x2 * y1
        A += cross
        Cx += (x1 + x2) * cross
        Cy += (y1 + y2) * cross

    if A == 0.0:
        # degenerált eset: vissza az első pont
        lon, lat = ring[0]
        return (lat, lon)

    A *= 0.5
    Cx /= (6.0 * A)
    Cy /= (6.0 * A)
    return (Cy, Cx)  # (lat, lon)
