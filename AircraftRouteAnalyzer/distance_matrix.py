import os
import pandas as pd
from math import radians, sin, cos, sqrt, asin
from geopy.distance import geodesic
from itertools import combinations

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs('output', exist_ok=True)

airports = pd.read_csv('data/airports.csv')

# ── Haversine (great-circle, sphere model) ─────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return round(R * 2 * asin(sqrt(a)), 2)

# ── Geodesic (Karney's algorithm, ellipsoid model) ─────────
def geodesic_distance(lat1, lon1, lat2, lon2):
    return round(geodesic((lat1, lon1), (lat2, lon2)).km, 2)

# ── Generate ALL 15×14/2 = 105 unique city-pair combinations ──
results = []

for (i, row1), (j, row2) in combinations(airports.iterrows(), 2):
    hav = haversine(row1['latitude'], row1['longitude'],
                    row2['latitude'], row2['longitude'])
    geo = geodesic_distance(row1['latitude'], row1['longitude'],
                            row2['latitude'], row2['longitude'])

    results.append({
        'origin_iata':      row1['iata_code'],
        'origin_city':      row1['city'],
        'destination_iata': row2['iata_code'],
        'destination_city': row2['city'],
        'haversine_km':     hav,
        'geodesic_km':      geo,
        'difference_km':    round(geo - hav, 2)
    })

# ── Save to CSV ─────────────────────────────────────────────
matrix_df = pd.DataFrame(results)
matrix_df.to_csv('output/distance_matrix.csv', index=False)

print(f"Total city-pair combinations: {len(matrix_df)}")
print(f"Saved to output/distance_matrix.csv")
print("\nSample (first 5 rows):")
print(matrix_df.head())

print("\nAverage difference (Geodesic - Haversine):")
print(f"{matrix_df['difference_km'].mean():.4f} km")