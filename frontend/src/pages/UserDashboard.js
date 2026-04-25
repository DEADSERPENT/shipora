import React, { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { io } from 'socket.io-client';
import { useAuth } from '../context/AuthContext';
import VehicleMap from '../components/VehicleMap';

const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000';
const RADIUS_KM  = 3;

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

function scheduleLabel(s) {
  return { daily: 'Every Day', alternate: 'Alternate Days', weekly: 'Weekly' }[s] || s;
}
function wasteLabel(w) {
  return { mixed: '🗑️ Mixed', household: '🏠 Household', recyclable: '♻️ Recyclable', organic: '🌿 Organic' }[w] || w;
}

export default function UserDashboard() {
  const { user } = useAuth();
  const [vehicles,    setVehicles]    = useState({});
  const [connected,   setConnected]   = useState(false);
  const [lastUpdate,  setLastUpdate]  = useState(null);

  const userLocation = user?.location;

  // ── Socket connection ──────────────────────────────────────────────────────
  useEffect(() => {
    const socket = io(SOCKET_URL, { transports: ['websocket', 'polling'] });

    socket.on('connect', () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));

    const handleUpdate = (data) => {
      setVehicles(data);
      setLastUpdate(new Date());
    };
    socket.on('vehicles:initial', handleUpdate);
    socket.on('vehicles:update',  handleUpdate);

    return () => socket.disconnect();
  }, []);

  // ── Nearest active vehicle ─────────────────────────────────────────────────
  const nearestVehicle = useCallback(() => {
    if (!userLocation) return null;
    const active = Object.values(vehicles).filter(v => v.isActive && v.lat);
    if (!active.length) return null;
    return active.reduce((closest, v) => {
      const d = haversine(userLocation.lat, userLocation.lng, v.lat, v.lng);
      const cd = closest
        ? haversine(userLocation.lat, userLocation.lng, closest.lat, closest.lng)
        : Infinity;
      return d < cd ? v : closest;
    }, null);
  }, [vehicles, userLocation]);

  const nearest = nearestVehicle();
  const nearestDist = nearest && userLocation
    ? haversine(userLocation.lat, userLocation.lng, nearest.lat, nearest.lng)
    : null;
  const isNearby = nearestDist !== null && nearestDist <= RADIUS_KM;

  const activeCount = Object.values(vehicles).filter(v => v.isActive).length;

  return (
    <div className="page" style={{ maxWidth: 1280, margin: '0 auto' }}>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: '#1a3a1a', marginBottom: 4 }}>
            Welcome back, {user?.name} 👋
          </h1>
          <p style={{ color: '#6b8f6b', fontSize: 14 }}>
            📍 {user?.address || 'Address not set'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={`badge ${connected ? 'badge-green' : 'badge-red'}`}>
            {connected ? '🟢 Live' : '🔴 Offline'}
          </span>
          {lastUpdate && (
            <span style={{ fontSize: 12, color: '#9aab9a' }}>
              Updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* ── Main Layout: sidebar + map ─────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 20, alignItems: 'start' }}>

        {/* ── Left Sidebar ──────────────────────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* Quick Actions */}
          <div className="card" style={{ padding: '14px 16px' }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: '#1a3a1a', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Quick Actions
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <Link to="/collection-log" className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}>🗓️ Collection Log</Link>
              <Link to="/complaints"     className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}>📣 Complaints</Link>
            </div>
          </div>

          {/* Stats */}
          <div className="card" style={{ padding: '14px 16px' }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: '#1a3a1a', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Live Stats
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                { icon: '🚛', label: 'Active Vehicles',      value: activeCount },
                { icon: isNearby ? '✅' : '⏳', label: 'Nearest Vehicle',
                  value: nearestDist !== null ? `${nearestDist.toFixed(2)} km` : 'No vehicle',
                  valueColor: nearestDist !== null ? (isNearby ? '#2d7a2d' : '#d97706') : undefined },
                { icon: '🕐', label: 'Estimated Arrival',    value: nearest?.eta || '—' },
                { icon: '📍', label: "Vehicle's Area",       value: nearest?.currentArea || '—' },
                { icon: '📅', label: 'Your Schedule',        value: scheduleLabel(user?.pickupSchedule) },
                { icon: '♻️', label: 'Waste Type',           value: wasteLabel(user?.wasteType) },
              ].map(s => (
                <div key={s.label} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 10px', background: '#f8fdf8', borderRadius: 8,
                  border: '1px solid #d1e7d1'
                }}>
                  <span style={{ fontSize: 18, flexShrink: 0 }}>{s.icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: '#6b8f6b', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>{s.label}</div>
                    <div style={{ fontWeight: 700, fontSize: 13, color: s.valueColor || '#1a3a1a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.value}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Active Vehicles */}
          <div className="card" style={{ padding: '14px 16px' }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: '#1a3a1a', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              🚛 Active Vehicles ({activeCount})
            </div>
            {activeCount === 0 ? (
              <div style={{ textAlign: 'center', padding: '16px 0', color: '#9aab9a' }}>
                <div style={{ fontSize: 28, marginBottom: 4 }}>🌙</div>
                <p style={{ fontSize: 13 }}>No active vehicles</p>
              </div>
            ) : (
              Object.values(vehicles).filter(v => v.isActive).map(v => {
                const dist = userLocation
                  ? haversine(userLocation.lat, userLocation.lng, v.lat, v.lng)
                  : null;
                return (
                  <div key={v.driverId} style={{
                    padding: '9px 10px', border: '1px solid #d1e7d1', borderRadius: 8,
                    marginBottom: 8, background: dist !== null && dist <= RADIUS_KM ? '#f0faf0' : '#fff'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, fontSize: 13 }}>{v.vehicleNo}</span>
                      {dist !== null && (
                        <span className={`badge ${dist <= RADIUS_KM ? 'badge-green' : 'badge-amber'}`} style={{ fontSize: 11 }}>
                          {dist.toFixed(2)} km
                        </span>
                      )}
                    </div>
                    <p style={{ fontSize: 12, color: '#6b8f6b', margin: '2px 0 0' }}>{v.driverName} · {v.currentArea}</p>
                  </div>
                );
              })
            )}
          </div>

          {/* Areas Covered */}
          <div className="card" style={{ padding: '14px 16px' }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: '#1a3a1a', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              ✅ Areas Covered Today
            </div>
            {nearest?.areasCompleted?.length ? (
              <div>
                <p style={{ fontSize: 12, color: '#6b8f6b', marginBottom: 8 }}>
                  By {nearest.driverName}
                </p>
                {nearest.areasCompleted.map((area, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 8px', background: '#f0faf0', borderRadius: 5,
                    marginBottom: 5, border: '1px solid #c8e6c8'
                  }}>
                    <span style={{ color: '#2d7a2d', fontWeight: 700, fontSize: 13 }}>✓</span>
                    <span style={{ fontSize: 13 }}>{area}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '12px 0', color: '#9aab9a' }}>
                <div style={{ fontSize: 24, marginBottom: 4 }}>🗺️</div>
                <p style={{ fontSize: 13 }}>No areas covered yet</p>
              </div>
            )}
          </div>
        </div>

        {/* ── Right: Map ────────────────────────────────────────────────────── */}
        <div>
          {/* Proximity Alert */}
          {isNearby && nearest && (
            <div className="alert alert-success" style={{ marginBottom: 12, fontSize: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 20 }}>🚛</span>
              <span>
                <strong>Vehicle nearby!</strong> {nearest.driverName}'s truck ({nearest.vehicleNo}) is{' '}
                <strong>{nearestDist.toFixed(2)} km</strong> away. ETA: <strong>{nearest.eta || 'arriving soon'}</strong>.
              </span>
            </div>
          )}

          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid #d1e7d1', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontWeight: 700, color: '#1a3a1a', fontSize: 15 }}>🗺️ Live Vehicle Tracking</h3>
              <span style={{ fontSize: 12, color: '#6b8f6b' }}>
                3 km radius · Route appears when vehicle is nearby
              </span>
            </div>
            <div style={{ height: 520 }}>
              {userLocation ? (
                <VehicleMap
                  userLocation={userLocation}
                  vehicles={vehicles}
                  role="user"
                  RADIUS_KM={RADIUS_KM}
                />
              ) : (
                <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9aab9a', flexDirection: 'column', gap: 8 }}>
                  <span style={{ fontSize: 40 }}>📍</span>
                  <p>No home location set. Please update your profile.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
