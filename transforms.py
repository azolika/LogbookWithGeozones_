import datetime as dt
from datetime import timezone
from typing import List, Dict, Any, Optional

from geoutils import geozones_for_point

def parse_iso(ts: Optional[str]) -> Optional[dt.datetime]:
    try:
        if ts and ts.endswith("Z"):
            return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.datetime.fromisoformat(ts) if ts else None
    except Exception:
        return dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") if ts else None

def _combine_trips(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Egybefűz több, egymást követő tripet egyetlen trip-pé."""
    first, last = group[0], group[-1]
    return {
        # kezdő és záró blokkokat átvesszük az első/utolsóból
        "trip_start": first.get("trip_start") or {},
        "trip_end": last.get("trip_end") or {},
        # összegezzük a számokat
        "mileage": sum(float(t.get("mileage") or 0.0) for t in group),
        "trip_duration": int(sum(int(t.get("trip_duration") or 0) for t in group)),
        # típus: az utolsó (vagy "merged")
        "trip_type": last.get("trip_type") or first.get("trip_type") or "merged",
        # bármi egyéb mezőt, ami kellhet, itt később hozzá lehet adni
    }

def merge_short_trips(trips: List[Dict[str, Any]], min_minutes: int) -> List[Dict[str, Any]]:
    """
    Az N percnél rövidebb trippeket összevonja a szomszédosakkal.
    - Időrendben dolgozik.
    - Egy futó "rövid" csoportot a következő "nem rövid" trippel egyesít.
    - Ha a lista végén marad "rövid" csoport, azt az előző elemmel fűzi egybe.
    - Ha minden elem rövid, mindet egyetlen trip-pé fűzi.
    min_minutes <= 0 esetén nem módosít.

    """
    if not trips or min_minutes is None or min_minutes <= 0:
        return trips

    thr_s = int(min_minutes) * 60

    def start_dt(t: Dict[str, Any]) -> Optional[dt.datetime]:
        return parse_iso((t.get("trip_start") or {}).get("datetime"))

    trips_sorted = sorted(trips, key=lambda t: start_dt(t) or dt.datetime.min)
    result: List[Dict[str, Any]] = []
    pending_short: List[Dict[str, Any]] = []

    for t in trips_sorted:
        dur = int(t.get("trip_duration") or 0)
        if dur < thr_s:
            # gyűjtjük a rövid trippeket
            pending_short.append(t)
            continue

        # aktuális trip már nem rövid
        if pending_short:
            # rövid csoport + aktuális nem-rövid → egybe fűzzük
            merged = _combine_trips(pending_short + [t])
            result.append(merged)
            pending_short = []
        else:
            result.append(t)

    # ha a végén maradt rövid csoport
    if pending_short:
        if result:
            last_long = result.pop()
            merged = _combine_trips([last_long] + pending_short)
            result.append(merged)
        else:
            # minden trip rövid volt
            result.append(_combine_trips(pending_short))

    return result


def pair_out_in(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OUT->IN párosítás; a zónanév + cím egyetlen mezőben: '<b style='color:red'>Zóna</b> : Cím'."""
    rows: List[Dict[str, Any]] = []
    pending_out: Optional[Dict[str, Any]] = None

    def zone_with_address(ev: Dict[str, Any]) -> str:
        name = ev.get("geozone_name") or ""
        addr = ev.get("geozone_address") or {}  # dict
        addr_str = format_address(addr) if isinstance(addr, dict) else str(addr or "")
        return f"<b style='color:red'>{name}</b> : {addr_str}"

    for ev in events:
        direction = (ev.get("direction") or "").upper()
        if direction == "OUT":
            pending_out = ev
        elif direction == "IN":
            if pending_out:
                rows.append({
                    "Departure": zone_with_address(pending_out),
                    "Departure at": pending_out.get("dt"),
                    "Departure mileage": pending_out.get("mileage"),
                    "Arrival": zone_with_address(ev),
                    "Arrival at": ev.get("dt"),
                    "Arrival mileage": ev.get("mileage"),
                })
                pending_out = None
    return rows

def format_address(addr: Optional[Dict[str, Any]]) -> str:
    if not addr:
        return ""
    parts = [
        addr.get("country"),
        addr.get("region"),
        addr.get("locality"),
        addr.get("street"),
        addr.get("house_number"),
        addr.get("zip"),
    ]
    return ", ".join([p for p in parts if p])

def trips_to_zone_pairs(trips: List[Dict[str, Any]], geozones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Creates zone-to-zone transition rows:
    - Aggregates total distance and duration (from multiple trips)
    - Adds "Stay (hh:mm:ss)" column showing how long the vehicle stayed
      in the arrival zone before the next trip started (based on Trips API only)
    """

    def fmt_hms(total_seconds: float | int | None) -> str:
        s = int(total_seconds or 0)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"

    # Előkészítés: trip -> zónák, idők, címek
    prepared: List[Dict[str, Any]] = []
    for t in trips:
        start = t.get("trip_start", {}) or {}
        end = t.get("trip_end", {}) or {}
        s_lat, s_lon = start.get("latitude"), start.get("longitude")
        e_lat, e_lon = end.get("latitude"), end.get("longitude")
        prepared.append({
            "trip": t,
            "start_dt": parse_iso(start.get("datetime")),
            "end_dt": parse_iso(end.get("datetime")),
            "start_zones": geozones_for_point(s_lat, s_lon, geozones),
            "end_zones": geozones_for_point(e_lat, e_lon, geozones),
            "start_address": format_address(start.get("address")),
            "end_address": format_address(end.get("address")),
        })

    # Időrend
    prepared.sort(key=lambda x: (x["start_dt"] or dt.datetime.min.replace(tzinfo=timezone.utc)))

    rows: List[Dict[str, Any]] = []

    # Aktív szegmens állapot
    active_dep_name: Optional[str] = None
    active_dep_addr: Optional[str] = None
    active_dep_dt: Optional[dt.datetime] = None
    active_total_meters: float = 0.0
    active_total_duration_s: int = 0

    def close_segment(arr_names: List[str], arr_addr: str, arr_dt: Optional[dt.datetime],
                      stay_seconds: Optional[int] = None) -> None:
        """Lezár egy szegmenst és hozzáadja a táblához"""
        nonlocal active_dep_name, active_dep_addr, active_dep_dt, active_total_meters, active_total_duration_s
        if not active_dep_name:
            return
        rows.append({
            "Departure": f"<b style='color:red'>{active_dep_name}</b> : {active_dep_addr or ''}",
            "Departure at": active_dep_dt,
            "Arrival": f"<b style='color:red'>{', '.join(arr_names)}</b> : {arr_addr or ''}",
            "Arrival at": arr_dt,
            "Distance (km)": round((active_total_meters or 0.0) / 1000.0, 3),
            "Duration": fmt_hms(active_total_duration_s),
            "Stay (hh:mm:ss)": fmt_hms(stay_seconds) if stay_seconds is not None else "",
        })
        # reset
        active_dep_name = None
        active_dep_addr = None
        active_dep_dt = None
        active_total_meters = 0.0
        active_total_duration_s = 0

    for idx, item in enumerate(prepared):
        trip = item["trip"]
        trip_meters = float(trip.get("mileage") or 0.0)
        trip_dur_s = int(trip.get("trip_duration") or 0)
        start_has_zone = bool(item["start_zones"])
        end_has_zone = bool(item["end_zones"])

        # Szegmens nyitása, ha zónából indul
        if active_dep_name is None and start_has_zone:
            active_dep_name = ", ".join(item["start_zones"])
            active_dep_addr = item["start_address"]
            active_dep_dt = item["start_dt"]
            active_total_meters = 0.0
            active_total_duration_s = 0

        # Ha van aktív szegmens, MINDEN trip távját és idejét hozzáadjuk
        if active_dep_name is not None:
            active_total_meters += trip_meters
            active_total_duration_s += trip_dur_s

            # Ha zónában ér véget, lezárjuk
            if end_has_zone:
                # Következő trip kezdete (stay kiszámításhoz)
                stay_seconds = None
                if idx + 1 < len(prepared):
                    next_trip = prepared[idx + 1]
                    if next_trip.get("start_dt") and item.get("end_dt"):
                        delta = (next_trip["start_dt"] - item["end_dt"]).total_seconds()
                        if delta > 0:
                            stay_seconds = int(delta)

                close_segment(item["end_zones"], item["end_address"], item["end_dt"], stay_seconds)
                continue

            # Ha közben újra zónából indul (pl. másik zóna)
            if start_has_zone:
                active_dep_name = ", ".join(item["start_zones"])
                active_dep_addr = item["start_address"]
                active_dep_dt = item["start_dt"]
                active_total_meters = trip_meters
                active_total_duration_s = trip_dur_s

    # Nyitott szegmens (nincs záró zóna) nem kerül be
    return rows

