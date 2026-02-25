import csv
import json
import urllib.request
import urllib.parse
from time import sleep
import argparse
import os

def geocode(search_query):
    if "Austria" not in search_query and "Österreich" not in search_query:
        search_query += ", Austria"
    # Use Nominatim API
    url = "https://nominatim.openstreetmap.org/search?q=" + urllib.parse.quote(search_query) + "&format=json&limit=1"
    req = urllib.request.Request(url, headers={'User-Agent': 'ViennaAttractionsDistances/4.0'})
    try:
        response = urllib.request.urlopen(req, timeout=10)
        data = json.loads(response.read().decode('utf-8'))
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        print(f"Geocode error for {search_query}: {e}")
    return None

def get_routing(lat1, lon1, lat2, lon2):
    # Use OSRM API for walking route
    url = f"http://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ViennaAttractionsDistances/3.0'})
        response = urllib.request.urlopen(req, timeout=15)
        data = json.loads(response.read().decode('utf-8'))
        if data.get('code') == 'Ok' and data.get('routes'):
            route = data['routes'][0]
            distance = route['distance'] # meters
            duration = route['duration'] # seconds
            return distance, duration
    except Exception as e:
        print(f"OSRM error: {e}")
    return None, None

def format_duration(seconds):
    if seconds is None:
        return "N/A"
    mins = int(seconds // 60)
    hours = mins // 60
    mins = mins % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"

def format_distance(meters):
    if meters is None:
        return "N/A"
    if meters < 1000:
        return f"{int(meters)} m"
    return f"{meters/1000:.1f} km"

def estimate_transit_time(distance_m, walking_sec):
    if distance_m is None:
        return "N/A"
    if distance_m < 1500:
        return format_duration(walking_sec) + " (Walk recommended)"
    
    transit_sec = (distance_m / 4.16) + 300
    if transit_sec > walking_sec:
        transit_sec = walking_sec * 0.8 
        
    return format_duration(transit_sec)


def load_hotels(hotels_path, hotel_filter=None):
    hotels = []
    with open(hotels_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get('Name') or '').strip()
            address = (row.get('Address') or '').strip()
            if not name or not address:
                continue
            if hotel_filter and name.lower() != hotel_filter.lower():
                continue
            hotels.append({'Name': name, 'Address': address})
    return hotels


def main():
    parser = argparse.ArgumentParser(description="Calculate distances to attractions.")
    parser.add_argument('--update', action='store_true', help="Only calculate distances for new or changed attractions.")
    parser.add_argument('--hotel', help="Optional: only calculate distances for a specific hotel name from hotels.csv.")
    parser.add_argument('--hotels-file', default='hotels.csv', help="CSV file with Name,Address columns.")
    args = parser.parse_args()

    hotels = load_hotels(args.hotels_file, args.hotel)
    if not hotels:
        msg = f"No valid hotels found in {args.hotels_file}"
        if args.hotel:
            msg += f" matching '{args.hotel}'"
        print(msg + ".")
        return

    attractions = []
    with open('attractions.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get('Attraction') or not row.get('Address'):
                continue
            attractions.append(row)

    cache_file = 'distances_cache.json'
    cache = {}
    if args.update:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                try:
                    cache = json.load(f)
                except json.JSONDecodeError:
                    pass
        elif os.path.exists('distances.csv'):
            print("Initializing cache from existing distances.csv...")
            try:
                existing_results = {}
                with open('distances.csv', 'r', encoding='utf-8') as f:
                    csv_reader = csv.DictReader(f)
                    for r in csv_reader:
                        attraction_name = (r.get('Attraction') or '').strip()
                        hotel_name = (r.get('Hotel') or '').strip()
                        existing_results[(hotel_name, attraction_name)] = r
                for row in attractions:
                    _name = row['Attraction']
                    _addr = row['Address'].strip()
                    for hotel in hotels:
                        _hotel_name = hotel['Name']
                        existing = existing_results.get((_hotel_name, _name))
                        if existing:
                            cache_key = f"{_hotel_name}|{_name}|{_addr}"
                            cache[cache_key] = existing
            except Exception as e:
                print(f"Could not initialize cache: {e}")

    results = []

    for hotel in hotels:
        hotel_name = hotel['Name']
        hotel_address = hotel['Address']
        print(f"\nGeocoding hotel: {hotel_name} ({hotel_address})")
        hotel_coords = geocode(hotel_address)
        sleep(1.5)
        if not hotel_coords:
            print(f"Failed to geocode {hotel_name}. Skipping this hotel.")
            continue

        for i, row in enumerate(attractions):
            name = row['Attraction']
            address = row['Address'].strip()

            cache_key = f"{hotel_name}|{name}|{address}"

            if "Multiple locations" in address or not address:
                res = {
                    'Hotel': hotel_name,
                    'Attraction': name,
                    'Walking Distance': 'N/A',
                    'Walking Time': 'N/A',
                    'Transit/Bus Time': 'N/A',
                    'Transit Price': 'N/A'
                }
                results.append(res)
                cache[cache_key] = res
                continue

            if args.update and cache_key in cache:
                print(f"[{hotel_name}] [{i+1}/{len(attractions)}] {name} (Skipping, already calculated)")
                results.append(cache[cache_key])
                continue

            print(f"[{hotel_name}] [{i+1}/{len(attractions)}] {name}")

            coords = geocode(address)
            sleep(1.5)  # rate limit for nominatim

            if not coords:
                print(f"  Fallback geocoding for {name}...")
                coords = geocode(f"{name}, Vienna")
                sleep(1.5)

            if coords:
                dist, dur = get_routing(hotel_coords[0], hotel_coords[1], coords[0], coords[1])
                sleep(0.5)

                if dist is not None:
                    dur = dist / 1.39

                w_dist = format_distance(dist)
                w_time = format_duration(dur)
                t_time = estimate_transit_time(dist, dur)
                t_price = "€2.40 (Single Ticket)" if dist and dist > 1500 else "Free (Walk)"

                res = {
                    'Hotel': hotel_name,
                    'Attraction': name,
                    'Walking Distance': w_dist,
                    'Walking Time': w_time,
                    'Transit/Bus Time': t_time,
                    'Transit Price': t_price
                }
                results.append(res)
                cache[cache_key] = res
            else:
                print(f"  Could not geocode {name}")
                res = {
                    'Hotel': hotel_name,
                    'Attraction': name,
                    'Walking Distance': 'Error geocoding',
                    'Walking Time': 'N/A',
                    'Transit/Bus Time': 'N/A',
                    'Transit Price': 'N/A'
                }
                results.append(res)
                cache[cache_key] = res
            
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    with open('distances.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['Hotel', 'Attraction', 'Walking Distance', 'Walking Time', 'Transit/Bus Time', 'Transit Price']
        )
        writer.writeheader()
        for res in results:
            writer.writerow(res)
            
    print(f"\nDone! Saved {len(results)} rows to distances.csv")

if __name__ == "__main__":
    main()
