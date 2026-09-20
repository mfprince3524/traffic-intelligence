from fastapi import FastAPI
import asyncio
import os
import httpx
import pandas as pd
import numpy as np

app = FastAPI(title="Traffic Forecast Service", version="0.3.0")
DATA = os.getenv("DATA_SERVICE_URL", "http://localhost:8001")


async def get(path):
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(DATA + path)
        response.raise_for_status()
        return response.json()


@app.get("/health")
def health():
    return {"status": "ok", "method": "rolling-trend-baseline"}


def forecast_from_history(segment_id, history):
    df = pd.DataFrame(history)
    if df.empty or "congestion_index" not in df.columns:
        return None
    y = pd.to_numeric(df["congestion_index"], errors="coerce").dropna().tail(12)
    if y.empty:
        return None
    current = float(y.iloc[-1])
    tail = y.tail(6)
    trend = float(np.polyfit(np.arange(len(tail)), tail, 1)[0]) if len(tail) > 1 else 0.0
    return {
        "segment_id": str(segment_id),
        "current_congestion_pct": round(current * 100, 1),
        "forecast": [
            {
                "minutes": minutes,
                "predicted_congestion_pct": round(float(np.clip(current + trend * (minutes / 5), 0, 1)) * 100, 1),
            }
            for minutes in [15, 30, 45, 60]
        ],
    }


@app.get("/forecast/{segment_id}")
async def forecast(segment_id: str):
    history = await get(f"/traffic/history/{segment_id}?limit=12")
    result = forecast_from_history(segment_id, history)
    if result is None:
        return {"available": False}
    return {"available": True, "method": "rolling-trend-baseline", **result}


@app.post("/forecast/route")
async def route_forecast(body: dict):
    segment_ids = [str(x) for x in body.get("segment_ids", [])]
    if not segment_ids:
        return {"available": False, "reason": "No route segments supplied"}

    async def one(segment_id):
        try:
            history = await get(f"/traffic/history/{segment_id}?limit=12")
            return forecast_from_history(segment_id, history)
        except Exception:
            return None

    results = [x for x in await asyncio.gather(*(one(sid) for sid in segment_ids)) if x]
    if not results:
        return {"available": False, "reason": "No forecast history available for this route"}

    points = []
    for minutes in [15, 30, 45, 60]:
        values = [
            item["forecast"][i]["predicted_congestion_pct"]
            for item in results
            for i, point in enumerate(item["forecast"])
            if point["minutes"] == minutes
        ]
        points.append({"minutes": minutes, "predicted_congestion_pct": round(float(np.mean(values)), 1)})

    current_values = [item["current_congestion_pct"] for item in results]
    return {
        "available": True,
        "method": "route-aggregated-rolling-trend-baseline",
        "segment_count": len(results),
        "current_congestion_pct": round(float(np.mean(current_values)), 1),
        "forecast": points,
        "segments": [item["segment_id"] for item in results],
    }
