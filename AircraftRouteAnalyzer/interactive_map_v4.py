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

def estimate_time(distance_km):
    hours = (distance_km / 750) + 0.5
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}h {m}m"

#  Aircraft fuel specs
AIRCRAFT_SPECS = {
    'ATR 72-600': {'fuel_per_km': 1.8, 'taxi': 80,  'climb': 150, 'seats': 70},
    'A320neo':    {'fuel_per_km': 3.2, 'taxi': 200, 'climb': 700, 'seats': 180},
    'A321neo':    {'fuel_per_km': 3.8, 'taxi': 220, 'climb': 800, 'seats': 220},
    'B737-800':   {'fuel_per_km': 3.4, 'taxi': 210, 'climb': 720, 'seats': 189},
    'B737 MAX 8': {'fuel_per_km': 3.0, 'taxi': 200, 'climb': 680, 'seats': 189},
}

def calc_fuel(distance_km, aircraft):
    sp = AIRCRAFT_SPECS.get(aircraft, AIRCRAFT_SPECS['A320neo'])
    total_litres = distance_km * sp['fuel_per_km'] + sp['taxi'] + sp['climb']
    co2_kg = total_litres * 0.8 * 3.16
    pax = int(sp['seats'] * 0.85)
    return {
        'fuel_litres':    round(total_litres, 1),
        'co2_kg':         round(co2_kg, 1),
        'co2_per_pax_kg': round(co2_kg / pax, 2),
        'fuel_cost_inr':  round(total_litres * 90, 0)
    }

#  Load data 
airports      = pd.read_csv('data/airports.csv')
airline_routes = pd.read_csv('data/airline_routes.csv')

# Airline colours for map
AIRLINE_COLORS = {
    'IndiGo':    '#1a3fff',   # IndiGo blue
    'Air India': '#205e52',   # Air India red
    'Akasa Air': '#ff6b00',   # Akasa orange
    'SpiceJet':  '#61482f',   # SpiceJet red
    'All':       'steelblue'
}

AIRLINES = ['All', 'IndiGo', 'Air India', 'Akasa Air', 'SpiceJet']

# Build one graph per airline + one combined
def build_graph(routes_df):
    G = nx.Graph()
    for _, row in airports.iterrows():
        G.add_node(row['iata_code'], city=row['city'],
                   lat=row['latitude'], lon=row['longitude'])
    seen = set()
    for _, row in routes_df.iterrows():
        pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
        if pair not in seen:
            seen.add(pair)
            src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
            dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
            dist = haversine(src['latitude'], src['longitude'],
                             dst['latitude'], dst['longitude'])
            G.add_edge(row['origin_iata'], row['destination_iata'], weight=dist)
    return G

# Build graphs
graphs = {'All': build_graph(airline_routes)}
for airline in AIRLINES[1:]:
    df = airline_routes[airline_routes['airline'] == airline]
    if not df.empty:
        graphs[airline] = build_graph(df)

# Precompute shortest paths for each airline 
def precompute_paths(G, airline_df):
    all_paths = {}
    iata_list = airports['iata_code'].tolist()

    # Get aircraft lookup for this airline
    aircraft_lookup = {}
    for _, row in airline_df.iterrows():
        pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
        aircraft_lookup[pair] = row['aircraft_type']

    for source in iata_list:
        for target in iata_list:
            if source == target:
                continue
            try:
                path  = nx.dijkstra_path(G, source, target, weight='weight')
                dist  = nx.dijkstra_path_length(G, source, target, weight='weight')
                coords = [[G.nodes[c]['lat'], G.nodes[c]['lon']] for c in path]

                # Leg distances + aircraft per leg
                leg_distances = []
                leg_aircraft  = []
                for i in range(len(path) - 1):
                    a = airports[airports['iata_code'] == path[i]].iloc[0]
                    b = airports[airports['iata_code'] == path[i+1]].iloc[0]
                    d = haversine(a['latitude'], a['longitude'],
                                  b['latitude'], b['longitude'])
                    leg_distances.append(d)
                    pair = tuple(sorted([path[i], path[i+1]]))
                    leg_aircraft.append(aircraft_lookup.get(pair, 'A320neo'))

                # Use first leg aircraft for overall fuel calc
                primary_aircraft = leg_aircraft[0] if leg_aircraft else 'A320neo'
                fuel = calc_fuel(dist, primary_aircraft)

                all_paths[f"{source}-{target}"] = {
                    "path":          path,
                    "path_cities":   [G.nodes[c]['city'] for c in path],
                    "distance_km":   round(dist, 1),
                    "time_str":      estimate_time(dist),
                    "stops":         len(path) - 2,
                    "coords":        coords,
                    "leg_distances": leg_distances,
                    "leg_aircraft":  leg_aircraft,
                    "aircraft":      primary_aircraft,
                    "fuel_litres":   fuel['fuel_litres'],
                    "co2_kg":        fuel['co2_kg'],
                    "co2_per_pax":   fuel['co2_per_pax_kg'],
                    "fuel_cost_inr": fuel['fuel_cost_inr']
                }
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                all_paths[f"{source}-{target}"] = None
    return all_paths

