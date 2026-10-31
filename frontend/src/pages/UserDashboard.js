import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import VehicleMap from '../components/VehicleMap';
import { EmptyState, Loading, ShipmentCard, StatCard } from '../components/ShipmentUI';
import { useShipmentRoom, useVehicleFeed } from '../hooks/useLive';
import { FAILED_STATUSES, haversine, isActive } from '../lib/shipora';
import { Archive, Circle, CircleCheck, ClipboardList, Clock, Map as MapIcon, MapPin, Megaphone, Package, Plus, Ruler, TriangleAlert, Truck, Zap } from 'lucide-react';
import { Ic } from '../components/Icon';

const RADIUS_KM = 3;

// Customer home: what is on its way, what needs attention, and where the delivery vehicles are.
export default function UserDashboard() {
  const { user, API } = useAuth();
  const navigate = useNavigate();
  const { vehicles, connected, lastUpdate } = useVehicleFeed();
  const [shipments, setShipments] = useState(null);
  const [error, setError]         = useState('');
  const [track, setTrack]         = useState('');

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/shipments`);
      setShipments(data); setError('');
    } catch {
      setError('Could not load your shipments.');
      setShipments(prev => prev || []);
    }
  }, [API]);

  useEffect(() => { load(); }, [load]);

  const active = useMemo(() => (shipments || []).filter(s => isActive(s.status)), [shipments]);
  // Live: any status change on an active shipment refreshes the list.
  useShipmentRoom(active.map(s => s.trackingNumber), load);

  const userLocation = user?.location;
  const liveVehicles = Object.values(vehicles).filter(v => v.isActive && v.lat);
  // Only vehicles actually carrying one of my shipments are "mine" — the rest is context on the map.
  const myAgentIds = new Set(active.map(s => s.assignedAgentId).filter(Boolean));
  const myVehicles = liveVehicles.filter(v => myAgentIds.has(v.driverId));

  const nearest = useMemo(() => {
    if (!userLocation) return null;
    return liveVehicles.reduce((best, v) => {
      const d = haversine(userLocation.lat, userLocation.lng, v.lat, v.lng);
      return !best || d < best.d ? { v, d } : best;
    }, null);
  }, [liveVehicles, userLocation]);

  if (!shipments) return <Loading text="Loading your shipments…" />;

  const outForDelivery = shipments.filter(s => s.status === 'OUT_FOR_DELIVERY');
  const delivered = shipments.filter(s => s.status === 'DELIVERED');
  const attention = shipments.filter(s => FAILED_STATUSES.includes(s.status));

  const goTrack = (e) => {
    e.preventDefault();
    const tn = track.trim().toUpperCase();
    if (tn) navigate(`/track/${tn}`);
  };

  return (
    <div className="page" style={{ maxWidth: 1280, margin: '0 auto' }}>
      <div className="hero" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <span className="chip" style={{ background: 'rgba(255,255,255,0.7)', marginBottom: 12 }}>
              <Ic icon={Zap} size={13} /> Same-day delivery · Bengaluru
            </span>
            <h1>Hey {(user?.name || '').split(' ')[0]}, what are we<br />delivering today?</h1>
            <p style={{ fontSize: 14, marginTop: 8 }}><Ic icon={MapPin} /> {user?.address || 'Address not set'}</p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', position: 'relative', zIndex: 1 }}>
            <span className={`badge ${connected ? 'badge-green' : 'badge-red'}`}>{connected ? <><Ic icon={Circle} size={10} fill="#22c55e" color="#22c55e" /> Live</> : <><Ic icon={Circle} size={10} fill="#ef4444" color="#ef4444" /> Offline</>}</span>
            {lastUpdate && <span style={{ fontSize: 12, color: 'rgba(20,32,26,0.7)' }}>Updated {lastUpdate.toLocaleTimeString()}</span>}
            <Link to="/shipments/new" className="btn btn-primary" style={{ padding: '14px 26px', fontSize: 16, borderRadius: 14, boxShadow: '0 4px 0 var(--brand-800)' }}><Ic icon={Plus} /> Send a parcel</Link>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="stats-grid" style={{ marginBottom: 20 }}>
        <StatCard icon={Package} value={active.length}         label="Active Shipments"  color="blue" />
        <StatCard icon={Truck} value={outForDelivery.length} label="Out for Delivery"  color="orange" />
        <StatCard icon={CircleCheck} value={delivered.length}      label="Delivered"         color="green" />
        <StatCard icon={TriangleAlert} value={attention.length}      label="Need Attention"    color={attention.length ? 'red' : 'gray'} />
      </div>

      <div className="split-layout">
        {/* ── Sidebar ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <form onSubmit={goTrack} className="card" style={{ padding: '14px 16px' }}>
            <div className="section-title">Track a Shipment</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input aria-label="Tracking number" value={track} onChange={e => setTrack(e.target.value.toUpperCase())} placeholder="SHP…"
                className="tracking-no" style={{ flex: 1, minWidth: 0, padding: '8px 10px', border: '1.5px solid var(--border)', borderRadius: 8 }} />
              <button className="btn btn-primary btn-sm" type="submit">Track</button>
            </div>
          </form>

          <div className="card" style={{ padding: '14px 16px' }}>
            <div className="section-title">Quick Actions</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <Link to="/shipments/new"     className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}><Ic icon={Package} /> Create Shipment</Link>
              <Link to="/shipments"         className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}><Ic icon={ClipboardList} /> My Shipments</Link>
              <Link to="/shipments/history" className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}><Ic icon={Archive} /> Delivery History</Link>
              <Link to="/issues"            className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}><Ic icon={Megaphone} /> Delivery Issues</Link>
            </div>
          </div>

          <div className="card" style={{ padding: '14px 16px' }}>
            <div className="section-title">Delivery Network</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                { icon: Truck, label: 'Vehicles on the road', value: liveVehicles.length },
                { icon: Package, label: 'Carrying my parcels', value: myVehicles.length },
                { icon: Ruler, label: 'Nearest vehicle', value: nearest ? `${nearest.d.toFixed(2)} km` : 'No vehicle' },
                { icon: Clock, label: 'Its ETA', value: nearest?.v.eta || '—' },
              ].map(s => (
                <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', background: 'var(--brand-50)', borderRadius: 8, border: '1px solid var(--border)' }}>
                  <span style={{ display: 'flex', color: 'var(--brand-700)' }}><Ic icon={s.icon} size={18} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>{s.label}</div>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{s.value}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Main ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
          {outForDelivery.length > 0 && (
            <div className="alert alert-info" style={{ marginBottom: 0, display: 'flex', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 22 }}><Ic icon={Truck} /></span>
              <span><strong>{outForDelivery.length === 1 ? 'A parcel is' : `${outForDelivery.length} parcels are`} out for delivery today.</strong>{' '}
                {outForDelivery.map(s => (
                  <Link key={s.trackingNumber} to={`/shipments/${s.trackingNumber}`} className="tracking-no" style={{ marginRight: 8 }}>{s.trackingNumber}</Link>
                ))}
              </span>
            </div>
          )}

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <h2 style={{ fontSize: 17, fontWeight: 800 }}>Active Deliveries</h2>
              <Link to="/shipments" style={{ fontSize: 13, color: 'var(--brand-700)', fontWeight: 600 }}>View all →</Link>
            </div>
            {active.length === 0 ? (
              <div className="card">
                <EmptyState icon={Package} title="No active shipments">
                  Send something — you will get a tracking number right away.
                  <div><Link to="/shipments/new" className="btn btn-primary" style={{ marginTop: 14 }}><Ic icon={Plus} /> Create Shipment</Link></div>
                </EmptyState>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
                {active.slice(0, 6).map(s => <ShipmentCard key={s._id} shipment={s} />)}
              </div>
            )}
          </div>

          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <h3 style={{ fontWeight: 700, fontSize: 15 }}><Ic icon={MapIcon} /> Live Delivery Vehicles</h3>
              <span style={{ fontSize: 12, color: 'var(--muted)' }}>{RADIUS_KM} km radius · route shows when a vehicle is nearby</span>
            </div>
            <div style={{ height: 440 }}>
              {userLocation ? (
                <VehicleMap userLocation={userLocation} vehicles={vehicles} role="user" RADIUS_KM={RADIUS_KM} />
              ) : (
                <EmptyState icon={MapPin} title="No saved address location">Update your profile to see nearby delivery vehicles.</EmptyState>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
