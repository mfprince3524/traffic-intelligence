# Urban Traffic Intelligence Frontend

React + Vite frontend for the traffic-intelligence microservices project.

## Map stack

- OpenStreetMap tiles
- Leaflet / React-Leaflet for map rendering
- Nominatim for address search
- Organizer network + backend NetworkX route generation

Google Maps is not required by this frontend.

## Run

```bash
npm install
npm run dev
```

The frontend expects the API gateway at `http://localhost:8000` unless `VITE_API_URL` is set.

## Data integrity

Traffic values, incidents, route metrics, and simulation outputs are rendered only when returned by the backend services. The frontend does not fabricate traffic observations.
