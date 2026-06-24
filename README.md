
# ✈️ GeoPython for Aerospace — Aircraft Route Analyzer

A Python-based geospatial analysis system for Indian domestic aviation,
built during an internship at Rotten Grapes Private Limited.

## 📌 Project Overview
This project models Indian domestic aviation as a weighted graph network
spanning 15 major airports and 36 routes across 4 airlines — IndiGo,
Air India, Akasa Air, and SpiceJet.

It implements:
- Haversine formula for great-circle distance calculation
- Dijkstra's Algorithm and A* Search for shortest path finding
- Aircraft-specific fuel burn and CO₂ emissions model (5 aircraft types)
- Interactive HTML map with dark UI, airline filtering, and real-time route results
- GIS exports in GeoJSON and Shapefile formats
- 9-test validation and benchmarking module

## 🛠️ Tech Stack
| Tool | Purpose |
|------|---------|
| Python 3.11 | Core language |
| NetworkX | Graph construction + pathfinding |
| Folium | Interactive map generation |
| Pandas | Data handling |
| GeoPandas | Shapefile / GeoJSON export |
| Shapely | Geometry objects |

## 📁 Project Structure
