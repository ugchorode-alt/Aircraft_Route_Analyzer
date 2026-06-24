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

G = nx.Graph()
for _, row in airports.iterrows():
    G.add_node(row['iata_code'], city=row['city'],
               lat=row['latitude'], lon=row['longitude'])

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

# Precompute all paths
all_paths = {}
for source in airports['iata_code']:
    for target in airports['iata_code']:
        if source == target:
            continue
        try:
            path = nx.dijkstra_path(G, source, target, weight='weight')
            dist = nx.dijkstra_path_length(G, source, target, weight='weight')
            coords = [[G.nodes[c]['lat'], G.nodes[c]['lon']] for c in path]

            # Per-leg distances
            leg_distances = []
            for i in range(len(path) - 1):
                a = airports[airports['iata_code'] == path[i]].iloc[0]
                b = airports[airports['iata_code'] == path[i+1]].iloc[0]
                leg_distances.append(haversine(
                    a['latitude'], a['longitude'],
                    b['latitude'], b['longitude']
                ))

            all_paths[f"{source}-{target}"] = {
                "path":          path,
                "path_cities":   [G.nodes[c]['city'] for c in path],
                "distance_km":   round(dist, 1),
                "time_str":      estimate_flight_time(dist),
                "stops":         len(path) - 2,
                "coords":        coords,
                "leg_distances": leg_distances
            }
        except nx.NetworkXNoPath:
            all_paths[f"{source}-{target}"] = None

# Dropdown options
dropdown_options = "\n".join(
    f'<option value="{r["iata_code"]}">{r["iata_code"]} — {r["city"]}</option>'
    for _, r in airports.iterrows()
)

# Build base map
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5, tiles='CartoDB positron')

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
        color='steelblue', weight=1.2, opacity=0.35
    ).add_to(m)

for _, row in airports.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],
        icon=folium.Icon(color='darkblue', icon='plane', prefix='fa'),
        tooltip=f"{row['iata_code']} — {row['city']}"
    ).add_to(m)

map_var = m.get_name()

