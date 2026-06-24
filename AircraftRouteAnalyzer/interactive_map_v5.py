"""
interactive_map_v5.py — Aircraft Route Analyzer
GeoPython for Aerospace — Rotten Grapes Private Limited
Team: Hritikesh Gaikwad, Utkarsh Chorode, Hriiday Garud (ADYPU)

Step 9: Interactive Folium Map with Dark Aviation UI (v5)
Run: python interactive_map_v5.py
Output: output/interactive_route_map.html
"""

import os
import json
import pandas as pd
import networkx as nx
import folium
from math import radians, sin, cos, sqrt, asin

# Always run from the script's own folder
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs('output', exist_ok=True)

# ── Haversine distance ────────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points."""
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return round(R * 2 * asin(sqrt(a)), 2)

# ── Flight time estimate ──────────────────────────────────────────────────────
def estimate_time(distance_km):
    """Estimate flight time: (distance / cruise speed) + 30-min taxi/climb."""
    hours = (distance_km / 750) + 0.5
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}h {m}m"

# ── Aircraft fuel specifications ──────────────────────────────────────────────
# Sources: Airbus/Boeing published performance data, ICAO Annex 16
# fuel_per_km: litres per km at cruise (average load factor)
# taxi: litres burned during taxi-in + taxi-out
# climb: litres burned during climb phase
# seats: max certified seats
AIRCRAFT_SPECS = {
    'ATR 72-600': {'fuel_per_km': 1.8, 'taxi': 80,  'climb': 150, 'seats': 70},
    'A320neo':    {'fuel_per_km': 3.2, 'taxi': 200, 'climb': 700, 'seats': 180},
    'A321neo':    {'fuel_per_km': 3.8, 'taxi': 220, 'climb': 800, 'seats': 220},
    'B737-800':   {'fuel_per_km': 3.4, 'taxi': 210, 'climb': 720, 'seats': 189},
    'B737 MAX 8': {'fuel_per_km': 3.0, 'taxi': 200, 'climb': 680, 'seats': 189},
}

ATF_PRICE_PER_LITRE = 90      # ₹/litre (Indian Aviation Turbine Fuel)
CO2_PER_KG_FUEL     = 3.16   # kg CO₂ per kg Jet-A burned (ICAO standard)
FUEL_DENSITY        = 0.8     # kg/litre (Jet-A approx density)
LOAD_FACTOR         = 0.85    # 85% seat occupancy (DGCA industry average)

def calc_fuel(distance_km, aircraft):
    """Calculate total fuel burn, CO₂ emissions and cost for a flight."""
    sp = AIRCRAFT_SPECS.get(aircraft, AIRCRAFT_SPECS['A320neo'])
    total_litres = distance_km * sp['fuel_per_km'] + sp['taxi'] + sp['climb']
    co2_kg       = total_litres * FUEL_DENSITY * CO2_PER_KG_FUEL
    pax          = int(sp['seats'] * LOAD_FACTOR)
    return {
        'fuel_litres':    round(total_litres, 1),
        'co2_kg':         round(co2_kg, 1),
        'co2_per_pax_kg': round(co2_kg / pax, 2),
        'fuel_cost_inr':  round(total_litres * ATF_PRICE_PER_LITRE, 0)
    }

# ── Load CSV data ─────────────────────────────────────────────────────────────
print("Loading data...")
airports       = pd.read_csv('data/airports.csv')
airline_routes = pd.read_csv('data/airline_routes.csv')

# ── Airline colour scheme ─────────────────────────────────────────────────────
AIRLINE_COLORS = {
    'IndiGo':    '#1a3fff',   # IndiGo blue
    'Air India': '#e31837',   # Air India red
    'Akasa Air': '#ff6b00',   # Akasa orange
    'SpiceJet':  '#ff0000',   # SpiceJet red
    'All':       'steelblue'
}
AIRLINES = ['All', 'IndiGo', 'Air India', 'Akasa Air', 'SpiceJet']

