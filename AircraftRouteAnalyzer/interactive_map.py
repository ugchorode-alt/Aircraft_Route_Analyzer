import os
import json
import pandas as pd
import networkx as nx
import folium
from math import radians, sin, cos, sqrt, asin

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs('output', exist_ok=True)

# ── Haversine formula ──────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return round(R * 2 * asin(sqrt(a)), 2)

# ── Flight time estimate ────────────────────────────────────
CRUISE_SPEED_KMH = 750   # average block speed for narrow-body jets
OVERHEAD_HOURS   = 0.5   # taxi + takeoff + landing + taxi-in

def estimate_flight_time(distance_km):
    hours = (distance_km / CRUISE_SPEED_KMH) + OVERHEAD_HOURS
    h = int(hours)
    m = int(round((hours - h) * 60))
    return hours, f"{h}h {m}m"

# ── Load data ──────────────────────────────────────────────
airports = pd.read_csv('data/airports.csv')
routes   = pd.read_csv('data/flight_frequencies.csv')

# ── Build graph (deduplicated edges) ───────────────────────
G = nx.Graph()

for _, row in airports.iterrows():
    G.add_node(row['iata_code'],
               name=row['airport_name'],
               city=row['city'],
               lat=row['latitude'],
               lon=row['longitude'])

seen_pairs = set()
for _, row in routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    if pair not in seen_pairs:
        seen_pairs.add(pair)
        src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
        dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
        dist = haversine(src['latitude'], src['longitude'],
                         dst['latitude'], dst['longitude'])
        G.add_edge(row['origin_iata'], row['destination_iata'], weight=dist)

print(f"Graph: {G.number_of_nodes()} airports, {G.number_of_edges()} routes")

# ── Precompute shortest path for EVERY pair (all 105 combos) ──
all_paths = {}
iata_list = airports['iata_code'].tolist()

for source in iata_list:
    for target in iata_list:
        if source == target:
            continue
        try:
            path = nx.dijkstra_path(G, source, target, weight='weight')
            dist = nx.dijkstra_path_length(G, source, target, weight='weight')
            time_hours, time_str = estimate_flight_time(dist)

            # Coordinates for drawing the line
            coords = []
            for code in path:
                node = G.nodes[code]
                coords.append([node['lat'], node['lon']])

            all_paths[f"{source}-{target}"] = {
                "path": path,
                "path_cities": [G.nodes[c]['city'] for c in path],
                "distance_km": round(dist, 1),
                "time_hours": round(time_hours, 2),
                "time_str": time_str,
                "stops": len(path) - 2,
                "coords": coords
            }
        except nx.NetworkXNoPath:
            all_paths[f"{source}-{target}"] = None

print(f"Precomputed {len(all_paths)} origin-destination pairs")

# ── Airport list for dropdowns ─────────────────────────────
airport_options = []
for _, row in airports.iterrows():
    airport_options.append({
        "iata": row['iata_code'],
        "city": row['city'],
        "lat": row['latitude'],
        "lon": row['longitude']
    })

# ══════════════════════════════════════════════════════════
# BUILD THE MAP
# ══════════════════════════════════════════════════════════
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5, tiles='CartoDB positron')

# All routes (faint background)
routes_layer = folium.FeatureGroup(name='All Routes', show=True)
for _, row in routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
    dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
    folium.PolyLine(
        locations=[[src['latitude'], src['longitude']],
                   [dst['latitude'], dst['longitude']]],
        color='steelblue', weight=1, opacity=0.4
    ).add_to(routes_layer)
routes_layer.add_to(m)

# Airport markers
for _, row in airports.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],
        icon=folium.Icon(color='darkblue', icon='plane', prefix='fa'),
        tooltip=f"{row['iata_code']} — {row['city']}"
    ).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# Get the JS variable name Folium assigned to this map
map_name = m.get_name()

# ── Inject the dropdown UI + JavaScript ────────────────────
dropdown_options = ""
for ap in airport_options:
    dropdown_options += f'<option value="{ap["iata"]}">{ap["iata"]} - {ap["city"]}</option>\n'

custom_html = f"""
<div id="route-finder" style="
    position: fixed; top: 10px; left: 60px; z-index: 9999;
    background: white; padding: 12px; border-radius: 8px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3); font-family: Arial; font-size: 13px;">

    <b>Find Shortest Route</b><br><br>

    From: <select id="origin-select">
        {dropdown_options}
    </select><br><br>

    To: <select id="destination-select">
        {dropdown_options}
    </select><br><br>

    <button onclick="findRoute()" style="
        background:#1a73e8; color:white; border:none;
        padding:6px 14px; border-radius:4px; cursor:pointer;">
        Find Route
    </button>

    <div id="result-box" style="margin-top:10px;"></div>
</div>

<script>
// All precomputed shortest paths, embedded as JSON
var allPaths = {json.dumps(all_paths)};

// Reference to the Folium map object
var mapObj = {map_name};

// Keep track of the currently drawn route line
var currentRouteLine = null;

function findRoute() {{
    var origin = document.getElementById('origin-select').value;
    var destination = document.getElementById('destination-select').value;
    var resultBox = document.getElementById('result-box');

    if (origin === destination) {{
        resultBox.innerHTML = "<span style='color:red'>Please select two different airports.</span>";
        return;
    }}

    var key = origin + "-" + destination;
    var data = allPaths[key];

    if (!data) {{
        resultBox.innerHTML = "<span style='color:red'>No route found between these airports.</span>";
        return;
    }}

    // Remove previous route line if it exists
    if (currentRouteLine) {{
        mapObj.removeLayer(currentRouteLine);
    }}

    // Draw the new shortest path in red
    currentRouteLine = L.polyline(data.coords, {{color: 'red', weight: 4, opacity: 0.9}}).addTo(mapObj);

    // Zoom map to fit the route
    mapObj.fitBounds(currentRouteLine.getBounds());

    // Display the info
    resultBox.innerHTML = `
        <b>Route:</b> ${{data.path.join(' &rarr; ')}}<br>
        <b>Cities:</b> ${{data.path_cities.join(' &rarr; ')}}<br>
        <b>Distance:</b> ${{data.distance_km}} km<br>
        <b>Est. Flight Time:</b> ${{data.time_str}}<br>
        <b>Stops:</b> ${{data.stops}}
    `;
}}
</script>
"""

m.get_root().html.add_child(folium.Element(custom_html))

# ── Save ─────────────────────────────────────────────────
m.save('output/interactive_route_map.html')
print("Saved: output/interactive_route_map.html")
print("Open this in your browser and select any two airports!")