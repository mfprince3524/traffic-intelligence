import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Traffic Intelligence API Gateway", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

URLS = {
    "traffic": os.getenv("TRAFFIC_SERVICE_URL", "http://localhost:8002"),
    "route": os.getenv("ROUTE_SERVICE_URL", "http://localhost:8003"),
    "prediction": os.getenv("PREDICTION_SERVICE_URL", "http://localhost:8004"),
    "simulation": os.getenv("SIMULATION_SERVICE_URL", "http://localhost:8005"),
    "explanation": os.getenv("EXPLANATION_SERVICE_URL", "http://localhost:8006"),
    "data": os.getenv("DATA_SERVICE_URL", "http://localhost:8001"),
    "live": os.getenv("LIVE_TRAFFIC_SERVICE_URL", "http://localhost:8007"),
}


async def proxy(service: str, path: str, method: str = "GET", body=None):
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.request(method, URLS[service] + path, json=body)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json()
        except ValueError:
            detail = exc.response.text or f"{service} service returned HTTP {exc.response.status_code}"
        raise HTTPException(status_code=exc.response.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(503, f"{service} service unavailable: {exc}")


@app.get("/health")
async def health():
    return {"status": "ok", "services": URLS}


@app.get("/api/traffic")
async def traffic():
    return await proxy("traffic", "/state")


@app.get("/api/traffic/summary")
async def traffic_summary():
    return await proxy("traffic", "/summary")


@app.get("/api/traffic/congestion")
async def traffic_congestion(state: str | None = None, limit: int = 50):
    suffix = f"?limit={limit}"
    if state:
        suffix += f"&state={state}"
    return await proxy("traffic", "/congestion" + suffix)


@app.get("/api/traffic/segments/{segment_id}")
async def traffic_segment(segment_id: str):
    return await proxy("traffic", f"/segment/{segment_id}")


@app.get("/api/anomalies")
async def anomalies(contamination: float = 0.05):
    return await proxy("traffic", f"/anomalies?contamination={contamination}")


@app.get("/api/incidents")
async def incidents():
    return await proxy("traffic", "/incidents")


@app.get("/api/incidents/recent")
async def recent_incidents(limit: int = 10):
    return await proxy("traffic", f"/incidents/recent?limit={limit}")


@app.get("/api/network")
async def network():
    return await proxy("data", "/network")


@app.post("/api/routes")
async def routes(body: dict):
    return await proxy("route", "/routes", "POST", body)


@app.get("/api/forecast/{segment_id}")
async def forecast(segment_id: str):
    return await proxy("prediction", f"/forecast/{segment_id}")


@app.post("/api/simulation")
async def simulation(body: dict):
    return await proxy("simulation", "/simulate", "POST", body)


@app.post("/api/explain")
async def explain(body: dict):
    return await proxy("explanation", "/explain", "POST", body)


@app.post("/api/live/route")
async def live_route(body: dict):
    # The frontend sends the selected route and network geometry. The API key
    # remains server-side in the Live Traffic Service.
    return await proxy("live", "/route", "POST", body)


@app.post("/api/live/external-route")
async def live_external_route(body: dict):
    return await proxy("live", "/external-route", "POST", body)


@app.get("/api/live/health")
async def live_health():
    return await proxy("live", "/health")