injected = f"""
<div id="route-panel" style="
    position:fixed; top:10px; left:60px; z-index:9999;
    background:white; padding:14px 16px; border-radius:10px;
    box-shadow:0 2px 10px rgba(0,0,0,0.25);
    font-family:Arial,sans-serif; font-size:13px; min-width:260px;">

    <div style="font-weight:bold; font-size:14px; margin-bottom:10px;">
        ✈️ Find Shortest Route
    </div>

    <label>From:</label><br>
    <select id="origin-select" style="width:100%;margin-bottom:8px;padding:4px;">
        {dropdown_options}
    </select>

    <label>To:</label><br>
    <select id="destination-select" style="width:100%;margin-bottom:10px;padding:4px;">
        {dropdown_options}
    </select>

    <button onclick="findRoute()" style="
        width:100%;background:#1a73e8;color:white;
        border:none;padding:8px;border-radius:5px;
        cursor:pointer;font-size:13px;font-weight:bold;">
        🔍 Find Route
    </button>

    <div id="result-box" style="margin-top:12px;line-height:1.8;font-size:12.5px;"></div>
</div>

<script>
var ALL_PATHS = {json.dumps(all_paths)};
var mapObj = null;

// THE KEY: store ALL drawn layers so we can remove them cleanly
var drawnLayers = [];

window.addEventListener('load', function() {{
    mapObj = {map_var};
}});

function clearDrawnLayers() {{
    // Remove every previously drawn line and marker
    drawnLayers.forEach(function(layer) {{
        mapObj.removeLayer(layer);
    }});
    drawnLayers = [];  // reset the list
}}

function findRoute() {{
    var origin      = document.getElementById('origin-select').value;
    var destination = document.getElementById('destination-select').value;
    var resultBox   = document.getElementById('result-box');

    if (!mapObj) {{
        resultBox.innerHTML = "<span style='color:orange'>Map loading, try again.</span>";
        return;
    }}
    if (origin === destination) {{
        resultBox.innerHTML = "<span style='color:red'>⚠ Select two different airports.</span>";
        return;
    }}

    var key  = origin + "-" + destination;
    var data = ALL_PATHS[key];

    if (!data) {{
        resultBox.innerHTML = "<span style='color:red'>No route found.</span>";
        return;
    }}

    // ── Clear all previously drawn layers first ────────────
    clearDrawnLayers();

    var path   = data.path;
    var cities = data.path_cities;
    var coords = data.coords;
    var legs   = data.leg_distances;

    // ── Draw each leg as a separate colored line ───────────
    // This lets us color origin→stop differently from stop→destination
    for (var i = 0; i < coords.length - 1; i++) {{
        var segColor = (i === 0) ? '#e63946'       // first leg: bright red
                     : (i === coords.length - 2) ? '#e63946'  // last leg: bright red
                     : '#ff6b35';                  // middle legs: orange-red

        var leg = L.polyline([coords[i], coords[i+1]], {{
            color:   segColor,
            weight:  4,
            opacity: 0.9
        }});
        leg.bindTooltip(
            "✈ Leg " + (i+1) + ": " + path[i] + " → " + path[i+1] +
            "<br>Distance: " + legs[i] + " km"
        );
        leg.addTo(mapObj);
        drawnLayers.push(leg);  // store so we can remove later
    }}

    // ── Draw markers at each airport in the path ───────────
    coords.forEach(function(coord, i) {{
        var isOrigin      = (i === 0);
        var isDestination = (i === coords.length - 1);
        var isStop        = (!isOrigin && !isDestination);

        // Color: green=origin, red=destination, orange=stop
        var fillColor = isOrigin      ? '#2dc653'   // green
                      : isDestination ? '#e63946'   // red
                      : '#ff9f1c';                  // orange for stops

        var radius = isStop ? 7 : 10;

        // Label: 1=Origin, 2=Stop, 3=Dest
        var label = isOrigin      ? '🟢 ORIGIN'
                  : isDestination ? '🔴 DEST'
                  : '🟠 STOP ' + i;

        var marker = L.circleMarker(coord, {{
            radius:      radius,
            color:       'white',
            fillColor:   fillColor,
            fillOpacity: 1,
            weight:      2.5
        }});

        // Popup shows full info for this airport
        marker.bindPopup(
            "<b>" + label + "</b><br>" +
            "<b>" + path[i] + "</b> — " + cities[i] +
            (isStop ? "<br><i>Connection airport</i>" : "")
        );

        // Tooltip on hover
        marker.bindTooltip(path[i] + " — " + cities[i]);

        marker.addTo(mapObj);
        drawnLayers.push(marker);  // store for cleanup
    }});

    // ── Zoom map to fit the route ──────────────────────────
    var routeLine = L.polyline(coords);
    mapObj.fitBounds(routeLine.getBounds(), {{padding: [60, 60]}});

    // ── Build the leg-by-leg breakdown table ───────────────
    var legRows = "";
    for (var j = 0; j < path.length - 1; j++) {{
        var legTime = Math.round((legs[j] / 750 + 0.5) * 60);
        legRows += "<tr style='border-bottom:1px solid #eee;'>" +
            "<td style='padding:3px 6px;'><b>" + (j+1) + "</b></td>" +
            "<td style='padding:3px 6px;'>" + path[j] + " → " + path[j+1] + "</td>" +
            "<td style='padding:3px 6px;'>" + legs[j] + " km</td>" +
            "<td style='padding:3px 6px;'>~" + legTime + " min</td>" +
            "</tr>";
    }}

    // ── Build stop badges ──────────────────────────────────
    var stopBadges = "";
    if (data.stops === 0) {{
        stopBadges = "<span style='background:#2dc653;color:white;padding:2px 8px;border-radius:10px;font-size:11px;'>✈ Direct</span>";
    }} else {{
        for (var k = 1; k < path.length - 1; k++) {{
            stopBadges += "<span style='background:#ff9f1c;color:white;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:4px;'>" +
                "🔁 " + path[k] + " (" + cities[k] + ")</span> ";
        }}
    }}

    // ── Display result ─────────────────────────────────────
    resultBox.innerHTML =
        "<div style='background:#f8f9fa;padding:8px;border-radius:6px;margin-bottom:8px;'>" +
            "<b>🛫 " + cities[0] + " (" + path[0] + ")</b><br>" +
            "<span style='color:#666;font-size:11px;'>↓ " + data.distance_km + " km total</span><br>" +
            "<b>🛬 " + cities[cities.length-1] + " (" + path[path.length-1] + ")</b>" +
        "</div>" +

        "<b>⏱ Est. Time:</b> " + data.time_str + "<br>" +
        "<b>📍 Stops:</b> " + stopBadges + "<br><br>" +

        "<b>Leg-by-leg breakdown:</b>" +
        "<table style='width:100%;border-collapse:collapse;margin-top:4px;font-size:12px;'>" +
            "<tr style='background:#f0f0f0;'>" +
                "<th style='padding:3px 6px;text-align:left;'>#</th>" +
                "<th style='padding:3px 6px;text-align:left;'>Route</th>" +
                "<th style='padding:3px 6px;text-align:left;'>Dist</th>" +
                "<th style='padding:3px 6px;text-align:left;'>Time</th>" +
            "</tr>" +
            legRows +
        "</table>";
}}
</script>
"""

m.get_root().html.add_child(folium.Element(injected))
m.save('output/interactive_route_map.html')
print("Saved: output/interactive_route_map.html")