from typing import Any

import httpx
import numpy as np
import pandas as pd
import os
from fastapi import FastAPI, HTTPException, Query
from sklearn.ensemble import IsolationForest

app = FastAPI(title="Traffic Intelligence Service", version="0.2.0")
DATA = os.getenv("DATA_SERVICE_URL", "http://localhost:8001")

STATE_THRESHOLDS = {
    "normal_max": 0.60,
    "moderate_max": 0.80,
    "heavy_max": 1.00,
}


def classify(value: float) -> str:
    if value < STATE_THRESHOLDS["normal_max"]:
        return "normal"
    if value < STATE_THRESHOLDS["moderate_max"]:
        return "moderate"
    if value <= STATE_THRESHOLDS["heavy_max"]:
        return "heavy"
    return "severe"


async def get(path: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.get(DATA + path)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Data service unavailable: {exc}")


def numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


@app.get("/health")
def health():
    return {"status": "ok", "service": "traffic-intelligence"}


@app.get("/config")
def config():
    return {"congestion_thresholds": STATE_THRESHOLDS, "anomaly_method": "IsolationForest"}


@app.get("/state")
async def state():
    payload = await get("/traffic/latest")
    df = numeric(pd.DataFrame(payload["rows"]), [
        "speed_kmh", "flow_vph", "occupancy_pct", "travel_time_min",
        "free_flow_time_min", "delay_min", "queue_length_veh", "congestion_index"
    ])
    if df.empty:
        return {"timestamp": payload["timestamp"], "rows": [], "summary": {}}

    df["traffic_state"] = df["congestion_index"].fillna(0).clip(lower=0).map(classify)
    df["congestion_pct"] = (df["congestion_index"].fillna(0).clip(lower=0) * 100).round(1)
    counts = df["traffic_state"].value_counts().to_dict()
    summary = {
        "segments": int(len(df)),
        "normal": int(counts.get("normal", 0)),
        "moderate": int(counts.get("moderate", 0)),
        "heavy": int(counts.get("heavy", 0)),
        "severe": int(counts.get("severe", 0)),
        "average_speed_kmh": round(float(df["speed_kmh"].mean()), 2),
        "average_congestion_pct": round(float(df["congestion_index"].mean() * 100), 2),
        "average_delay_min": round(float(df["delay_min"].mean()), 2),
        "total_queue_vehicles": round(float(df["queue_length_veh"].sum()), 1),
    }
    return {"timestamp": payload["timestamp"], "rows": df.replace({np.nan: None}).to_dict("records"), "summary": summary}


@app.get("/summary")
async def summary():
    result = await state()
    return {"timestamp": result["timestamp"], "summary": result["summary"]}


@app.get("/congestion")
async def congestion(
    state_filter: str | None = Query(None, alias="state"),
    limit: int = Query(50, ge=1, le=436),
):
    result = await state()
    rows = result["rows"]
    if state_filter:
        rows = [r for r in rows if r.get("traffic_state") == state_filter.lower()]
    rows.sort(key=lambda r: r.get("congestion_pct") or 0, reverse=True)
    return {"timestamp": result["timestamp"], "rows": rows[:limit]}


@app.get("/anomalies")
async def anomalies(
    contamination: float = Query(0.05, ge=0.001, le=0.25),
    baseline_days: int = Query(7, ge=1, le=30),
):
    """Detect unusual current road behavior relative to recent same-hour history.

    Isolation Forest is applied to current observations plus baseline-deviation features.
    The baseline is computed only from historical traffic observations; forecast targets
    are never used as model inputs.
    """
    current = await get("/traffic/latest")
    baseline = await get(
        f"/traffic/baselines?days={baseline_days}&latest_timestamp={current['timestamp']}"
    )
    df = numeric(pd.DataFrame(current["rows"]), [
        "speed_kmh", "flow_vph", "occupancy_pct", "queue_length_veh", "congestion_index", "delay_min"
    ])
    if df.empty:
        return {"timestamp": current["timestamp"], "rows": [], "method": "unavailable"}

    df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
    base = pd.DataFrame(baseline.get("rows", []))
    if not base.empty:
        base = numeric(base, [
            "baseline_speed_kmh", "baseline_flow_vph", "baseline_occupancy_pct",
            "baseline_delay_min", "baseline_queue_length_veh", "baseline_congestion_index",
            "baseline_congestion_std"
        ])
        df = df.merge(base, on=["segment_id", "hour"], how="left")

    # Explicit deviation features make the anomaly detector temporal/context-aware.
    pairs = [
        ("speed_kmh", "baseline_speed_kmh", "speed_deviation"),
        ("flow_vph", "baseline_flow_vph", "flow_deviation"),
        ("occupancy_pct", "baseline_occupancy_pct", "occupancy_deviation"),
        ("delay_min", "baseline_delay_min", "delay_deviation"),
        ("queue_length_veh", "baseline_queue_length_veh", "queue_deviation"),
        ("congestion_index", "baseline_congestion_index", "congestion_deviation"),
    ]
    for current_col, baseline_col, deviation_col in pairs:
        if baseline_col in df.columns:
            denom = df[baseline_col].abs().replace(0, np.nan)
            df[deviation_col] = (df[current_col] - df[baseline_col]) / denom
            df[deviation_col] = df[deviation_col].replace([np.inf, -np.inf], np.nan).fillna(0)

    features = [c for c in [
        "speed_kmh", "flow_vph", "occupancy_pct", "queue_length_veh", "congestion_index", "delay_min",
        "speed_deviation", "flow_deviation", "occupancy_deviation", "delay_deviation",
        "queue_deviation", "congestion_deviation"
    ] if c in df.columns]
    X = df[features].replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median(numeric_only=True)).fillna(0)

    if len(df) < 20:
        return {"timestamp": current["timestamp"], "rows": [], "method": "unavailable"}

    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    prediction = model.fit_predict(X)
    df["anomaly"] = prediction == -1
    df["anomaly_score"] = (-model.score_samples(X)).round(4)
    df["anomaly_method"] = "IsolationForest"

    rows = df.loc[df["anomaly"]].sort_values("anomaly_score", ascending=False)
    return {
        "timestamp": current["timestamp"],
        "method": "IsolationForest",
        "baseline_days": baseline_days,
        "features": features,
        "rows": rows.replace({np.nan: None}).to_dict("records"),
    }


@app.get("/incidents")
async def incident_intelligence():
    current = await get("/traffic/latest")
    active = await get(f"/incidents/active?timestamp={current['timestamp']}")
    traffic = pd.DataFrame(current["rows"])
    active_df = pd.DataFrame(active["rows"])

    if traffic.empty:
        return {"timestamp": current["timestamp"], "rows": []}

    traffic["traffic_state"] = traffic["congestion_index"].astype(float).map(classify)
    incident_rows = []
    if not active_df.empty:
        for _, inc in active_df.iterrows():
            segment = str(inc["segment_id"])
            match = traffic.loc[traffic["segment_id"].astype(str).eq(segment)]
            evidence = ["active incident record in organizer dataset"]
            if not match.empty:
                row = match.iloc[0]
                if float(row.get("congestion_index", 0)) >= 0.8:
                    evidence.append("heavy/severe congestion on affected segment")
                if float(row.get("delay_min", 0)) > 0:
                    evidence.append("observed travel delay")
            incident_rows.append({
                "segment_id": segment,
                "classification": "possible incident",
                "incident_type": inc.get("incident_type"),
                "severity": inc.get("severity"),
                "lanes_blocked": inc.get("lanes_blocked"),
                "confidence": "dataset-supported",
                "evidence": evidence,
            })
    return {"timestamp": current["timestamp"], "rows": incident_rows}


@app.get("/incidents/recent")
async def recent_incidents(limit: int = Query(10, ge=1, le=50)):
    """Return the most recent incident records at or before the current dataset snapshot."""
    current = await get("/traffic/latest")
    rows = await get("/incidents")
    df = pd.DataFrame(rows)
    if df.empty:
        return {"timestamp": current["timestamp"], "rows": []}
    ts = pd.to_datetime(current["timestamp"])
    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df = df.loc[df["start_time"] <= ts].copy()
    df["hours_before_snapshot"] = ((ts - df["start_time"]).dt.total_seconds() / 3600).round(2)
    df = df.sort_values("start_time", ascending=False).head(limit)
    return {"timestamp": current["timestamp"], "rows": df.replace({np.nan: None}).to_dict("records")}

@app.get("/segment/{segment_id}")
async def segment(segment_id: str):
    current = await get("/traffic/latest")
    row = next((r for r in current["rows"] if str(r.get("segment_id")) == segment_id), None)
    if row is None:
        raise HTTPException(404, "Road segment not found in current snapshot")
    history = await get(f"/traffic/history/{segment_id}?limit=288")
    h = numeric(pd.DataFrame(history), ["congestion_index", "speed_kmh", "delay_min"])
    result = dict(row)
    if not h.empty:
        result["historical_mean_congestion_pct"] = round(float(h["congestion_index"].mean() * 100), 2)
        result["historical_mean_speed_kmh"] = round(float(h["speed_kmh"].mean()), 2)
        result["historical_mean_delay_min"] = round(float(h["delay_min"].mean()), 2)
    result["traffic_state"] = classify(float(result.get("congestion_index") or 0))
    return {"timestamp": current["timestamp"], "segment": result, "history_points": len(history)}
