# Vienna Attractions Planner 🗺️

A fully-featured Streamlit-based web application to help you seamlessly plan your days traversing Vienna! This tool empowers you to filter, discover, and visualize popular tourist attractions based on your starting point (your hotel or another attraction), maximum travel time, your preferred transport mode (walking or public transit), and budget.

## Features
- **Map Visualization**: View your starting points and destinations on an interactive map. Pins are color-coded (Green for free, Blue for ticketed).
- **Dynamic Time & Distance Routing**: Pre-calculates accurate walking and transit durations from your hotels using OSRM, and handles on-the-fly straight-line estimates between individual attractions.
- **Smart Filtering**: Find free attractions or filter strictly by price (e.g., Under €15, Under €25), maximum travel time, or transport modes. 
- **Automated Data Pipelines**: Includes robust Python scripts to geocode physical addresses and pre-calculate walking/transit matrices for instantaneous performance in the UI.

## Project Structure
- `app.py`: The main Streamlit web application.
- `geocode_data.py`: Geocodes addresses found in `attractions.csv` and `hotels.csv` into explicit coordinates using the Nominatim API. Outputs `attractions_geocoded.csv` and `hotel_geocoded.csv`.
- `calc_distances.py`: Connects to the OSRM API to compute walking distances and durations between every hotel and attraction, outputting route estimates into `distances.csv`.
- `attractions.csv` & `hotels.csv`: Raw input files containing your target destinations.
- `*_geocoded.csv` & `distances.csv`: The artifacts loaded by the Streamlit application serving the dashboard.

## Prerequisites
- Python 3.8+

## Installation
1. Clone the repository and navigate into the folder:
   ```bash
   cd vienna_attractions
   ```
2. Install the combined dependencies required for the pipelines and Streamlit application:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### 1. Data Preparation
Before properly running the application, make sure all locations are converted into Map Coordinates and the routing matrices are built!

**Geocode Coordinates:**
```bash
python geocode_data.py
```
*(If you are just adding a few new rows, use the `--update` flag to skip locations you already queried)*

**Calculate Routes:**
```bash
python calc_distances.py
```
*(Similarly, utilizing the `--update` flag will respect already cached calculations to avoid blowing through API limits.)*

### 2. Launching the App
Start the Streamlit application using:
```bash
streamlit run app.py
```
When it spins up, simply open your web browser to the provided local URL (typically `http://localhost:8501`).

## Data Formats

### `hotels.csv`
Must contain the following headers:
- `Name`: Name of the hotel.
- `Address`: Full street address in Vienna.

### `attractions.csv`
Must contain the following headers:
- `Attraction`: Name of the attraction.
- `Address`: Full address or relative marker.
- `Price`: Free-form admission price (e.g., "€15", "Free").
- `Weekday Hours`, `Weekend Hours`: Associated opening times.

## APIs & Libraries Built With
- **[Streamlit](https://streamlit.io/)**: Interactive web UI framing.
- **[PyDeck](https://deckgl.readthedocs.io/en/latest/)**: Performant map-rendering canvas block.
- **Nominatim (OpenStreetMap)**: Translating input address text strings to geographic coordinates.
- **OSRM (Open Source Routing Machine)**: Sourcing point-to-point walking paths.
