import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import time
import argparse
from pathlib import Path

def geocode_data(update=False):
    print("Initializing geocoder...")
    geolocator = Nominatim(user_agent="vienna_attractions_app")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    print("Geocoding hotels.csv...")
    try:
        hotels_df = pd.read_csv("hotels.csv")
        if update and Path("hotel_geocoded.csv").exists():
            geo_df = pd.read_csv("hotel_geocoded.csv")
            if 'Latitude' in geo_df.columns and 'Longitude' in geo_df.columns:
                hotels_df = hotels_df.merge(geo_df[['Name', 'Latitude', 'Longitude']], on='Name', how='left')

        if 'Latitude' not in hotels_df.columns:
            hotels_df['Latitude'] = None
        if 'Longitude' not in hotels_df.columns:
            hotels_df['Longitude'] = None

        if update:
            hotel_mask = hotels_df['Latitude'].isna() | hotels_df['Longitude'].isna()
            print(f"Update mode: geocoding {hotel_mask.sum()} hotel row(s) missing coordinates.")
        else:
            hotel_mask = pd.Series(True, index=hotels_df.index)

        hotels_df['address_search'] = hotels_df['Address'].str.replace(", 1040 Wien", ", Vienna, Austria", regex=False)
        hotels_df['location'] = None
        hotels_df.loc[hotel_mask, 'location'] = hotels_df.loc[hotel_mask, 'address_search'].apply(geocode)
        if hotel_mask.any():
            hotels_df.loc[hotel_mask, 'Latitude'] = hotels_df.loc[hotel_mask, 'location'].apply(lambda loc: loc.latitude if loc is not None else float('nan')).astype(float)
            hotels_df.loc[hotel_mask, 'Longitude'] = hotels_df.loc[hotel_mask, 'location'].apply(lambda loc: loc.longitude if loc is not None else float('nan')).astype(float)
        
        # Drop temporary columns
        hotels_df = hotels_df.drop(columns=['address_search', 'location'])
        hotels_df.to_csv("hotel_geocoded.csv", index=False)
        print("hotel_geocoded.csv saved.")
    except Exception as e:
        print(f"Error processing hotels.csv: {e}")

    print("Geocoding attractions.csv...")
    try:
        attractions_df = pd.read_csv("attractions.csv")
        if update and Path("attractions_geocoded.csv").exists():
            geo_df = pd.read_csv("attractions_geocoded.csv")
            if 'Latitude' in geo_df.columns and 'Longitude' in geo_df.columns:
                attractions_df = attractions_df.merge(geo_df[['Attraction', 'Latitude', 'Longitude']], on='Attraction', how='left')

        if 'Latitude' not in attractions_df.columns:
            attractions_df['Latitude'] = None
        if 'Longitude' not in attractions_df.columns:
            attractions_df['Longitude'] = None
        
        # Clean addresses for better search, e.g., "1040 Wien" to "Vienna, Austria"
        def clean_address(addr):
            if pd.isna(addr):
                return ""
            if "Wien" in addr:
                return addr.replace("Wien", "Vienna, Austria")
            if "Vienna" in addr and "Austria" not in addr:
                return addr + ", Austria"
            return addr

        attractions_df['address_search'] = attractions_df['Address'].apply(clean_address)
        
        # Some are just "Multiple locations" or "N/A"
        invalid_addresses = ["Multiple locations", "N/A"]
        
        def geocode_with_fallback(addr, attraction_name):
            if any(inv in str(addr) for inv in invalid_addresses):
                print(f"Invalid address for {attraction_name}: {addr}, trying attraction name '{attraction_name}'...")
                return geocode(f"{attraction_name}, Vienna, Austria")
                
            loc = geocode(addr)
            if loc is None:
                # Fallback to searching by attraction name + "Vienna, Austria"
                print(f"Could not find address {addr}, trying attraction name '{attraction_name}'...")
                loc = geocode(f"{attraction_name}, Vienna, Austria")
            return loc

        if update:
            attraction_mask = attractions_df['Latitude'].isna() | attractions_df['Longitude'].isna()
            print(f"Update mode: geocoding {attraction_mask.sum()} attraction row(s) missing coordinates.")
        else:
            attraction_mask = pd.Series(True, index=attractions_df.index)

        # Initialize columns
        locations = []
        for index, row in attractions_df.iterrows():
            if not attraction_mask.loc[index]:
                locations.append(None)
                continue
            print(f"Geocoding: {row['Attraction']}")
            loc = geocode_with_fallback(row['address_search'], row['Attraction'])
            locations.append(loc)
            time.sleep(0.5)  # additional sleep to be safe

        attractions_df['location'] = locations
        if attraction_mask.any():
            attractions_df.loc[attraction_mask, 'Latitude'] = attractions_df.loc[attraction_mask, 'location'].apply(lambda loc: loc.latitude if loc is not None else float('nan')).astype(float)
            attractions_df.loc[attraction_mask, 'Longitude'] = attractions_df.loc[attraction_mask, 'location'].apply(lambda loc: loc.longitude if loc is not None else float('nan')).astype(float)

        attractions_df = attractions_df.drop(columns=['address_search', 'location'])
        attractions_df.to_csv("attractions_geocoded.csv", index=False)
        print("attractions_geocoded.csv saved.")
        
        # Print missing coordinates
        missing = attractions_df[attractions_df['Latitude'].isna()]
        if not missing.empty:
            print(f"Could not find coordinates for {len(missing)} attractions:")
            for _, row in missing.iterrows():
                print(f"- {row['Attraction']}")
                
    except Exception as e:
        print(f"Error processing attractions.csv: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Geocode hotels and attractions data.")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Only geocode rows missing Latitude/Longitude, using existing geocoded CSVs when available.",
    )
    args = parser.parse_args()
    geocode_data(update=args.update)
