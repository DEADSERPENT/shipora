import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowDownToLine, ArrowUpFromLine, Timer, Truck } from 'lucide-react';
import { Ic } from './Icon';
import { fmtINR } from '../lib/estimate';
import { ParcelIllustration } from './Illustrations';
import {
  HAPPY_PATH, statusMeta, progressOf, isDelayed, serviceLabel, parcelLabel, fmtDateTime,
} from '../lib/shipora';

export function StatusBadge({ status }) {
  const m = statusMeta(status);
  return <span className={`pill pill-${m.tone}`}><Ic icon={m.icon} size={13} /> {m.label}</span>;
}

export function ProgressBar({ shipment }) {
  const pct = progressOf(shipment);
  return (
    <div className={`progress ${shipment.status === 'DELIVERED' ? 'done' : ''}`} role="progressbar"
      aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

// Compact card used in every shipment list (customer, agent, admin).
export function ShipmentCard({ shipment: s, perspective = 'customer', children }) {
  const delayed = isDelayed(s);
  return (
    <div className="shipment-card" style={{ position: 'relative' }}>
      <Link to={`/shipments/${s.trackingNumber}`} style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          <div>
            <div className="tracking-no" style={{ fontSize: 15 }}>{s.trackingNumber}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
              {serviceLabel(s.serviceType)} · {parcelLabel(s.parcel?.category)} · {s.parcel?.weightKg} kg
              {perspective === 'admin' && s.customerName ? ` · ${s.customerName}` : ''}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {delayed && <span className="pill pill-red"><Ic icon={Timer} /> Delayed</span>}
            <StatusBadge status={s.status} />
          </div>
        </div>
        <div className="route-line" style={{ marginBottom: 4 }}>
          <span title={s.sender?.address}><Ic icon={ArrowUpFromLine} /> {s.sender?.address}</span>
        </div>
        <div className="route-line" style={{ marginBottom: 12 }}>
          <span title={s.recipient?.address}><Ic icon={ArrowDownToLine} /> {s.recipient?.name} — {s.recipient?.address}</span>
        </div>
        <ProgressBar shipment={s} />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--muted)', marginTop: 8, gap: 8, flexWrap: 'wrap' }}>
          <span>{s.status === 'DELIVERED' ? `Delivered ${fmtDateTime(s.deliveredAt)}` : `Est. delivery ${fmtDateTime(s.estimatedDelivery)}`}</span>
          {s.fare > 0 && <span style={{ fontWeight: 700, color: 'var(--ink)' }}>{fmtINR(s.fare)}</span>}
          {s.assignedAgent && perspective !== 'agent' && <span><Ic icon={Truck} /> {s.assignedAgent.name}</span>}
        </div>
      </Link>
      {children}
    </div>
  );
}

// Vertical tracking timeline. Accepts either a full shipment (statusHistory with `at`)
// or the public view (`timeline`). Future happy-path steps are shown as pending.
export function ShipmentTimeline({ events = [], currentStatus }) {
  const seen = new Set(events.map(e => e.status));
  const terminalOrException = statusMeta(currentStatus).step === null;
  const pending = terminalOrException ? [] : HAPPY_PATH.filter(st => !seen.has(st));
  return (
    <ul className="timeline">
      {[...events].reverse().map((e, i) => {
        const m = statusMeta(e.status);
        const bad = m.tone === 'red';
        return (
          <li key={`${e.status}-${e.at}-${i}`} className={`${i === 0 ? 'current' : ''} ${bad ? 'bad' : ''}`}>
            <span className="dot"><Ic icon={m.icon} size={13} /></span>
            <div className="t-title">{m.label}</div>
            <div className="t-meta">{fmtDateTime(e.at)}{e.note && e.note !== 'seed' ? ` · ${e.note}` : ''}</div>
          </li>
        );
      })}
      {pending.map(st => {
        const m = statusMeta(st);
        return (
          <li key={st} className="pending">
            <span className="dot"><Ic icon={m.icon} size={13} /></span>
            <div className="t-title">{m.label}</div>
          </li>
        );
      })}
    </ul>
  );
}

// Action buttons for moving a shipment forward. `allowed` comes from the backend
// (`allowedNextStatuses`, already filtered for the signed-in role), so the lifecycle
// rules live in exactly one place. The next happy-path step is the primary button;
// exceptions go into a "Report problem" menu.
export function StatusActions({ shipment, onChange, busy }) {
  const allowed = shipment.allowedNextStatuses || [];
  const [note, setNote] = React.useState('');
  if (!allowed.length) return null;
  // Primary = the earliest happy-path step the backend allows (e.g. OUT_FOR_DELIVERY -> DELIVERED).
  const primary = allowed.filter(st => statusMeta(st).step !== null)
    .sort((x, y) => statusMeta(x).step - statusMeta(y).step)[0];
  const others = allowed.filter(st => st !== primary);
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}
      onClick={e => e.stopPropagation()}>
      {primary && (
        <button type="button" className="btn btn-primary btn-sm" disabled={busy}
          onClick={() => onChange(primary, note)}>
          <Ic icon={statusMeta(primary).icon} /> Mark {statusMeta(primary).label}
        </button>
      )}
      {others.length > 0 && (
        <select aria-label="Other status" disabled={busy} value=""
          onChange={e => e.target.value && onChange(e.target.value, note)}
          style={{ padding: '6px 10px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 13, background: '#fff' }}>
          <option value="">{primary ? 'Report problem / other…' : 'Change status…'}</option>
          {others.map(st => <option key={st} value={st}>{statusMeta(st).label}</option>)}
        </select>
      )}
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="Optional note"
        style={{ flex: '1 1 140px', minWidth: 0, padding: '6px 10px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 13 }} />
    </div>
  );
}

export function EmptyState({ title, children }) {  // `icon` is accepted by callers but the illustration replaces it
  return (
    <div className="empty-state">
      <div className="emoji"><ParcelIllustration size={110} /></div>
      <p style={{ marginTop: 10, fontWeight: 600 }}>{title}</p>
      {children && <div style={{ fontSize: 13, marginTop: 4 }}>{children}</div>}
    </div>
  );
}

export function Loading({ text = 'Loading…' }) {
  return (
    <div className="loading-screen">
      <div className="spinner" />
      <p style={{ color: 'var(--muted)', fontWeight: 600 }}>{text}</p>
    </div>
  );
}

export function StatCard({ icon, value, label, color = 'blue' }) {
  const palette = {
    blue:   { accent: '#0c831f', bg: '#dff5e3' },
    orange: { accent: '#c2410c', bg: '#ffedd5' },
    green:  { accent: '#15803d', bg: '#dcfce7' },
    red:    { accent: '#b91c1c', bg: '#fee2e2' },
    purple: { accent: '#6d28d9', bg: '#ede9fe' },
    gray:   { accent: '#475569', bg: '#e2e8f0' },
  };
  const c = palette[color] || palette.blue;
  return (
    <div className="stat-card" style={{ borderLeft: `4px solid ${c.accent}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div>
          <div className="stat-value" style={{ color: c.accent, fontSize: 28 }}>{value}</div>
          <div className="stat-label">{label}</div>
        </div>
        <div style={{ fontSize: 26, background: c.bg, borderRadius: 10, padding: '8px 9px', display: 'flex' }}><Ic icon={icon} size={24} style={{ color: c.accent }} /></div>
      </div>
    </div>
  );
}
