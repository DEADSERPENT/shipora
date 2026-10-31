import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';
import LocationPicker from '../components/LocationPicker';
import EstimateCard from '../components/EstimateCard';
import { findArea } from '../lib/areas';
import { MAX_PARCEL_KG, PAYMENT_METHODS, fmtINR, getEstimate } from '../lib/estimate';
import { PARCEL_CATEGORIES, apiError, newIdempotencyKey, inBengaluru, OUTSIDE_BENGALURU_MSG } from '../lib/shipora';
import { ArrowDownToLine, ArrowUpFromLine, Gift, Package, Wallet, Wine, Zap } from 'lucide-react';
import { Ic } from '../components/Icon';

const PHONE_RE = /^[6-9]\d{9}$/;
const cleanPhone = v => v.replace(/\D/g, '').slice(0, 10);

const section = { fontSize: 15, fontWeight: 700, color: 'var(--text)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 };

export default function CreateShipment() {
  const { user, API } = useAuth();
  const navigate = useNavigate();
  const [prefill] = useSearchParams();  // ?type=&pickup=&drop=&weight= from the home page estimate card
  const dropArea = findArea(prefill.get('drop'));
  const pickupArea = findArea(prefill.get('pickup'));
  const areaPin = (a) => (a ? { lat: a.lat, lng: a.lng, address: `${a.name}, Bengaluru` } : null);
  const prefillKg = parseFloat(prefill.get('weight'));

  // Pickup: the customer's saved address by default, or a different one picked on the map.
  const [useSaved,   setUseSaved]   = useState(!!user?.address && !pickupArea);
  const [pickupLoc,  setPickupLoc]  = useState(areaPin(pickupArea));
  const [pickupAddr, setPickupAddr] = useState(pickupArea ? `${pickupArea.name}, Bengaluru` : '');
  const [pickupName,  setPickupName]  = useState(user?.name || '');
  const [pickupPhone, setPickupPhone] = useState('');

  const [receiver, setReceiver] = useState({ name: '', phone: '', address: dropArea ? `${dropArea.name}, Bengaluru` : '' });
  const [dropLoc,  setDropLoc]  = useState(areaPin(dropArea));

  const [parcel, setParcel] = useState({ category: PARCEL_CATEGORIES.some(c => c.value === prefill.get('type')) ? prefill.get('type') : 'other', weightKg: prefillKg > 0 && prefillKg <= MAX_PARCEL_KG ? String(prefillKg) : '1', description: '', declaredValue: '', fragile: false });

  const [payment, setPayment] = useState('cash');
  const [estimate, setEstimate] = useState(null);
  const [estError, setEstError] = useState('');
  const [estLoading, setEstLoading] = useState(false);

  const [error, setError]   = useState('');
  const [saving, setSaving] = useState(false);
  // One key per form instance: a double-click, a retry after a network error, or a re-sent request all carry the
  // same key, so the server returns the original shipment instead of creating a second parcel.
  const idempotencyKey = useRef(newIdempotencyKey());

  const setR = (k, v) => setReceiver(p => ({ ...p, [k]: v }));
  const setP = (k, v) => setParcel(p => ({ ...p, [k]: v }));

  const pickDrop = (loc) => { setDropLoc(loc); if (loc.address) setR('address', loc.address); };
  const pickPickup = (loc) => { setPickupLoc(loc); if (loc.address) setPickupAddr(loc.address); };

  // Live fare: re-quoted (debounced) whenever the pickup pin, drop pin or weight changes.
  const fromLat = (useSaved ? user?.location : pickupLoc)?.lat, fromLng = (useSaved ? user?.location : pickupLoc)?.lng;
  const toLat = dropLoc?.lat, toLng = dropLoc?.lng;
  useEffect(() => {
    if (fromLat == null || toLat == null) { setEstimate(null); setEstError(''); return undefined; }
    const kg = parseFloat(parcel.weightKg);
    let live = true;
    setEstLoading(true);
    const timer = setTimeout(() => {
      getEstimate({ lat: fromLat, lng: fromLng }, { lat: toLat, lng: toLng }, kg > 0 ? kg : undefined)
        .then(q => { if (live) { setEstimate(q); setEstError(''); } })
        .catch(err => { if (live) { setEstimate(null); setEstError(err.message); } })
        .finally(() => { if (live) setEstLoading(false); });
    }, 350);
    return () => { live = false; clearTimeout(timer); };
  }, [fromLat, fromLng, toLat, toLng, parcel.weightKg]);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const weight = parseFloat(parcel.weightKg);
    if (!(weight > 0)) return setError('Enter a parcel weight greater than 0 kg.');
    if (weight > MAX_PARCEL_KG) return setError(`Parcels can weigh at most ${MAX_PARCEL_KG} kg for same-day bike delivery.`);
    if (!PHONE_RE.test(receiver.phone)) return setError('Enter a valid 10-digit receiver mobile number (starts with 6–9).');
    if (!receiver.address.trim()) return setError('Enter or pick the delivery address.');
    if (!dropLoc) return setError('Pick the delivery location on the map (Bengaluru only).');
    if (!inBengaluru(dropLoc.lat, dropLoc.lng)) return setError(OUTSIDE_BENGALURU_MSG);
    if (!useSaved) {
      if (!pickupAddr.trim()) return setError('Enter or pick the pickup address.');
      if (!PHONE_RE.test(pickupPhone)) return setError('Enter a valid 10-digit pickup contact number.');
      if (pickupLoc && !inBengaluru(pickupLoc.lat, pickupLoc.lng)) return setError(OUTSIDE_BENGALURU_MSG);
    }

    const body = {
      recipient: {
        name: receiver.name.trim(), phone: receiver.phone, address: receiver.address.trim(),
        location: dropLoc ? { lat: dropLoc.lat, lng: dropLoc.lng } : null,
      },
      parcel: {
        category: parcel.category, weightKg: weight, description: parcel.description.trim(),
        declaredValue: parseFloat(parcel.declaredValue) || 0, fragile: parcel.fragile || parcel.category === 'fragile',
      },
      serviceType: 'same_day',
      paymentMethod: payment,
    };
    if (!useSaved) {
      body.sender = {
        name: pickupName.trim() || user.name, phone: pickupPhone, address: pickupAddr.trim(),
        location: pickupLoc ? { lat: pickupLoc.lat, lng: pickupLoc.lng } : null,
      };
    }

    setSaving(true);
    try {
      const { data } = await axios.post(`${API}/shipments`, body, { headers: { 'Idempotency-Key': idempotencyKey.current } });
      navigate(`/shipments/${data.trackingNumber}`, { state: { justCreated: true } });
    } catch (err) {
      setError(apiError(err, 'Could not create the shipment.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page" style={{ maxWidth: 820, margin: '0 auto' }}>
      <BackButton to="/dashboard" label="Dashboard" />
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800 }}><Ic icon={Package} /> Create Shipment</h1>
        <p style={{ color: 'var(--muted)', fontSize: 14 }}>Tell us where to collect, where to deliver, and what is in the parcel.</p>
      </div>

      {error && <div className="alert alert-error" role="alert">{error}</div>}

      <form onSubmit={submit}>
        {/* ── Pickup ── */}
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={section}><Ic icon={ArrowUpFromLine} /> Pickup address</div>
          {user?.address && (
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', marginBottom: 12 }}>
              <input type="checkbox" checked={useSaved} onChange={e => setUseSaved(e.target.checked)} style={{ marginTop: 3 }} />
              <span style={{ fontSize: 14 }}>
                <strong>Use my saved address</strong><br />
                <span style={{ color: 'var(--muted)', fontSize: 13 }}>{user.address}</span>
              </span>
            </label>
          )}
          {!useSaved && (
            <>
              <div className="form-row">
                <div className="form-group">
                  <label>Contact name</label>
                  <input value={pickupName} onChange={e => setPickupName(e.target.value)} />
                </div>
                <div className="form-group">
                  <label>Contact phone</label>
                  <input inputMode="numeric" value={pickupPhone} onChange={e => setPickupPhone(cleanPhone(e.target.value))} placeholder="9876543210" />
                </div>
              </div>
              <div className="form-group">
                <label>Pickup address</label>
                <input value={pickupAddr} onChange={e => setPickupAddr(e.target.value)} placeholder="Search on the map below or type the address" />
              </div>
              <LocationPicker value={pickupLoc} onChange={pickPickup} />
            </>
          )}
        </div>

        {/* ── Receiver / delivery ── */}
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={section}><Ic icon={ArrowDownToLine} /> Receiver &amp; delivery address</div>
          <div className="form-row">
            <div className="form-group">
              <label>Receiver name</label>
              <input required value={receiver.name} onChange={e => setR('name', e.target.value)} placeholder="Who will receive it?" />
            </div>
            <div className="form-group">
              <label>Receiver phone</label>
              <input required inputMode="numeric" value={receiver.phone} onChange={e => setR('phone', cleanPhone(e.target.value))} placeholder="9876543210" />
            </div>
          </div>
          <div className="form-group">
            <label>Delivery address</label>
            <input required value={receiver.address} onChange={e => setR('address', e.target.value)} placeholder="Search on the map below or type the address" />
          </div>
          <LocationPicker value={dropLoc} onChange={pickDrop} />
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
            Pinning the location lets you see the route and the delivery vehicle on the tracking map.
          </p>
        </div>

        {/* ── Parcel ── */}
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={section}><Ic icon={Gift} /> Parcel details</div>
          <div className="form-row">
            <div className="form-group">
              <label>Parcel type</label>
              <select value={parcel.category} onChange={e => setP('category', e.target.value)}>
                {PARCEL_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Weight (kg, max {MAX_PARCEL_KG})</label>
              <input required type="number" min="0.1" max={MAX_PARCEL_KG} step="0.1" value={parcel.weightKg} onChange={e => setP('weightKg', e.target.value)} />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Declared value (₹, optional)</label>
              <input type="number" min="0" step="1" value={parcel.declaredValue} onChange={e => setP('declaredValue', e.target.value)} />
            </div>
            <div className="form-group">
              <label>Contents (optional)</label>
              <input value={parcel.description} onChange={e => setP('description', e.target.value)} maxLength={120} placeholder="e.g. Laptop charger" />
            </div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
            <input type="checkbox" checked={parcel.fragile} onChange={e => setP('fragile', e.target.checked)} />
            <Ic icon={Wine} /> Handle with care (fragile)
          </label>
        </div>

        {/* ── Fare & payment ── */}
        <div className="card" style={{ marginBottom: 20 }}>
          <div style={section}><Ic icon={Wallet} /> Fare &amp; payment</div>
          {estimate || estLoading || estError
            ? <EstimateCard estimate={estimate} loading={estLoading} error={estError} />
            : <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>Pin the pickup and delivery locations to see your fare, distance and ETA.</div>}
          <div className="pay-grid" role="radiogroup" aria-label="Payment method">
            {PAYMENT_METHODS.map(m => (
              <label key={m.value} className={`pay-opt ${payment === m.value ? 'on' : ''}`}>
                <input type="radio" name="payment" value={m.value} checked={payment === m.value} onChange={() => setPayment(m.value)} />
                <strong>{m.label}</strong>
                <span>{m.desc}</span>
              </label>
            ))}
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 12 }}>
            <Ic icon={Zap} size={13} /> Same-day delivery · Bengaluru only · pickup and delivery must both be inside the city.
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-ghost" onClick={() => navigate('/dashboard')}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving} style={{ minWidth: 190 }}>
            {saving ? 'Creating…' : <><Ic icon={Package} /> {estimate ? `Book · ${fmtINR(estimate.fare)}` : 'Create Shipment'}</>}
          </button>
        </div>
      </form>
    </div>
  );
}
