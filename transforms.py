from geoutils import geozones_for_point
from datetime import timezone
import datetime as dt
from typing import List, Dict, Any, Optional


def parse_iso(ts: Optional[str]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt_obj = dt.datetime.fromisoformat(ts)
        # ha tz-naiv, tekintsük UTC-nek
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
        return dt_obj
    except Exception:
        # utolsó fallback: tekintsük UTC-nek
        dt_obj = dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        return dt_obj.replace(tzinfo=timezone.utc)

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

# transforms.py


def merge_short_trips(
    trips: List[Dict[str, Any]],
    min_minutes: int = 0,
    max_gap_minutes: int = 0,
) -> List[Dict[str, Any]]:
    """
    Trip-összevonás két szabály szerint:
      1) min_minutes: az ennél rövidebb trippeket a szomszédaikkal egyesíti
      2) max_gap_minutes: ha két trip között a szünet <= küszöb, azokat összevonja
         (pl. border crossing, rövid megálló). 0-val kikapcsolható.

    Megjegyzések:
    - Időrendben dolgozik.
    - Az egymást érő (0 mp gap) trippeket automatikusan összevonja, ha max_gap_minutes >= 0.
    """
    if not trips:
        return trips

    thr_s = max(0, int(min_minutes)) * 60
    gap_thr_s = max(0, int(max_gap_minutes)) * 60

    def parse_iso(ts: Optional[str]) -> Optional[dt.datetime]:
        if not ts:
            return None
        try:
            if ts.endswith("Z"):
                return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            obj = dt.datetime.fromisoformat(ts)
            return obj if obj.tzinfo else obj.replace(tzinfo=dt.timezone.utc)
        except Exception:
            obj = dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
            return obj.replace(tzinfo=dt.timezone.utc)

    def start_dt(t: Dict[str, Any]) -> Optional[dt.datetime]:
        return parse_iso((t.get("trip_start") or {}).get("datetime"))

    def end_dt(t: Dict[str, Any]) -> Optional[dt.datetime]:
        return parse_iso((t.get("trip_end") or {}).get("datetime"))

    def _combine(group: List[Dict[str, Any]]) -> Dict[str, Any]:
        first, last = group[0], group[-1]
        return {
            "trip_start": first.get("trip_start") or {},
            "trip_end":   last.get("trip_end") or {},
            "mileage":    sum(float(x.get("mileage") or 0.0) for x in group),
            "trip_duration": int(sum(int(x.get("trip_duration") or 0) for x in group)),
            "trip_type":  last.get("trip_type") or first.get("trip_type") or "merged",
        }

    trips_sorted = sorted(trips, key=lambda t: start_dt(t) or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    result: List[Dict[str, Any]] = []
    group: List[Dict[str, Any]] = []

    for t in trips_sorted:
        dur = int(t.get("trip_duration") or 0)

        if not group:
            group = [t]
            continue

        prev = group[-1]
        prev_end = end_dt(prev)
        curr_start = start_dt(t)
        gap_s = None
        if prev_end and curr_start:
            gap_s = int((curr_start - prev_end).total_seconds())

        # ha rövid a trip VAGY a gap <= küszöb → megy a csoportba
        if dur < thr_s or (gap_s is not None and gap_s <= gap_thr_s):
            group.append(t)
        else:
            # lezárjuk az előző csoportot és új csoportot kezdünk
            result.append(_combine(group))
            group = [t]

    if group:
        result.append(_combine(group))

    return result

    if not trips or min_minutes is None or min_minutes < 0:
        return trips

    thr_s = int(min_minutes) * 60

    def start_dt(t: Dict[str, Any]) -> Optional[dt.datetime]:
        return parse_iso((t.get("trip_start") or {}).get("datetime"))

    def end_dt(t: Dict[str, Any]) -> Optional[dt.datetime]:
        return parse_iso((t.get("trip_end") or {}).get("datetime"))

    trips_sorted = sorted(trips, key=lambda t: start_dt(t) or dt.datetime.min)
    result: List[Dict[str, Any]] = []
    pending_group: List[Dict[str, Any]] = []

    for i, t in enumerate(trips_sorted):
        dur = int(t.get("trip_duration") or 0)

        # ha ez az első trip, mindig kezdünk vele
        if not pending_group:
            pending_group = [t]
            continue

        prev = pending_group[-1]
        prev_end = end_dt(prev)
        curr_start = start_dt(t)
        gap_s = None
        if prev_end and curr_start:
            gap_s = (curr_start - prev_end).total_seconds()

        # ha rövid vagy nulla szünet van az előzőhöz képest, vagy a trip rövid, akkor összevonjuk
        if (gap_s is not None and gap_s <= 0) or dur < thr_s:
            pending_group.append(t)
            continue

        # különben lezárjuk az eddigit és új csoportot kezdünk
        if pending_group:
            merged = _combine_trips(pending_group)
            result.append(merged)
        pending_group = [t]

    # maradék lezárása
    if pending_group:
        merged = _combine_trips(pending_group)
        result.append(merged)

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

    def parse_hms(hms: str | None) -> int:
        """'HH:MM:SS' -> összes másodperc. Üres/None -> 0."""
        if not hms or not isinstance(hms, str):
            return 0
        try:
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            return 0

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

