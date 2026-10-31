import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';
import { EmptyState, Loading, ShipmentCard, StatCard } from '../components/ShipmentUI';
import { useShipmentRoom } from '../hooks/useLive';
import { FAILED_STATUSES, apiError, isActive, isTerminal } from '../lib/shipora';
import { Archive, CircleCheck, ClipboardList, Inbox, Package, Plus, Truck } from 'lucide-react';
import { Ic } from '../components/Icon';

const FILTERS = [
  { key: 'all',       label: 'All',       test: () => true },
  { key: 'active',    label: 'Active',    test: s => isActive(s.status) },
  { key: 'delivered', label: 'Delivered', test: s => s.status === 'DELIVERED' },
  { key: 'attention', label: 'Needs attention', test: s => FAILED_STATUSES.includes(s.status) },
  { key: 'closed',    label: 'Cancelled / Returned', test: s => ['CANCELLED', 'RETURN_TO_ORIGIN'].includes(s.status) },
];

// "My Shipments" (all) and "Delivery History" (completed) share one list; the route picks the starting filter.
export default function ShipmentHistory({ initialFilter = 'all' }) {
  const { API } = useAuth();
  const [shipments, setShipments] = useState(null);
  const [error, setError]   = useState('');
  const [filter, setFilter] = useState(initialFilter);
  const [query, setQuery]   = useState('');

  useEffect(() => { setFilter(initialFilter); }, [initialFilter]);

  const load = useCallback(() => {
    axios.get(`${API}/shipments`)
      .then(({ data }) => { setShipments(data); setError(''); })
      .catch(err => { setError(apiError(err, 'Failed to load shipments.')); setShipments(prev => prev || []); });
  }, [API]);
  useEffect(() => { load(); }, [load]);

  useShipmentRoom((shipments || []).filter(s => !isTerminal(s.status)).map(s => s.trackingNumber), load);

  const isHistory = initialFilter === 'history';
  const rows = useMemo(() => {
    const list = shipments || [];
    const base = isHistory ? list.filter(s => isTerminal(s.status)) : list.filter((FILTERS.find(f => f.key === filter) || FILTERS[0]).test);
    const q = query.trim().toLowerCase();
    return q ? base.filter(s => `${s.trackingNumber} ${s.recipient?.name} ${s.recipient?.address}`.toLowerCase().includes(q)) : base;
  }, [shipments, filter, query, isHistory]);

  if (!shipments) return <Loading text="Loading shipments…" />;

  const count = (k) => shipments.filter(FILTERS.find(f => f.key === k).test).length;

  return (
    <div className="page" style={{ maxWidth: 1000, margin: '0 auto' }}>
      <BackButton to="/dashboard" label="Dashboard" />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}>{isHistory ? <><Ic icon={Archive} size={22} /> Delivery History</> : <><Ic icon={ClipboardList} size={22} /> My Shipments</>}</h1>
          <p style={{ color: 'var(--muted)', fontSize: 14 }}>
            {isHistory ? 'Delivered, cancelled and returned shipments' : 'Every parcel you have sent, with live status'}
          </p>
        </div>
        <Link to="/shipments/new" className="btn btn-primary"><Ic icon={Plus} /> Create Shipment</Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="stats-grid" style={{ marginBottom: 20 }}>
        <StatCard icon={Package} value={shipments.length} label="Total Shipments" color="blue" />
        <StatCard icon={Truck} value={count('active')} label="Active" color="orange" />
        <StatCard icon={CircleCheck} value={count('delivered')} label="Delivered" color="green" />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
        {!isHistory && FILTERS.map(f => (
          <button key={f.key} type="button" onClick={() => setFilter(f.key)} style={{
            padding: '6px 14px', borderRadius: 20, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            border: filter === f.key ? '2px solid var(--brand-700)' : '2px solid var(--border)',
            background: filter === f.key ? 'var(--brand-50)' : '#fff',
            color: filter === f.key ? 'var(--brand-700)' : 'var(--muted)',
          }}>{f.label} ({count(f.key)})</button>
        ))}
        <input aria-label="Search shipments" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search tracking no. or receiver…"
          style={{ marginLeft: 'auto', flex: '0 1 260px', padding: '7px 12px', border: '1.5px solid var(--border)', borderRadius: 8, fontSize: 13 }} />
      </div>

      {rows.length === 0 ? (
        <div className="card">
          <EmptyState icon={Inbox} title={shipments.length === 0 ? 'No shipments yet' : 'No shipments match this view'}>
            {shipments.length === 0 && <Link to="/shipments/new" className="btn btn-primary" style={{ marginTop: 12 }}><Ic icon={Plus} /> Create your first shipment</Link>}
          </EmptyState>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 14 }}>
          {rows.map(s => <ShipmentCard key={s._id} shipment={s} />)}
        </div>
      )}
    </div>
  );
}
