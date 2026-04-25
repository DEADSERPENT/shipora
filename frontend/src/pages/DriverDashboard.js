import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { io } from 'socket.io-client';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import VehicleMap from '../components/VehicleMap';

const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000';
const API        = process.env.REACT_APP_API_URL    || 'http://localhost:5000/api';

export default function DriverDashboard() {
  const { user } = useAuth();

  const [sharing,      setSharing]      = useState(false);
  const [driverLoc,    setDriverLoc]    = useState(null);
  const [connected,    setConnected]    = useState(false);
  const [gpsError,     setGpsError]     = useState('');
  const [currentArea,  setCurrentArea]  = useState(user?.assignedArea || '');
  const [eta,          setEta]          = useState('');
  const [areaInput,    setAreaInput]    = useState('');
  const [completed,    setCompleted]    = useState([]);
  const [saveMsg,      setSaveMsg]      = useState('');
  const [statusSaving, setStatusSaving] = useState(false);

  const socketRef  = useRef(null);
  const watchIdRef = useRef(null);

  // ── Socket connection ──────────────────────────────────────────────────────
  useEffect(() => {
    socketRef.current = io(SOCKET_URL, { transports: ['websocket', 'polling'] });
    socketRef.current.on('connect',    () => setConnected(true));
    socketRef.current.on('disconnect', () => setConnected(false));
    return () => {
      stopSharing();
      socketRef.current?.disconnect();
    };
  }, []); // eslint-disable-line

  // ── Broadcast location via socket ─────────────────────────────────────────
  const broadcastLocation = useCallback((lat, lng) => {
    if (!socketRef.current?.connected) return;
    socketRef.current.emit('driver:location', {
      driverId:       user.id,
      lat,
      lng,
      driverName:     user.name,
      vehicleNo:      user.vehicleNo,
      currentArea,
      eta,
      areasCompleted: completed,
    });
  }, [user, currentArea, eta, completed]);

  // ── Start GPS tracking ─────────────────────────────────────────────────────
  const startSharing = () => {
    setGpsError('');
    if (!navigator.geolocation) {
      setGpsError('Geolocation is not supported by your browser.');
      return;
    }
    watchIdRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        const { latitude: lat, longitude: lng } = pos.coords;
        setDriverLoc({ lat, lng });
        broadcastLocation(lat, lng);
      },
      (err) => {
        setGpsError(`GPS error: ${err.message}`);
        setSharing(false);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
    );
    setSharing(true);
  };

  // ── Stop GPS tracking ──────────────────────────────────────────────────────
  const stopSharing = useCallback(() => {
    if (watchIdRef.current !== null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    socketRef.current?.emit('driver:offline', user?.id);
    setSharing(false);
  }, [user]);

  // Re-broadcast when area/eta change while actively sharing
  useEffect(() => {
    if (sharing && driverLoc) {
      broadcastLocation(driverLoc.lat, driverLoc.lng);
    }
  }, [currentArea, eta, completed]); // eslint-disable-line

  // ── Save status to DB ──────────────────────────────────────────────────────
  const saveStatus = async () => {
    setStatusSaving(true);
    setSaveMsg('');
    try {
      await axios.post(`${API}/vehicles/status`, { currentArea, eta, areasCompleted: completed });
      setSaveMsg('Status saved!');
      setTimeout(() => setSaveMsg(''), 3000);
    } catch (err) {
      setSaveMsg(err.response?.data?.message || 'Save failed');
    } finally {
      setStatusSaving(false);
    }
  };

  // ── Add completed area ─────────────────────────────────────────────────────
  const addArea = async () => {
    const trimmed = areaInput.trim();
    if (!trimmed || completed.includes(trimmed)) return;
    const next = [...completed, trimmed];
    setCompleted(next);
    setAreaInput('');
    try {
      await axios.post(`${API}/vehicles/area-complete`, { area: trimmed });
    } catch { /* best effort */ }
  };

  const removeArea = (area) => setCompleted(prev => prev.filter(a => a !== area));

  return (
    <div className="page" style={{ maxWidth: 1280, margin: '0 auto' }}>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: '#1a3a1a', marginBottom: 4 }}>
            Driver Dashboard 🚛
          </h1>
          <p style={{ color: '#6b8f6b', fontSize: 14 }}>
            {user?.vehicleNo} · Assigned: {user?.assignedArea}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className={`badge ${connected ? 'badge-green' : 'badge-red'}`}>
            {connected ? '🟢 Server Connected' : '🔴 Disconnected'}
          </span>
          <span className={`badge ${sharing ? 'badge-green' : 'badge-amber'}`}>
            {sharing ? '📡 Sharing Location' : '⏸ Location Off'}
          </span>
        </div>
      </div>

      {/* ── Quick Actions ─────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <Link to="/driver-history" className="btn btn-ghost btn-sm">📋 Collection History</Link>
        <Link to="/support"        className="btn btn-ghost btn-sm">🎧 Support</Link>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: 20, alignItems: 'start' }}>
        {/* ── Left: Map ─────────────────────────────────────────────────── */}
        <div>
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #d1e7d1', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontWeight: 700, color: '#1a3a1a' }}>📍 Your Location</h3>
              {driverLoc && (
                <span style={{ fontSize: 12, color: '#6b8f6b' }}>
                  {driverLoc.lat.toFixed(5)}, {driverLoc.lng.toFixed(5)}
                </span>
              )}
            </div>
            <div style={{ height: 440 }}>
              {driverLoc ? (
                <VehicleMap
                  driverLocation={driverLoc}
                  vehicles={{}}
                  role="driver"
                />
              ) : (
                <div style={{
                  height: '100%', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', flexDirection: 'column',
                  gap: 12, color: '#9aab9a', padding: 32, textAlign: 'center'
                }}>
                  <span style={{ fontSize: 48 }}>📡</span>
                  <p style={{ fontWeight: 600 }}>Start sharing your location</p>
                  <p style={{ fontSize: 13 }}>
                    Click "Start Sharing" to broadcast your GPS position to residents in real time.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Right: Controls ───────────────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Location Sharing Toggle */}
          <div className="card">
            <h3 style={{ fontWeight: 700, marginBottom: 12, color: '#1a3a1a' }}>📡 Location Sharing</h3>
            {gpsError && <div className="alert alert-error" style={{ marginBottom: 12 }}>{gpsError}</div>}
            <button
              className={`btn btn-lg ${sharing ? 'btn-danger' : 'btn-primary'}`}
              onClick={sharing ? stopSharing : startSharing}
            >
              {sharing ? '⏹ Stop Sharing Location' : '▶ Start Sharing Location'}
            </button>
            {sharing && (
              <p style={{ fontSize: 12, color: '#2d7a2d', marginTop: 8, textAlign: 'center' }}>
                🟢 Broadcasting your position to all users live
              </p>
            )}
          </div>

          {/* Status Update */}
          <div className="card">
            <h3 style={{ fontWeight: 700, marginBottom: 14, color: '#1a3a1a' }}>📋 Update Status</h3>
            {saveMsg && (
              <div className={`alert ${saveMsg.includes('!') ? 'alert-success' : 'alert-error'}`}>
                {saveMsg}
              </div>
            )}
            <div className="form-group">
              <label>Current Area / Street</label>
              <input
                value={currentArea}
                onChange={e => setCurrentArea(e.target.value)}
                placeholder="e.g. MG Road, Sector 5"
              />
            </div>
            <div className="form-group">
              <label>Estimated Arrival Time</label>
              <input
                type="time"
                value={eta}
                onChange={e => setEta(e.target.value)}
              />
            </div>
            <button
              className="btn btn-primary"
              style={{ width: '100%' }}
              onClick={saveStatus}
              disabled={statusSaving}
            >
              {statusSaving ? 'Saving...' : '💾 Save Status'}
            </button>
          </div>

          {/* Completed Areas */}
          <div className="card">
            <h3 style={{ fontWeight: 700, marginBottom: 14, color: '#1a3a1a' }}>
              ✅ Areas Completed ({completed.length})
            </h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <input
                value={areaInput}
                onChange={e => setAreaInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addArea()}
                placeholder="e.g. Park Street"
                style={{ flex: 1 }}
              />
              <button className="btn btn-secondary btn-sm" onClick={addArea}>Add</button>
            </div>
            {completed.length === 0 ? (
              <p style={{ fontSize: 13, color: '#9aab9a', textAlign: 'center', padding: '12px 0' }}>
                No areas marked yet
              </p>
            ) : (
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                {completed.map((area, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '7px 10px', background: '#f0faf0', borderRadius: 6,
                    marginBottom: 6, border: '1px solid #c8e6c8'
                  }}>
                    <span style={{ fontSize: 13 }}>✓ {area}</span>
                    <button
                      onClick={() => removeArea(area)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: 16, lineHeight: 1 }}
                    >×</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Today's Summary */}
          <div className="card" style={{ background: '#1a3a1a', border: 'none' }}>
            <h3 style={{ fontWeight: 700, marginBottom: 12, color: '#86efac' }}>📊 Today's Summary</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {[
                { label: 'Areas Done',    value: completed.length,            icon: '✅' },
                { label: 'GPS Status',    value: sharing ? 'Active' : 'Off',  icon: '📡' },
                { label: 'Current Area',  value: currentArea || '—',          icon: '📍' },
                { label: 'Next ETA',      value: eta || '—',                  icon: '🕐' },
              ].map(item => (
                <div key={item.label} style={{ background: 'rgba(255,255,255,0.08)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 18, marginBottom: 4 }}>{item.icon}</div>
                  <div style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>{item.value}</div>
                  <div style={{ color: '#86efac', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{item.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
