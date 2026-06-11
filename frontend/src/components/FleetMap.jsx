import React, { useEffect, useState, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";
import { MapPin, Loader2 } from "lucide-react";

// Inject pulse + marker CSS once
const STYLE_ID = "trata-fleet-map-styles";
if (typeof document !== "undefined" && !document.getElementById(STYLE_ID)) {
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.innerHTML = `
.veh-marker{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;
  border:2px solid white;box-shadow:0 2px 6px rgba(9,30,66,.25);font-size:14px;font-weight:700;color:white;}
.veh-available{background:#36B37E}
.veh-on_trip{background:#0052CC}
.veh-off_duty{background:#5E6C84}
.veh-maintenance{background:#FFAB00}
.sos-marker{position:relative;display:flex;align-items:center;justify-content:center;width:36px;height:36px;}
.sos-marker .core{position:absolute;width:18px;height:18px;border-radius:50%;background:#FF5630;border:3px solid white;box-shadow:0 2px 8px rgba(255,86,48,.6);z-index:2;}
.sos-marker .pulse{position:absolute;width:36px;height:36px;border-radius:50%;background:#FF5630;opacity:.4;animation:sosPulse 1.4s ease-out infinite;}
@keyframes sosPulse{0%{transform:scale(.4);opacity:.7}100%{transform:scale(1.6);opacity:0}}
.leaflet-popup-content{margin:8px 12px;font-family:'IBM Plex Sans',sans-serif;font-size:12px;}
.leaflet-popup-content b{font-family:'Chivo',sans-serif;}
.leaflet-container{font-family:inherit;}
`;
  document.head.appendChild(s);
}

const VEH_ICON = (state) =>
  L.divIcon({
    className: "",
    html: `<div class="veh-marker veh-${state}" title="${state}">🚑</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });

const SOS_ICON = L.divIcon({
  className: "",
  html: `<div class="sos-marker"><span class="pulse"></span><span class="core"></span></div>`,
  iconSize: [36, 36],
  iconAnchor: [18, 18],
});

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return;
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
  }, [points, map]);
  return null;
}

export default function FleetMap() {
  const [data, setData] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef(null);

  const load = async () => {
    const { data } = await api.get("/provider/fleet");
    setData(data);
  };
  useEffect(() => {
    load();
    intervalRef.current = setInterval(async () => {
      setRefreshing(true);
      try { await load(); } finally { setRefreshing(false); }
    }, 30000);
    return () => clearInterval(intervalRef.current);
  }, []);

  if (!data) {
    return (
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5 h-[440px] flex items-center justify-center text-sm text-[#5E6C84]" data-testid="fleet-map-loading">
        <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading fleet…
      </div>
    );
  }
  if (!data.center) {
    return (
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5 text-sm text-[#5E6C84]">No location data yet.</div>
    );
  }

  const center = [data.center.lat, data.center.lng];
  const points = [
    ...data.vehicles.map((v) => [v.lat, v.lng]),
    ...data.sos.map((s) => [s.lat, s.lng]).filter((p) => p[0] && p[1]),
  ];
  const stats = data.vehicles.reduce((acc, v) => { acc[v.state] = (acc[v.state] || 0) + 1; return acc; }, {});

  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="fleet-map">
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-[#DFE1E6]">
        <div>
          <div className="overline flex items-center gap-1.5"><MapPin className="h-3 w-3" /> Live Fleet Map</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1">
            {data.vehicles.length} vehicles · {data.sos.length} active SOS
            {refreshing && <Loader2 className="h-3 w-3 inline ml-2 animate-spin text-[#5E6C84]" />}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[11px]">
          <Legend dot="#36B37E" label="Available" count={stats.available || 0} />
          <Legend dot="#0052CC" label="On trip"   count={stats.on_trip || 0} />
          <Legend dot="#5E6C84" label="Off duty"  count={stats.off_duty || 0} />
          <Legend dot="#FFAB00" label="Maintenance" count={stats.maintenance || 0} />
          {data.sos.length > 0 && <Legend dot="#FF5630" label="Active SOS" count={data.sos.length} pulsing />}
        </div>
      </div>
      <div style={{ height: 440, width: "100%" }} data-testid="fleet-map-container">
        <MapContainer center={center} zoom={12} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {data.vehicles.map((v) => (
            <Marker key={v.id} position={[v.lat, v.lng]} icon={VEH_ICON(v.state)}>
              <Popup>
                <b style={{ fontWeight: 700 }}>{v.plate_number}</b><br />
                {v.vehicle_type} · Driver: {v.driver_name}<br />
                State: <span style={{ textTransform: "uppercase", fontWeight: 600 }}>{v.state.replace("_", " ")}</span>
                {v.state === "on_trip" && <><br />Speed: {v.speed_kmh} km/h</>}
                <br /><span style={{ color: "#5E6C84" }}>updated {relativeTime(v.last_updated)}</span>
              </Popup>
            </Marker>
          ))}
          {data.sos.map((s) => (s.lat && s.lng) && (
            <Marker key={s.id} position={[s.lat, s.lng]} icon={SOS_ICON}>
              <Popup>
                <b style={{ color: "#FF5630" }}>{s.title}</b><br />
                Patient: {s.contact_name}<br />
                Status: <b>{s.status}</b> · Priority: {s.priority || "—"}
                {s.response_time_minutes != null && <><br />ETA: {s.response_time_minutes} min</>}
                <br /><span style={{ color: "#5E6C84" }}>created {relativeTime(s.created_at)}</span>
              </Popup>
            </Marker>
          ))}
          <FitBounds points={points} />
        </MapContainer>
      </div>
    </div>
  );
}

function Legend({ dot, label, count, pulsing }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${pulsing ? "animate-pulse" : ""}`} style={{ background: dot }} />
      <span className="text-[#42526E] font-medium">{label}</span>
      <span className="font-mono text-[#091E42] font-semibold">{count}</span>
    </div>
  );
}
