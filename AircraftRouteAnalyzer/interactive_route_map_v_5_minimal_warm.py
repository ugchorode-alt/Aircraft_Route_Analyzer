"""Minimal warm-themed aircraft route map generator

Edit the constants at the top to change the look later.

Expected input files (adjust column mapping below if your headers differ):
- airports.csv
- airline_routes.csv or routes.csv

This script focuses on:
- Beige / brown / terracotta UI styling
- Black monochrome symbols instead of colorful emoji
- Distinct route colors by airline / frequency / distance tier
- Distinct origin and destination highlighting
- Folium map styling with cleaner popups and controls
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd
import folium
from branca.element import Element


# =========================
# USER-EDITABLE CONSTANTS
# =========================
BASE_DIR = Path(__file__).resolve().parent
AIRPORTS_CSV = BASE_DIR / "airports.csv"
ROUTES_CSV = BASE_DIR / "airline_routes.csv"
OUTPUT_HTML = BASE_DIR / "interactive_route_map_minimal_warm.html"

# Warm palette
BG_BEIGE = "#F5EFE6"
CARD_BEIGE = "#EFE5D5"
BORDER_BEIGE = "#D8C3A5"
TEXT_DARK = "#2B2118"
BROWN = "#7D5A50"
DARK_BROWN = "#4E342E"
TERRACOTTA = "#C97C5D"
SAND = "#F8F2E8"
MUTED = "#A58A74"

# Route palette: use different tones so lines are not all the same
ROUTE_PALETTE = [
    "#7D5A50",  # brown
    "#A47551",  # warm brown
    "#C97C5D",  # terracotta
    "#8D6E63",  # muted clay
    "#6F4E37",  # dark cocoa
    "#B08968",  # sand brown
]

# Black monochrome symbols (avoid colored emoji rendering)
ICON_PLANE = "✈"
ICON_TIME = "⏱"
ICON_FUEL = "◼"
ICON_CO2 = "◼"
ICON_COST = "◼"
ICON_STOP = "◉"
ICON_LOCATION = "◆"


# =========================
# COLUMN NORMALIZATION
# =========================
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns and strip spaces/special characters for flexible lookup."""
    out = df.copy()
    out.columns = [
        c.strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")
        for c in out.columns
    ]
    return out