print("Precomputing paths for all airlines...")
all_airline_paths = {}
for airline in AIRLINES:
    if airline in graphs:
        print(f"  Computing {airline}...")
        airline_df = airline_routes if airline == 'All' else \
                     airline_routes[airline_routes['airline'] == airline]
        all_airline_paths[airline] = precompute_paths(graphs[airline], airline_df)

print("Done!")

# Build base Folium map 
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5,
               tiles='CartoDB positron')

# Draw all routes (faint background)
seen = set()
for _, row in airline_routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    if pair in seen:
        continue
    seen.add(pair)
    src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
    dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
    folium.PolyLine(
        locations=[[src['latitude'], src['longitude']],
                   [dst['latitude'], dst['longitude']]],
        color='steelblue', weight=1, opacity=0.3
    ).add_to(m)

# Airport markers
for _, row in airports.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],
        icon=folium.Icon(color='darkblue', icon='plane', prefix='fa'),
        tooltip=f"{row['iata_code']} — {row['city']}"
    ).add_to(m)

map_var = m.get_name()

# Dropdown HTML
airport_options = "\n".join(
    f'<option value="{r["iata_code"]}">{r["iata_code"]} — {r["city"]}</option>'
    for _, r in airports.iterrows()
)

airline_options = "\n".join(
    f'<option value="{a}">{a}</option>' for a in AIRLINES
)

# Airline badge colours
airline_badge_css = {
    'IndiGo':    'background:#1a3fff;color:white',
    'Air India': 'background:#e31837;color:white',
    'Akasa Air': 'background:#ff6b00;color:white',
    'SpiceJet':  'background:#cc0000;color:white',
    'All':       'background:#555;color:white'
}

