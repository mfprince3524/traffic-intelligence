# AI-Powered Urban Traffic Flow & Incident Intelligence

Microservice MVP grounded in the supplied Smart Cities dataset.

## Architecture

- API Gateway: 8000
- Data Service: 8001
- Traffic Intelligence: 8002
- Route Intelligence: 8003
- Forecasting: 8004
- Simulation: 8005
- Evidence Explanation: 8006
- Frontend: 5173

## Data-first design

The supplied organizer dataset is mounted read-only. The system uses the actual traffic, network, nodes, incidents, context, roadworks, signals, turn restrictions, OD demand and planning-candidate data.

Forecast target files are deliberately excluded from model inputs to avoid target leakage.

## Completed milestones

### Step 1 — Dataset ingestion and normalization

- Real organizer dataset inspected.
- Traffic/network schema validated.
- Data Service provides current traffic, history, network and historical baselines.
- No fabricated traffic observations are used.

### Step 2 — Traffic Intelligence

The Traffic Intelligence service now provides:

- Current traffic state for all available road segments.
- Configurable congestion thresholds.
- Congestion ranking and summary metrics.
- Historical same-hour baselines.
- Isolation Forest anomaly detection using current observations plus historical deviation features.
- Evidence-based incident intelligence using active organizer incident records.
- Per-segment traffic detail and historical metrics.

## Run

1. Copy `.env.example` to `.env` and set secrets locally.
2. Set `frontend/.env` with your restricted Google Maps browser key when the map integration is enabled.
3. Run `docker compose up --build`.
4. Open `http://localhost:5173`.

## Current pipeline

DATA
→ PROCESS
→ TRAFFIC STATE
→ HISTORICAL BASELINE
→ ANOMALY
→ NETWORK GRAPH
→ ROUTES
→ ROUTE SCORE
→ FORECAST
→ SIMULATION
→ EVIDENCE EXPLANATION
→ VISUALIZATION

## Important

Do not commit real API keys. Use `.env` locally and keep `.env` out of Git.