def first_existing(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    colset = set(columns)
    for c in candidates:
        if c in colset:
            return c
    return None


def safe_float(value) -> Optional[float]:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


# =========================
# DISTANCE / COLOR LOGIC
# =========================
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def route_tier(distance_km: float) -> str:
    if distance_km < 500:
        return "short"
    if distance_km < 1200:
        return "medium"
    return "long"


def palette_color_for_route(row: pd.Series, idx: int, distance_km: float) -> str:
    """Differentiate routes using airline if available, otherwise by distance tier."""
    airline = str(row.get("airline", "")).strip().lower()
    if airline:
        # Stable hash-like selection by airline name.
        return ROUTE_PALETTE[sum(ord(ch) for ch in airline) % len(ROUTE_PALETTE)]

    tier = route_tier(distance_km)
    if tier == "short":
        return ROUTE_PALETTE[0]
    if tier == "medium":
        return ROUTE_PALETTE[2]
    return ROUTE_PALETTE[(idx + 4) % len(ROUTE_PALETTE)]


# =========================
# DATA LOADING
# =========================
def load_airports(path: Path) -> pd.DataFrame:
    df = normalize_columns(pd.read_csv(path))

    code_col = first_existing(df.columns, ["iata", "iata_code", "code", "airport_code"])
    name_col = first_existing(df.columns, ["airport_name", "name", "airport"])
    city_col = first_existing(df.columns, ["city", "town"])
    state_col = first_existing(df.columns, ["state", "province"])
    lat_col = first_existing(df.columns, ["latitude", "lat"])
    lon_col = first_existing(df.columns, ["longitude", "lon", "lng"])
    elev_col = first_existing(df.columns, ["elevation", "altitude", "elev"])

    required = [code_col, name_col, city_col, lat_col, lon_col]
    if any(c is None for c in required):
        raise ValueError(
            "airports.csv is missing required columns. Expected something like: "
            "iata/name/city/latitude/longitude"
        )

    out = pd.DataFrame({
        "iata": df[code_col].astype(str).str.upper().str.strip(),
        "airport_name": df[name_col].astype(str),
        "city": df[city_col].astype(str),
        "state": df[state_col].astype(str) if state_col else "",
        "lat": df[lat_col].apply(safe_float),
        "lon": df[lon_col].apply(safe_float),
        "elevation": df[elev_col].apply(safe_float) if elev_col else None,
    })
    return out.dropna(subset=["lat", "lon", "iata"]).reset_index(drop=True)


def load_routes(path: Path) -> pd.DataFrame:
    df = normalize_columns(pd.read_csv(path))

    origin_col = first_existing(df.columns, ["origin", "from", "src", "source", "departure", "origin_iata"])
    dest_col = first_existing(df.columns, ["destination", "to", "dst", "target", "arrival", "dest", "destination_iata"])
    airline_col = first_existing(df.columns, ["airline", "carrier"])
    freq_col = first_existing(df.columns, ["frequency", "weekly_flights", "flights_per_week", "freq"])
    stops_col = first_existing(df.columns, ["stops", "stop_count"])
    aircraft_col = first_existing(df.columns, ["aircraft", "aircraft_type", "type", "model"])

    if origin_col is None or dest_col is None:
        raise ValueError(
            "Routes CSV needs origin and destination columns. Expected something like: origin / destination"
        )

    out = pd.DataFrame({
        "origin": df[origin_col].astype(str).str.upper().str.strip(),
        "destination": df[dest_col].astype(str).str.upper().str.strip(),
        "airline": df[airline_col].astype(str).str.strip() if airline_col else "",
        "frequency": df[freq_col].apply(safe_float) if freq_col else None,
        "stops": df[stops_col].apply(safe_float) if stops_col else None,
        "aircraft": df[aircraft_col].astype(str).str.strip() if aircraft_col else "",
    })

    # Remove empty rows and duplicates that often cause repeated same-color polylines.
    out = out.dropna(subset=["origin", "destination"]).copy()
    out = out[out["origin"] != out["destination"]].copy()
    out = out.drop_duplicates(subset=["origin", "destination", "airline"], keep="first")
    return out.reset_index(drop=True)


# =========================
# MAP STYLING
# =========================
def inject_css(m: folium.Map) -> None:
    css = f"""
    <style>
      html, body {{
        background: {BG_BEIGE};
      }}
      .leaflet-container {{
        font-family: Inter, Arial, sans-serif;
        background: {BG_BEIGE};
      }}
      .warm-panel {{
        background: rgba(245, 239, 230, 0.90);
        color: {TEXT_DARK};
        border: 1px solid {BORDER_BEIGE};
        border-radius: 18px;
        box-shadow: 0 10px 24px rgba(43, 33, 24, 0.12);
        backdrop-filter: blur(8px);
      }}
      .warm-title {{
        font-weight: 700;
        font-size: 18px;
        color: {TEXT_DARK};
        margin-bottom: 8px;
      }}
      .warm-subtitle {{
        color: {MUTED};
        font-size: 12px;
        margin-bottom: 8px;
      }}
      .black-icon {{
        color: #111111;
        font-weight: 700;
        display: inline-block;
        width: 16px;
        text-align: center;
      }}
      .popup-card {{
        min-width: 240px;
        background: {SAND};
        color: {TEXT_DARK};
        border-radius: 14px;
        border: 1px solid {BORDER_BEIGE};
        padding: 14px 14px 12px 14px;
        font-size: 13px;
        line-height: 1.55;
      }}
      .popup-head {{
        font-size: 16px;
        font-weight: 800;
        margin-bottom: 8px;
      }}
      .popup-row {{
        margin: 2px 0;
      }}
      .popup-label {{
        color: {MUTED};
      }}
      .badge {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        background: {BROWN};
        color: white;
        font-size: 11px;
        font-weight: 700;
        margin-right: 6px;
      }}
      .badge-terracotta {{ background: {TERRACOTTA}; }}
      .badge-brown {{ background: {BROWN}; }}
      .badge-dark {{ background: {DARK_BROWN}; }}
      .legend-box {{
        background: rgba(245, 239, 230, 0.92);
        color: {TEXT_DARK};
        border: 1px solid {BORDER_BEIGE};
        border-radius: 16px;
        padding: 12px 14px;
        box-shadow: 0 10px 24px rgba(43, 33, 24, 0.12);
        line-height: 1.45;
        min-width: 190px;
      }}
      .legend-item {{
        margin: 4px 0;
        white-space: nowrap;
      }}
      .legend-swatch {{
        display: inline-block;
        width: 14px;
        height: 14px;
        border-radius: 4px;
        margin-right: 8px;
        vertical-align: middle;
      }}
    </style>
    """
    m.get_root().header.add_child(Element(css))


def make_popup_html(airport_row: pd.Series) -> folium.Popup:
    html = f"""
    <div class="popup-card">
      <div class="popup-head"><span class="black-icon">{ICON_LOCATION}</span> {airport_row['city']} ({airport_row['iata']})</div>
      <div class="popup-row"><span class="popup-label">Airport:</span> {airport_row['airport_name']}</div>
      <div class="popup-row"><span class="popup-label">State:</span> {airport_row.get('state', '')}</div>
      <div class="popup-row"><span class="popup-label">Latitude:</span> {airport_row['lat']:.4f}</div>
      <div class="popup-row"><span class="popup-label">Longitude:</span> {airport_row['lon']:.4f}</div>
      <div class="popup-row"><span class="popup-label">Elevation:</span> {'' if pd.isna(airport_row.get('elevation', None)) else airport_row.get('elevation')} m</div>
    </div>
    """
    return folium.Popup(folium.IFrame(html=html, width=290, height=195), max_width=320)


def make_route_popup(row: pd.Series, distance_km: float) -> folium.Popup:
    airline = str(row.get("airline", "")).strip() or "N/A"
    aircraft = str(row.get("aircraft", "")).strip() or "N/A"
    frequency = row.get("frequency", None)
    stops = row.get("stops", None)

    html = f"""
    <div class="popup-card">
      <div class="popup-head"><span class="black-icon">{ICON_PLANE}</span> {row['origin']} → {row['destination']}</div>
      <div class="popup-row"><span class="popup-label">Airline:</span> {airline}</div>
      <div class="popup-row"><span class="popup-label">Aircraft:</span> {aircraft}</div>
      <div class="popup-row"><span class="popup-label">Distance:</span> {distance_km:.1f} km</div>
      <div class="popup-row"><span class="popup-label">Frequency:</span> {'' if pd.isna(frequency) else frequency}</div>
      <div class="popup-row"><span class="popup-label">Stops:</span> {'' if pd.isna(stops) else stops}</div>
    </div>
    """
    return folium.Popup(folium.IFrame(html=html, width=290, height=195), max_width=320)


# =========================
# MAP BUILDING
# =========================
def build_map(airports: pd.DataFrame, routes: pd.DataFrame) -> folium.Map:
    center_lat = airports["lat"].mean()
    center_lon = airports["lon"].mean()

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=5,
        tiles="CartoDB Positron",
        control_scale=True,
        prefer_canvas=True,
    )
    inject_css(m)

    # Layers
    airports_fg = folium.FeatureGroup(name="Airports", show=True)
    routes_fg = folium.FeatureGroup(name="Routes", show=True)
    selected_fg = folium.FeatureGroup(name="Selected Route", show=True)

    # Airport markers: warm minimal style
    airport_lookup = airports.set_index("iata").to_dict(orient="index")
    for _, a in airports.iterrows():
        folium.CircleMarker(
            location=[a["lat"], a["lon"]],
            radius=9,
            color=DARK_BROWN,
            weight=2,
            fill=True,
            fill_color=BG_BEIGE,
            fill_opacity=1,
            popup=make_popup_html(a),
            tooltip=f"{a['iata']} — {a['city']}",
        ).add_to(airports_fg)

    # Build route polylines with different colors
    for idx, row in routes.iterrows():
        o = airport_lookup.get(row["origin"])
        d = airport_lookup.get(row["destination"])
        if not o or not d:
            continue

        distance_km = haversine_km(o["lat"], o["lon"], d["lat"], d["lon"])
        color = palette_color_for_route(row, idx, distance_km)
        weight = 2.0 if route_tier(distance_km) == "short" else 2.6 if route_tier(distance_km) == "medium" else 3.2
        opacity = 0.58 if route_tier(distance_km) == "short" else 0.64 if route_tier(distance_km) == "medium" else 0.72

        folium.PolyLine(
            locations=[[o["lat"], o["lon"]], [d["lat"], d["lon"]]],
            color=color,
            weight=weight,
            opacity=opacity,
            tooltip=f"{row['origin']} → {row['destination']} | {distance_km:.0f} km",
            popup=make_route_popup(row, distance_km),
        ).add_to(routes_fg)

    # Add a highlighted example route if data exists (first route)
    if not routes.empty:
        sample = routes.iloc[0]
        o = airport_lookup.get(sample["origin"])
        d = airport_lookup.get(sample["destination"])
        if o and d:
            folium.PolyLine(
                locations=[[o["lat"], o["lon"]], [d["lat"], d["lon"]]],
                color=TERRACOTTA,
                weight=5,
                opacity=0.95,
                tooltip=f"Highlighted: {sample['origin']} → {sample['destination']}",
            ).add_to(selected_fg)

            # Distinguish origin and destination clearly
            folium.Marker(
                [o["lat"], o["lon"]],
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        width:18px;height:18px;border-radius:50%;
                        background:{DARK_BROWN};
                        border:2px solid {SAND};
                        box-shadow:0 0 0 2px {DARK_BROWN};
                    "></div>
                    """
                ),
                tooltip=f"Origin: {sample['origin']}",
            ).add_to(selected_fg)
            folium.Marker(
                [d["lat"], d["lon"]],
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        width:18px;height:18px;border-radius:50%;
                        background:{TERRACOTTA};
                        border:2px solid {SAND};
                        box-shadow:0 0 0 2px {TERRACOTTA};
                    "></div>
                    """
                ),
                tooltip=f"Destination: {sample['destination']}",
            ).add_to(selected_fg)

    airports_fg.add_to(m)
    routes_fg.add_to(m)
    selected_fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Minimal warm title card
    title_html = f"""
    <div style="
        position: fixed;
        top: 18px;
        left: 58px;
        z-index: 9999;
        background: rgba(245,239,230,0.92);
        border: 1px solid {BORDER_BEIGE};
        border-radius: 18px;
        padding: 14px 16px;
        box-shadow: 0 10px 24px rgba(43,33,24,0.12);
        color: {TEXT_DARK};
        min-width: 280px;
        backdrop-filter: blur(8px);
    ">
      <div style="font-size:18px;font-weight:800;line-height:1.2;">
        <span style="color:{TEXT_DARK};">{ICON_PLANE}</span> Aircraft Route Analyzer
      </div>
      <div style="font-size:12px;color:{MUTED};margin-top:4px;">
        Minimal warm theme · beige, brown, terracotta
      </div>
    </div>
    """
    m.get_root().html.add_child(Element(title_html))

    # Legend
    legend_html = f"""
    <div class="legend-box" style="position: fixed; bottom: 22px; left: 22px; z-index: 9999;">
      <div style="font-weight:800; margin-bottom:8px;">◆ Legend</div>
      <div class="legend-item"><span class="legend-swatch" style="background:{DARK_BROWN};"></span>Airport marker</div>
      <div class="legend-item"><span class="legend-swatch" style="background:{TERRACOTTA};"></span>Highlighted route</div>
      <div class="legend-item"><span class="legend-swatch" style="background:{ROUTE_PALETTE[0]};"></span>Short route</div>
      <div class="legend-item"><span class="legend-swatch" style="background:{ROUTE_PALETTE[2]};"></span>Medium route</div>
      <div class="legend-item"><span class="legend-swatch" style="background:{ROUTE_PALETTE[4]};"></span>Long route</div>
    </div>
    """
    m.get_root().html.add_child(Element(legend_html))

    return m


def main() -> None:
    if not AIRPORTS_CSV.exists():
        raise FileNotFoundError(f"Missing airports file: {AIRPORTS_CSV}")
    if not ROUTES_CSV.exists():
        raise FileNotFoundError(f"Missing routes file: {ROUTES_CSV}")

    airports = load_airports(AIRPORTS_CSV)
    routes = load_routes(ROUTES_CSV)

    m = build_map(airports, routes)
    m.save(str(OUTPUT_HTML))
    print(f"Saved: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