injected = f"""
<div id="route-panel" style="
    position:fixed; top:10px; left:60px; z-index:9999;
    background:white; padding:14px 16px; border-radius:10px;
    box-shadow:0 2px 10px rgba(0,0,0,0.25);
    font-family:Arial,sans-serif; font-size:13px; min-width:270px;">

    <div style="font-weight:bold;font-size:14px;margin-bottom:10px;">
        ✈️ Aircraft Route Analyzer
    </div>

    <label>Airline:</label><br>
    <select id="airline-select" style="width:100%;margin-bottom:8px;padding:4px;">
        {airline_options}
    </select>

    <label>From:</label><br>
    <select id="origin-select" style="width:100%;margin-bottom:8px;padding:4px;">
        {airport_options}
    </select>

    <label>To:</label><br>
    <select id="destination-select" style="width:100%;margin-bottom:10px;padding:4px;">
        {airport_options}
    </select>

    <button onclick="findRoute()" style="
        width:100%;background:#1a73e8;color:white;border:none;
        padding:8px;border-radius:5px;cursor:pointer;
        font-size:13px;font-weight:bold;">
        🔍 Find Route
    </button>

    <div id="result-box" style="margin-top:12px;line-height:1.8;font-size:12px;"></div>
</div>

<script>
// All precomputed paths per airline
var ALL_AIRLINE_PATHS = {json.dumps(all_airline_paths)};

var AIRLINE_COLORS = {json.dumps(AIRLINE_COLORS)};

var mapObj = null;
var drawnLayers = [];

window.addEventListener('load', function() {{
    mapObj = {map_var};
}});

function clearLayers() {{
    drawnLayers.forEach(function(l) {{ mapObj.removeLayer(l); }});
    drawnLayers = [];
}}

function findRoute() {{
    var airline     = document.getElementById('airline-select').value;
    var origin      = document.getElementById('origin-select').value;
    var destination = document.getElementById('destination-select').value;
    var resultBox   = document.getElementById('result-box');

    if (!mapObj) {{
        resultBox.innerHTML = "<span style='color:orange'>Map loading...</span>";
        return;
    }}
    if (origin === destination) {{
        resultBox.innerHTML = "<span style='color:red'>⚠ Select two different airports.</span>";
        return;
    }}

    var paths = ALL_AIRLINE_PATHS[airline];
    if (!paths) {{
        resultBox.innerHTML = "<span style='color:red'>" + airline + " has no route data.</span>";
        return;
    }}

    var key  = origin + "-" + destination;
    var data = paths[key];

    if (!data) {{
        resultBox.innerHTML =
            "<span style='color:red'>⚠ " + airline + " does not operate this route.</span><br>" +
            "<small>Try selecting 'All' to see combined network.</small>";
        return;
    }}

    clearLayers();

    var path   = data.path;
    var cities = data.path_cities;
    var coords = data.coords;
    var legs   = data.leg_distances;
    var legAC  = data.leg_aircraft;
    var color  = AIRLINE_COLORS[airline] || '#e63946';

    // Draw each leg
    for (var i = 0; i < coords.length - 1; i++) {{
        var leg = L.polyline([coords[i], coords[i+1]], {{
            color: color, weight: 4, opacity: 0.9
        }});
        var legTime = Math.round((legs[i] / 750 + 0.5) * 60);
        leg.bindTooltip(
            "Leg " + (i+1) + ": " + path[i] + " → " + path[i+1] +
            "<br>Distance: " + legs[i] + " km" +
            "<br>Aircraft: " + legAC[i] +
            "<br>Est. Time: ~" + legTime + " min"
        );
        leg.addTo(mapObj);
        drawnLayers.push(leg);
    }}

    // Draw stop markers
    coords.forEach(function(coord, i) {{
        var isOrigin = (i === 0);
        var isDest   = (i === coords.length - 1);
        var fill = isOrigin ? '#2dc653' : isDest ? '#e63946' : '#ff9f1c';
        var marker = L.circleMarker(coord, {{
            radius: isDest || isOrigin ? 10 : 7,
            color: 'white', fillColor: fill,
            fillOpacity: 1, weight: 2.5
        }});
        marker.bindPopup(
            "<b>" + path[i] + "</b> — " + cities[i] +
            ((!isOrigin && !isDest) ? "<br><i>Connection stop</i>" : "")
        );
        marker.bindTooltip(path[i] + " — " + cities[i]);
        marker.addTo(mapObj);
        drawnLayers.push(marker);
    }});

    mapObj.fitBounds(L.polyline(coords).getBounds(), {{padding:[60,60]}});

    // Airline badge
    var badgeStyle = {{
        'IndiGo':    'background:#1a3fff;color:white',
        'Air India': 'background:#e31837;color:white',
        'Akasa Air': 'background:#ff6b00;color:white',
        'SpiceJet':  'background:#cc0000;color:white',
        'All':       'background:#555;color:white'
    }}[airline] || 'background:#555;color:white';

    // Stops
    var stopsBadge = data.stops === 0
        ? "<span style='background:#2dc653;color:white;padding:2px 8px;border-radius:10px;'>✈ Direct</span>"
        : data.path.slice(1,-1).map(function(c,i) {{
            return "<span style='background:#ff9f1c;color:white;padding:2px 6px;border-radius:10px;margin-right:3px;'>🔁 " + c + "</span>";
          }}).join('');

    // Leg table
    var legRows = "";
    for (var j = 0; j < path.length - 1; j++) {{
        var lt = Math.round((legs[j] / 750 + 0.5) * 60);
        legRows +=
            "<tr style='border-bottom:1px solid #eee;'>" +
            "<td style='padding:3px 5px;'><b>" + (j+1) + "</b></td>" +
            "<td style='padding:3px 5px;'>" + path[j] + "→" + path[j+1] + "</td>" +
            "<td style='padding:3px 5px;'>" + legs[j] + " km</td>" +
            "<td style='padding:3px 5px;'>" + legAC[j] + "</td>" +
            "<td style='padding:3px 5px;'>~" + lt + " min</td>" +
            "</tr>";
    }}

    resultBox.innerHTML =
        "<span style='" + badgeStyle + ";padding:2px 10px;border-radius:10px;font-size:11px;'>" +
            airline + "</span><br><br>" +

        "<div style='background:#f8f9fa;padding:8px;border-radius:6px;margin-bottom:8px;'>" +
            "<b>🛫 " + cities[0] + " (" + path[0] + ")</b><br>" +
            "<span style='color:#888;font-size:11px;'>↓ " + data.distance_km + " km</span><br>" +
            "<b>🛬 " + cities[cities.length-1] + " (" + path[path.length-1] + ")</b>" +
        "</div>" +

        "<b>⏱ Time:</b> " + data.time_str + "<br>" +
        "<b>✈ Aircraft:</b> " + data.aircraft + "<br>" +
        "<b>⛽ Fuel:</b> " + data.fuel_litres + " L<br>" +
        "<b>🌿 CO₂:</b> " + data.co2_kg + " kg (" + data.co2_per_pax + " kg/pax)<br>" +
        "<b>💰 Fuel Cost:</b> ₹" + data.fuel_cost_inr.toLocaleString('en-IN') + "<br>" +
        "<b>📍 Stops:</b> " + stopsBadge + "<br><br>" +

        "<b>Leg-by-leg breakdown:</b>" +
        "<table style='width:100%;border-collapse:collapse;margin-top:4px;font-size:11px;'>" +
            "<tr style='background:#f0f0f0;'>" +
                "<th style='padding:3px 5px;text-align:left;'>#</th>" +
                "<th style='padding:3px 5px;text-align:left;'>Route</th>" +
                "<th style='padding:3px 5px;text-align:left;'>Dist</th>" +
                "<th style='padding:3px 5px;text-align:left;'>Aircraft</th>" +
                "<th style='padding:3px 5px;text-align:left;'>Time</th>" +
            "</tr>" +
            legRows +
        "</table>";
}}
</script>
"""

m.get_root().html.add_child(folium.Element(injected))
m.save('output/interactive_route_map.html')
print("Saved: output/interactive_route_map.html")