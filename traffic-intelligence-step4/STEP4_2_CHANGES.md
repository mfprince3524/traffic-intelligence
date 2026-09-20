# Step 4.2 Changes

## Fixed / redesigned

1. Route generation no longer uses `networkx.shortest_simple_paths()` for the cyclic network. It now uses a fast primary shortest path plus two edge-penalized alternatives, avoiding multi-minute enumeration.
2. Route generation now returns route time, average speed, distance, average congestion, delay, and score.
3. Frontend now separates **Find Routes** from **Analyze Routes**.
4. After route generation, candidate paths are shown first; analysis then produces a Route A/B/C metric matrix.
5. The system provides an advisory route choice, while the user explicitly chooses the route.
6. Traffic Intelligence becomes route-focused after a route is selected.
7. Detect/Diagnose results are filtered to road segments belonging to the selected route.
8. Forecast automatically follows the selected route instead of staying on one startup hotspot.
9. Network Intelligence now reports selected-route footprint and structural bottlenecks.
10. Simulation now accepts the selected route's segment list and evaluates route-level flow/capacity diversion instead of only the first segment.
11. Data Service keeps missing CSV values as JSON `null` so legitimate `signal_id` gaps do not cause FastAPI JSON serialization errors.

## Realtime traffic

The current system remains dataset-first. A live traffic provider can be added as a separate optional evidence layer. The recommended integration point is a traffic-flow API that supplies current observed speed/travel time, then compares those values against the organizer dataset baseline. Live values must be labeled as external/current evidence and must not overwrite organizer dataset values.