# ── Build NetworkX graph ──────────────────────────────────────────────────────
def build_graph(routes_df):
    """Build undirected weighted graph. Edge weight = haversine distance (km)."""
    G = nx.Graph()
    # Add all 15 airport nodes
    for _, row in airports.iterrows():
        G.add_node(row['iata_code'],
                   city=row['city'],
                   lat=row['latitude'],
                   lon=row['longitude'])
    # Add edges (unique route pairs only)
    seen = set()
    for _, row in routes_df.iterrows():
        pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
        if pair in seen:
            continue
        seen.add(pair)
        src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
        dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
        dist = haversine(src['latitude'], src['longitude'],
                         dst['latitude'], dst['longitude'])
        G.add_edge(row['origin_iata'], row['destination_iata'], weight=dist)
    return G

# Build one graph per airline + one combined "All" graph
print("Building graphs...")
graphs = {'All': build_graph(airline_routes)}
for airline in AIRLINES[1:]:
    df = airline_routes[airline_routes['airline'] == airline]
    if not df.empty:
        graphs[airline] = build_graph(df)

# ── Precompute Dijkstra shortest paths ───────────────────────────────────────
def precompute_paths(G, airline_df):
    """
    Precompute shortest paths for all origin-destination pairs using Dijkstra.
    Returns a dict keyed by "ORIG-DEST" with full route + fuel metadata.
    """
    all_paths = {}
    iata_list = airports['iata_code'].tolist()

    # Build aircraft lookup: (sorted pair) → aircraft_type
    aircraft_lookup = {}
    for _, row in airline_df.iterrows():
        pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
        aircraft_lookup[pair] = row['aircraft_type']

    for source in iata_list:
        for target in iata_list:
            if source == target:
                continue
            try:
                path   = nx.dijkstra_path(G, source, target, weight='weight')
                dist   = nx.dijkstra_path_length(G, source, target, weight='weight')
                coords = [[G.nodes[c]['lat'], G.nodes[c]['lon']] for c in path]

                # Per-leg distances and aircraft types
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

                primary_aircraft = leg_aircraft[0] if leg_aircraft else 'A320neo'
                fuel = calc_fuel(round(dist, 1), primary_aircraft)

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

print("Precomputing shortest paths for all airlines...")
all_airline_paths = {}
for airline in AIRLINES:
    if airline in graphs:
        print(f"  Computing {airline}...")
        airline_df = airline_routes if airline == 'All' else \
                     airline_routes[airline_routes['airline'] == airline]
        all_airline_paths[airline] = precompute_paths(graphs[airline], airline_df)
print("Done!")

# ── Build base Folium map ─────────────────────────────────────────────────────
print("Building Folium map...")
m = folium.Map(
    location=[20.5937, 78.9629],   # Centre of India
    zoom_start=5,
    tiles='CartoDB positron'       # Clean light base map
)

# Draw all routes as faint background lines
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
        color='steelblue', weight=1, opacity=0.25
    ).add_to(m)

# Add airport markers
for _, row in airports.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],
        icon=folium.Icon(color='darkblue', icon='plane', prefix='fa'),
        tooltip=f"{row['iata_code']} — {row['city']}"
    ).add_to(m)

map_var = m.get_name()   # e.g. "map_abc123" — needed to reference map in JS

# ── Generate dropdown options ─────────────────────────────────────────────────
airport_options = "\n".join(
    f'<option value="{r["iata_code"]}">{r["iata_code"]} — {r["city"]}</option>'
    for _, r in airports.iterrows()
)

airline_options = "\n".join(
    f'<option value="{a}">{a if a != "All" else "All Airlines"}</option>'
    for a in AIRLINES
)

# ── HTML + CSS + JS panel to inject ──────────────────────────────────────────
injected = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Panel container ── */
#route-panel {{
  position: fixed;
  top: 12px;
  left: 60px;
  z-index: 9999;
  width: 300px;
  background: linear-gradient(160deg, rgba(10,14,30,0.97) 0%, rgba(16,22,48,0.97) 100%);
  border: 1px solid rgba(99,140,255,0.2);
  border-radius: 16px;
  box-shadow: 0 8px 40px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04) inset;
  font-family: 'Inter', Arial, sans-serif;
  font-size: 13px;
  color: #c8d4f0;
  overflow: hidden;
}}

