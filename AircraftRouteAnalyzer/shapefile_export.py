import os
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
from math import radians, sin, cos, sqrt, asin

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs('output/shapefiles', exist_ok=True)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return round(R * 2 * asin(sqrt(a)), 2)

airports = pd.read_csv('data/airports.csv')
routes   = pd.read_csv('data/flight_frequencies.csv')

# ── Airport Points Shapefile ───────────────────────────────
points_gdf = gpd.GeoDataFrame(
    airports,
    geometry=[Point(row['longitude'], row['latitude'])
              for _, row in airports.iterrows()],
    crs='EPSG:4326'
)
points_gdf.to_file('output/shapefiles/airports.shp')
print("Saved: airports.shp")

# ── Route Lines Shapefile ──────────────────────────────────
seen = set()
line_data = []

for _, row in routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    if pair in seen:
        continue
    seen.add(pair)

    src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
    dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
    dist = haversine(src['latitude'], src['longitude'],
                     dst['latitude'], dst['longitude'])

    line_data.append({
        'origin':      row['origin_iata'],
        'destination': row['destination_iata'],
        'dist_km':     dist,
        'freq_week':   row['flights_per_week'],
        'geometry':    LineString([
            (src['longitude'], src['latitude']),
            (dst['longitude'], dst['latitude'])
        ])
    })

lines_gdf = gpd.GeoDataFrame(line_data, crs='EPSG:4326')
lines_gdf.to_file('output/shapefiles/routes.shp')
print("Saved: routes.shp")

# ── Also save as GeoJSON ───────────────────────────────────
points_gdf.to_file('output/airports_points.geojson', driver='GeoJSON')
lines_gdf.to_file('output/routes_lines.geojson', driver='GeoJSON')
print("Saved: GeoJSON files")
print("\nAll shapefiles ready for QGIS import!")