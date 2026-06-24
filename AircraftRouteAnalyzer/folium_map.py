import os
import json
import pandas as pd
import networkx as nx
import folium
from folium.plugins import MeasureControl, MiniMap
from math import radians, sin, cos, sqrt, asin

os.chdir(os.path.dirname(os.path.abspath(__file__)))

airports = pd.read_csv('data/airports.csv')
routes   = pd.read_csv('data/flight_frequencies.csv')

# Load shortest paths output
paths_df = pd.read_csv('output/shortest_paths.csv')

# ── Base map centered on India ─────────────────────────────
m = folium.Map(
    location=[20.5937, 78.9629],
    zoom_start=5,
    tiles='CartoDB positron'
)

# ── Layer groups (toggleable in the map) ──────────────────
routes_layer   = folium.FeatureGroup(name='All Routes', show=True)
airports_layer = folium.FeatureGroup(name='Airports', show=True)
shortest_layer = folium.FeatureGroup(name='Shortest Paths', show=True)

# ── Plot all routes (blue) ─────────────────────────────────
seen = set()
for _, row in routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    if pair in seen:
        continue
    seen.add(pair)

    src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
    dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]

    folium.PolyLine(
        locations=[
            [src['latitude'], src['longitude']],
            [dst['latitude'], dst['longitude']]
        ],
        color='steelblue',
        weight=1.5,
        opacity=0.6,
        tooltip=f"{row['origin_iata']} ↔ {row['destination_iata']} | {row['flights_per_week']} flights/week"
    ).add_to(routes_layer)

# ── Plot airport markers ───────────────────────────────────
for _, row in airports.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],
        icon=folium.Icon(color='darkblue', icon='plane', prefix='fa'),
        popup=folium.Popup(
            f"""
            <b>{row['airport_name']}</b><br>
            IATA: {row['iata_code']}<br>
            City: {row['city']}<br>
            Elevation: {row['elevation_ft']} ft
            """,
            max_width=250
        ),
        tooltip=f"{row['iata_code']} — {row['city']}"
    ).add_to(airports_layer)

# ── Plot shortest paths (red) ──────────────────────────────
# Load from the GeoJSON we exported
with open('output/shortest_paths.geojson') as f:
    paths_geojson = json.load(f)

for feature in paths_geojson['features']:
    coords = feature['geometry']['coordinates']
    # GeoJSON is [lon, lat] — Folium needs [lat, lon]
    latlon = [[c[1], c[0]] for c in coords]
    props  = feature['properties']

    folium.PolyLine(
        locations=latlon,
        color='red',
        weight=4,
        opacity=0.9,
        tooltip=f"Shortest: {props['path']} | {props['distance_km']} km"
    ).add_to(shortest_layer)

# ── Add all layers to map ──────────────────────────────────
routes_layer.add_to(m)
airports_layer.add_to(m)
shortest_layer.add_to(m)

# ── Add controls ───────────────────────────────────────────
folium.LayerControl(collapsed=False).add_to(m)
MeasureControl().add_to(m)
MiniMap().add_to(m)

# ── Save ───────────────────────────────────────────────────
m.save('output/aircraft_route_map.html')
print("Map saved to output/aircraft_route_map.html")
print("Open this file in any browser!")