/* ── Header bar ── */
.rp-header {{
  background: linear-gradient(90deg, rgba(30,60,160,0.6) 0%, rgba(15,30,90,0.4) 100%);
  border-bottom: 1px solid rgba(99,140,255,0.18);
  padding: 14px 16px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}}
.rp-header-icon {{ font-size: 20px; line-height: 1; }}
.rp-title {{
  font-size: 13px;
  font-weight: 700;
  color: #e8eeff;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}}
.rp-subtitle {{
  font-size: 10px;
  color: rgba(140,165,230,0.7);
  margin-top: 1px;
  letter-spacing: 0.04em;
}}

/* ── Body ── */
.rp-body {{ padding: 14px 16px 16px; }}

/* ── Labels ── */
.rp-label {{
  display: block;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(140,165,230,0.75);
  margin-bottom: 5px;
}}

/* ── Dropdowns ── */
.rp-select {{
  width: 100%;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(99,140,255,0.22);
  border-radius: 8px;
  color: #dce6ff;
  padding: 8px 28px 8px 10px;
  font-family: 'Inter', Arial, sans-serif;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  outline: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%237090d0' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  transition: border-color 0.2s, background-color 0.2s;
  margin-bottom: 10px;
}}
.rp-select:hover {{
  border-color: rgba(99,140,255,0.5);
  background-color: rgba(255,255,255,0.08);
}}
.rp-select:focus {{
  border-color: rgba(99,140,255,0.7);
  box-shadow: 0 0 0 3px rgba(60,100,255,0.12);
}}
.rp-select option {{ background: #0e1530; color: #dce6ff; }}

/* ── From / To row ── */
.rp-route-row {{
  display: flex;
  gap: 8px;
  align-items: flex-end;
}}
.rp-route-row .rp-field {{ flex: 1; }}
.rp-route-row .rp-select {{ margin-bottom: 0; }}
.rp-swap-icon {{
  font-size: 14px;
  color: rgba(99,140,255,0.5);
  padding-bottom: 8px;
  flex-shrink: 0;
}}

/* ── Find Route button ── */
.rp-btn {{
  width: 100%;
  background: linear-gradient(135deg, #2a56e8 0%, #1a3abf 100%);
  color: #ffffff;
  border: none;
  border-radius: 10px;
  padding: 10px;
  font-family: 'Inter', Arial, sans-serif;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
  transition: background 0.2s, transform 0.1s, box-shadow 0.2s;
  box-shadow: 0 4px 15px rgba(42,86,232,0.35);
}}
.rp-btn:hover {{
  background: linear-gradient(135deg, #3d67f5 0%, #2548d4 100%);
  box-shadow: 0 6px 20px rgba(42,86,232,0.5);
  transform: translateY(-1px);
}}
.rp-btn:active {{ transform: translateY(0); }}

/* ── Result box ── */
#result-box {{ margin-top: 14px; font-size: 12px; line-height: 1.7; }}

/* ── Result card components ── */
.res-route-header {{
  background: rgba(42,86,232,0.12);
  border: 1px solid rgba(42,86,232,0.25);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
}}
.res-cities {{
  font-size: 13px;
  font-weight: 700;
  color: #e0e8ff;
  margin-bottom: 6px;
  line-height: 1.5;
}}
.res-airline-badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  margin-right: 5px;
}}
.res-stats-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px;
  margin: 10px 0;
}}
.res-stat {{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 8px;
  padding: 8px 10px;
}}
.res-stat-label {{
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: rgba(140,165,230,0.65);
  margin-bottom: 3px;
}}
.res-stat-value {{
  font-size: 13px;
  font-weight: 700;
  color: #dce6ff;
}}
.res-legs-title {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: rgba(140,165,230,0.65);
  margin: 10px 0 6px;
}}
.res-leg-row {{
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: rgba(255,255,255,0.03);
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 11.5px;
  color: #bdd0ff;
}}
.res-leg-dot {{
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #3a64f0;
  flex-shrink: 0;
}}
.res-leg-ac {{
  margin-left: auto;
  font-size: 10px;
  color: rgba(140,165,230,0.6);
  font-weight: 500;
}}
.res-error {{
  background: rgba(220,60,60,0.12);
  border: 1px solid rgba(220,60,60,0.25);
  border-radius: 8px;
  padding: 10px 12px;
  color: #ffaaaa;
  font-size: 12px;
  line-height: 1.6;
}}
</style>

<!-- ═══ ROUTE PANEL ═══ -->
<div id="route-panel">
  <div class="rp-header">
    <div class="rp-header-icon">✈️</div>
    <div>
      <div class="rp-title">Route Analyzer</div>
      <div class="rp-subtitle">Indian Domestic Aviation · 15 Airports</div>
    </div>
  </div>

  <div class="rp-body">

    <!-- Airline dropdown -->
    <label class="rp-label">Airline</label>
    <select id="airline-select" class="rp-select">
      {airline_options}
    </select>

    <!-- From / To row -->
    <div class="rp-route-row">
      <div class="rp-field">
        <label class="rp-label">From</label>
        <select id="origin-select" class="rp-select">
          {airport_options}
        </select>
      </div>
      <div class="rp-swap-icon">⇄</div>
      <div class="rp-field">
        <label class="rp-label">To</label>
        <select id="destination-select" class="rp-select">
          {airport_options}
        </select>
      </div>
    </div>

    <button class="rp-btn" onclick="findRoute()">
      <span>🔍</span> Find Route
    </button>

    <div id="result-box"></div>
  </div>
</div>

<script>
// ── Precomputed paths for all airlines ──
var ALL_AIRLINE_PATHS = {json.dumps(all_airline_paths)};
var AIRLINE_COLORS    = {json.dumps(AIRLINE_COLORS)};

var mapObj      = null;
var drawnLayers = [];

// Get map reference after Leaflet finishes loading
window.addEventListener('load', function() {{
    mapObj = {map_var};
}});

// Clear previously drawn route layers
function clearLayers() {{
    drawnLayers.forEach(function(l) {{ mapObj.removeLayer(l); }});
    drawnLayers = [];
}}

// ── Main route finder ──
function findRoute() {{
    var airline     = document.getElementById('airline-select').value;
    var origin      = document.getElementById('origin-select').value;
    var destination = document.getElementById('destination-select').value;
    var resultBox   = document.getElementById('result-box');

    // Guard: map not ready
    if (!mapObj) {{
        resultBox.innerHTML = "<div class='res-error'>⏳ Map is still loading, please wait...</div>";
        return;
    }}
    // Guard: same airport selected
    if (origin === destination) {{
        resultBox.innerHTML = "<div class='res-error'>⚠ Please select two different airports.</div>";
        return;
    }}
    // Guard: airline has no data
    var paths = ALL_AIRLINE_PATHS[airline];
    if (!paths) {{
        resultBox.innerHTML = "<div class='res-error'>⚠ No route data found for " + airline + ".</div>";
        return;
    }}
    // Guard: no path exists for this origin-destination
    var key  = origin + "-" + destination;
    var data = paths[key];
    if (!data) {{
        resultBox.innerHTML =
            "<div class='res-error'>⚠ " + airline + " does not operate this route.<br>" +
            "<span style='font-size:10px;opacity:0.8;'>Try selecting <b>All Airlines</b> to see the full network.</span></div>";
        return;
    }}

    clearLayers();

    var path   = data.path;
    var cities = data.path_cities;
    var coords = data.coords;
    var legs   = data.leg_distances;
    var legAC  = data.leg_aircraft;
    var color  = AIRLINE_COLORS[airline] || '#3a64f0';

    // ── Draw each leg as a coloured polyline ──
    for (var i = 0; i < coords.length - 1; i++) {{
        var legTime = Math.round((legs[i] / 750 + 0.5) * 60);
        var leg = L.polyline([coords[i], coords[i+1]], {{
            color: color, weight: 4, opacity: 0.9
        }});
        leg.bindTooltip(
            "Leg " + (i+1) + ": " + path[i] + " → " + path[i+1] +
            "<br>Distance: " + legs[i] + " km" +
            "<br>Aircraft: " + legAC[i] +
            "<br>Est. Time: ~" + legTime + " min"
        );
        leg.addTo(mapObj);
        drawnLayers.push(leg);
    }}

    // ── Draw stop markers ──
    coords.forEach(function(coord, i) {{
        var isOrigin = (i === 0);
        var isDest   = (i === coords.length - 1);
        var fill     = isOrigin ? '#2dc653' : isDest ? '#e63946' : '#ff9f1c';
        var marker   = L.circleMarker(coord, {{
            radius: (isOrigin || isDest) ? 10 : 7,
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

    // Zoom map to fit route
    mapObj.fitBounds(L.polyline(coords).getBounds(), {{padding: [60, 60]}});

    // ── Build result card ──
    var badgeColors = {{
        'IndiGo':    '#1a3fff',
        'Air India': '#e31837',
        'Akasa Air': '#ff6b00',
        'SpiceJet':  '#cc0000',
        'All':       '#3a64f0'
    }};
    var bc = badgeColors[airline] || '#3a64f0';

    var stopsLabel = data.stops === 0
        ? "<span style='background:rgba(45,198,83,0.2);color:#60e080;border:1px solid rgba(45,198,83,0.3);padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;'>✈ Direct</span>"
        : "<span style='background:rgba(255,159,28,0.2);color:#ffb84d;border:1px solid rgba(255,159,28,0.3);padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;'>🔁 " + data.stops + " Stop" + (data.stops > 1 ? "s" : "") + "</span>";

    // Leg breakdown rows
    var legRows = "";
    for (var j = 0; j < path.length - 1; j++) {{
        var lt = Math.round((legs[j] / 750 + 0.5) * 60);
        legRows +=
            "<div class='res-leg-row'>" +
            "<div class='res-leg-dot'></div>" +
            "<span><b>" + path[j] + "</b> → <b>" + path[j+1] + "</b> &nbsp;·&nbsp; " + legs[j] + " km</span>" +
            "<span class='res-leg-ac'>" + legAC[j] + " · ~" + lt + "m</span>" +
            "</div>";
    }}

    resultBox.innerHTML =
        "<div class='res-route-header'>" +
            "<div class='res-cities'>" +
                "🛫 " + cities[0] + " (" + path[0] + ")<br>" +
                "<span style='color:rgba(140,165,230,0.4);font-size:11px;'>  ↓</span><br>" +
                "🛬 " + cities[cities.length-1] + " (" + path[path.length-1] + ")" +
            "</div>" +
            "<div style='margin-top:7px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;'>" +
                "<span class='res-airline-badge' style='background:" + bc + "33;color:" + bc + ";border:1px solid " + bc + "55;'>" +
                    (airline === 'All' ? 'All Airlines' : airline) +
                "</span>" +
                stopsLabel +
            "</div>" +
        "</div>" +

        "<div class='res-stats-grid'>" +
            "<div class='res-stat'><div class='res-stat-label'>Distance</div><div class='res-stat-value'>" + data.distance_km + " km</div></div>" +
            "<div class='res-stat'><div class='res-stat-label'>Flight Time</div><div class='res-stat-value'>" + data.time_str + "</div></div>" +
            "<div class='res-stat'><div class='res-stat-label'>Fuel</div><div class='res-stat-value'>" + data.fuel_litres + " L</div></div>" +
            "<div class='res-stat'><div class='res-stat-label'>CO₂ / pax</div><div class='res-stat-value'>" + data.co2_per_pax + " kg</div></div>" +
            "<div class='res-stat'><div class='res-stat-label'>Total CO₂</div><div class='res-stat-value'>" + data.co2_kg + " kg</div></div>" +
            "<div class='res-stat'><div class='res-stat-label'>Fuel Cost</div><div class='res-stat-value'>₹" + (data.fuel_cost_inr/100000).toFixed(1) + "L</div></div>" +
        "</div>" +

        "<div class='res-legs-title'>Leg-by-Leg Breakdown</div>" +
        legRows;
}}
</script>
"""

# ── Inject panel into the Folium HTML and save ────────────────────────────────
m.get_root().html.add_child(folium.Element(injected))
m.save('output/interactive_route_map.html')
print("✅ Saved: output/interactive_route_map.html")
print("   Open this file in your browser to use the map.")
