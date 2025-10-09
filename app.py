import datetime as dt
from datetime import timezone
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo
from fm_api import list_objects, list_geozones, find_trips
from transforms import parse_iso, trips_to_zone_pairs, format_address, geozones_for_point, merge_short_trips
import math


def round_nearest_int(x: float | int | None) -> int:
    if x is None:
        return 0
    return int(math.floor(float(x) + 0.5))

st.set_page_config(page_title="Logbook with geozones", page_icon="🗺️", layout="wide")
st.title("Logbook with geozones")

# -------- Sidebar / settings ----------
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("API key", type="password")

    tz_options = ["Europe/Vienna", "Europe/Bucharest", "Europe/Budapest", "UTC", "Europe/London"]
    user_tz_name = st.selectbox("Time zone", options=tz_options, index=0, key="tz_select")
    user_tz = ZoneInfo(user_tz_name)

    # --- Defaults in user's local time ---
    now_local = dt.datetime.now(tz=user_tz)

    # If the vehicle was changed in the main area, reset dates to today here before creating the widgets
    if st.session_state.get("reset_dates_to_today"):
        st.session_state["from_date"] = now_local.date()
        st.session_state["from_time"] = dt.time(0, 0)  # 00:00
        st.session_state["to_date"] = now_local.date()
        st.session_state["to_time"] = dt.time(23, 59)  # 23:59
        st.session_state["reset_dates_to_today"] = False

    # If not initialized yet, set defaults (today)
    if "from_date" not in st.session_state:
        st.session_state["from_date"] = now_local.date()
    if "from_time" not in st.session_state:
        st.session_state["from_time"] = dt.time(0, 0)
    if "to_date" not in st.session_state:
        st.session_state["to_date"] = now_local.date()
    if "to_time" not in st.session_state:
        st.session_state["to_time"] = dt.time(23, 59)

    # Date/time inputs (local) – these already receive values from session_state
    from_date = st.date_input("From date", value=st.session_state["from_date"], key="from_date")
    from_time = st.time_input("From time", value=st.session_state["from_time"], step=dt.timedelta(minutes=15),
                              key="from_time")
    to_date = st.date_input("To date", value=st.session_state["to_date"], key="to_date")
    to_time = st.time_input("To time", value=st.session_state["to_time"], step=dt.timedelta(minutes=15), key="to_time")

    merge_trips = st.checkbox(
        "Merge trips into zone-to-zone segments",
        value=False,
        help="If unchecked, all trips are shown (with zone names highlighted in red if applicable)."
    )

    raw_mode = st.checkbox(
        "Show raw data (no rounding)",
        value=False,
        help="If checked, distances keep 3 decimals. If unchecked, distances are rounded to nearest whole km."
    )
    short_trip_minutes = st.number_input(
        "Merge trips shorter than (minutes)",
        min_value=0, max_value=120, value=0, step=1,
        help="Trips shorter than this duration will be merged with adjacent trips. Set to 0 to disable."
    )

    stay_gap_minutes = st.number_input(
        "Merge if stay between trips ≤ (minutes)",
        min_value=0, max_value=120, value=10, step=1,
        help="If the pause between two trips is ≤ this value, they will be merged (e.g., border crossings)."
    )

# Build local datetimes, then convert to UTC for the API
from_dt_local = dt.datetime.combine(from_date, from_time).replace(tzinfo=user_tz)
to_dt_local   = dt.datetime.combine(to_date,   to_time).replace(tzinfo=user_tz)
from_dt = from_dt_local.astimezone(timezone.utc)
to_dt   = to_dt_local.astimezone(timezone.utc)

# --- Load lists after API key is entered ---
if api_key and (not st.session_state.get("objects") or not st.session_state.get("geozones")):
    try:
        st.session_state.objects = list_objects(api_key)
        st.session_state.geozones = list_geozones(api_key)
        st.sidebar.success("Objects and geozones loaded ✅")
    except Exception as e:
        st.sidebar.error(f"Loading error: {e}")
        st.stop()

if not api_key:
    st.info("Enter API key in sidebar.")
    st.stop()
if not st.session_state.get("objects"):
    st.warning("No objects available.")
    st.stop()

# --- Vehicle selector + geozone exclude ---
col1, col2 = st.columns([1, 2], vertical_alignment="bottom")

