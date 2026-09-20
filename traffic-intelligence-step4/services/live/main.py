from fastapi import FastAPI, HTTPException
import asyncio
import math
import os
import time
from typing import Any

import httpx

app = FastAPI(title="Live Traffic Service", version="0.1.0")

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "").strip()
TOMTOM_BASE_URL = os.getenv("TOMTOM_BASE_URL", "https://api.tomtom.com")
FLOW_VERSION = "4"
INCIDENT_VERSION = "5"
CACHE_TTL_SECONDS = int(os.getenv("LIVE_TRAFFIC_CACHE_TTL_SECONDS", "60"))
MAX_FLOW_REQUESTS = int(os.getenv("LIVE_TRAFFIC_MAX_FLOW_REQUESTS", "30"))

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def cached_get(key: str):
    item = _cache.get(key)
    if not item:
        return None
    created, value = item
    if time.time() - created > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return value


def cached_put(key: str, value: dict[str, Any]):
    _cache[key] = (time.time(), value)


def midpoint(edge, nodes_by_id):
    source = nodes_by_id.get(str(edge.get("source_node")))
    target = nodes_by_id.get(str(edge.get("target_node")))
    if not source or not target:
        return None
    return (
        (float(source["lat"]) + float(target["lat"])) / 2,
        (float(source["lon"]) + float(target["lon"])) / 2,
    )


