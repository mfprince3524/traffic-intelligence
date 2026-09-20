from fastapi import FastAPI, HTTPException
import math
import os
import httpx
import networkx as nx

app = FastAPI(title="Route Intelligence Service", version="0.5.0")
DATA = os.getenv("DATA_SERVICE_URL", "http://localhost:8001")
TRAFFIC = os.getenv("TRAFFIC_SERVICE_URL", "http://localhost:8002")
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org")
COVERAGE_PADDING_KM = float(os.getenv("DATASET_COVERAGE_PADDING_KM", "1.0"))


async def get(url: str):
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest(nodes, lat, lon):
    best = None
    for node in nodes:
        distance = haversine_km(lat, lon, float(node["lat"]), float(node["lon"]))
        if best is None or distance < best["distance_km"]:
            best = {"node_id": str(node["node_id"]), "distance_km": distance}
    return best


def coverage_bounds(nodes, lat):
    lats = [float(node["lat"]) for node in nodes]
    lons = [float(node["lon"]) for node in nodes]
    lat_padding = COVERAGE_PADDING_KM / 111.32
    lon_padding = COVERAGE_PADDING_KM / (111.32 * max(math.cos(math.radians(lat)), 0.2))
    return min(lats), max(lats), min(lons), max(lons), lat_padding, lon_padding


def is_inside_dataset(nodes, lat, lon):
    min_lat, max_lat, min_lon, max_lon, lat_padding, lon_padding = coverage_bounds(nodes, lat)
    return (
        min_lat - lat_padding <= lat <= max_lat + lat_padding
        and min_lon - lon_padding <= lon <= max_lon + lon_padding
    )


def parse_point(point, label):
    try:
        lat = float(point["lat"])
        lon = float(point["lon"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, f"Invalid {label} coordinates")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, f"Invalid {label} coordinates")
    return lat, lon


def validate_dataset_point(nodes, point, label):
    lat, lon = parse_point(point, label)
    nearest_node = nearest(nodes, lat, lon)
    if not nearest_node:
        raise HTTPException(503, "Dataset network is unavailable")
    return lat, lon, nearest_node, is_inside_dataset(nodes, lat, lon)


def build(net, rows):
    traffic = {str(r["segment_id"]): r for r in rows}
    graph = nx.DiGraph()
    for node in net["nodes"]:
        graph.add_node(str(node["node_id"]))
    for edge in net["segments"]:
        row = traffic.get(str(edge["segment_id"]), {})
        speed = max(float(row.get("speed_kmh") or edge.get("free_flow_speed_kmh") or 1), 1)
        distance = float(edge.get("length_km") or 0)
        congestion = float(row.get("congestion_index") or 0)
        travel_time = distance / speed * 60
        weight = travel_time * (1 + 2 * max(congestion, 0))
        graph.add_edge(
            str(edge["source_node"]), str(edge["target_node"]),
            segment_id=str(edge["segment_id"]), length_km=distance,
            travel_time_min=travel_time, congestion=congestion,
            speed_kmh=speed, delay_min=float(row.get("delay_min") or 0), weight=weight,
        )
    return graph


def path_metrics(graph, path):
    edges = [graph[path[i]][path[i + 1]] for i in range(len(path) - 1)]
    distance = sum(edge["length_km"] for edge in edges)
    time_min = sum(edge["travel_time_min"] for edge in edges)
    total_delay = sum(edge["delay_min"] for edge in edges)
    avg_speed = distance / max(time_min / 60, 1e-9)
    avg_congestion = sum(edge["congestion"] for edge in edges) / max(len(edges), 1)
    return {
        "nodes": path, "segments": [edge["segment_id"] for edge in edges],
        "distance_km": round(distance, 2), "travel_time_min": round(time_min, 1),
        "avg_speed_kmh": round(avg_speed, 1), "avg_congestion_pct": round(avg_congestion * 100, 1),
        "delay_min": round(total_delay, 1), "score": round(sum(edge["weight"] for edge in edges), 2),
        "source": "organizer_dataset", "traffic_supported": True,
    }


