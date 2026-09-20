from fastapi import FastAPI
import os
import httpx

app = FastAPI(title="Traffic Simulation Service", version="0.4.0")
DATA = os.getenv("DATA_SERVICE_URL", "http://localhost:8001")
TRAFFIC = os.getenv("TRAFFIC_SERVICE_URL", "http://localhost:8002")


async def get(url: str):
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def route_before(selected, network):
    if not selected:
        return None

    total_flow = sum(float(row.get("flow_vph") or 0) for row, _ in selected)
    total_capacity = sum(max(float(edge.get("capacity_vph") or 1), 1) for _, edge in selected)
    total_delay = sum(float(row.get("delay_min") or 0) for row, _ in selected)
    distance = sum(float(edge.get("length_km") or 0) for _, edge in selected)
    weighted_speed = (
        sum(float(row.get("speed_kmh") or 0) * float(row.get("flow_vph") or 0) for row, _ in selected)
        / max(total_flow, 1)
    )
    congestion = min(total_flow / max(total_capacity, 1), 1.5)
    return {
        "congestion_pct": round(congestion * 100, 1),
        "speed_kmh": round(weighted_speed, 1),
        "delay_min": round(total_delay, 1),
        "flow_vph": round(total_flow, 1),
        "distance_km": round(distance, 2),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/simulate")
async def simulate(body: dict):
    segment_ids = [str(x) for x in body.get("segment_ids", [])]
    if not segment_ids:
        return {"available": False, "reason": "No route segments supplied"}

    scenario = str(body.get("scenario", "traffic_increase")).lower()
    severity = max(0.05, min(float(body.get("severity_pct", 30)) / 100, 0.95))
    traffic_increase = max(0.0, min(float(body.get("traffic_increase_pct", 20)) / 100, 2.0))
    diversion = max(0.0, min(float(body.get("diversion_pct", 20)) / 100, 0.9))

    net = await get(DATA + "/network")
    state = await get(TRAFFIC + "/state")
    traffic_by_id = {str(row["segment_id"]): row for row in state.get("rows", [])}
    network_by_id = {str(edge["segment_id"]): edge for edge in net.get("segments", [])}

    selected = [
        (traffic_by_id[sid], network_by_id[sid])
        for sid in segment_ids
        if sid in traffic_by_id and sid in network_by_id
    ]
    if not selected:
        return {"available": False, "reason": "Route segments are not present in the current snapshot"}

    before = route_before(selected, network_by_id)

    flow_multiplier = 1.0
    capacity_multiplier = 1.0
    speed_multiplier = 1.0
    scenario_label = "Traffic increase"

    if scenario == "traffic_increase":
        flow_multiplier = 1.0 + traffic_increase
        scenario_label = f"Traffic demand +{round(traffic_increase * 100)}%"
    elif scenario == "incident":
        capacity_multiplier = 1.0 - severity
        speed_multiplier = max(0.25, 1.0 - severity * 0.65)
        scenario_label = f"Incident severity {round(severity * 100)}%"
    elif scenario == "lane_reduction":
        capacity_multiplier = max(0.2, 1.0 - severity)
        speed_multiplier = max(0.45, 1.0 - severity * 0.35)
        scenario_label = f"Lane/capacity reduction {round(severity * 100)}%"
    elif scenario == "closure":
        capacity_multiplier = 0.0
        speed_multiplier = 0.0
        scenario_label = "Road closure"
    elif scenario == "diversion":
        flow_multiplier = max(0.1, 1.0 - diversion)
        scenario_label = f"Traffic diversion -{round(diversion * 100)}%"
    else:
        return {"available": False, "reason": f"Unknown scenario: {scenario}"}

    if capacity_multiplier == 0:
        after = {
            "available": False,
            "congestion_pct": 150.0,
            "speed_kmh": 0.0,
            "delay_min": None,
            "flow_vph": round(before["flow_vph"] * flow_multiplier, 1),
            "distance_km": before["distance_km"],
        }
    else:
        new_flow = before["flow_vph"] * flow_multiplier
        new_capacity = max(
            sum(max(float(edge.get("capacity_vph") or 1), 1) for _, edge in selected) * capacity_multiplier,
            1,
        )
        new_congestion = min(new_flow / new_capacity, 1.5)
        speed_after = max(before["speed_kmh"] * speed_multiplier, 1.0)
        congestion_ratio = max(new_congestion / max(before["congestion_pct"] / 100, 0.01), 0.1)
        delay_after = before["delay_min"] * congestion_ratio
        after = {
            "available": True,
            "congestion_pct": round(new_congestion * 100, 1),
            "speed_kmh": round(speed_after, 1),
            "delay_min": round(delay_after, 1),
            "flow_vph": round(new_flow, 1),
            "distance_km": before["distance_km"],
        }

    alternatives = []
    for route in body.get("alternatives", []):
        if str(route.get("route_id")) != str(body.get("selected_route_id")):
            alternatives.append({
                "route_id": route.get("route_id"),
                "travel_time_min": route.get("travel_time_min"),
                "distance_km": route.get("distance_km"),
                "avg_congestion_pct": route.get("avg_congestion_pct"),
            })

    selected_route_id = body.get("selected_route_id", "selected")
    if after["available"]:
        after_time = before["distance_km"] / max(after["speed_kmh"], 1) * 60
        selected_result = {"route_id": selected_route_id, "travel_time_min": round(after_time, 1)}
    else:
        selected_result = {"route_id": selected_route_id, "travel_time_min": None}

    comparison = [selected_result] + [
        {"route_id": item["route_id"], "travel_time_min": item["travel_time_min"]}
        for item in alternatives
    ]
    usable = [item for item in comparison if item.get("travel_time_min") is not None]
    advisory = None
    if usable:
        advisory = min(usable, key=lambda item: float(item["travel_time_min"]))

    return {
        "available": True,
        "simulated": True,
        "scenario": scenario,
        "scenario_label": scenario_label,
        "segment_count": len(selected),
        "model": "dataset-backed what-if capacity/flow scenario",
        "before": before,
        "after": after,
        "route_comparison": comparison,
        "advisory": advisory,
        "note": "Simulation is a scenario model based on current organizer-dataset traffic and network capacity; it is not a prediction of an actual future event.",
    }