with col1:
    options = {o["name"]: o["id"] for o in st.session_state.objects}
    vehicle_name = st.selectbox("Select Vehicle", options=list(options.keys()))
    vehicle_id = options[vehicle_name]

    # If the user switched to a new vehicle → request date reset and trigger rerun
    if st.session_state.get("last_vehicle") != vehicle_id:
        st.session_state["last_vehicle"] = vehicle_id
        st.session_state["reset_dates_to_today"] = True
        st.rerun()

with col2:
    all_zone_names = [g["name"] for g in st.session_state.geozones]
    excluded_zone_names = st.multiselect(
        "Exclude geozones (optional)",
        options=sorted(all_zone_names),
        default=[],
        help="The selected geozones will not be considered when checking whether a point falls inside a zone."
    )

def get_filtered_geozones():
    if not excluded_zone_names:
        return st.session_state.geozones
    return [g for g in st.session_state.geozones if g.get("name") not in set(excluded_zone_names)]


st.session_state["short_trip_minutes"] = short_trip_minutes


# --- RUN button ---
if st.button("▶️ RUN"):
    st.session_state["report_ready"] = True

# --- Generate report if ready ---
if st.session_state.get("report_ready"):
    try:
        st.markdown(f"### Vehicle: {vehicle_name}")

        trips = find_trips(api_key, from_dt, to_dt, vehicle_id)

        short_trip_minutes = int(st.session_state.get("short_trip_minutes", 3))  # 0 = disabled
        trips = merge_short_trips(
            trips,
            min_minutes=int(short_trip_minutes),
            max_gap_minutes=int(stay_gap_minutes),
        )

        filtered_geozones = get_filtered_geozones()

        # Shared helper function
        def fmt_hms(total_seconds: int | float | None) -> str:
            s = int(total_seconds or 0)
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"

        def parse_hms(hms: str | None) -> int:
            """'HH:MM:SS' → total seconds. Empty or None → 0."""
            if not hms or not isinstance(hms, str):
                return 0
            try:
                h, m, s = hms.split(":")
                return int(h) * 3600 + int(m) * 60 + int(s)
            except Exception:
                return 0

        # ================================
        # MODE 1 — Merge trips by geozones
        # ================================
        if merge_trips:
            trip_pairs = trips_to_zone_pairs(trips, filtered_geozones)
            df_log = pd.DataFrame(trip_pairs)

            if not df_log.empty:
                # Local time formatting
                for col in ["Departure at", "Arrival at"]:
                    df_log[col] = df_log[col].apply(
                        lambda x: x.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S")
                        if isinstance(x, dt.datetime) else ""
                    )

                # Rounding if not in raw mode
                if "Distance (km)" in df_log.columns and not raw_mode:
                    df_log["Distance (km)"] = df_log["Distance (km)"].apply(
                        lambda x: round_nearest_int(float(x)) if x not in (None, "") else 0
                    )

                css = """
                <style>
                .tbl { width: 100%; border-collapse: collapse; font-size: 0.95rem; table-layout: fixed; }
                .tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 8px 10px; vertical-align: top; }
                .tbl thead th { background: #f8fafc; text-align: left; }
                .tbl td { line-height: 1.25; word-wrap: break-word; overflow-wrap: anywhere; }
                .tbl td:nth-child(1), .tbl td:nth-child(3) { min-width: 280px; }
                </style>
                """.strip()

                table_html = df_log.to_html(escape=False, index=False, border=0, classes="tbl").lstrip()

                # --- Totals (aggregated view) ---
                total_distance_val = float(pd.to_numeric(df_log["Distance (km)"], errors="coerce").fillna(0).sum())
                total_distance_str = f"{total_distance_val:.3f}" if raw_mode else f"{round_nearest_int(total_distance_val)}"
                total_travel_s = int(df_log["Duration"].fillna("").map(parse_hms).sum())
                total_stay_s = int(df_log["Stay (hh:mm:ss)"].fillna("").map(parse_hms).sum())

                summary_html = f"""
                <div class="totals">Totals — Distance: <b>{total_distance_str} km</b> · Travel time: <b>{fmt_hms(total_travel_s)}</b> · Stop time: <b>{fmt_hms(total_stay_s)}</b></div>
                <style>.totals{{margin-top:6px;}}</style>
                """

                # >>> Single render block <<<
                st.subheader("Trips-derived Logbook (zone-filtered pairs)")
                st.markdown(css, unsafe_allow_html=True)
                st.markdown(table_html, unsafe_allow_html=True)
                st.markdown(summary_html, unsafe_allow_html=True)
            else:
                st.info("No trips found for the selected period.")

        # ================================
        # MODE 2 — Show all trips (default)
        # ================================
        else:
            rows = []
            for i, t in enumerate(trips):
                start = t.get("trip_start", {}) or {}
                end = t.get("trip_end", {}) or {}

                s_lat, s_lon = start.get("latitude"), start.get("longitude")
                e_lat, e_lon = end.get("latitude"), end.get("longitude")

                start_zones = geozones_for_point(s_lat, s_lon, filtered_geozones)
                end_zones = geozones_for_point(e_lat, e_lon, filtered_geozones)

                start_address = format_address(start.get("address"))
                end_address = format_address(end.get("address"))

                # If inside a geozone, highlight in red
                if start_zones:
                    start_address = f"<b style='color:red'>{', '.join(start_zones)}</b> : {start_address}"
                if end_zones:
                    end_address = f"<b style='color:red'>{', '.join(end_zones)}</b> : {end_address}"

                # Compute stay time
                stay = ""
                if i + 1 < len(trips):
                    next_trip = trips[i + 1]
                    cur_end = parse_iso(end.get("datetime"))
                    next_start = parse_iso(next_trip.get("trip_start", {}).get("datetime"))
                    if cur_end and next_start:
                        delta = (next_start - cur_end).total_seconds()
                        if delta > 0:
                            stay = fmt_hms(delta)

                base_km = (t.get("mileage") or 0) / 1000.0
                distance_value = (round(base_km, 3) if raw_mode else round_nearest_int(base_km))

                rows.append({
                    "Departure": start_address,
                    "Departure at": parse_iso(start.get("datetime")),
                    "Arrival": end_address,
                    "Arrival at": parse_iso(end.get("datetime")),
                    "Distance (km)": distance_value,
                    "Duration": fmt_hms(t.get("trip_duration")),
                    "Stay (hh:mm:ss)": stay,
                })

            df_trips = pd.DataFrame(rows)
            if not df_trips.empty:
                for col in ["Departure at", "Arrival at"]:
                    df_trips[col] = df_trips[col].apply(
                        lambda x: x.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S") if isinstance(x,
                                                                                                    dt.datetime) else ""
                    )

                css = """
                <style>
                .tbl { width: 100%; border-collapse: collapse; font-size: 0.95rem; table-layout: fixed; }
                .tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 8px 10px; vertical-align: top; }
                .tbl thead th { background: #f8fafc; text-align: left; }
                .tbl td { line-height: 1.25; word-wrap: break-word; overflow-wrap: anywhere; }
                .tbl td:nth-child(1), .tbl td:nth-child(3) { min-width: 280px; }
                </style>
                """.strip()
                table_html = df_trips.to_html(escape=False, index=False, border=0, classes="tbl").lstrip()

                # --- Totals (detailed view) ---
                # Distance: the table already contains rounded/raw values according to the checkbox
                total_distance_val = float(pd.to_numeric(df_trips["Distance (km)"], errors="coerce").fillna(0).sum())
                total_distance_str = f"{total_distance_val:.3f}" if raw_mode else f"{round_nearest_int(total_distance_val)}"

                total_travel_s = int(df_trips["Duration"].fillna("").map(parse_hms).sum())
                total_stay_s = int(df_trips["Stay (hh:mm:ss)"].fillna("").map(parse_hms).sum())

                summary_html = f"""
                <div class="totals">Totals — Distance: <b>{total_distance_str} km</b> · Travel time: <b>{fmt_hms(total_travel_s)}</b> · Stop time: <b>{fmt_hms(total_stay_s)}</b></div>
                <style>.totals{{margin-top:6px;}}</style>
                """

                st.subheader("All Trips (detailed view)")
                st.markdown(css, unsafe_allow_html=True)
                st.markdown(table_html, unsafe_allow_html=True)
                st.markdown(summary_html, unsafe_allow_html=True)  # <-- NEW: summary bar

            else:
                st.info("No trips found for the selected period.")

    except Exception as e:
        st.error(f"Error: {e}")
