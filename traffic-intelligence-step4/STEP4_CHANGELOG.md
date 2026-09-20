# Step 4 — Full Traffic Intelligence Dashboard

Built on the Step 3 OpenStreetMap/Leaflet project.

## Added
- Real organizer-dataset road network visualization on Leaflet.
- Traffic-state coloring from backend traffic observations.
- Click any road segment to inspect current evidence and load its 15/30/45/60 minute forecast.
- Forecast chart using the prediction service.
- Isolation Forest anomaly analysis from the traffic service.
- Recent incident records plus incident markers on the map.
- Route explanation through the explanation service.
- Network intelligence: nodes, segments, and structural bottlenecks.
- What-if diversion slider (5–50%) using the simulation service.
- Dataset timestamp shown explicitly; dashboard does not call historical training data "live".
- Gateway endpoints for segment detail, anomalies, active/recent incidents, forecast, simulation and explanation.
- Removed the Google Maps frontend dependency; OpenStreetMap + Leaflet + Nominatim remain the map stack.

## Backend changes
- `services/traffic/main.py`: added `GET /incidents/recent`.
- `services/gateway/main.py`: added/verified routes for traffic segment detail, anomalies, active/recent incidents, forecast, simulation and explanation.

## Windows direct-run ports
- Gateway 8000
- Data 8001
- Traffic 8002
- Route 8003
- Prediction 8004
- Simulation 8005
- Explanation 8006

Keep the service environment variables pointing at localhost when running without Docker.


## Step 4.1 — Connectivity and interaction polish
- Fixed direct-Uvicorn localhost defaults for traffic and gateway services.
- Gateway now defaults to localhost for all services when Docker hostnames are unavailable.
- Frontend dashboard loading now uses partial-success handling so one unavailable endpoint does not discard healthy traffic/network data.
- Added visible hover, focus-visible, active/pressed, selected, and disabled states to interactive controls.
- Dataset start/destination and anomaly actions retain visible selected state.
