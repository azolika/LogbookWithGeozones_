from typing import List, Dict, Tuple
import folium

def _first_center(geozones: List[Dict]) -> Tuple[float, float]:
    # Romania center fallback
    start_lat, start_lon = 45.9432, 24.9668
    for g in geozones:
        if g.get("type") == "POINT" and g.get("circle"):
            return g["circle"]["latitude"], g["circle"]["longitude"]
        elif g.get("type") == "POLYGON":
            coords = g.get("feature", {}).get("geometry", {}).get("coordinates")
            if coords and coords[0]:
                lon, lat = coords[0][0]
                return lat, lon
    return start_lat, start_lon

def draw_geozones(geozones: List[Dict]) -> folium.Map:
    lat, lon = _first_center(geozones)
    m = folium.Map(location=[lat, lon], zoom_start=7)

    for g in geozones:
        gname = g.get("name", "unnamed")
        if g.get("type") == "POINT" and g.get("circle"):
            circle = g["circle"]
            folium.Circle(
                location=[circle["latitude"], circle["longitude"]],
                radius=circle["radius"],
                color="blue",
                fill=True,
                fill_opacity=0.3,
                tooltip=gname
            ).add_to(m)

        elif g.get("type") == "POLYGON":
            coords = g.get("feature", {}).get("geometry", {}).get("coordinates")
            if coords:
                # GeoJSON: [lon, lat]
                folium.Polygon(
                    locations=[(lat, lon) for lon, lat in coords[0]],
                    color="green",
                    fill=True,
                    fill_opacity=0.3,
                    tooltip=gname
                ).add_to(m)

    return m
