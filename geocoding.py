from __future__ import annotations
import requests
from typing import Optional, Dict

USER_AGENT = "cargotrack-logbook/1.0 (contact: it@cargotrack.ro)"

def reverse_geocode(lat: float, lon: float) -> str:
    """Visszaad egy display_name stringet (megmarad kompatibilitásnak)."""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "zoom": 18, "addressdetails": 1}
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code == 200:
            return (resp.json() or {}).get("display_name") or ""
        return ""
    except Exception:
        return ""

def reverse_geocode_struct(lat: float, lon: float) -> Dict[str, str]:
    """
    Struktúrált cím (dict) a format_address() számára.
    Kulcsok: country, region, locality, street, house_number, zip (ha elérhető).
    """
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "zoom": 18, "addressdetails": 1, "accept-language": "en"}
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code != 200:
            return {}
        data = resp.json() or {}
        addr = data.get("address") or {}

        # normalizálás a format_address kulcsaihoz
        return {
            "country": addr.get("country") or "",
            "region": addr.get("state") or addr.get("region") or "",
            "locality": addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or "",
            "street": addr.get("road") or addr.get("pedestrian") or addr.get("footway") or addr.get("path") or "",
            "house_number": addr.get("house_number") or "",
            "zip": addr.get("postcode") or "",
        }
    except Exception:
        return {}
