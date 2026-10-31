import React, { useEffect, useState, useCallback } from 'react';
import {
  MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap
} from 'react-leaflet';
import L from 'leaflet';
import { renderToStaticMarkup } from 'react-dom/server';
import { haversine, BENGALURU } from '../lib/shipora';
import { ArrowDownToLine, ArrowUpFromLine, House, MapPin, Navigation, Truck } from 'lucide-react';
import { Ic } from './Icon';

// ── Custom markers: a lucide icon on a coloured disc, rendered to static SVG ─
const makeIcon = (Icon, color, size = 38) =>
  L.divIcon({
    className: '',
    html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center">${renderToStaticMarkup(<Icon size={Math.round(size * 0.52)} color="#fff" strokeWidth={2.2} />)}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
  });

const homeIcon     = makeIcon(House, '#0a5c16');
const vehicleMark  = makeIcon(Truck, '#f97316', 40);
const myLocIcon    = makeIcon(Navigation, '#0c831f');
const pickupIcon   = makeIcon(ArrowUpFromLine, '#0c831f');
const dropIcon     = makeIcon(ArrowDownToLine, '#15803d');

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

// Fit the viewport around a list of [lat,lng] points whenever the set changes.
function FitBounds({ points }) {
  const map = useMap();
  const key = points.map(p => p.join(',')).join('|');
  useEffect(() => {
    if (points.length > 1) map.fitBounds(points, { padding: [40, 40], maxZoom: 15 });
    else if (points.length === 1) map.setView(points[0], 14);
  }, [key, map]); // eslint-disable-line
  return null;
}

const activeVehicles = (vehicles) => Object.values(vehicles).filter(v => v.lat && v.lng && v.isActive);

