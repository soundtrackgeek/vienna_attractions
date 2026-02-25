import streamlit as st
import pandas as pd
import pydeck as pdk
import numpy as np
import re
from geopy.distance import geodesic

st.set_page_config(page_title="Vienna Trip Planner", page_icon="🗺️", layout="wide")

# CSS to make the app look a bit nicer
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
    }
    .stDataFrame {
        font-size: 14px;
    }
    .metric-card {
        background-color: #000000;
        color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🗺️ Vienna Attractions Planner")
st.markdown("Plan your days in Vienna based on distance, time, and budget!")

def parse_duration_minutes(t_str):
    if pd.isna(t_str) or t_str == 'N/A':
        return 0
    t_str = str(t_str).lower()
    minutes = 0
    if 'h' in t_str:
        parts = t_str.split('h')
        if parts[0].strip().isdigit():
            minutes += int(parts[0].strip()) * 60
        if len(parts) > 1 and 'm' in parts[1]:
            m_part = parts[1].replace('m', '').strip()
            if m_part.isdigit():
                minutes += int(m_part)
    elif 'm' in t_str:
        m_part = t_str.replace('m', '').strip()
        if m_part.isdigit():
            minutes += int(m_part)
    return minutes


def format_minutes(minutes):
    if pd.isna(minutes):
        return "N/A"
    minutes = int(max(0, minutes))
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def parse_price(price_str):
    if pd.isna(price_str) or "Free" in str(price_str):
        return 0.0
    price_str = str(price_str)
    match = re.search(r'€(\d+\.?\d*)', price_str)
    if match:
        return float(match.group(1))
    return None


@st.cache_data
def load_data():
    try:
        attractions_df = pd.read_csv("attractions_geocoded.csv")
        hotel_df = pd.read_csv("hotel_geocoded.csv")
        hotels_raw_df = pd.read_csv("hotels.csv")
        distances_df = pd.read_csv("distances.csv")
        attractions_df['Numeric Price'] = attractions_df['Price'].apply(parse_price)
        return attractions_df, hotel_df, hotels_raw_df, distances_df
    except FileNotFoundError as e:
        st.error(f"Error loading data files: {e}. Did you run geocode_data.py?")
        return None, None, None, None

attractions_df, hotel_df, hotels_raw_df, distances_df = load_data()

if attractions_df is not None:
    # Work on a per-run copy so cached data does not get mutated across reruns.
    working_df = attractions_df.copy()

    # Sidebar Filters
    st.sidebar.header("Filters ⚙️")
    
    # Starting Point Selector
    valid_attractions = working_df.dropna(subset=['Latitude', 'Longitude'])['Attraction'].tolist()
    valid_hotels_df = hotel_df.dropna(subset=['Latitude', 'Longitude']).copy()
    hotel_name_source = hotels_raw_df['Name'].dropna().tolist() if hotels_raw_df is not None and 'Name' in hotels_raw_df.columns else valid_hotels_df['Name'].tolist()
    hotel_options = [f"🏨 {name}" for name in hotel_name_source]
    start_options = hotel_options + valid_attractions
    selected_start = st.sidebar.selectbox("Starting Point", start_options, help="Select where you are starting from.")

    if hotels_raw_df is not None and not hotels_raw_df.empty:
        missing_hotel_names = set(hotels_raw_df['Name']) - set(hotel_df['Name'])
        if missing_hotel_names:
            st.sidebar.info("Some hotels in hotels.csv are not geocoded yet. Run geocode_data.py to include them.")

    selected_is_hotel = selected_start in hotel_options
    selected_hotel_name = selected_start.replace("🏨 ", "", 1) if selected_is_hotel else None
    selected_hotel_rows = valid_hotels_df[valid_hotels_df['Name'] == selected_hotel_name] if selected_is_hotel else pd.DataFrame()
    selected_hotel_idx = selected_hotel_rows.index[0] if not selected_hotel_rows.empty else None
    using_precomputed_hotel_times = False

    if selected_is_hotel and selected_hotel_idx is None:
        st.warning("Selected hotel is not geocoded yet, so route times and map centering are unavailable. Run geocode_data.py to enable this hotel.")
        st.stop()

    # Initialize distance-related columns so downstream rendering is stable.
    for col, default in [
        ('Walking Distance', 'N/A'),
        ('Walking Time', 'N/A'),
        ('Transit/Bus Time', 'N/A'),
        ('Transit Price', 'N/A'),
    ]:
        if col not in working_df.columns:
            working_df[col] = default

    # Load precomputed hotel distances for selected hotel when available.
    if selected_hotel_idx is not None:
        hotel_distances = distances_df.copy()
        if 'Hotel' in hotel_distances.columns:
            hotel_distances = hotel_distances[hotel_distances['Hotel'] == selected_hotel_name]
        elif not hotel_distances.empty:
            default_hotel_name = valid_hotels_df['Name'].iloc[0] if not valid_hotels_df.empty else None
            if selected_hotel_name != default_hotel_name:
                hotel_distances = hotel_distances.iloc[0:0]

        if not hotel_distances.empty:
            distance_cols = ['Attraction', 'Walking Distance', 'Walking Time', 'Transit/Bus Time', 'Transit Price']
            working_df = working_df.drop(columns=['Walking Distance', 'Walking Time', 'Transit/Bus Time', 'Transit Price'], errors='ignore')
            working_df = pd.merge(working_df, hotel_distances[distance_cols], on='Attraction', how='left')
            using_precomputed_hotel_times = True

            working_df['Walking Time (mins)'] = working_df['Walking Time'].apply(parse_duration_minutes)
            working_df['Transit Time (mins)'] = working_df['Transit/Bus Time'].apply(parse_duration_minutes)
            walk_recommended = working_df['Transit/Bus Time'].str.contains('Walk recommended', na=False)
            working_df.loc[walk_recommended, 'Transit Time (mins)'] = working_df['Walking Time (mins)']

    # If selected hotel does not have precomputed times, recalculate walking-based times.
    if selected_hotel_idx is not None and not using_precomputed_hotel_times:
        hotel_row = valid_hotels_df.loc[selected_hotel_idx]
        start_coords = (hotel_row['Latitude'], hotel_row['Longitude'])
        
        def calc_walk_time_from_hotel(row):
            if pd.isna(row['Latitude']) or pd.isna(row['Longitude']):
                return np.nan
            dist_km = geodesic(start_coords, (row['Latitude'], row['Longitude'])).kilometers
            # Approx 14 mins per km for city walking
            return int(dist_km * 14)
            
        working_df['Walking Time (mins)'] = working_df.apply(calc_walk_time_from_hotel, axis=1)
        working_df['Transit Time (mins)'] = working_df['Walking Time (mins)']
        working_df['Walking Time'] = working_df['Walking Time (mins)'].apply(format_minutes)
        working_df['Transit/Bus Time'] = working_df['Transit Time (mins)'].apply(format_minutes)
        working_df['Transit Price'] = "Estimated"
    
    # If not hotel, recalculate distances
    if not selected_is_hotel:
        start_row = working_df[working_df['Attraction'] == selected_start].iloc[0]
        start_coords = (start_row['Latitude'], start_row['Longitude'])
        
        def calc_walk_time(row):
            if pd.isna(row['Latitude']) or pd.isna(row['Longitude']):
                return np.nan
            if row['Attraction'] == selected_start:
                return 0
            dist_km = geodesic(start_coords, (row['Latitude'], row['Longitude'])).kilometers
            # Approx 14 mins per km for city walking
            return int(dist_km * 14)
            
        working_df['Walking Time (mins)'] = working_df.apply(calc_walk_time, axis=1)
        # Use walking time for transit time since we don't have transit data between attractions
        working_df['Transit Time (mins)'] = working_df['Walking Time (mins)']
        working_df['Walking Time'] = working_df['Walking Time (mins)'].apply(format_minutes)
        working_df['Transit/Bus Time'] = working_df['Transit Time (mins)'].apply(format_minutes)
        working_df['Transit Price'] = "N/A"

    # Filter by Time/Distance Mode
    mode_options = ["Transit / Bus", "Walking"]
    selected_mode = st.sidebar.radio("Transport Mode", mode_options)
    
    # Filter by Transit Time
    if selected_mode == "Transit / Bus":
        if not using_precomputed_hotel_times:
            st.sidebar.warning("Note: Transit times are not precomputed for this starting point. Using approximate walking times instead.")
            time_column = 'Walking Time (mins)'
        else:
            time_column = 'Transit Time (mins)'
    else:
        time_column = 'Walking Time (mins)'
        
    max_time_value = working_df[time_column].max()
    if pd.isna(max_time_value) or max_time_value == 0:
        max_time = 120
    else:
        max_time = int(max_time_value)
    
    selected_max_time = st.sidebar.slider(
        f"Max {selected_mode} Time (minutes)", 
        min_value=0, 
        max_value=max_time, 
        value=min(30, max_time),
        help=f"Maximum time to reach the destination via {selected_mode}."
    )
    
    # Filter by Budget
    budget_options = ["All", "Free Only", "Under €15", "Under €25"]
    selected_budget = st.sidebar.selectbox("Budget", budget_options)
    
    # Apply Filters
    filtered_df = working_df.copy()
    
    # Apply Time Filter 
    filtered_df = filtered_df[
        (filtered_df[time_column] > 0) & 
        (filtered_df[time_column] <= selected_max_time)
    ]
    
    # Apply Budget Filter
    if selected_budget == "Free Only":
        filtered_df = filtered_df[filtered_df['Numeric Price'] == 0.0]
    elif selected_budget == "Under €15":
        filtered_df = filtered_df[(filtered_df['Numeric Price'].isna()) | (filtered_df['Numeric Price'] <= 15.0)]
    elif selected_budget == "Under €25":
        filtered_df = filtered_df[(filtered_df['Numeric Price'].isna()) | (filtered_df['Numeric Price'] <= 25.0)]

    # Metrics Row
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"<div class='metric-card'><h3>{len(filtered_df)}</h3><p>Attractions matched</p></div>", unsafe_allow_html=True)
    with col2:
        free_count = len(filtered_df[filtered_df['Numeric Price'] == 0.0])
        st.markdown(f"<div class='metric-card'><h3>{free_count}</h3><p>Free Attractions matched</p></div>", unsafe_allow_html=True)
    with col3:
        if not filtered_df.empty and filtered_df['Transit Time (mins)'].max() > 0:
            avg_time = int(filtered_df[filtered_df['Transit Time (mins)'] > 0]['Transit Time (mins)'].mean())
            st.markdown(f"<div class='metric-card'><h3>~{avg_time}m</h3><p>Average Transit Time</p></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='metric-card'><h3>-</h3><p>Average Transit Time</p></div>", unsafe_allow_html=True)

    # Main Tabs
    tab1, tab2 = st.tabs(["🗺️ Map View", "📋 Data Table"])
    
    with tab1:
        st.subheader("Attractions Map")
        
        # Prepare Map Data
        # Filter out rows without coordinates
        map_df = filtered_df.dropna(subset=['Latitude', 'Longitude']).copy()
        
        if not map_df.empty and not hotel_df.empty:
            # Center Data
            if selected_hotel_idx is not None:
                center_lat = valid_hotels_df.loc[selected_hotel_idx, 'Latitude']
                center_lon = valid_hotels_df.loc[selected_hotel_idx, 'Longitude']
                center_name = "🏨 " + valid_hotels_df.loc[selected_hotel_idx, 'Name']
            else:
                start_row = working_df[working_df['Attraction'] == selected_start].iloc[0]
                center_lat = start_row['Latitude']
                center_lon = start_row['Longitude']
                center_name = "📍 " + selected_start
            
            # Map configuration using pydeck for distinct colors
            # Center layer (Red)
            center_layer = pdk.Layer(
                "ScatterplotLayer",
                data=pd.DataFrame({"lat": [center_lat], "lon": [center_lon], "name": [center_name]}),
                get_position="[lon, lat]",
                get_color="[255, 0, 0, 200]",
                get_radius=200,
                pickable=True,
                auto_highlight=True,
            )
            
            # Attractions layer (Blue)
            # Add a color column: Green if free, Blue if paid
            def get_color(price):
                if price == 0.0:
                    return [0, 200, 0, 160] # Green
                return [0, 0, 255, 160] # Blue
                
            map_df['color'] = map_df['Numeric Price'].apply(get_color)
            
            attractions_layer = pdk.Layer(
                "ScatterplotLayer",
                data=map_df,
                get_position="[Longitude, Latitude]",
                get_color="color",
                get_radius=150,
                pickable=True,
                auto_highlight=True,
            )
            
            # Text layer for center pin
            text_layer = pdk.Layer(
                "TextLayer",
                data=pd.DataFrame({"lat": [center_lat], "lon": [center_lon], "name": [center_name]}),
                get_position="[lon, lat]",
                get_text="name",
                get_color="[255, 0, 0, 255]",
                get_size=16,
                get_alignment_baseline="'bottom'",
                get_pixel_offset="[0, -15]"
            )

            # View state centered around starting point
            view_state = pdk.ViewState(
                latitude=center_lat,
                longitude=center_lon,
                zoom=13,
                pitch=0,
            )

            # Render map
            st.pydeck_chart(pdk.Deck(
                layers=[center_layer, attractions_layer, text_layer],
                initial_view_state=view_state,
                tooltip={"text": "{Attraction}\nCost: {Price}\nTransit: {Transit/Bus Time}"}
            ))
            
            st.caption("🔴 Red = Starting Point | 🟢 Green = Free Attraction | 🔵 Blue = Paid Attraction")
            
        else:
            st.info("No attractions found with the current filters that have valid coordinates.")

    with tab2:
        st.subheader("Filtered Attractions Details")
        
        display_cols = [
            'Attraction', 'Price', 'Transit/Bus Time', 'Walking Time', 
            'Weekday Hours', 'Weekend Hours', 'Transit Price'
        ]
        
        st.dataframe(
            filtered_df[display_cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )
