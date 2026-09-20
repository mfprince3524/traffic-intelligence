from pathlib import Path
import os
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Traffic Data Service", version="0.2.0")
DATA = Path(os.getenv("DATA_DIR", "/app/data"))
cache: dict[str, pd.DataFrame] = {}

FILES = {
    "network": "network.csv",
    "nodes": "nodes.csv",
    "traffic": "traffic_train.csv",
    "incidents": "incidents_train.csv",
    "context": "context_train.csv",
    "roadworks": "roadworks_train.csv",
    "signals": "signal_plans.csv",
    "turn_restrictions": "turn_restrictions.csv",
    "od": "od_demand_profiles.csv",
    "planning": "planning_candidates.csv",
}


def load(name: str) -> pd.DataFrame:
    if name not in FILES:
        raise KeyError(name)
    if name not in cache:
        path = DATA / FILES[name]
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path)
        for c in ["timestamp", "start_time", "end_time"]:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors="coerce")
        cache[name] = df
    return cache[name]


@app.get("/health")
def health():
    return {"status": "ok", "datasets": list(FILES)}


@app.get("/schema/{name}")
def schema(name: str):
    try:
        df = load(name)
    except KeyError:
        raise HTTPException(404, "Unknown dataset")
    except FileNotFoundError:
        raise HTTPException(404, "Dataset file not found")
    return {
        "rows": len(df),
        "columns": [
            {
                "name": c,
                "dtype": str(df[c].dtype),
                "missing": int(df[c].isna().sum()),
            }
            for c in df.columns
        ],
    }


@app.get("/network")
def network():
    nodes = load("nodes").astype(object).where(pd.notna(load("nodes")), None)
    segments = load("network").astype(object).where(pd.notna(load("network")), None)
    return {
        "nodes": nodes.to_dict("records"),
        "segments": segments.to_dict("records"),
    }


@app.get("/traffic/latest")
def latest():
    df = load("traffic")
    ts = df["timestamp"].max()
    out = df.loc[df["timestamp"].eq(ts)].copy()
    return {"timestamp": ts.isoformat(), "rows": out.where(pd.notna(out), None).to_dict("records")}


@app.get("/traffic/history/{segment_id}")
def history(segment_id: str, limit: int = Query(288, ge=1, le=2880)):
    df = load("traffic")
    out = (
        df.loc[df["segment_id"].astype(str).eq(segment_id)]
        .sort_values("timestamp")
        .tail(limit)
    )
    return out.where(pd.notna(out), None).to_dict("records")


@app.get("/traffic/baselines")
def baselines(
    days: int = Query(7, ge=1, le=30),
    latest_timestamp: Optional[str] = None,
):
    """Return historical per-segment baselines without sending the full raw dataset."""
    df = load("traffic")[[
        "timestamp", "segment_id", "speed_kmh", "flow_vph",
        "occupancy_pct", "delay_min", "queue_length_veh", "congestion_index"
    ]].copy()
    end = pd.to_datetime(latest_timestamp) if latest_timestamp else df["timestamp"].max()
    start = end - pd.Timedelta(days=days)
    df = df.loc[(df["timestamp"] < end) & (df["timestamp"] >= start)].copy()
    if df.empty:
        return {"rows": []}
    df["hour"] = df["timestamp"].dt.hour
    # Hour-of-day baseline captures the dominant daily pattern without using future target files.
    grouped = df.groupby(["segment_id", "hour"], as_index=False).agg(
        baseline_speed_kmh=("speed_kmh", "mean"),
        baseline_flow_vph=("flow_vph", "mean"),
        baseline_occupancy_pct=("occupancy_pct", "mean"),
        baseline_delay_min=("delay_min", "mean"),
        baseline_queue_length_veh=("queue_length_veh", "mean"),
        baseline_congestion_index=("congestion_index", "mean"),
        baseline_congestion_std=("congestion_index", "std"),
        observations=("congestion_index", "count"),
    )
    return {"rows": grouped.fillna(0).to_dict("records"), "days": days}


@app.get("/incidents")
def incidents():
    return load("incidents").where(pd.notna(load("incidents")), None).to_dict("records")


@app.get("/incidents/active")
def active_incidents(timestamp: Optional[str] = None):
    ts = pd.to_datetime(timestamp) if timestamp else load("traffic")["timestamp"].max()
    df = load("incidents")
    if df.empty:
        return {"timestamp": ts.isoformat(), "rows": []}
    active = df.loc[(df["start_time"] <= ts) & (df["end_time"] >= ts)].copy()
    return {
        "timestamp": ts.isoformat(),
        "rows": active.where(pd.notna(active), None).to_dict("records"),
    }