async def flow_for_segment(client, segment_id, edge, nodes_by_id):
    point = midpoint(edge, nodes_by_id)
    if point is None:
        return None

    lat, lon = point
    url = f"{TOMTOM_BASE_URL}/traffic/services/{FLOW_VERSION}/flowSegmentData/absolute/10/json"
    params = {
        "key": TOMTOM_API_KEY,
        "point": f"{lat:.6f},{lon:.6f}",
        "unit": "kmph",
    }
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json().get("flowSegmentData", {})
        current_speed = float(payload.get("currentSpeed") or 0)
        free_speed = float(payload.get("freeFlowSpeed") or 0)
        current_tt = float(payload.get("currentTravelTime") or 0)
        free_tt = float(payload.get("freeFlowTravelTime") or 0)
        speed_ratio = current_speed / free_speed if free_speed > 0 else None
        delay_pct = ((current_tt - free_tt) / free_tt * 100) if free_tt > 0 else None
        return {
            "segment_id": str(segment_id),
            "point": {"lat": lat, "lon": lon},
            "current_speed_kmh": round(current_speed, 1),
            "free_flow_speed_kmh": round(free_speed, 1),
            "current_travel_time_sec": round(current_tt, 1),
            "free_flow_travel_time_sec": round(free_tt, 1),
            "speed_ratio_pct": round(speed_ratio * 100, 1) if speed_ratio is not None else None,
            "delay_pct": round(delay_pct, 1) if delay_pct is not None else None,
            "confidence": payload.get("confidence"),
            "road_closure": bool(payload.get("roadClosure", False)),
            "source": "TomTom Traffic Flow API",
        }
    except httpx.HTTPStatusError as exc:
        return {"segment_id": str(segment_id), "error": f"TomTom HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"segment_id": str(segment_id), "error": str(exc)}


async def live_incidents(client, edges, nodes_by_id):
    points = [midpoint(edge, nodes_by_id) for edge in edges]
    points = [p for p in points if p]
    if not points:
        return []

    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    bbox = f"{min(lons)},{min(lats)},{max(lons)},{max(lats)}"
    url = f"{TOMTOM_BASE_URL}/traffic/services/{INCIDENT_VERSION}/incidentDetails"
    fields = "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description},delay,length,roadNumbers,startTime,endTime}}}"
    params = {
        "key": TOMTOM_API_KEY,
        "bbox": bbox,
        "fields": fields,
        "language": "en-GB",
        "timeValidityFilter": "present",
    }
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json().get("incidents", [])
    except Exception:
        return []


def sample_geometry(coords, limit):
    if len(coords) <= limit:
        return coords
    step = (len(coords) - 1) / max(limit - 1, 1)
    return [coords[min(round(i * step), len(coords) - 1)] for i in range(limit)]


async def flow_for_point(client, point):
    lat, lon = float(point[0]), float(point[1])
    url = f"{TOMTOM_BASE_URL}/traffic/services/{FLOW_VERSION}/flowSegmentData/absolute/10/json"
    params = {"key": TOMTOM_API_KEY, "point": f"{lat:.6f},{lon:.6f}", "unit": "kmph"}
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json().get("flowSegmentData", {})
        current_speed = float(payload.get("currentSpeed") or 0)
        free_speed = float(payload.get("freeFlowSpeed") or 0)
        current_tt = float(payload.get("currentTravelTime") or 0)
        free_tt = float(payload.get("freeFlowTravelTime") or 0)
        delay_pct = ((current_tt - free_tt) / free_tt * 100) if free_tt > 0 else None
        return {
            "point": {"lat": lat, "lon": lon},
            "current_speed_kmh": round(current_speed, 1),
            "free_flow_speed_kmh": round(free_speed, 1),
            "current_travel_time_sec": round(current_tt, 1),
            "free_flow_travel_time_sec": round(free_tt, 1),
            "delay_pct": round(delay_pct, 1) if delay_pct is not None else None,
            "confidence": payload.get("confidence"),
            "road_closure": bool(payload.get("roadClosure", False)),
            "source": "TomTom Traffic Flow API",
        }
    except Exception as exc:
        return {"point": {"lat": lat, "lon": lon}, "error": str(exc)}


async def incidents_for_points(client, points):
    if not points:
        return []
    lats = [float(p[0]) for p in points]
    lons = [float(p[1]) for p in points]
    bbox = f"{min(lons)},{min(lats)},{max(lons)},{max(lats)}"
    url = f"{TOMTOM_BASE_URL}/traffic/services/{INCIDENT_VERSION}/incidentDetails"
    fields = "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description},delay,length,roadNumbers,startTime,endTime}}}"
    params = {"key": TOMTOM_API_KEY, "bbox": bbox, "fields": fields, "language": "en-GB", "timeValidityFilter": "present"}
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json().get("incidents", [])
    except Exception:
        return []


@app.get("/health")
def health():
    return {
        "status": "ok",
        "provider": "TomTom",
        "configured": bool(TOMTOM_API_KEY),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


@app.post("/route")
async def route_live(body: dict):
    if not TOMTOM_API_KEY:
        raise HTTPException(
            503,
            detail={
                "error_code": "LIVE_TRAFFIC_NOT_CONFIGURED",
                "message": "TomTom API key is not configured on the Live Traffic Service.",
            },
        )

    segment_ids = [str(x) for x in body.get("segment_ids", [])]
    if not segment_ids:
        raise HTTPException(400, "No route segments supplied")

    network = body.get("network")
    if not network:
        raise HTTPException(400, "Network data is required")

    nodes_by_id = {str(n["node_id"]): n for n in network.get("nodes", [])}
    edges_by_id = {str(e["segment_id"]): e for e in network.get("segments", [])}
    selected_edges = [edges_by_id[sid] for sid in segment_ids if sid in edges_by_id]
    if not selected_edges:
        raise HTTPException(400, "No matching network segments found")

    # A route normally contains far fewer than 30 segments. If it is larger,
    # sample evenly so a demo cannot unexpectedly consume a large number of API calls.
    request_ids = segment_ids
    if len(request_ids) > MAX_FLOW_REQUESTS:
        step = len(request_ids) / MAX_FLOW_REQUESTS
        request_ids = [request_ids[min(int(i * step), len(request_ids) - 1)] for i in range(MAX_FLOW_REQUESTS)]
        request_ids = list(dict.fromkeys(request_ids))

    async with httpx.AsyncClient(timeout=20) as client:
        tasks = []
        for sid in request_ids:
            edge = edges_by_id.get(sid)
            if edge:
                key = f"flow:{sid}"
                cached = cached_get(key)
                if cached is not None:
                    tasks.append(asyncio.sleep(0, result=cached))
                else:
                    tasks.append(flow_for_segment(client, sid, edge, nodes_by_id))
        results = await asyncio.gather(*tasks)

        fresh = []
        for sid, result in zip(request_ids, results):
            if result and not result.get("error"):
                cached_put(f"flow:{sid}", result)
            if result:
                fresh.append(result)

        incidents = await live_incidents(client, selected_edges, nodes_by_id)

    usable = [r for r in fresh if not r.get("error")]
    if not usable:
        raise HTTPException(502, "TomTom returned no usable live traffic observations")

    speeds = [r["current_speed_kmh"] for r in usable if r.get("current_speed_kmh") is not None]
    free_speeds = [r["free_flow_speed_kmh"] for r in usable if r.get("free_flow_speed_kmh") is not None]
    delays = [r["delay_pct"] for r in usable if r.get("delay_pct") is not None]

    return {
        "available": True,
        "provider": "TomTom Traffic API",
        "updated_note": "TomTom Traffic Flow data is refreshed frequently; this service caches each segment observation for 60 seconds.",
        "requested_segments": len(segment_ids),
        "observed_segments": len(usable),
        "sampled": len(request_ids) < len(segment_ids),
        "average_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "average_free_flow_speed_kmh": round(sum(free_speeds) / len(free_speeds), 1) if free_speeds else None,
        "average_delay_pct": round(sum(delays) / len(delays), 1) if delays else None,
        "road_closures": sum(1 for r in usable if r.get("road_closure")),
        "segments": fresh,
        "incidents": incidents,
    }


@app.post("/external-route")
async def external_route(body: dict):
    if not TOMTOM_API_KEY:
        raise HTTPException(503, detail={
            "error_code": "LIVE_TRAFFIC_NOT_CONFIGURED",
            "message": "TomTom API key is not configured on the Live Traffic Service.",
        })
    geometry = body.get("geometry") or []
    if len(geometry) < 2:
        raise HTTPException(400, "External route geometry is required")
    points = sample_geometry(geometry, min(MAX_FLOW_REQUESTS, 12))
    async with httpx.AsyncClient(timeout=20) as client:
        observations = await asyncio.gather(*(flow_for_point(client, p) for p in points))
        incidents = await incidents_for_points(client, points)
    usable = [x for x in observations if not x.get("error") and x.get("current_speed_kmh") is not None]
    if not usable:
        raise HTTPException(502, "TomTom returned no usable live traffic observations for this route")
    speeds = [x["current_speed_kmh"] for x in usable]
    free_speeds = [x["free_flow_speed_kmh"] for x in usable if x.get("free_flow_speed_kmh") is not None]
    delays = [x["delay_pct"] for x in usable if x.get("delay_pct") is not None]
    return {
        "available": True, "provider": "TomTom Traffic API", "mode": "external_route",
        "requested_points": len(points), "observed_points": len(usable),
        "average_speed_kmh": round(sum(speeds) / len(speeds), 1),
        "average_free_flow_speed_kmh": round(sum(free_speeds) / len(free_speeds), 1) if free_speeds else None,
        "average_delay_pct": round(sum(delays) / len(delays), 1) if delays else None,
        "road_closures": sum(1 for x in usable if x.get("road_closure")),
        "incidents": incidents, "points": usable,
        "note": "Live traffic is shown as current external information because the organizer dataset does not cover this route.",
    }
