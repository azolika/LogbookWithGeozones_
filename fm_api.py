import datetime as dt
from typing import Any, Dict, List, Optional
import requests

FM_API_BASE = "https://api.fm-track.com"

def _get(url: str, api_key: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    # Add API key and version if not present, then send a GET request
    params = dict(params or {})
    params["api_key"] = api_key
    if "version=" not in url and "version" not in params:
        params["version"] = 1
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    return requests.get(url, params=params, headers=headers, timeout=60)

def _post(url: str, api_key: str, payload: Dict[str, Any]) -> requests.Response:
    # Send a POST request with API key and version
    params = {"api_key": api_key, "version": 1}
    headers = {"Content-Type": "application/json"}
    return requests.post(url, params=params, json=payload, headers=headers, timeout=60)

def list_objects(api_key: str, limit: int = 500) -> List[Dict[str, Any]]:
    # Retrieve a list of objects from the FM API
    resp = _get(f"{FM_API_BASE}/objects", api_key, params={"limit": limit})
    if resp.status_code != 200:
        raise RuntimeError(f"Objects GET failed: {resp.status_code} - {resp.text}")
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Objects response is not a list")
    return data

def list_geozones(api_key: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Returns geozones with geometry (POINT circle or POLYGON coordinates)."""
    items: List[Dict[str, Any]] = []
    continuation_token: Optional[int] = 0
    while True:
        params = {"limit": limit, "continuation_token": continuation_token, "include_geometry": 1}
        resp = _get(f"{FM_API_BASE}/geozones", api_key, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Geozones GET failed: {resp.status_code} - {resp.text}")
        data = resp.json()
        page_items = data.get("items", []) or []
        items.extend(page_items)
        ct = data.get("continuation_token", 0)
        # Stop if no continuation token or no more items
        if not ct or len(page_items) == 0:
            break
        continuation_token = ct
    return items

def find_trips(api_key: str,
               from_dt: dt.datetime,
               to_dt: dt.datetime,
               object_id: str,
               limit: int = 500) -> list[dict]:
    # Retrieve trips for a specific object within a time range, handling pagination
    trips: List[Dict[str, Any]] = []
    continuation_token: Optional[str] = None
    while True:
        params = {
            "from_datetime": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to_datetime": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": limit,
            "continuation_token": continuation_token
        }
        resp = _get(f"{FM_API_BASE}/objects/{object_id}/trips", api_key, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Trips GET failed: {resp.status_code} - {resp.text}")
        data = resp.json()
        trips.extend(data.get("trips", []) or [])
        continuation_token = data.get("continuation_token")
        # Stop if there is no continuation token
        if not continuation_token:
            break
    return trips
