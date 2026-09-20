# Live Traffic Setup

This project keeps the organizer traffic dataset as the primary routing/intelligence source and adds TomTom as an optional live comparison layer.

## 1. Get a TomTom API key

1. Create/sign in to a TomTom account.
2. Open **API & SDK Keys**.
3. Copy the API key created for your account.
4. The live service uses TomTom Traffic Flow Segment Data and Incident Details.

Official key guide:
https://docs.tomtom.com/platform/documentation/my-tomtom/how-to-get-a-tomtom-api-key

## 2. Add the key locally

Do NOT put the key in `frontend/.env` or any React source file.

Create:

`services/live/.env`

with:

```env
TOMTOM_API_KEY=PASTE_YOUR_KEY_HERE
LIVE_TRAFFIC_CACHE_TTL_SECONDS=60
LIVE_TRAFFIC_MAX_FLOW_REQUESTS=30
```

`services/live/.env` is ignored by Git if `.gitignore` is unchanged.

## 3. Start the Live Traffic Service

PowerShell:

```powershell
cd services\live
uvicorn main:app --reload --port 8007 --env-file .env
```

Then test:

`http://localhost:8007/health`

The response should contain:

```json
{
  "status": "ok",
  "provider": "TomTom",
  "configured": true
}
```

## 4. Gateway

Start the Gateway on port 8000 as usual. It proxies:

- `POST /api/live/route`
- `GET /api/live/health`

The browser never receives the TomTom API key.

## 5. Frontend

The dashboard has a **Compare Live Traffic** button inside the Live Traffic panel. It sends the selected route to the backend, which requests current TomTom flow observations and compares them with the organizer dataset.

## Important

The live service uses the Flow Segment Data endpoint for road-level observations. It queries the road closest to the midpoint of each selected dataset segment, so the result is a **live comparison/approximation**, not a claim that TomTom's road segment IDs equal the organizer's segment IDs.

The service caches observations for 60 seconds and limits the number of flow requests per route request.

Free usage is subject to TomTom's current free-tier limits and QPS/daily restrictions. Do not expose or commit the API key.
