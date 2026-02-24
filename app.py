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

@st.cache_data
def load_data():
    try:
        attractions_df = pd.read_csv("attractions_geocoded.csv")
        hotel_df = pd.read_csv("hotel_geocoded.csv")
        distances_df = pd.read_csv("distances.csv")
        
        # Merge attractions with distances
        merged_df = pd.merge(attractions_df, distances_df, on="Attraction", how="left")
        
        # Parse Transit Time (e.g., "16m", "1h 12m", "N/A") for filtering
        def parse_time(t_str):
            if pd.isna(t_str) or t_str == 'N/A' or 'Walk recommended' in t_str:
                return 0 # Or fallback to walking time
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

        merged_df['Transit Time (mins)'] = merged_df['Transit/Bus Time'].apply(parse_time)
        
        # Also parse walk time explicitly to use if transit time says "Walk recommended"
        def parse_walk_time(t_str):
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
            
        merged_df['Walking Time (mins)'] = merged_df['Walking Time'].apply(parse_walk_time)
        
        # Use walk time if transit time says 'Walk recommended'
        merged_df.loc[merged_df['Transit/Bus Time'].str.contains('Walk recommended', na=False), 'Transit Time (mins)'] = merged_df['Walking Time (mins)']

        # Try to extract numerical price for filtering (rough approximation)
        def parse_price(price_str):
            if pd.isna(price_str) or "Free" in str(price_str):
                return 0.0
            price_str = str(price_str)
            # Find first float-like string
            match = re.search(r'€(\d+\.?\d*)', price_str)
            if match:
                return float(match.group(1))
            return None # Unknown/Variable
            
        merged_df['Numeric Price'] = merged_df['Price'].apply(parse_price)

        return merged_df, hotel_df
    except FileNotFoundError as e:
        st.error(f"Error loading data files: {e}. Did you run geocode_data.py?")
        return None, None

merged_df, hotel_df = load_data()

if merged_df is not None:
    # Sidebar Filters
    st.sidebar.header("Filters ⚙️")
    
    # Starting Point Selector
    valid_attractions = merged_df.dropna(subset=['Latitude', 'Longitude'])['Attraction'].tolist()
    start_options = ["🏨 Your Hotel"] + valid_attractions
    selected_start = st.sidebar.selectbox("Starting Point", start_options, help="Select where you are starting from.")
    
    # If not hotel, recalculate distances
    if selected_start != "🏨 Your Hotel":
        start_row = merged_df[merged_df['Attraction'] == selected_start].iloc[0]
        start_coords = (start_row['Latitude'], start_row['Longitude'])
        
        def calc_walk_time(row):
            if pd.isna(row['Latitude']) or pd.isna(row['Longitude']):
                return np.nan
            if row['Attraction'] == selected_start:
                return 0
            dist_km = geodesic(start_coords, (row['Latitude'], row['Longitude'])).kilometers
            # Approx 14 mins per km for city walking
            return int(dist_km * 14)
            
        merged_df['Walking Time (mins)'] = merged_df.apply(calc_walk_time, axis=1)
        # Use walking time for transit time since we don't have transit data between attractions
        merged_df['Transit Time (mins)'] = merged_df['Walking Time (mins)']

    # Filter by Time/Distance Mode
    mode_options = ["Transit / Bus", "Walking"]
    selected_mode = st.sidebar.radio("Transport Mode", mode_options)
    
    # Filter by Transit Time
    if selected_mode == "Transit / Bus":
        # Cannot use transit if we don't start from the hotel!
        if selected_start != "🏨 Your Hotel":
            st.sidebar.warning("Note: Transit times are only available from the Hotel. Using approximate walking times instead.")
            time_column = 'Walking Time (mins)'
        else:
            time_column = 'Transit Time (mins)'
    else:
        time_column = 'Walking Time (mins)'
        
    max_time = int(merged_df[time_column].max())
    if max_time == 0 or np.isnan(max_time): max_time = 120
    
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
    filtered_df = merged_df.copy()
    
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
            if selected_start == "🏨 Your Hotel":
                center_lat = hotel_df['Latitude'].iloc[0]
                center_lon = hotel_df['Longitude'].iloc[0]
                center_name = "🏨 " + hotel_df['Name'].iloc[0]
            else:
                start_row = merged_df[merged_df['Attraction'] == selected_start].iloc[0]
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
