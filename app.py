import datetime as dt
from datetime import timezone
import pandas as pd
import streamlit as st

from fm_api import list_objects, list_geozones, find_trips
from transforms import parse_iso, trips_to_zone_pairs
from geoutils import geozones_for_point

st.set_page_config(page_title="Logbook with geozones", page_icon="🗺️", layout="wide")
st.title("Logbook with geozones")

# -------- Sidebar / settings ----------
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("API key", type="password")
    now = dt.datetime.now(tz=timezone.utc)
    default_from = (now - dt.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    default_to = now.replace(microsecond=0)

    from_date = st.date_input("From date", value=default_from.date())
    from_time = st.time_input("From time", value=default_from.time())
    from_dt = dt.datetime.combine(from_date, from_time).replace(tzinfo=timezone.utc)

    to_date = st.date_input("To date", value=default_to.date())
    to_time = st.time_input("To time", value=default_to.time())
    to_dt = dt.datetime.combine(to_date, to_time).replace(tzinfo=timezone.utc)

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

# --- RUN button ---
if st.button("▶️ RUN"):
    st.session_state["report_ready"] = True

# --- Generate report if ready ---
if st.session_state.get("report_ready"):
    try:
        st.markdown(f"### Vehicle: {vehicle_name}")

        trips = find_trips(api_key, from_dt, to_dt, vehicle_id)
        filtered_geozones = get_filtered_geozones()

        # ===== Trips-derived Logbook (zone-filtered pairs) only =====
        trip_pairs = trips_to_zone_pairs(trips, filtered_geozones)
        df_triplog = pd.DataFrame(trip_pairs)
        if not df_triplog.empty:
            for col in ["Departure at", "Arrival at"]:
                df_triplog[col] = df_triplog[col].apply(
                    lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if hasattr(x, "strftime") else ""
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

            table_html = df_triplog.to_html(escape=False, index=False, border=0, classes="tbl").lstrip()

            st.subheader("Trips-derived Logbook (zone-filtered pairs)")
            st.markdown(css, unsafe_allow_html=True)
            st.markdown(table_html, unsafe_allow_html=True)
        else:
            st.info("No trips found for the selected period.")

    except Exception as e:
        st.error(f"Error: {e}")