async def external_routes(start, destination):
    # Outside the organizer dataset, we still provide normal map routing.
    # Traffic intelligence is explicitly marked unavailable until the live layer is queried.
    slon, slat = float(start["lon"]), float(start["lat"])
    dlon, dlat = float(destination["lon"]), float(destination["lat"])
    url = f"{OSRM_BASE_URL.rstrip('/')}/route/v1/driving/{slon},{slat};{dlon},{dlat}"
    params = {"alternatives": "true", "overview": "full", "geometries": "geojson", "steps": "false"}
    try:
        async with httpx.AsyncClient(timeout=45, headers={"User-Agent": "Traffic-Intelligence-Hackathon/1.0"}) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"External route service unavailable: {exc}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"External route service returned HTTP {exc.response.status_code}")

    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise HTTPException(422, "No road route could be found for the selected locations.")

    result = []
    for index, route in enumerate(payload["routes"][:3]):
        geometry = route.get("geometry", {}).get("coordinates", [])
        coords = [[float(latlon[1]), float(latlon[0])] for latlon in geometry]
        distance_km = float(route.get("distance", 0)) / 1000
        time_min = float(route.get("duration", 0)) / 60
        avg_speed = distance_km / max(time_min / 60, 1e-9)
        result.append({
            "route_id": chr(65 + index), "nodes": [], "segments": [],
            "geometry": coords, "distance_km": round(distance_km, 2),
            "travel_time_min": round(time_min, 1), "avg_speed_kmh": round(avg_speed, 1),
            "avg_congestion_pct": None, "delay_min": None,
            "score": round(time_min, 2), "recommended": index == 0,
            "source": "OpenStreetMap routing via OSRM", "traffic_supported": False,
        })
    return result


@app.get("/health")
def health():
    return {"status": "ok", "coverage_padding_km": COVERAGE_PADDING_KM, "external_routing": OSRM_BASE_URL}


@app.post("/routes")
async def routes(body: dict):
    net = await get(DATA + "/network")
    nodes = net.get("nodes", [])
    if not nodes:
        raise HTTPException(503, "Dataset network is unavailable")

    start = body.get("start") or {}
    destination = body.get("destination") or {}
    slat, slon, start_nearest, start_supported = validate_dataset_point(nodes, start, "start")
    dlat, dlon, destination_nearest, destination_supported = validate_dataset_point(nodes, destination, "destination")

    # If either point is outside the supplied dataset, do NOT block the user.
    # Provide ordinary road routing and clearly mark dataset intelligence unavailable.
    if not (start_supported and destination_supported):
        external = await external_routes(
            {"lat": slat, "lon": slon}, {"lat": dlat, "lon": dlon}
        )
        return {
            "success": True, "mode": "external_route_only",
            "traffic_intelligence_available": False,
            "message": "Route available, but the organizer traffic dataset does not cover one or both selected locations. Dataset-based traffic analysis, forecasting and simulation are unavailable for this route.",
            "start_supported": start_supported, "destination_supported": destination_supported,
            "start_nearest_dataset_distance_km": round(start_nearest["distance_km"], 2),
            "destination_nearest_dataset_distance_km": round(destination_nearest["distance_km"], 2),
            "routes": external,
        }

    traffic = await get(TRAFFIC + "/state")
    start_node = start_nearest["node_id"]
    destination_node = destination_nearest["node_id"]
    if start_node == destination_node:
        raise HTTPException(400, "Start and destination resolve to the same network node")

    graph = build(net, traffic.get("rows", []))
    paths, penalties = [], {}
    for _ in range(3):
        for _, _, data in graph.edges(data=True):
            data["search_weight"] = data["weight"] * penalties.get(data["segment_id"], 1.0)
        try:
            path = nx.shortest_path(graph, start_node, destination_node, weight="search_weight")
        except nx.NetworkXNoPath:
            break
        if path in paths:
            break
        paths.append(path)
        for i in range(len(path) - 1):
            sid = graph[path[i]][path[i + 1]]["segment_id"]
            penalties[sid] = penalties.get(sid, 1.0) * 3.0

    if not paths:
        # Dataset coverage exists, but its directed network cannot connect the points.
        external = await external_routes({"lat": slat, "lon": slon}, {"lat": dlat, "lon": dlon})
        return {
            "success": True, "mode": "external_route_only", "traffic_intelligence_available": False,
            "message": "A road route is available, but the supplied traffic network has no connected path between these points. Dataset-based route intelligence is unavailable for this journey.",
            "start_supported": True, "destination_supported": True, "routes": external,
        }

    result = []
    for index, path in enumerate(paths):
        item = path_metrics(graph, path)
        item["route_id"] = chr(65 + index)
        item["recommended"] = False
        result.append(item)
    result.sort(key=lambda item: item["score"])
    if result:
        result[0]["recommended"] = True

    # Attach map geometry directly so the frontend does not need to draw the hidden full network.
    node_by_id = {str(n["node_id"]): n for n in nodes}
    for item in result:
        item["geometry"] = [
            [float(node_by_id[n]["lat"]), float(node_by_id[n]["lon"])]
            for n in item["nodes"] if n in node_by_id
        ]

    return {
        "success": True, "mode": "dataset_route", "traffic_intelligence_available": True,
        "message": "Dataset-supported routes found.",
        "start_node": start_node, "destination_node": destination_node,
        "start_supported": True, "destination_supported": True, "routes": result,
    }
