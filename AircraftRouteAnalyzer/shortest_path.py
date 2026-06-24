import os
import json
import pandas as pd
import networkx as nx
from math import radians, sin, cos, sqrt, asin

# ── Always run from project folder ────────────────────────
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

# ── Load data ──────────────────────────────────────────────
airports = pd.read_csv('data/airports.csv')
routes   = pd.read_csv('data/flight_frequencies.csv')

# ── Build NetworkX graph ───────────────────────────────────
G = nx.Graph()  # undirected — flights go both ways

for _, row in airports.iterrows():
    G.add_node(row['iata_code'],
               name=row['airport_name'],
               city=row['city'],
               lat=row['latitude'],
               lon=row['longitude'])

# Deduplicate and add edges
seen_pairs = set()
for _, row in routes.iterrows():
    pair = tuple(sorted([row['origin_iata'], row['destination_iata']]))
    if pair not in seen_pairs:
        seen_pairs.add(pair)
        src = airports[airports['iata_code'] == row['origin_iata']].iloc[0]
        dst = airports[airports['iata_code'] == row['destination_iata']].iloc[0]
        dist = haversine(src['latitude'], src['longitude'],
                         dst['latitude'], dst['longitude'])
        G.add_edge(row['origin_iata'], row['destination_iata'],
                   weight=dist,
                   frequency=row['flights_per_week'])

print(f"Graph ready: {G.number_of_nodes()} airports, {G.number_of_edges()} routes")

# ══════════════════════════════════════════════════════════
# DIJKSTRA'S ALGORITHM
# ══════════════════════════════════════════════════════════
def dijkstra_path(source, target):
    try:
        path = nx.dijkstra_path(G, source, target, weight='weight')
        dist = nx.dijkstra_path_length(G, source, target, weight='weight')
        return path, round(dist, 2)
    except nx.NetworkXNoPath:
        return None, None

# ══════════════════════════════════════════════════════════
# A* ALGORITHM
# ══════════════════════════════════════════════════════════
def heuristic(u, v):
    # Straight-line haversine distance as the heuristic
    u_data = G.nodes[u]
    v_data = G.nodes[v]
    return haversine(u_data['lat'], u_data['lon'],
                     v_data['lat'], v_data['lon'])

def astar_path(source, target):
    try:
        path = nx.astar_path(G, source, target,
                             heuristic=heuristic, weight='weight')
        dist = nx.astar_path_length(G, source, target,
                                    heuristic=heuristic, weight='weight')
        return path, round(dist, 2)
    except nx.NetworkXNoPath:
        return None, None

# ══════════════════════════════════════════════════════════
# RUN QUERIES — change these pairs as needed
# ══════════════════════════════════════════════════════════
queries = [
    ('DEL', 'COK'),
    ('DEL', 'BBI'),
    ('IXC', 'MAA'),
    ('JAI', 'CCU'),
    ('GOI', 'BBI'),
]

results = []

print("\n" + "="*60)
print("SHORTEST PATH RESULTS")
print("="*60)

for source, target in queries:
    d_path, d_dist = dijkstra_path(source, target)
    a_path, a_dist = astar_path(source, target)

    src_city = G.nodes[source]['city']
    tgt_city = G.nodes[target]['city']

    print(f"\n{source} ({src_city}) → {target} ({tgt_city})")
    print(f"  Dijkstra : {' → '.join(d_path)} | {d_dist} km")
    print(f"  A*       : {' → '.join(a_path)} | {a_dist} km")
    print(f"  Stops    : {len(d_path) - 2} intermediate airport(s)")

    results.append({
        'source':       source,
        'target':       target,
        'source_city':  src_city,
        'target_city':  tgt_city,
        'dijkstra_path': ' → '.join(d_path),
        'astar_path':    ' → '.join(a_path),
        'distance_km':   d_dist,
        'stops':         len(d_path) - 2
    })

# ── Save results to CSV ────────────────────────────────────
results_df = pd.DataFrame(results)
results_df.to_csv('output/shortest_paths.csv', index=False)
print("\nResults saved to output/shortest_paths.csv")

# ══════════════════════════════════════════════════════════
# EXPORT SHORTEST PATH AS GEOJSON (for QGIS)
# ══════════════════════════════════════════════════════════
def path_to_geojson(path, distance, algorithm_name):
    coordinates = []
    for iata in path:
        node = G.nodes[iata]
        coordinates.append([node['lon'], node['lat']])

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates
        },
        "properties": {
            "path":       ' → '.join(path),
            "distance_km": distance,
            "algorithm":  algorithm_name,
            "stops":      len(path) - 2
        }
    }

# Export all query results as a single GeoJSON
all_paths_geojson = {
    "type": "FeatureCollection",
    "features": []
}

for i, (source, target) in enumerate(queries):
    d_path, d_dist = dijkstra_path(source, target)
    if d_path:
        all_paths_geojson["features"].append(
            path_to_geojson(d_path, d_dist, "Dijkstra")
        )

with open('output/shortest_paths.geojson', 'w') as f:
    json.dump(all_paths_geojson, f, indent=2)

print("GeoJSON saved to output/shortest_paths.geojson")
print("\nAll done!")