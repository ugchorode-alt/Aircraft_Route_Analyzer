import os
import json
import pandas as pd
import networkx as nx
import folium
from math import radians, sin, cos, sqrt, asin

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs('output', exist_ok=True)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return round(R * 2 * asin(sqrt(a)), 2)

def estimate_flight_time(distance_km):
    hours = (distance_km / 750) + 0.5
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}h {m}m"

airports = pd.read_csv('data/airports.csv')
routes   = pd.read_csv('data/flight_frequencies.csv')

# ── Build graph ────────────────────────────────────────────
G = nx.Graph()
for _, row in airports.iterrows():
    G.add_node(row['iata_code'],
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

# ── Precompute all paths ────────────────────────────────────
all_paths = {}
iata_list = airports['iata_code'].tolist()

for source in iata_list:
    for target in iata_list:
        if source == target:
            continue
        try:
            path = nx.dijkstra_path(G, source, target, weight='weight')
            dist = nx.dijkstra_path_length(G, source, target, weight='weight')
            coords = [[G.nodes[c]['lat'], G.nodes[c]['lon']] for c in path]
            all_paths[f"{source}-{target}"] = {
                "path":        path,
                "path_cities": [G.nodes[c]['city'] for c in path],
                "distance_km": round(dist, 1),
                "time_str":    estimate_flight_time(dist),
                "stops":       len(path) - 2,
                "coords":      coords
            }
        except nx.NetworkXNoPath:
            all_paths[f"{source}-{target}"] = None

print(f"Precomputed {len(all_paths)} paths")

# ── Build dropdown options ─────────────────────────────────
dropdown_options = "\n".join(
    f'<option value="{row["iata_code"]}">{row["iata_code"]} — {row["city"]}</option>'
    for _, row in airports.iterrows()
)

# ── Build Folium base map ──────────────────────────────────
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5, tiles='CartoDB positron')

# All routes (faint blue)
seen = set()
for _, row in routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    if pair in seen:
        continue
    seen.add(pair)
    src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
    dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
    folium.PolyLine(
        locations=[[src['latitude'], src['longitude']],
                   [dst['latitude'], dst['longitude']]],
        color='steelblue', weight=1.2, opacity=0.4
    ).add_to(m)

# Airport markers
for _, row in airports.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],
        icon=folium.Icon(color='darkblue', icon='plane', prefix='fa'),
        tooltip=f"{row['iata_code']} — {row['city']}"
    ).add_to(m)

# ── THE FIX: inject UI + JS after map initializes ─────────
# We use folium's JsCode injection which runs AFTER the map is ready
map_var = m.get_name()

# Embed all path data + the UI panel + findRoute function
# The key fix: wrap everything in window.onload so JS runs
# only after the Leaflet map object is fully initialized
injected = f"""
<div id="route-panel" style="
    position: fixed; top: 10px; left: 60px; z-index: 9999;
    background: white; padding: 14px 16px; border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.25);
    font-family: Arial, sans-serif; font-size: 13px;
    min-width: 240px;">

    <div style="font-weight:bold; font-size:14px; margin-bottom:10px;">
        ✈️ Find Shortest Route
    </div>

    <label>From:</label><br>
    <select id="origin-select" style="width:100%; margin-bottom:8px; padding:4px;">
        {dropdown_options}
    </select>

    <label>To:</label><br>
    <select id="destination-select" style="width:100%; margin-bottom:10px; padding:4px;">
        {dropdown_options}
    </select>

    <button onclick="findRoute()" style="
        width:100%; background:#1a73e8; color:white;
        border:none; padding:8px; border-radius:5px;
        cursor:pointer; font-size:13px;">
        Find Route
    </button>

    <div id="result-box" style="margin-top:12px; line-height:1.7;"></div>
</div>

<script>
// Embed all precomputed path data
var ALL_PATHS = {json.dumps(all_paths)};

// THE FIX: get the map object only after full page load
// This guarantees the Leaflet map is initialized before we reference it
var mapObj = null;
var currentLine = null;

window.addEventListener('load', function() {{
    // Now the Leaflet map variable exists
    mapObj = {map_var};
    console.log("Map object loaded:", mapObj);
}});

function findRoute() {{
    var origin      = document.getElementById('origin-select').value;
    var destination = document.getElementById('destination-select').value;
    var resultBox   = document.getElementById('result-box');

    // Guard: map not ready yet
    if (!mapObj) {{
        resultBox.innerHTML = "<span style='color:orange'>Map still loading, try again.</span>";
        return;
    }}

    // Guard: same airport selected
    if (origin === destination) {{
        resultBox.innerHTML = "<span style='color:red'>Please select two different airports.</span>";
        return;
    }}

    var key  = origin + "-" + destination;
    var data = ALL_PATHS[key];

    // Guard: no path found
    if (!data) {{
        resultBox.innerHTML = "<span style='color:red'>No route found.</span>";
        return;
    }}

    // Remove previous drawn line
    if (currentLine) {{
        mapObj.removeLayer(currentLine);
        currentLine = null;
    }}

    // Draw new shortest path line in red
    currentLine = L.polyline(data.coords, {{
        color:   'red',
        weight:  4,
        opacity: 0.9
    }}).addTo(mapObj);

    // Add animated dots at each stop along the path
    data.coords.forEach(function(coord, i) {{
        L.circleMarker(coord, {{
            radius:      6,
            color:       'red',
            fillColor:   'white',
            fillOpacity: 1,
            weight:      2
        }}).bindTooltip(data.path[i] + " — " + data.path_cities[i]).addTo(mapObj);
    }});

    // Zoom the map to fit the route
    mapObj.fitBounds(currentLine.getBounds(), {{padding: [40, 40]}});

    // Show result info
    var stopsText = data.stops === 0
        ? "<span style='color:green'>Direct flight (no stops)</span>"
        : "<span style='color:orange'>" + data.stops + " stop(s): " +
          data.path.slice(1, -1).join(" → ") + "</span>";

    resultBox.innerHTML =
        "<b>Route:</b> " + data.path.join(" → ") + "<br>" +
        "<b>Cities:</b> " + data.path_cities.join(" → ") + "<br>" +
        "<b>Distance:</b> " + data.distance_km + " km<br>" +
        "<b>Est. Time:</b> " + data.time_str + "<br>" +
        "<b>Stops:</b> " + stopsText;
}}
</script>
"""

m.get_root().html.add_child(folium.Element(injected))

m.save('output/interactive_route_map.html')
print("Saved: output/interactive_route_map.html")
print("Open in browser and test any airport pair!")