function VehiclePopup({ v, extra }) {
  return (
    <div style={{ minWidth: 180 }}>
      <b><Ic icon={Truck} /> {v.vehicleNo}</b><br />
      <span>Agent: {v.driverName}</span><br />
      <span>Area: {v.currentArea}</span><br />
      <span>ETA: {v.eta}</span>
      {extra}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VehicleMap — delivery-vehicle map used across Shipora.
//
// `role` selects the view (wire-level role names, kept for compatibility):
//   'user'     – customer dashboard: customer's address + nearby delivery vehicles
//   'driver'   – delivery agent: their own GPS position
//   'admin'    – operations: the whole live delivery network
//   'shipment' – one shipment: pickup + destination + the assigned vehicle
//
// Props:
//   userLocation   – { lat, lng }  customer address ('user')
//   vehicles       – { [agentId]: vehicleData }  live feed (keyed by `driverId`)
//   driverLocation – { lat, lng }  agent GPS ('driver')
//   origin, destination – { lat, lng, label } ('shipment')
//   focusAgentId   – id of the assigned agent's vehicle ('shipment')
//   RADIUS_KM      – default 3
// ─────────────────────────────────────────────────────────────────────────────
export default function VehicleMap({
  userLocation,
  vehicles = {},
  driverLocation,
  role = 'user',
  RADIUS_KM = 3,
  origin,
  destination,
  focusAgentId,
}) {
  const [routeCoords, setRouteCoords] = useState({});  // { agentId: [[lat,lng]...] }

  const defaultCenter =
    userLocation     ? [userLocation.lat, userLocation.lng]
    : driverLocation ? [driverLocation.lat, driverLocation.lng]
    : destination    ? [destination.lat, destination.lng]
    : origin         ? [origin.lat, origin.lng]
    : BENGALURU.center;

  // ── Customer view: road route for vehicles within the radius ─────────────
  const processVehicles = useCallback(async () => {
    if (role !== 'user' || !userLocation) return;
    const newRoutes = {};
    for (const v of activeVehicles(vehicles)) {
      if (haversine(userLocation.lat, userLocation.lng, v.lat, v.lng) <= RADIUS_KM) {
        const route = await fetchOSRMRoute(v.lat, v.lng, userLocation.lat, userLocation.lng);
        if (route) newRoutes[v.driverId] = route;
      }
    }
    setRouteCoords(newRoutes);
  }, [vehicles, userLocation, role, RADIUS_KM]);

  useEffect(() => { processVehicles(); }, [processVehicles]);

  // ── Shipment view: route from the assigned vehicle to the destination ────
  const focus = role === 'shipment' && focusAgentId ? vehicles[focusAgentId] : null;
  const focusLive = focus && focus.isActive && focus.lat ? focus : null;
  const [shipRoute, setShipRoute] = useState(null);
  const fromKey = focusLive ? `${focusLive.lat.toFixed(3)},${focusLive.lng.toFixed(3)}` : '';
  useEffect(() => {
    let cancelled = false;
    if (focusLive && destination) {
      fetchOSRMRoute(focusLive.lat, focusLive.lng, destination.lat, destination.lng).then(r => { if (!cancelled) setShipRoute(r); });
    } else if (origin && destination) {
      fetchOSRMRoute(origin.lat, origin.lng, destination.lat, destination.lng).then(r => { if (!cancelled) setShipRoute(r); });
    } else {
      setShipRoute(null);
    }
    return () => { cancelled = true; };
  }, [fromKey, destination?.lat, destination?.lng, origin?.lat, origin?.lng]); // eslint-disable-line

  const shipmentPoints = [origin, destination, focusLive].filter(Boolean).map(p => [p.lat, p.lng]);

  return (
    <MapContainer
      center={defaultCenter}
      zoom={14}
      minZoom={11}
      maxBounds={BENGALURU.bounds}
      maxBoundsViscosity={1.0}
      style={{ height: '100%', width: '100%', minHeight: 320 }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='© <a href="https://www.openstreetmap.org">OpenStreetMap</a>'
      />

      {/* ── CUSTOMER VIEW ────────────────────────────────────────────────── */}
      {role === 'user' && userLocation && (
        <>
          <Marker position={[userLocation.lat, userLocation.lng]} icon={homeIcon}>
            <Popup><b><Ic icon={House} /> Your address</b></Popup>
          </Marker>
          <Circle
            center={[userLocation.lat, userLocation.lng]}
            radius={RADIUS_KM * 1000}
            pathOptions={{ color: '#0c831f', fillColor: '#2fb44a', fillOpacity: 0.06, weight: 2, dashArray: '8 6' }}
          />
          {activeVehicles(vehicles).map(v => {
            const dist = haversine(userLocation.lat, userLocation.lng, v.lat, v.lng);
            const isNear = dist <= RADIUS_KM;
            return (
              <React.Fragment key={v.driverId}>
                <Marker position={[v.lat, v.lng]} icon={vehicleMark}>
                  <Popup>
                    <VehiclePopup v={v} extra={<><br /><span style={{ color: isNear ? '#15803d' : '#d97706', fontWeight: 700 }}>
                      {dist.toFixed(2)} km away {isNear ? 'Nearby' : ''}
                    </span></>} />
                  </Popup>
                </Marker>
                {isNear && routeCoords[v.driverId] && (
                  <Polyline positions={routeCoords[v.driverId]} pathOptions={{ color: '#0c831f', weight: 4, opacity: 0.85, dashArray: '12 4' }} />
                )}
              </React.Fragment>
            );
          })}
        </>
      )}

      {/* ── DELIVERY AGENT VIEW ──────────────────────────────────────────── */}
      {role === 'driver' && driverLocation && (
        <>
          <Marker position={[driverLocation.lat, driverLocation.lng]} icon={myLocIcon}>
            <Popup><b><Ic icon={MapPin} /> Your current location</b></Popup>
          </Marker>
          <MapCenter center={[driverLocation.lat, driverLocation.lng]} />
        </>
      )}

      {/* ── OPERATIONS VIEW: whole network ───────────────────────────────── */}
      {role === 'admin' && (
        <>
          {activeVehicles(vehicles).map(v => (
            <Marker key={v.driverId} position={[v.lat, v.lng]} icon={vehicleMark}>
              <Popup><VehiclePopup v={v} extra={<><br /><span>Zones covered: {v.areasCompleted?.length || 0}</span></>} /></Popup>
            </Marker>
          ))}
          <FitBounds points={activeVehicles(vehicles).map(v => [v.lat, v.lng])} />
        </>
      )}

      {/* ── SINGLE SHIPMENT VIEW ─────────────────────────────────────────── */}
      {role === 'shipment' && (
        <>
          {origin && <Marker position={[origin.lat, origin.lng]} icon={pickupIcon}><Popup><b><Ic icon={ArrowUpFromLine} /> Pickup</b><br />{origin.label}</Popup></Marker>}
          {destination && <Marker position={[destination.lat, destination.lng]} icon={dropIcon}><Popup><b><Ic icon={ArrowDownToLine} /> Delivery</b><br />{destination.label}</Popup></Marker>}
          {focusLive && (
            <Marker position={[focusLive.lat, focusLive.lng]} icon={vehicleMark}>
              <Popup><VehiclePopup v={focusLive} /></Popup>
            </Marker>
          )}
          {shipRoute && <Polyline positions={shipRoute} pathOptions={{ color: focusLive ? '#f97316' : '#0c831f', weight: 4, opacity: 0.85, dashArray: focusLive ? '12 4' : undefined }} />}
          <FitBounds points={shipmentPoints} />
        </>
      )}
    </MapContainer>
  );
}
