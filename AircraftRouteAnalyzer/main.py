import json
import pandas as pd
from math import radians, sin, cos, sqrt, asin

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

airports = pd.read_csv('data/airports.csv')
routes   = pd.read_csv('data/flight_frequencies.csv')

# Fix: Remove duplicate reverse routes 
seen_pairs = set()
unique_routes = []

for _, row in routes.iterrows():
    # Sort the pair so DEL-BOM and BOM-DEL are treated as the same
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    
    if pair not in seen_pairs:
        seen_pairs.add(pair)
        unique_routes.append(row)

print(f"Original routes: {len(routes)}")
print(f"After removing duplicates: {len(unique_routes)}")

# Airport Points GeoJSON 
points_geojson = {
    "type": "FeatureCollection",
    "features": []
}

for _, row in airports.iterrows():
    points_geojson["features"].append({
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [row['longitude'], row['latitude']]
        },
        "properties": {
            "iata":      row['iata_code'],
            "name":      row['airport_name'],
            "city":      row['city'],
            "elevation": row['elevation_ft']
        }
    })

with open('output/airports_points.geojson', 'w') as f:
    json.dump(points_geojson, f, indent=2)

print("airports_points.geojson saved!")

# Route Lines GeoJSON (deduplicated) 
lines_geojson = {
    "type": "FeatureCollection",
    "features": []
}

for row in unique_routes:
    src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
    dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
    dist = haversine(src['latitude'], src['longitude'],
                     dst['latitude'], dst['longitude'])

    lines_geojson["features"].append({
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [src['longitude'], src['latitude']],
                [dst['longitude'], dst['latitude']]
            ]
        },
        "properties": {
            "origin":        row['origin_iata'],
            "destination":   row['destination_iata'],
            "distance_km":   round(dist, 2),
            "freq_per_week": row['flights_per_week']
        }
    })

with open('output/routes_lines.geojson', 'w') as f:
    json.dump(lines_geojson, f, indent=2)

print("routes_lines.geojson saved!")
print("Done — no duplicate route lines!")