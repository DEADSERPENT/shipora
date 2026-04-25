import React, { useEffect, useState, useCallback } from 'react';
import {
  MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap
} from 'react-leaflet';
import L from 'leaflet';

// ── Haversine distance (km) ────────────────────────────────────────────────
function haversine(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ── Custom icons (emoji-based DivIcon) ──────────────────────────────────────
const makeIcon = (emoji, size = 36) =>
  L.divIcon({
    className: '',
    html: `<div style="font-size:${size}px;line-height:1;filter:drop-shadow(1px 2px 4px rgba(0,0,0,0.35))">${emoji}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size],
    popupAnchor: [0, -size],
  });

const homeIcon   = makeIcon('🏠', 36);
const truckIcon  = makeIcon('🚛', 36);
const myLocIcon  = makeIcon('📍', 32);

// ── Fetch road route from OSRM (free, no key needed) ────────────────────────
async function fetchOSRMRoute(fromLat, fromLng, toLat, toLng) {
  try {
    const url =
      `https://router.project-osrm.org/route/v1/driving/` +
      `${fromLng},${fromLat};${toLng},${toLat}` +
      `?overview=full&geometries=geojson`;
    const res  = await fetch(url);
    const data = await res.json();
    if (data.code === 'Ok' && data.routes[0]) {
      return data.routes[0].geometry.coordinates.map(([lng, lat]) => [lat, lng]);
    }
  } catch (e) {
    console.error('OSRM route error:', e);
  }
  return null;
}

// ── Auto-recenter on prop change ─────────────────────────────────────────────
function MapCenter({ center }) {
  const map = useMap();
  useEffect(() => { if (center) map.setView(center, map.getZoom()); }, [center, map]);
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// VehicleMap — used in both UserDashboard and DriverDashboard
//
// Props:
//   userLocation   – { lat, lng }  (user's home – only for 'user' view)
//   vehicles       – { [driverId]: vehicleData }
//   driverLocation – { lat, lng }  (driver's GPS – only for 'driver' view)
//   role           – 'user' | 'driver'
//   RADIUS_KM      – default 3
// ─────────────────────────────────────────────────────────────────────────────
export default function VehicleMap({
  userLocation,
  vehicles = {},
  driverLocation,
  role = 'user',
  RADIUS_KM = 3
}) {
  const [routeCoords, setRouteCoords] = useState({});  // { driverId: [[lat,lng]...] }
  // nearbyVehicles is derived for route-fetch side effects only

  const defaultCenter =
    userLocation   ? [userLocation.lat, userLocation.lng]
    : driverLocation ? [driverLocation.lat, driverLocation.lng]
    : [20.5937, 78.9629];

  // ── Calculate distances & fetch routes ────────────────────────────────────
  const processVehicles = useCallback(async () => {
    if (role !== 'user' || !userLocation) return;

    const nearby = [];
    const newRoutes = {};

    for (const v of Object.values(vehicles)) {
      if (!v.lat || !v.lng || !v.isActive) continue;
      const dist = haversine(userLocation.lat, userLocation.lng, v.lat, v.lng);
      if (dist <= RADIUS_KM) {
        nearby.push({ ...v, distance: dist });
        // Fetch road route if within radius
        const route = await fetchOSRMRoute(v.lat, v.lng, userLocation.lat, userLocation.lng);
        if (route) newRoutes[v.driverId] = route;
      }
    }

    void nearby; // used for route-fetch side effects
    setRouteCoords(newRoutes);
  }, [vehicles, userLocation, role, RADIUS_KM]);

  useEffect(() => { processVehicles(); }, [processVehicles]);

  return (
    <MapContainer
      center={defaultCenter}
      zoom={14}
      style={{ height: '100%', width: '100%', minHeight: 400 }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='© <a href="https://www.openstreetmap.org">OpenStreetMap</a>'
      />

      {/* ── USER VIEW ────────────────────────────────────────────────────── */}
      {role === 'user' && userLocation && (
        <>
          {/* Home marker */}
          <Marker position={[userLocation.lat, userLocation.lng]} icon={homeIcon}>
            <Popup><b>🏠 Your Home</b></Popup>
          </Marker>

          {/* 3 km radius circle */}
          <Circle
            center={[userLocation.lat, userLocation.lng]}
            radius={RADIUS_KM * 1000}
            pathOptions={{
              color: '#2d7a2d', fillColor: '#4db84d',
              fillOpacity: 0.06, weight: 2, dashArray: '8 6'
            }}
          />

          {/* All active vehicles */}
          {Object.values(vehicles).filter(v => v.lat && v.isActive).map(v => {
            const dist = haversine(userLocation.lat, userLocation.lng, v.lat, v.lng);
            const isNear = dist <= RADIUS_KM;
            return (
              <React.Fragment key={v.driverId}>
                <Marker position={[v.lat, v.lng]} icon={truckIcon}>
                  <Popup>
                    <div style={{ minWidth: 180 }}>
                      <b>🚛 {v.vehicleNo}</b><br />
                      <span>Driver: {v.driverName}</span><br />
                      <span>Area: {v.currentArea}</span><br />
                      <span>ETA: {v.eta}</span><br />
                      <span style={{ color: isNear ? '#2d7a2d' : '#d97706', fontWeight: 700 }}>
                        {dist.toFixed(2)} km away {isNear ? '✅ Nearby!' : ''}
                      </span>
                    </div>
                  </Popup>
                </Marker>

                {/* Route line when within radius */}
                {isNear && routeCoords[v.driverId] && (
                  <Polyline
                    positions={routeCoords[v.driverId]}
                    pathOptions={{ color: '#2d7a2d', weight: 4, opacity: 0.85, dashArray: '12 4' }}
                  />
                )}
              </React.Fragment>
            );
          })}
        </>
      )}

      {/* ── DRIVER VIEW ──────────────────────────────────────────────────── */}
      {role === 'driver' && driverLocation && (
        <>
          <Marker position={[driverLocation.lat, driverLocation.lng]} icon={myLocIcon}>
            <Popup><b>📍 Your Current Location</b></Popup>
          </Marker>
          <MapCenter center={[driverLocation.lat, driverLocation.lng]} />
        </>
      )}
    </MapContainer>
  );
}
