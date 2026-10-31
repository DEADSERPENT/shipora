import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { io } from 'socket.io-client';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import RiderNavigator from '../components/RiderNavigator';
import { MAX_ACCURACY_M, isPrecise } from '../lib/navigation';
import { EmptyState, Loading, ShipmentCard, StatCard, StatusActions } from '../components/ShipmentUI';
import { useShipmentRoom } from '../hooks/useLive';
import { GPS_HEARTBEAT_MS, SOCKET_URL, apiError, backendDateKey, socketOptions, isActive, statusMeta, vehicleIcon } from '../lib/shipora';
import { ChartColumn, Check, Circle, CircleCheck, ClipboardList, Clock, Headset, Hourglass, Map as MapIcon, MapPin, Package, Pause, Radio, Route, Truck, Van } from 'lucide-react';
import { Ic } from '../components/Icon';

// Delivery-agent console. The page/route/socket names keep their wire-level "driver"
// spelling (`driver:location`, `/driver`); everything the agent sees says Delivery Agent.
export default function DriverDashboard() {
  const { user, API } = useAuth();

  const [shipments, setShipments] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [busyId,    setBusyId]    = useState(null);
  const [actionMsg, setActionMsg] = useState({ type: '', text: '' });
  const [deliveredToday, setDeliveredToday] = useState(0);

  const [mode,         setMode]         = useState('off');   // 'off' | 'gps' | 'demo'
  const sharing = mode !== 'off';
  const [agentLoc,     setAgentLoc]     = useState(null);
  const [gpsNote,      setGpsNote]      = useState('');
  const [connected,    setConnected]    = useState(false);
  const [gpsError,     setGpsError]     = useState('');
  const [currentArea,  setCurrentArea]  = useState(user?.assignedArea || '');
  const [eta,          setEta]          = useState('');
  const [live,         setLive]         = useState({});      // distance / minutes / target from the navigator
  const [areaInput,    setAreaInput]    = useState('');
  const [completed,    setCompleted]    = useState([]);

  const socketRef  = useRef(null);
  const watchIdRef = useRef(null);
  const lastLocRef  = useRef(null);       // last GPS fix, for heartbeats and re-sending after a reconnect
  const sharingRef  = useRef(false);
  const broadcastRef = useRef(() => {});  // always points at the latest broadcastLocation closure

  // ── Assigned shipments + today's delivered count ──────────────────────────
  const loadShipments = useCallback(async () => {
    try {
      const [{ data: list }, { data: logs }] = await Promise.all([
        axios.get(`${API}/shipments`),
        axios.get(`${API}/vehicles/history?days=1`),
      ]);
      setShipments(list);
      setDeliveredToday(logs.find(l => l.date === backendDateKey())?.deliveredCount || 0);
      setLoadError('');
    } catch (err) {
      setLoadError(apiError(err, 'Could not load your assigned shipments.'));
      setShipments(prev => prev || []);
    }
  }, [API]);
  useEffect(() => { loadShipments(); }, [loadShipments]);

  const active = useMemo(() => (shipments || []).filter(s => isActive(s.status)), [shipments]);
  useShipmentRoom(active.map(s => s.trackingNumber), loadShipments);

  const changeStatus = async (shipment, status, note) => {
    setBusyId(shipment._id); setActionMsg({ type: '', text: '' });
    try {
      await axios.post(`${API}/shipments/${shipment._id}/status`, { status, note: note || '' });
      setActionMsg({ type: 'success', text: `${shipment.trackingNumber} → ${statusMeta(status).label}` });
      await loadShipments();
    } catch (err) {
      setActionMsg({ type: 'error', text: apiError(err, 'Status update failed.') });
    } finally { setBusyId(null); }
  };

  // ── Socket connection ──────────────────────────────────────────────────────
  useEffect(() => {
    socketRef.current = io(SOCKET_URL, socketOptions());   // authenticated with the JWT; the server rejects positions from anyone else
    socketRef.current.on('connect', () => {
      setConnected(true);
      // After a dropped connection the server has marked this vehicle offline — report again right away
      // instead of waiting for the next GPS movement.
      const last = lastLocRef.current;
      if (sharingRef.current && last) broadcastRef.current(last.lat, last.lng);
    });
    socketRef.current.on('disconnect', () => setConnected(false));
    return () => {
      stopSharing();
      socketRef.current?.disconnect();
    };
  }, []); // eslint-disable-line

  // ── Broadcast location via socket (wire event: driver:location) ───────────
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
      etaMinutes:     live.etaMinutes,
      distanceKm:     live.distanceKm,
      target:         live.target,
      areasCompleted: completed,
    });
  }, [user, currentArea, eta, completed, live]);
  broadcastRef.current = broadcastLocation;
  sharingRef.current = sharing;

  // Heartbeat: a parked vehicle produces no GPS movement, but must not turn "stale".
  useEffect(() => {
    if (!sharing) return undefined;
    const timer = setInterval(() => {
      const last = lastLocRef.current;
      if (last) broadcastRef.current(last.lat, last.lng);
    }, GPS_HEARTBEAT_MS);
    return () => clearInterval(timer);
  }, [sharing]);

  // One entry point for every position, real or demo. A fix that is not precise enough to be GPS (a desktop's Wi-Fi/IP
  // guess is typically 1-50 km off) is never used to steer or shown to customers.
  const ingestFix = useCallback(({ lat, lng, accuracy }) => {
    if (!isPrecise(accuracy)) {
      setGpsNote(`Your device only knows your location to about ${accuracy >= 1000 ? `${(accuracy / 1000).toFixed(1)} km` : `${Math.round(accuracy)} m`} — that is a Wi-Fi/IP estimate, not GPS (needs under ${MAX_ACCURACY_M} m). Open Shipora on your phone with Location set to High accuracy.`);
      return;
    }
    setGpsNote('');
    setAgentLoc({ lat, lng });
    lastLocRef.current = { lat, lng };
    broadcastRef.current(lat, lng);
  }, []);

  const startGps = () => {
    setGpsError('');
    if (!navigator.geolocation) {
      setGpsError('Geolocation is not supported by your browser.');
      return;
    }
    watchIdRef.current = navigator.geolocation.watchPosition(
      (pos) => ingestFix({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy }),
      (err) => {
        setGpsError(`GPS error: ${err.message}`);
        setMode('off');
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 }   // maximumAge 0: never a cached/old position
    );
    setMode('gps');
  };

  const stopSharing = useCallback(() => {
    if (watchIdRef.current !== null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    socketRef.current?.emit('driver:offline', user?.id);
    setMode('off');
    setAgentLoc(null);
    lastLocRef.current = null;
    setGpsNote('');
  }, [user]);

  useEffect(() => {
    if (sharing && agentLoc) broadcastLocation(agentLoc.lat, agentLoc.lng);
  }, [currentArea, eta, completed]); // eslint-disable-line

  // Street name and arrival time come from the navigator (GPS + road route), not from typing.
  const onTelemetry = useCallback((t) => {
    if (t.currentArea !== undefined) setCurrentArea(t.currentArea || user?.assignedArea || '');
    setEta(t.eta || '');
    setLive({ etaMinutes: t.etaMinutes, distanceKm: t.distanceKm, target: t.target });
  }, [user]);

  const addArea = async () => {
    const trimmed = areaInput.trim();
    if (!trimmed || completed.includes(trimmed)) return;
    setCompleted([...completed, trimmed]);
    setAreaInput('');
    try { await axios.post(`${API}/vehicles/area-complete`, { area: trimmed }); } catch { /* best effort */ }
  };
  const removeArea = (area) => setCompleted(prev => prev.filter(a => a !== area));

  if (!shipments) return <Loading text="Loading your deliveries…" />;

  const outNow   = active.filter(s => s.status === 'OUT_FOR_DELIVERY');
  const pickups  = active.filter(s => ['PICKUP_SCHEDULED'].includes(s.status));
  const inFlight = active.filter(s => !['OUT_FOR_DELIVERY', 'PICKUP_SCHEDULED'].includes(s.status));
  const pending  = active.length - outNow.length;
  const ordered  = [...outNow, ...pickups, ...inFlight];

  return (
    <div className="page" style={{ maxWidth: 1280, margin: '0 auto' }}>
      <div className="hero-dark" style={{ marginBottom: 20 }}>
        <div className="hero-dark-row">
          <div>
            <span className="chip chip-yellow"><Ic icon={vehicleIcon(user?.vehicleType)} size={13} /> {user?.vehicleNo} · {user?.assignedArea}</span>
            <h1>Hey {(user?.name || '').split(' ')[0]}, ready to ride?</h1>
            <p>{active.length === 0 ? 'No parcels assigned right now.' : `${active.length} parcel${active.length === 1 ? '' : 's'} on your list today.`}</p>
          </div>
          <div className="hero-dark-side">
            <div className="hero-dark-chips">
              <span className={`badge ${connected ? 'badge-green' : 'badge-red'}`}>{connected ? <><Ic icon={Circle} size={10} fill="#22c55e" color="#22c55e" /> Server Connected</> : <><Ic icon={Circle} size={10} fill="#ef4444" color="#ef4444" /> Disconnected</>}</span>
              <span className={`badge ${sharing ? 'badge-green' : 'badge-amber'}`}>{sharing ? <><Ic icon={Radio} /> {mode === 'demo' ? 'Simulated Trip Live' : 'Sharing Location'}</> : <><Ic icon={Pause} /> Trip Not Started</>}</span>
            </div>
            <div className="hero-dark-actions">
              <Link to="/agent/history" className="btn btn-light btn-sm"><Ic icon={ClipboardList} /> Delivery History</Link>
              <Link to="/support"       className="btn btn-light btn-sm"><Ic icon={Headset} /> Support</Link>
            </div>
          </div>
        </div>
      </div>

      <div className="stats-grid" style={{ marginBottom: 20 }}>
        <StatCard icon={Package} value={active.length}  label="Assigned Shipments"   color="blue" />
        <StatCard icon={Truck} value={outNow.length}  label="Out for Delivery"     color="orange" />
        <StatCard icon={Hourglass} value={pending}        label="Pending"              color="gray" />
        <StatCard icon={CircleCheck} value={deliveredToday} label="Completed Today"      color="green" />
      </div>

      {loadError && <div className="alert alert-error">{loadError}</div>}
      {gpsError && <div className="alert alert-error">{gpsError}</div>}
      {actionMsg.text && <div className={`alert alert-${actionMsg.type}`}>{actionMsg.text}</div>}

      <div style={{ marginBottom: 20 }}>
        <RiderNavigator
          shipments={active}
          position={agentLoc}
          mode={mode}
          gpsNote={gpsNote}
          onStartGps={startGps}
          onStartDemo={() => setMode('demo')}
          onStop={stopSharing}
          onFix={ingestFix}
          onTelemetry={onTelemetry}
          renderActions={(s) => <StatusActions shipment={s} busy={busyId === s._id} onChange={(st, note) => changeStatus(s, st, note)} />}
        />
      </div>

      <div className="split-layout-r">
        {/* ── Left: shipments ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>

          <div>
            <h2 style={{ fontSize: 17, fontWeight: 800, marginBottom: 10 }}>All Assigned Shipments</h2>
            {ordered.length === 0 ? (
              <div className="card"><EmptyState icon={Route} title="Nothing assigned right now">New shipments appear here as soon as operations assigns them to you.</EmptyState></div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {ordered.map(s => (
                  <ShipmentCard key={s._id} shipment={s} perspective="agent">
                    <StatusActions shipment={s} busy={busyId === s._id} onChange={(st, note) => changeStatus(s, st, note)} />
                  </ShipmentCard>
                ))}
              </div>
            )}
          </div>

        </div>

        {/* ── Right: controls ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
          <div className="card">
            <h3 style={{ fontWeight: 700, marginBottom: 12 }}><Ic icon={Van} /> Live Vehicle Status</h3>
            <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 12 }}>Filled in automatically from your route — nothing to type.</p>
            {[
              { label: 'Current street', value: currentArea || '—', icon: MapPin },
              { label: 'Arrival at next stop', value: eta || '—', icon: Clock },
              { label: 'Distance left', value: live.distanceKm != null ? `${live.distanceKm} km` : '—', icon: Route },
              { label: 'Tracking', value: mode === 'demo' ? 'Simulated drive' : mode === 'gps' ? 'Device GPS' : 'Off', icon: Radio },
            ].map(r => (
              <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '9px 0', borderBottom: '1px dashed var(--border)', fontSize: 13.5 }}>
                <span style={{ color: 'var(--muted)', fontWeight: 600 }}><Ic icon={r.icon} size={14} /> {r.label}</span>
                <strong style={{ textAlign: 'right' }}>{r.value}</strong>
              </div>
            ))}
          </div>

          <div className="card">
            <h3 style={{ fontWeight: 700, marginBottom: 14 }}><Ic icon={MapIcon} /> Areas Covered ({completed.length})</h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <input value={areaInput} onChange={e => setAreaInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && addArea()}
                placeholder="e.g. Park Street" style={{ flex: 1, minWidth: 0 }} />
              <button className="btn btn-secondary btn-sm" onClick={addArea}>Add</button>
            </div>
            {completed.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--muted)', textAlign: 'center', padding: '12px 0' }}>No areas marked yet</p>
            ) : (
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                {completed.map((area, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 10px', background: 'var(--brand-50)', borderRadius: 6, marginBottom: 6, border: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 13 }}><Ic icon={Check} size={13} /> {area}</span>
                    <button onClick={() => removeArea(area)} aria-label={`Remove ${area}`} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: 16, lineHeight: 1 }}>×</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ background: 'var(--brand-900)', border: 'none' }}>
            <h3 style={{ fontWeight: 700, marginBottom: 12, color: '#f8cb46' }}><Ic icon={ChartColumn} /> Today's Summary</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {[
                { label: 'Delivered',    value: deliveredToday,             icon: CircleCheck },
                { label: 'Trip',         value: sharing ? 'Live' : 'Off',   icon: Radio },
                { label: 'Current Area', value: currentArea || '—',         icon: MapPin },
                { label: 'Next ETA',     value: eta || '—',                 icon: Clock },
              ].map(item => (
                <div key={item.label} style={{ background: 'rgba(255,255,255,0.08)', borderRadius: 8, padding: '10px 12px', minWidth: 0 }}>
                  <div style={{ marginBottom: 4, color: '#f8cb46' }}><Ic icon={item.icon} size={18} /></div>
                  <div style={{ color: '#fff', fontWeight: 700, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.value}</div>
                  <div style={{ color: '#f8cb46', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{item.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
