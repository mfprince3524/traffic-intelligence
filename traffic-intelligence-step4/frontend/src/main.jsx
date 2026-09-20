import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import L from 'leaflet';
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet';
import { BarChart, Bar, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import 'leaflet/dist/leaflet.css';
import './style.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const NOMINATIM = 'https://nominatim.openstreetmap.org/search';
const DEFAULT_CENTER = [17.385, 78.486];

const markerIcon = L.divIcon({ className: 'map-pin', html: '<span></span>', iconSize: [16, 16], iconAnchor: [8, 8] });
const startIcon = L.divIcon({ className: 'map-pin start-pin', html: '<span>S</span>', iconSize: [30, 30], iconAnchor: [15, 15] });
const destinationIcon = L.divIcon({ className: 'map-pin destination-pin', html: '<span>D</span>', iconSize: [30, 30], iconAnchor: [15, 15] });
const incidentIcon = L.divIcon({ className: 'incident-pin', html: '<span>!</span>', iconSize: [24, 24], iconAnchor: [12, 12] });

function MapViewport({ center, zoom }) {
  const map = useMap();
  useEffect(() => { if (center) map.setView(center, zoom); }, [center, zoom, map]);
  return null;
}

function App() {
  const [traffic, setTraffic] = useState([]);
  const [network, setNetwork] = useState({ nodes: [], segments: [] });
  const [recentIncidents, setRecentIncidents] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [anomalyLoading, setAnomalyLoading] = useState(false);
  const [forecast, setForecast] = useState(null);
  const [fromQuery, setFromQuery] = useState('');
  const [toQuery, setToQuery] = useState('');
  const [fromResults, setFromResults] = useState([]);
  const [toResults, setToResults] = useState([]);
  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [routeExplanation, setRouteExplanation] = useState('');
  const [loading, setLoading] = useState(false);
  const [dataStatus, setDataStatus] = useState('loading');
  const [searchingFrom, setSearchingFrom] = useState(false);
  const [searchingTo, setSearchingTo] = useState(false);
  const [sim, setSim] = useState(null);
  const [scenario, setScenario] = useState('traffic_increase');
  const [scenarioValue, setScenarioValue] = useState(20);
  const [notice, setNotice] = useState('');
  const [selectedSegment, setSelectedSegment] = useState(null);
  const [lastAction, setLastAction] = useState('');
  const [selectedRouteId, setSelectedRouteId] = useState(null);
  const [routeAnalyzed, setRouteAnalyzed] = useState(false);
  const [live, setLive] = useState(null);
  const [liveLoading, setLiveLoading] = useState(false);

  const nodeById = useMemo(() => Object.fromEntries(network.nodes.map(n => [String(n.node_id), n])), [network.nodes]);
  const trafficById = useMemo(() => Object.fromEntries(traffic.map(r => [String(r.segment_id), r])), [traffic]);
  const segmentById = useMemo(() => Object.fromEntries(network.segments.map(s => [String(s.segment_id), s])), [network.segments]);

  const resetRouteAnalysis = () => {
    setRoutes([]);
    setSelectedRouteId(null);
    setRouteAnalyzed(false);
    setSelectedSegment(null);
    setForecast(null);
    setRouteExplanation('');
    setSim(null);
    setLive(null);
    setAnomalies([]);
  };

  const loadData = async () => {
    setDataStatus('loading');
    const results = await Promise.allSettled([
      axios.get(`${API}/api/traffic`),
      axios.get(`${API}/api/network`),
      axios.get(`${API}/api/incidents/recent?limit=8`)
    ]);
    const [trafficResult, networkResult, recentResult] = results;

    if (trafficResult.status === 'fulfilled') setTraffic(trafficResult.value.data.rows || []);
    if (networkResult.status === 'fulfilled') setNetwork(networkResult.value.data || { nodes: [], segments: [] });
    if (recentResult.status === 'fulfilled') setRecentIncidents(recentResult.value.data.rows || []);

    const ready = trafficResult.status === 'fulfilled' && networkResult.status === 'fulfilled';
    setDataStatus(ready ? 'connected' : 'offline');
    if (!ready) {
      setNotice('The dataset backend is not fully available. Check ports 8001, 8002 and 8000.');
    }
  };

  useEffect(() => { loadData(); }, []);

  const loadForecast = async (route) => {
    if (!route?.segments?.length) return;
    try {
      const response = await axios.post(`${API}/api/forecast/route`, { segment_ids: route.segments });
      setForecast(response.data?.available ? response.data : null);
    } catch (error) {
      console.error(error);
      setForecast(null);
    }
  };

  const analyzeRouteEvidence = async () => {
    if (!selectedRouteId) {
      setNotice('Choose a route first. Detect and Diagnose will then focus only on that route.');
      return;
    }
    setAnomalyLoading(true);
    setLastAction('anomalies');
    try {
      const response = await axios.get(`${API}/api/anomalies?contamination=0.05`);
      setAnomalies(response.data.rows || []);
      const count = (response.data.rows || []).filter(row => activeRouteSegmentIds.has(String(row.segment_id))).length;
      setNotice(`${count} anomaly record(s) found on the selected route.`);
    } catch (error) {
      console.error(error);
      setNotice('Route evidence analysis is temporarily unavailable.');
    } finally {
      setAnomalyLoading(false);
    }
  };

  const searchAddress = async (query, setter, setSearching) => {
    if (query.trim().length < 3) { setter([]); return; }
    setSearching(true);
    try {
      const response = await axios.get(NOMINATIM, {
        params: { q: query, format: 'jsonv2', limit: 5, countrycodes: 'in' },
        headers: { Accept: 'application/json' }
      });
      setter(response.data || []);
    } catch (error) {
      console.error(error);
      setter([]);
      setNotice('Address search is temporarily unavailable.');
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    const id = setTimeout(() => searchAddress(fromQuery, setFromResults, setSearchingFrom), 450);
    return () => clearTimeout(id);
  }, [fromQuery]);

  useEffect(() => {
    const id = setTimeout(() => searchAddress(toQuery, setToResults, setSearchingTo), 450);
    return () => clearTimeout(id);
  }, [toQuery]);

  const handleFromChange = (value) => {
    setFromQuery(value);
    setFrom(null);
    resetRouteAnalysis();
  };

  const handleToChange = (value) => {
    setToQuery(value);
    setTo(null);
    resetRouteAnalysis();
  };

  const selectPlace = (place, type) => {
    const selected = { lat: Number(place.lat), lon: Number(place.lon), label: place.display_name };
    if (type === 'from') {
      setFrom(selected);
      setFromQuery(place.display_name);
      setFromResults([]);
    } else {
      setTo(selected);
      setToQuery(place.display_name);
      setToResults([]);
    }
    resetRouteAnalysis();
    setNotice('Location selected. Find a route to check dataset coverage and available live traffic.');
  };

  const useDemoStart = () => {
    const node = network.nodes[0];
    if (!node) return setNotice('Network data is not loaded yet.');
    const selected = { lat: Number(node.lat), lon: Number(node.lon), label: `Dataset node ${node.node_id}` };
    setFrom(selected);
    setFromQuery(selected.label);
    setFromResults([]);
    resetRouteAnalysis();
    setNotice(`Dataset start selected: ${node.node_id}`);
  };

  const useDemoDestination = () => {
    const node = network.nodes.at(-1);
    if (!node) return setNotice('Network data is not loaded yet.');
    const selected = { lat: Number(node.lat), lon: Number(node.lon), label: `Dataset node ${node.node_id}` };
    setTo(selected);
    setToQuery(selected.label);
    setToResults([]);
    resetRouteAnalysis();
    setNotice(`Dataset destination selected: ${node.node_id}`);
  };

  const findRoute = async () => {
    if (!from || !to) {
      setNotice('Select both a starting location and destination.');
      return;
    }

    setLoading(true);
    resetRouteAnalysis();
    setLastAction('route');
    try {
      const response = await axios.post(`${API}/api/routes`, { start: from, destination: to });
      const candidateRoutes = response.data.routes || [];
      setRoutes(candidateRoutes);

      if (!candidateRoutes.length) {
        setNotice('No supporting dataset route was found between these locations.');
      } else {
        setNotice(response.data?.traffic_intelligence_available ? `${candidateRoutes.length} dataset-supported paths found. Review them, then click Analyse.` : `${candidateRoutes.length} road route${candidateRoutes.length === 1 ? '' : 's'} found. Dataset traffic intelligence is unavailable for this area; live traffic can still be checked.`);
      }
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      const message = typeof detail === 'object' ? detail.message : detail;
      setRoutes([]);
      setNotice(message || 'No road route was found for these locations.');
    } finally {
      setLoading(false);
    }
  };

  const analyzeRoutes = async () => {
    if (!routes.length) return;
    if (routes[0]?.traffic_supported === false) {
      setNotice('Dataset analysis is unavailable for this route. You can still choose the map route and check current live traffic.');
      return;
    }
    setLastAction('analyze-routes');
    setRouteAnalyzed(true);
    const advised = routes.find(r => r.recommended);
    try {
      if (advised) {
        const explanation = await axios.post(`${API}/api/explain`, { route: advised });
        setRouteExplanation(explanation.data?.explanation || `Route ${advised.route_id} has the lowest calculated route score in the current dataset snapshot.`);
      }
    } catch (error) {
      setRouteExplanation(advised
        ? `The system advises Route ${advised.route_id} based on the calculated dataset traffic and network metrics.`
        : '');
    }
    setNotice('Routes analysed. The system gives advice, but you choose the final route.');
  };

  const chooseRoute = (route) => {
    setSelectedRouteId(route.route_id);
    setSelectedSegment(route.segments?.[0] || null);
    setLastAction(`route-${route.route_id}`);
    setSim(null);
    setLive(null);
    if (route.traffic_supported === false) {
      setForecast(null);
      setAnomalies([]);
      setNotice(`Route ${route.route_id} selected. Dataset traffic intelligence is unavailable here; current live traffic can still be checked.`);
      return;
    }
    loadForecast(route);
    setNotice(`Route ${route.route_id} selected. Traffic, forecast, evidence and simulation now focus on this route.`);
  };

  const simulate = async () => {
    if (!activeRoute) {
      setNotice('Choose a route before running a simulation.');
      return;
    }
    try {
      const response = await axios.post(`${API}/api/simulation`, {
        segment_ids: activeRoute.segments,
        selected_route_id: activeRoute.route_id,
        scenario,
        severity_pct: scenarioValue,
        traffic_increase_pct: scenarioValue,
        diversion_pct: scenarioValue,
        alternatives: routes
      });
      setSim(response.data);
      document.getElementById('simulation')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (error) {
      console.error(error);
      setNotice('Simulation service is unavailable.');
    }
  };

  const compareLiveTraffic = async () => {
    if (!activeRoute) {
      setNotice('Choose a route before comparing live traffic.');
      return;
    }
    setLiveLoading(true);
    try {
      const endpoint = activeRoute.traffic_supported === false ? `${API}/api/live/external-route` : `${API}/api/live/route`;
      const payload = activeRoute.traffic_supported === false
        ? { geometry: activeRoute.geometry || [] }
        : { segment_ids: activeRoute.segments, network };
      const response = await axios.post(endpoint, payload);
      setLive(response.data);
      setNotice('Live traffic comparison updated from TomTom.');
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      const message = typeof detail === 'object' ? detail.message : detail;
      setNotice(message || 'Live traffic is unavailable. Check the TomTom API key on port 8007.');
    } finally {
      setLiveLoading(false);
    }
  };

  const inspectSegment = (segmentId) => {
    if (!activeRouteSegmentIds.has(String(segmentId))) return;
    setSelectedSegment(segmentId);
  };

  const activeRoute = routes.find(route => route.route_id === selectedRouteId) || null;
  const activeRouteSegmentIds = new Set((activeRoute?.segments || []).map(String));
  const activeRouteRows = activeRoute
    ? traffic.filter(row => activeRouteSegmentIds.has(String(row.segment_id)))
    : [];

  const routeSnapshot = activeRouteRows.length ? {
    segments: activeRouteRows.length,
    average_congestion_pct: (activeRouteRows.reduce((sum, r) => sum + Number(r.congestion_pct || 0), 0) / activeRouteRows.length).toFixed(1),
    average_speed_kmh: (activeRouteRows.reduce((sum, r) => sum + Number(r.speed_kmh || 0), 0) / activeRouteRows.length).toFixed(1),
    average_delay_min: (activeRouteRows.reduce((sum, r) => sum + Number(r.delay_min || 0), 0) / activeRouteRows.length).toFixed(1),
    normal: activeRouteRows.filter(r => r.traffic_state === 'normal').length,
    moderate: activeRouteRows.filter(r => r.traffic_state === 'moderate').length,
    heavy: activeRouteRows.filter(r => r.traffic_state === 'heavy').length,
    severe: activeRouteRows.filter(r => r.traffic_state === 'severe').length
  } : null;

  const routeLines = routes.map(route => {
    const coords = route.geometry?.length
      ? route.geometry.map(point => [Number(point[0]), Number(point[1])])
      : (route.nodes || []).map(id => nodeById[String(id)]).filter(Boolean).map(node => [Number(node.lat), Number(node.lon)]);
    const isSelected = route.route_id === selectedRouteId;
    return { ...route, coords, color: isSelected ? '#6B1F2B' : '#168C87' };
  });

  const mapCenter = from ? [from.lat, from.lon] : DEFAULT_CENTER;
  const selectedRow = selectedSegment ? trafficById[String(selectedSegment)] : null;
  const selectedNetwork = selectedSegment ? segmentById[String(selectedSegment)] : null;
  const routeBottlenecks = activeRoute
    ? activeRoute.segments.filter(id => Number(segmentById[String(id)]?.structural_bottleneck) === 1).length
    : 0;
  const forecastChart = (forecast?.forecast || []).map(point => ({
    name: `+${point.minutes}m`,
    congestion: point.predicted_congestion_pct
  }));
  const routeAnomalies = activeRoute
    ? anomalies.filter(row => activeRouteSegmentIds.has(String(row.segment_id)))
    : [];
  const routeIncidents = activeRoute
    ? recentIncidents.filter(row => activeRouteSegmentIds.has(String(row.segment_id)))
    : [];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Traffic <span>Intelligence</span></div>
        <nav><a href="#routes">Routes</a><a href="#traffic">Traffic</a><a href="#alerts">Alerts</a><a href="#forecast">Forecast</a><a href="#simulation">Simulation</a></nav>
      </header>

      <main>
        <section className="hero">
          <p className="eyebrow">AI-POWERED URBAN TRAFFIC INTELLIGENCE</p>
          <h1>Move smarter through the network.</h1>
          <p className="hero-copy">A decision-support dashboard grounded in the supplied traffic and road-network dataset.</p>

          <div className="search-panel">
            <div className="search-field">
              <label>FROM</label>
              <input value={fromQuery} onChange={e => handleFromChange(e.target.value)} placeholder="Search a starting location" />
              {searchingFrom && <small className="searching">Searching…</small>}
              {fromResults.length > 0 && <SearchResults results={fromResults} onSelect={p => selectPlace(p, 'from')} />}
            </div>
            <div className="search-field">
              <label>TO</label>
              <input value={toQuery} onChange={e => handleToChange(e.target.value)} placeholder="Search a destination" />
              {searchingTo && <small className="searching">Searching…</small>}
              {toResults.length > 0 && <SearchResults results={toResults} onSelect={p => selectPlace(p, 'to')} />}
            </div>
            <button className={`primary action-button ${lastAction === 'route' ? 'is-active' : ''}`} onClick={findRoute} disabled={loading}>
              {loading ? 'Finding paths…' : 'Find Routes'}
            </button>
          </div>

          <div className="quick-actions">
            <button onClick={useDemoStart}>Use dataset start</button>
            <button onClick={useDemoDestination}>Use dataset destination</button>
            <span className={`status ${dataStatus}`}><i /> {dataStatus === 'connected' ? 'Dataset connected' : dataStatus === 'loading' ? 'Connecting…' : 'Backend offline'}</span>
          </div>
          {notice && <div className="notice">{notice}</div>}
        </section>

        <section className="dashboard-grid" id="traffic">
          <div className="map-card">
            <MapContainer center={mapCenter} zoom={12} scrollWheelZoom className="traffic-map">
              <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              <MapViewport center={mapCenter} zoom={from ? 13 : 12} />

              {routeLines.map(route => route.coords.length > 1 && (
                <Polyline
                  key={`route-${route.route_id}`}
                  positions={route.coords}
                  pathOptions={{
                    color: route.color,
                    weight: route.route_id === selectedRouteId ? 7 : route.recommended ? 6 : 4,
                    opacity: route.route_id === selectedRouteId ? 1 : 0.75,
                    dashArray: route.route_id === selectedRouteId ? undefined : '8 8'
                  }}
                >
                  <Popup><b>Route {route.route_id}</b><br />{route.distance_km} km · {route.travel_time_min} min</Popup>
                </Polyline>
              ))}

              {activeRoute && routeIncidents.slice(0, 8).map((incident, i) => {
                const seg = segmentById[String(incident.segment_id)];
                const a = seg && nodeById[String(seg.source_node)];
                const b = seg && nodeById[String(seg.target_node)];
                if (!a || !b) return null;
                const pos = [(Number(a.lat) + Number(b.lat)) / 2, (Number(a.lon) + Number(b.lon)) / 2];
                return <Marker key={`${incident.incident_id || incident.segment_id}-${i}`} position={pos} icon={incidentIcon}>
                  <Popup><b>{incident.incident_type || 'Incident'}</b><br />Segment: {incident.segment_id}<br />Severity: {incident.severity ?? '—'}</Popup>
                </Marker>;
              })}

              {from && <Marker position={[from.lat, from.lon]} icon={startIcon}><Popup>Start<br />{from.label}</Popup></Marker>}
              {to && <Marker position={[to.lat, to.lon]} icon={destinationIcon}><Popup>Destination<br />{to.label}</Popup></Marker>}

              {activeRoute && activeRoute.segments.map(segmentId => {
                const edge = segmentById[String(segmentId)];
                const a = edge && nodeById[String(edge.source_node)];
                const b = edge && nodeById[String(edge.target_node)];
                if (!a || !b) return null;
                const row = trafficById[String(segmentId)];
                const selected = String(segmentId) === String(selectedSegment);
                return <Polyline
                  key={`selected-route-segment-${segmentId}`}
                  positions={[[Number(a.lat), Number(a.lon)], [Number(b.lat), Number(b.lon)]]}
                  pathOptions={{ color: selected ? '#6B1F2B' : '#168C87', weight: selected ? 9 : 6, opacity: 0.95 }}
                  eventHandlers={{ click: () => inspectSegment(segmentId) }}
                >
                  <Popup><b>{segmentId}</b><br />{row?.congestion_pct ?? '—'}% congestion · {row?.speed_kmh ?? '—'} km/h</Popup>
                </Polyline>;
              })}
            </MapContainer>
            <div className="map-legend">
              <span><i style={{background:'#168C87'}} /> Candidate route</span>
              <span><i style={{background:'#6B1F2B'}} /> Selected route/segment</span>
            </div>
          </div>

          <aside className="intelligence-card">
            <div className="card-kicker">TRAFFIC INTELLIGENCE</div>
            <h2>{activeRoute ? `Route ${activeRoute.route_id} snapshot` : 'Waiting for route analysis'}</h2>
            {!activeRoute ? (
              <div className="empty-state">
                <b>No route selected.</b><br />
                Enter a start and destination, find dataset-supported routes, analyse them, then choose a route. Traffic metrics will appear here.
              </div>
            ) : routeSnapshot ? (
              <>
                <div className="snapshot-time">Dataset snapshot<br /><b>{traffic.find(r => activeRouteSegmentIds.has(String(r.segment_id)))?.timestamp || 'Current dataset snapshot'}</b></div>
                <div className="metric"><strong>{routeSnapshot.segments}</strong><span> route segments</span></div>
                <div className="metric-row">
                  <div><b>{routeSnapshot.normal}</b><span>Normal</span></div>
                  <div><b>{routeSnapshot.moderate}</b><span>Moderate</span></div>
                  <div><b>{routeSnapshot.heavy}</b><span>Heavy</span></div>
                  <div><b>{routeSnapshot.severe}</b><span>Severe</span></div>
                </div>
                <div className="evidence"><span>Average congestion</span><b>{routeSnapshot.average_congestion_pct}%</b></div>
                <div className="evidence"><span>Average speed</span><b>{routeSnapshot.average_speed_kmh} km/h</b></div>
                <div className="evidence"><span>Average delay</span><b>{routeSnapshot.average_delay_min} min</b></div>
                {selectedRow && <div className="selected-segment"><span>Selected route road</span><b>{selectedSegment}</b><small>{selectedRow.traffic_state} · {selectedRow.congestion_pct}% congestion · {selectedRow.speed_kmh} km/h</small></div>}
              </>
            ) : (
              <div className="empty-state">The selected route has no matching current traffic observations.</div>
            )}
          </aside>
        </section>

        <section className="routes-section" id="routes">
          <div className="section-heading">
            <div><div className="card-kicker">ROUTE EVALUATION</div><h2>Candidate routes</h2></div>
            <span>{routes.length ? `${routes.length} candidate paths` : 'Awaiting route generation'}</span>
          </div>

          {!routes.length ? (
            <div className="empty-panel">Choose a start and destination. Routes can still be displayed outside the supplied traffic dataset; dataset-based intelligence is enabled only when coverage exists.</div>
          ) : (
            <>
              <div className="route-actions">
                <button className="primary action-button" onClick={analyzeRoutes} disabled={routeAnalyzed || routes[0]?.traffic_supported === false}>
                  {routes[0]?.traffic_supported === false ? 'Dataset analysis unavailable' : routeAnalyzed ? 'Routes analysed' : 'Analyse'}
                </button>
                <span className="muted">First compare the paths. The system advises; the user makes the final route choice.</span>
              </div>

              {routeAnalyzed && (
                <div className="route-matrix">
                  <div className="matrix-row matrix-head"><b>Metric</b>{routes.map(r => <b key={r.route_id}>Route {r.route_id}</b>)}</div>
                  {[
                    ['Time', r => `${r.travel_time_min} min`],
                    ['Speed', r => r.avg_speed_kmh == null ? '—' : `${r.avg_speed_kmh} km/h`],
                    ['Distance', r => `${r.distance_km} km`],
                    ['Congestion', r => r.avg_congestion_pct == null ? '—' : `${r.avg_congestion_pct}%`],
                    ['Delay', r => r.delay_min == null ? '—' : `${r.delay_min} min`]
                  ].map(([label, getter]) => (
                    <div className="matrix-row" key={label}><span>{label}</span>{routes.map(r => <span key={r.route_id}>{getter(r)}</span>)}</div>
                  ))}
                  <div className="matrix-row matrix-choice">
                    <span>Choose</span>
                    {routes.map(r => (
                      <button key={r.route_id} className={selectedRouteId === r.route_id ? 'is-active' : ''} onClick={() => chooseRoute(r)}>
                        Route {r.route_id}{r.recommended ? ' · System advice' : ''}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {!routeAnalyzed && (
                <div className="route-list">
                  {routes.map(route => (
                    <article className="route-card" key={route.route_id}>
                      <div className="route-label"><span className="route-letter">{route.route_id}</span><div><h3>Route {route.route_id}</h3><p>{route.distance_km} km · {route.travel_time_min} min{route.avg_congestion_pct == null ? '' : ` · ${route.avg_congestion_pct}% congestion`}</p></div></div>
                      <div className="route-card-actions">
                        <span className="muted">{route.traffic_supported === false ? 'Map route · live status available' : route.recommended ? 'System advice' : 'Candidate'}</span>
                        {route.traffic_supported === false && <button className="small-action" onClick={() => chooseRoute(route)}>Use Route</button>}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          )}
          {routeExplanation && <div className="explanation"><b>System advice:</b> {routeExplanation}</div>}
        </section>

        <section className="analysis-grid" id="forecast">
          <section className="info-card">
            <div className="card-kicker">PREDICT</div>
            <h2>Route forecast · 15–60 minutes</h2>
            {activeRoute && activeRoute.traffic_supported !== false && forecast ? (
              <>
                <p className="muted">Route {activeRoute.route_id} · {forecast.segment_count} segments · current congestion {forecast.current_congestion_pct}%</p>
                <div className="chart-wrap">
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={forecastChart}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" />
                      <YAxis domain={[0, 100]} />
                      <Tooltip formatter={(value) => [`${value}%`, 'Predicted congestion']} />
                      <Bar dataKey="congestion" fill="#6B1F2B" radius={[4,4,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : (
              <p className="muted">Choose a route after Analyse to generate a route-specific forecast.</p>
            )}
          </section>

          <section className="info-card">
            <div className="card-kicker">NETWORK</div>
            <h2>Selected route intelligence</h2>
            {activeRoute && activeRoute.traffic_supported !== false ? (
              <>
                <div className="network-stat"><strong>{activeRoute.segments.length}</strong><span>route segments</span></div>
                <div className="network-stat"><strong>{routeBottlenecks}</strong><span>structural bottlenecks</span></div>
                {selectedNetwork && <div className="selected-segment"><span>Selected road</span><b>{selectedNetwork.segment_id}</b><small>{selectedNetwork.road_class} · {selectedNetwork.lanes} lanes · capacity {selectedNetwork.capacity_vph} vph</small></div>}
                <p className="muted">Only the selected route is analysed here; the full dataset network remains hidden from the map.</p>
              </>
            ) : <p className="muted">Choose a route to inspect its network footprint and bottlenecks.</p>}
          </section>
        </section>

        <section className="lower-grid" id="alerts">
          <section className="info-card">
            <div className="card-kicker">DETECT · DIAGNOSE</div>
            <h2>{activeRoute ? `Route ${activeRoute.route_id} evidence` : 'Route evidence'}</h2>
            <button className="primary small-action" onClick={analyzeRouteEvidence} disabled={!activeRoute || anomalyLoading}>
              {anomalyLoading ? 'Analysing…' : 'Detect route evidence'}
            </button>
            {activeRoute && activeRoute.traffic_supported !== false && routeAnomalies.length ? (
              <div className="alert-list">{routeAnomalies.slice(0, 7).map(a => <div className="alert" key={a.segment_id}><b>{a.segment_id}</b><span>Anomalous pattern · score {a.anomaly_score}</span></div>)}</div>
            ) : activeRoute && routeIncidents.length ? (
              <div className="alert-list">{routeIncidents.slice(0, 6).map(incident => <div className="alert" key={incident.incident_id}><b>{incident.segment_id}</b><span>{incident.incident_type || 'Dataset incident'} · severity {incident.severity ?? '—'}</span></div>)}</div>
            ) : (
              <p className="muted">{activeRoute?.traffic_supported === false ? 'Dataset evidence analysis is unavailable for this route. Use Live Traffic to view current conditions.' : activeRoute ? 'Run Detect route evidence to check anomalies and incidents on this route.' : 'Choose a route first.'}</p>
            )}
          </section>

          <section className="info-card live-card">
            <div className="card-kicker">LIVE TRAFFIC</div>
            <h2>{activeRoute?.traffic_supported === false ? 'Current live traffic status' : 'Dataset vs current traffic'}</h2>
            <p className="muted">Optional external live layer. The organizer dataset remains the primary source for routing and analysis.</p>
            <button className="primary small-action" onClick={compareLiveTraffic} disabled={!activeRoute || liveLoading}>
              {liveLoading ? 'Checking live traffic…' : 'Compare Live Traffic'}
            </button>
            {live?.available ? (
              <div className="compare">
                {activeRoute?.traffic_supported !== false && <div><span>Dataset speed</span><strong>{routeSnapshot?.average_speed_kmh ?? '—'}</strong><small>km/h</small></div>}
                <div><span>Live speed</span><strong>{live.average_speed_kmh ?? '—'}</strong><small>km/h</small></div>
              </div>
            ) : <p className="muted">Add the TomTom key to the Live Traffic Service to activate this panel.</p>}
            {live?.available && <div className="live-meta"><b>{activeRoute?.traffic_supported === false ? `${live.observed_points}/${live.requested_points}` : `${live.observed_segments}/${live.requested_segments}`}</b> {activeRoute?.traffic_supported === false ? 'route points' : 'route segments'} observed · <b>{live.road_closures}</b> live closures · <b>{live.incidents?.length || 0}</b> live incidents</div>}
          </section>

          <section className="info-card" id="simulation">
            <div className="card-kicker">SIMULATE</div>
            <h2>What-if route simulation</h2>
            <p className="muted">Test how the selected dataset-supported route changes if traffic demand rises, an incident occurs, capacity is reduced, or the road is closed. Results are scenario calculations, not guaranteed future predictions.</p>
            <div className="scenario-grid">
              {[
                ['traffic_increase', 'Traffic increase'],
                ['incident', 'Incident'],
                ['lane_reduction', 'Capacity reduction'],
                ['closure', 'Road closure'],
                ['diversion', 'Traffic diversion']
              ].map(([value, label]) => <button key={value} className={scenario === value ? 'scenario-active' : ''} onClick={() => setScenario(value)}>{label}</button>)}
            </div>
            {scenario !== 'closure' && <div className="slider-row"><label>{scenario === 'traffic_increase' ? 'Change' : scenario === 'diversion' ? 'Diversion' : 'Severity'}</label><input type="range" min="5" max="80" step="5" value={scenarioValue} onChange={e => setScenarioValue(Number(e.target.value))} /><b>{scenarioValue}%</b></div>}
            <button className="primary action-button" onClick={simulate} disabled={!activeRoute || activeRoute.traffic_supported === false}>Run simulation</button>
            {sim?.available && (
              <>
                <div className="compare">
                  <div><span>Before</span><strong>{sim.before.congestion_pct}%</strong><small>{sim.before.speed_kmh} km/h · {sim.before.delay_min ?? '—'} min delay</small></div>
                  <div><span>After</span><strong>{sim.after.congestion_pct}%</strong><small>{sim.after.speed_kmh} km/h · {sim.after.delay_min ?? '—'} min delay</small></div>
                </div>
                <div className="simulation-advice">
                  <b>Scenario:</b> {sim.scenario_label}<br />
                  {sim.advisory ? <>Calculated advisory: Route {sim.advisory.route_id} has the lowest simulated/baseline travel time among the compared routes.</> : <>The selected route becomes unavailable under this scenario; compare the remaining routes.</>}
                </div>
              </>
            )}
          </section>
        </section>
      </main>
    </div>
  );
}

function SearchResults({ results, onSelect }) {
  return <div className="search-results">{results.map(place => <button key={place.place_id} onClick={() => onSelect(place)}>{place.display_name}</button>)}</div>;
}

createRoot(document.getElementById('root')).render(<App />);
