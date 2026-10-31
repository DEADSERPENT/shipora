import React, { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';
import VehicleMap from '../components/VehicleMap';
import { Loading, ShipmentTimeline, StatusActions, StatusBadge } from '../components/ShipmentUI';
import LiveOrderHero from '../components/LiveOrderHero';
import { useShipmentRoom, useVehicleFeed } from '../hooks/useLive';
import { ArrowDownToLine, ArrowUpFromLine, Ban, Circle, Clock, Gift, Map as MapIcon, MapPin, Megaphone, PartyPopper, Timer, Truck, Wine } from 'lucide-react';
import { Ic } from '../components/Icon';
import { fmtINR } from '../lib/estimate';
import {
  apiError, fmtDateTime, isDelayed, parcelLabel, roleHome, serviceLabel, statusMeta, vehicleIcon,
} from '../lib/shipora';

const Row = ({ label, children }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '7px 0', borderBottom: '1px dashed var(--border)', fontSize: 13 }}>
    <span style={{ color: 'var(--muted)', fontWeight: 600 }}>{label}</span>
    <span style={{ fontWeight: 600, textAlign: 'right', minWidth: 0, overflowWrap: 'anywhere' }}>{children}</span>
  </div>
);

// One shipment, three perspectives: the customer tracks / cancels, the delivery agent
// advances the status, operations assigns an agent and can override.
export default function ShipmentDetail() {
  const { trackingNumber } = useParams();
  const { user, API } = useAuth();
  const location = useLocation();
  const [shipment, setShipment] = useState(null);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState(false);
  const [actionMsg, setActionMsg] = useState({ type: '', text: '' });
  const [agents, setAgents]     = useState([]);
  const [agentId, setAgentId]   = useState('');
  const [live, setLive]         = useState(false);

  const { vehicles } = useVehicleFeed();

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/shipments/${trackingNumber}`);
      setShipment(data);
      setError('');
    } catch (err) {
      setError(apiError(err, 'Could not load this shipment.'));
    }
  }, [API, trackingNumber]);

  useEffect(() => { load(); }, [load]);

  // Backend pushes `shipment:update` for every status change — refetch the full record.
  const connected = useShipmentRoom(shipment?.trackingNumber, () => { setLive(true); load(); });

  useEffect(() => {
    if (user.role !== 'admin') return;
    axios.get(`${API}/admin/drivers`).then(({ data }) => setAgents(data)).catch(() => {});
  }, [API, user.role]);

  const changeStatus = async (status, note) => {
    setBusy(true); setActionMsg({ type: '', text: '' });
    try {
      const { data } = await axios.post(`${API}/shipments/${shipment._id}/status`, { status, note: note || '' });
      setShipment(data);
      setActionMsg({ type: 'success', text: `Status updated to ${statusMeta(status).label}.` });
    } catch (err) {
      setActionMsg({ type: 'error', text: apiError(err, 'Status update failed.') });
    } finally { setBusy(false); }
  };

  const assign = async () => {
    if (!agentId) return;
    setBusy(true); setActionMsg({ type: '', text: '' });
    try {
      const { data } = await axios.put(`${API}/shipments/${shipment._id}/assign`, { agentId });
      setShipment(data);
      setActionMsg({ type: 'success', text: `Assigned to ${data.assignedAgent?.name}.` });
    } catch (err) {
      setActionMsg({ type: 'error', text: apiError(err, 'Assignment failed.') });
    } finally { setBusy(false); }
  };

  if (!shipment && !error) return <Loading text="Loading shipment…" />;
  if (error) {
    return (
      <div className="page" style={{ maxWidth: 700, margin: '0 auto' }}>
        <BackButton to={roleHome(user.role)} label="Dashboard" />
        <div className="alert alert-error">{error}</div>
      </div>
    );
  }

  const s = shipment;
  const o = s.sender?.location, d = s.recipient?.location;
  const hasMap = !!(o || d);
  const canAssign = user.role === 'admin' && !['DELIVERED', 'CANCELLED', 'RETURN_TO_ORIGIN'].includes(s.status);
  const canIssue = user.role === 'user';
  const vehicleLive = s.assignedAgentId && vehicles[s.assignedAgentId]?.isActive;
  const hasControls = !!(actionMsg.text || user.role === 'driver' || user.role === 'admin' || canAssign || (user.role === 'user' && (s.allowedNextStatuses || []).includes('CANCELLED')));

  return (
    <div className="page" style={{ maxWidth: 1180, margin: '0 auto' }}>
      <BackButton to={roleHome(user.role)} label="Dashboard" />

      {location.state?.justCreated && (
        <div className="alert alert-success"><Ic icon={PartyPopper} /> Shipment created! Share the tracking number <strong>{s.trackingNumber}</strong> with the receiver.</div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Tracking number</div>
          <h1 className="tracking-no" style={{ fontSize: 26, marginBottom: 6 }}>{s.trackingNumber}</h1>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <StatusBadge status={s.status} />
            {isDelayed(s) && <span className="pill pill-red"><Ic icon={Timer} /> Delayed</span>}
            <span className="pill pill-gray">{serviceLabel(s.serviceType)}</span>
          </div>
        </div>
        <span className={`badge ${connected ? 'badge-green' : 'badge-red'}`} title="Live shipment updates">
          {connected ? <><Ic icon={Circle} size={10} fill="#22c55e" color="#22c55e" /> {live ? 'Live — just updated' : 'Live updates on'}</> : <><Ic icon={Circle} size={10} fill="#ef4444" color="#ef4444" /> Reconnecting…</>}
        </span>
      </div>

      <LiveOrderHero shipment={s} role={user.role}
        liveArea={vehicleLive ? (vehicles[s.assignedAgentId].currentArea || 'On route') : ''}
        liveEta={vehicleLive ? vehicles[s.assignedAgentId].eta : ''} />

      {hasControls && <div className="card" style={{ marginBottom: 20 }}>
        {actionMsg.text && <div className={`alert alert-${actionMsg.type}`} style={{ marginTop: 12, marginBottom: 0 }}>{actionMsg.text}</div>}
        {(user.role === 'driver' || user.role === 'admin') && (
          <StatusActions shipment={s} onChange={changeStatus} busy={busy} />
        )}
        {user.role === 'user' && (s.allowedNextStatuses || []).includes('CANCELLED') && (
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-danger btn-sm" disabled={busy}
              onClick={() => changeStatus('CANCELLED', 'Cancelled by customer')}><Ic icon={Ban} /> Cancel shipment</button>
            <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 10 }}>Possible until the parcel is picked up.</span>
          </div>
        )}
        {canAssign && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 14, paddingTop: 14, borderTop: '1px dashed var(--border)' }}>
            <strong style={{ fontSize: 13 }}><Ic icon={Truck} /> Delivery agent:</strong>
            <select value={agentId} onChange={e => setAgentId(e.target.value)}
              style={{ padding: '7px 10px', borderRadius: 8, border: '1.5px solid var(--border)', minWidth: 220 }}>
              <option value="">{s.assignedAgent ? `Reassign (now ${s.assignedAgent.name})…` : 'Select an agent…'}</option>
              {agents.map(a => <option key={a._id} value={a._id}>{a.name} · {a.vehicleNo} · {a.assignedArea}</option>)}
            </select>
            <button type="button" className="btn btn-secondary btn-sm" disabled={!agentId || busy} onClick={assign}>
              {s.assignedAgent ? 'Reassign' : 'Assign & schedule pickup'}
            </button>
          </div>
        )}
      </div>}

      <div className="split-layout-r">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {hasMap ? (
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <h3 style={{ fontWeight: 700, fontSize: 15 }}><Ic icon={MapIcon} /> Route &amp; live vehicle</h3>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  {vehicleLive ? `${s.assignedAgent?.vehicleNo} is live` : 'Vehicle location appears when the agent is sharing GPS'}
                </span>
              </div>
              <div style={{ height: 380 }}>
                <VehicleMap role="shipment" vehicles={vehicles} focusAgentId={s.assignedAgentId}
                  origin={o ? { ...o, label: s.sender.address } : null}
                  destination={d ? { ...d, label: s.recipient.address } : null} />
              </div>
            </div>
          ) : (
            <div className="alert alert-info" style={{ marginBottom: 0 }}>
              <Ic icon={MapIcon} /> No map pins were saved for this shipment, so only the address details are shown.
            </div>
          )}

          <div className="card">
            <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 12 }}><Ic icon={MapPin} /> Shipment details</h3>
            <div className="form-row" style={{ gap: 24 }}>
              <div>
                <div className="section-title"><Ic icon={ArrowUpFromLine} /> Pickup</div>
                <Row label="From">{s.sender.name}</Row>
                <Row label="Phone">{s.sender.phone}</Row>
                <Row label="Address">{s.sender.address}</Row>
                <Row label="Pickup scheduled">{fmtDateTime(s.pickupScheduledAt)}</Row>
              </div>
              <div>
                <div className="section-title"><Ic icon={ArrowDownToLine} /> Delivery</div>
                <Row label="To">{s.recipient.name}</Row>
                <Row label="Phone">{s.recipient.phone}</Row>
                <Row label="Address">{s.recipient.address}</Row>
                <Row label={s.status === 'DELIVERED' ? 'Delivered' : 'Est. delivery'}>{s.status === 'DELIVERED' ? fmtDateTime(s.deliveredAt) : fmtDateTime(s.estimatedDelivery)}</Row>
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="card">
            <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 14 }}><Ic icon={Clock} /> Tracking timeline</h3>
            <ShipmentTimeline events={s.statusHistory} currentStatus={s.status} />
          </div>

          <div className="card">
            <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 8 }}><Ic icon={Gift} /> Package</h3>
            <Row label="Type">{parcelLabel(s.parcel.category)}</Row>
            <Row label="Weight">{s.parcel.weightKg} kg</Row>
            {s.fare > 0 && <Row label="Fare">{fmtINR(s.fare)} · {s.distanceKm} km</Row>}
            {s.fare > 0 && <Row label="Payment">{s.paymentMethod === 'upi' ? 'UPI' : 'Cash'} to the rider on delivery</Row>}
            {s.parcel.description && <Row label="Contents">{s.parcel.description}</Row>}
            {s.parcel.declaredValue > 0 && <Row label="Declared value">₹{s.parcel.declaredValue}</Row>}
            {s.parcel.fragile && <Row label="Handling"><Ic icon={Wine} /> Fragile</Row>}
            <Row label="Delivery attempts">{s.deliveryAttempts} / 3</Row>
            {user.role === 'admin' && <Row label="Customer">{s.customerName}</Row>}
          </div>

          <div className="card">
            <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 8 }}><Ic icon={Truck} /> Delivery agent</h3>
            {s.assignedAgent ? (
              <>
                <Row label="Agent">{s.assignedAgent.name}</Row>
                {user.role !== 'driver' && <Row label="Phone">{s.assignedAgent.phone}</Row>}
                <Row label="Vehicle"><Ic icon={vehicleIcon(s.assignedAgent.vehicleType)} /> {s.assignedAgent.vehicleNo}</Row>
                <Row label="Live">{vehicleLive ? <><Ic icon={Circle} size={10} fill="#22c55e" color="#22c55e" /> {vehicles[s.assignedAgentId].currentArea || 'On route'}{vehicles[s.assignedAgentId].eta ? ` · ETA ${vehicles[s.assignedAgentId].eta}` : ''}</> : <><Ic icon={Circle} size={10} fill="#94a3b8" color="#94a3b8" /> Not sharing location</>}</Row>
              </>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--muted)' }}>No agent assigned yet. An agent is assigned when pickup is scheduled.</p>
            )}
          </div>

          {canIssue && (
            <Link to={`/issues?tn=${s.trackingNumber}`} className="btn btn-ghost" style={{ justifyContent: 'center' }}>
              <Ic icon={Megaphone} /> Report a delivery issue
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
