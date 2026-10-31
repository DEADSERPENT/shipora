import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';
import { EmptyState, Loading, StatCard, StatusBadge } from '../components/ShipmentUI';
import { apiError, backendDateKey, fmtDateTime } from '../lib/shipora';
import { Calendar, ChartColumn, Check, Circle, CircleCheck, ClipboardList, Clock, MapPin, Package, Route } from 'lucide-react';
import { Ic } from '../components/Icon';

// Delivery agent's history: shipments they have finished + their daily tracking logs.
export default function AgentHistory() {
  const { API } = useAuth();
  const [logs, setLogs]           = useState(null);
  const [shipments, setShipments] = useState([]);
  const [error, setError]         = useState('');

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/vehicles/history?days=30`),
      axios.get(`${API}/shipments`),
    ])
      .then(([{ data: l }, { data: s }]) => { setLogs(l); setShipments(s); })
      .catch(err => { setError(apiError(err, 'Failed to load history.')); setLogs([]); });
  }, [API]);

  if (!logs) return <Loading text="Loading history…" />;

  const finished = shipments.filter(s => ['DELIVERED', 'CANCELLED', 'RETURN_TO_ORIGIN'].includes(s.status));
  const delivered = shipments.filter(s => s.status === 'DELIVERED');
  const todayStr = backendDateKey();
  const activeDays = logs.filter(l => (l.deliveredCount || 0) > 0 || l.areasCompleted?.length > 0).length;

  return (
    <div className="page" style={{ maxWidth: 900, margin: '0 auto' }}>
      <BackButton to="/driver" label="Deliveries" />

      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}><Ic icon={ClipboardList} /> Delivery History</h1>
        <p style={{ color: 'var(--muted)', fontSize: 14 }}>Your completed deliveries and daily route logs for the past 30 days</p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="stats-grid" style={{ marginBottom: 24 }}>
        <StatCard icon={CircleCheck} value={delivered.length} label="Parcels Delivered" color="green" />
        <StatCard icon={Calendar} value={activeDays}       label="Active Days"       color="blue" />
        <StatCard icon={ChartColumn} value={logs.length}      label="Daily Logs"        color="orange" />
      </div>

      <h2 style={{ fontSize: 17, fontWeight: 800, marginBottom: 10 }}>Completed Shipments</h2>
      <div className="card" style={{ marginBottom: 28, padding: 0 }}>
        {finished.length === 0 ? (
          <EmptyState icon={Package} title="No completed shipments yet">Delivered parcels will be listed here.</EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead><tr><th>Tracking</th><th>Receiver</th><th>Address</th><th>Status</th><th>Completed</th></tr></thead>
              <tbody>
                {finished.map(s => (
                  <tr key={s._id}>
                    <td><Link to={`/shipments/${s.trackingNumber}`} className="tracking-no">{s.trackingNumber}</Link></td>
                    <td>{s.recipient.name}</td>
                    <td style={{ maxWidth: 260, fontSize: 13, color: 'var(--muted)' }}>{s.recipient.address}</td>
                    <td><StatusBadge status={s.status} /></td>
                    <td style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{fmtDateTime(s.deliveredAt || s.updatedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <h2 style={{ fontSize: 17, fontWeight: 800, marginBottom: 10 }}>Daily Route Logs</h2>
      {logs.length === 0 ? (
        <div className="card"><EmptyState icon={Route} title="No route logs in the past 30 days">Logs are created when you share your location or update your vehicle status.</EmptyState></div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {logs.map(log => {
            const isToday = log.date === todayStr;
            return (
              <div key={log._id} className="card" style={{ padding: '18px 22px', borderLeft: `4px solid ${isToday ? '#0c831f' : '#cbd5e1'}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15 }}><Ic icon={Calendar} /> {isToday ? 'Today' : log.date}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>Last updated: {log.lastUpdated ? new Date(log.lastUpdated).toLocaleTimeString() : '—'}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span className={`badge ${log.isActive ? 'badge-green' : 'badge-blue'}`}>{log.isActive ? <><Ic icon={Circle} size={9} fill="currentColor" /> Active</> : <><Ic icon={Check} size={13} /> Completed</>}</span>
                    <span className="badge badge-green">{log.deliveredCount || 0} delivered</span>
                    <span className="badge badge-blue">{log.areasCompleted?.length || 0} areas</span>
                  </div>
                </div>
                {log.areasCompleted?.length > 0 && (
                  <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {log.areasCompleted.map((a, i) => <span key={i} className="badge badge-blue" style={{ fontSize: 12 }}><Ic icon={Check} size={12} /> {a}</span>)}
                  </div>
                )}
                {(log.currentArea || log.eta) && (
                  <div style={{ marginTop: 10, fontSize: 13, color: 'var(--muted)', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    {log.currentArea && <span><Ic icon={MapPin} /> Area: <strong>{log.currentArea}</strong></span>}
                    {log.eta && <span><Ic icon={Clock} /> ETA: <strong>{log.eta}</strong></span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
