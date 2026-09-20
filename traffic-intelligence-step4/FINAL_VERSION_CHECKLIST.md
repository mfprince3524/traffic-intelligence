# Final Version Cross-Check

- Dataset network remains internal; full 436-edge grid is hidden from the map.
- Initial dashboard does not show route-specific traffic metrics until a route is selected.
- Dataset-supported locations use fast NetworkX route alternatives and route-specific intelligence.
- Locations outside dataset coverage still receive ordinary road routing through OSRM; they are not blocked.
- Outside-dataset routes are explicitly marked as `traffic_supported: false`; forecast, dataset anomaly analysis and simulation remain disabled for those routes.
- Outside-dataset routes can still be selected and can query current live traffic through the TomTom Live Traffic Service.
- Inside-dataset routes can compare organizer dataset traffic with TomTom live traffic.
- TomTom API key remains server-side in `services/live/.env`.
- Gateway preserves downstream HTTP errors instead of masking 422 coverage responses as service-unavailable.
- Data `/network` serialization converts missing CSV values to JSON `null`.
- Simulation remains a dataset-backed what-if model and is not presented as a guaranteed future prediction.
- Python syntax for all backend `main.py` files has been checked with `py_compile`.
- Frontend dependency installation could not be completed in this environment because `npm install` timed out; run `npm install` and `npm run dev` locally.
- External OSRM/TomTom network calls could not be live-tested in this build environment because outbound DNS/network access is unavailable; the integrations are isolated and clearly reported when unavailable.
