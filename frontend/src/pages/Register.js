import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LocationPicker from '../components/LocationPicker';

// ── Validators ────────────────────────────────────────────────────────────────
const PHONE_RE   = /^[6-9]\d{9}$/;
// Indian DL: 2-letter state + 2-digit RTO + 4-digit year (19xx/20xx) + 7-digit unique
const LICENSE_RE = /^[A-Z]{2}\d{2}(19|20)\d{2}\d{7}$/;
// Indian vehicle plate: state(2) + district(1-2 digits) + series(1-3 letters) + number(1-4 digits)
const VEHICLE_RE = /^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/;

const cleanPhone   = v => v.replace(/\D/g, '').slice(0, 10);
const cleanPlate   = v => v.replace(/\s/g, '').toUpperCase();
const cleanLicense = v => v.replace(/[-\s]/g, '').toUpperCase();

function FieldHint({ show, text }) {
  if (!show) return null;
  return <span style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, display: 'block' }}>{text}</span>;
}
function FieldError({ show, text }) {
  if (!show) return null;
  return <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}>⚠ {text}</span>;
}

// ── Waste / Schedule options ──────────────────────────────────────────────────
const WASTE_TYPES = [
  { value: 'mixed',      label: '🗑️ Mixed Waste' },
  { value: 'household',  label: '🏠 Household' },
  { value: 'recyclable', label: '♻️ Recyclable' },
  { value: 'organic',    label: '🌿 Organic' },
];
const SCHEDULES = [
  { value: 'daily',     label: '📅 Daily' },
  { value: 'alternate', label: '📆 Alternate Days' },
  { value: 'weekly',    label: '🗓️ Weekly' },
];

// ── User Form ─────────────────────────────────────────────────────────────────
function UserForm({ onSubmit, loading, error }) {
  const [form, setForm] = useState({
    name: '', email: '', password: '', phone: '',
    address: '', wasteType: 'mixed', pickupSchedule: 'daily', residentType: 'house',
  });
  const [location,  setLocation]  = useState(null);
  const [formError, setFormError] = useState('');
  const [touched,   setTouch]     = useState({});

  const set   = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  const touch = k      => setTouch(prev => ({ ...prev, [k]: true }));

  const phoneOk   = PHONE_RE.test(form.phone);
  const phoneWarn = touched.phone && form.phone.length > 0 && !phoneOk;

  const submit = (e) => {
    e.preventDefault();
    if (!phoneOk)  { setFormError('Enter a valid 10-digit Indian mobile number (starts with 6–9).'); return; }
    if (!location) { setFormError('Please select your home location on the map.'); return; }
    setFormError('');
    onSubmit({ ...form, location }, 'user');
  };

  return (
    <form onSubmit={submit}>
      {(error || formError) && <div className="alert alert-error">{error || formError}</div>}
      <div className="form-row">
        <div className="form-group">
          <label>Full Name</label>
          <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="John Doe" />
        </div>
        <div className="form-group">
          <label>Phone Number</label>
          <input
            required
            inputMode="numeric"
            maxLength={10}
            value={form.phone}
            onChange={e => set('phone', cleanPhone(e.target.value))}
            onBlur={() => touch('phone')}
            placeholder="9876543210"
            style={phoneWarn ? { borderColor: 'var(--red)' } : {}}
          />
          <FieldHint show={!touched.phone || phoneOk} text="10-digit Indian mobile (no +91)" />
          <FieldError show={phoneWarn} text="Must be exactly 10 digits starting with 6, 7, 8, or 9" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Email Address</label>
          <input required type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="you@example.com" />
        </div>
        <div className="form-group">
          <label>Password</label>
          <input required type="password" value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 6 characters" minLength={6} />
        </div>
      </div>
      <div className="form-group">
        <label>Residence Type</label>
        <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
          {[
            { value: 'house', label: '🏠 Independent House' },
            { value: 'flat',  label: '🏢 Flat / Apartment' },
          ].map(r => (
            <label key={r.value} style={{
              flex: 1, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
              padding: '10px 14px', borderRadius: 8,
              border: `1.5px solid ${form.residentType === r.value ? 'var(--green-600)' : 'var(--border)'}`,
              background: form.residentType === r.value ? 'var(--green-50)' : '#fff',
              transition: 'all 0.15s',
            }}>
              <input
                type="radio" name="residentType" value={r.value}
                checked={form.residentType === r.value}
                onChange={() => set('residentType', r.value)}
                style={{ accentColor: 'var(--green-600)' }}
              />
              <span style={{ fontSize: 14, fontWeight: 600 }}>{r.label}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Waste Type</label>
          <select value={form.wasteType} onChange={e => set('wasteType', e.target.value)}>
            {WASTE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label>Pickup Schedule</label>
          <select value={form.pickupSchedule} onChange={e => set('pickupSchedule', e.target.value)}>
            {SCHEDULES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
      </div>
      <div className="form-group">
        <label>Home Address</label>
        <input value={form.address} onChange={e => set('address', e.target.value)} placeholder="Auto-filled when you pick location" />
      </div>
      <div className="form-group">
        <label>Home Location on Map *</label>
        <LocationPicker value={location} onChange={({ lat, lng, address }) => {
          setLocation({ lat, lng });
          if (address) set('address', address);
        }} />
      </div>
      <button type="submit" className="btn btn-primary btn-lg" disabled={loading}>
        {loading ? 'Creating account…' : '🏠 Register as Resident'}
      </button>
    </form>
  );
}

// ── Driver Form ───────────────────────────────────────────────────────────────
function DriverForm({ onSubmit, loading, error }) {
  const [form, setForm] = useState({
    name: '', email: '', password: '', phone: '',
    vehicleNo: '', licenseNo: '', assignedArea: '',
  });
  const [formError, setFormError] = useState('');
  const [touched,   setTouch]     = useState({});

  const set   = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  const touch = k      => setTouch(prev => ({ ...prev, [k]: true }));

  const phoneOk    = PHONE_RE.test(form.phone);
  const vehicleOk  = VEHICLE_RE.test(form.vehicleNo);
  const licenseOk  = LICENSE_RE.test(form.licenseNo);

  const submit = (e) => {
    e.preventDefault();
    if (!phoneOk)   { setFormError('Enter a valid 10-digit Indian mobile number (starts with 6–9).'); return; }
    if (!vehicleOk) { setFormError('Enter a valid vehicle number (e.g. MH01AB1234).'); return; }
    if (!licenseOk) { setFormError('Enter a valid 15-character Indian DL number (e.g. MH1220150123456).'); return; }
    setFormError('');
    onSubmit(form, 'driver');
  };

  return (
    <form onSubmit={submit}>
      {(error || formError) && <div className="alert alert-error">{error || formError}</div>}
      <div className="form-row">
        <div className="form-group">
          <label>Full Name</label>
          <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Driver Name" />
        </div>
        <div className="form-group">
          <label>Phone Number</label>
          <input
            required
            inputMode="numeric"
            maxLength={10}
            value={form.phone}
            onChange={e => set('phone', cleanPhone(e.target.value))}
            onBlur={() => touch('phone')}
            placeholder="9876543210"
            style={touched.phone && form.phone && !phoneOk ? { borderColor: 'var(--red)' } : {}}
          />
          <FieldHint show={!touched.phone || phoneOk} text="10-digit Indian mobile (no +91)" />
          <FieldError show={touched.phone && form.phone.length > 0 && !phoneOk}
            text="Must be exactly 10 digits starting with 6, 7, 8, or 9" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Email Address</label>
          <input required type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="driver@example.com" />
        </div>
        <div className="form-group">
          <label>Password</label>
          <input required type="password" value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 6 characters" minLength={6} />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Vehicle Number</label>
          <input
            required
            maxLength={13}
            value={form.vehicleNo}
            onChange={e => set('vehicleNo', cleanPlate(e.target.value))}
            onBlur={() => touch('vehicleNo')}
            placeholder="MH01AB1234"
            style={touched.vehicleNo && form.vehicleNo && !vehicleOk ? { borderColor: 'var(--red)' } : {}}
          />
          <FieldHint show={!touched.vehicleNo || vehicleOk} text="Format: MH01AB1234 (state + district + series + number)" />
          <FieldError show={touched.vehicleNo && form.vehicleNo.length > 0 && !vehicleOk}
            text="Invalid plate — use format MH01AB1234 (no spaces)" />
        </div>
        <div className="form-group">
          <label>Driving Licence No.</label>
          <input
            required
            maxLength={15}
            value={form.licenseNo}
            onChange={e => set('licenseNo', cleanLicense(e.target.value))}
            onBlur={() => touch('licenseNo')}
            placeholder="MH1220150123456"
            style={touched.licenseNo && form.licenseNo && !licenseOk ? { borderColor: 'var(--red)' } : {}}
          />
          <FieldHint show={!touched.licenseNo || licenseOk} text="15 chars: state(2) + RTO(2) + year(4) + number(7)" />
          <FieldError show={touched.licenseNo && form.licenseNo.length > 0 && !licenseOk}
            text="Invalid DL — must be 15 chars, e.g. MH1220150123456" />
        </div>
      </div>
      <div className="form-group">
        <label>Assigned Area / Zone</label>
        <input required value={form.assignedArea} onChange={e => set('assignedArea', e.target.value)} placeholder="e.g. Zone A – Sector 12" />
      </div>
      <button type="submit" className="btn btn-secondary btn-lg" disabled={loading}>
        {loading ? 'Creating account…' : '🚛 Register as Driver'}
      </button>
    </form>
  );
}

// ── Admin Form ────────────────────────────────────────────────────────────────
function AdminForm({ onSubmit, loading, error }) {
  const [form, setForm] = useState({ name: '', email: '', password: '', organization: '' });
  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  return (
    <form onSubmit={e => { e.preventDefault(); onSubmit(form, 'admin'); }}>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="alert alert-info" style={{ marginBottom: 16 }}>
        Admin accounts have full visibility into driver activity and collection logs.
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Full Name</label>
          <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Admin Name" />
        </div>
        <div className="form-group">
          <label>Organization</label>
          <input value={form.organization} onChange={e => set('organization', e.target.value)} placeholder="e.g. City Municipality" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Email Address</label>
          <input required type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="admin@org.com" />
        </div>
        <div className="form-group">
          <label>Password</label>
          <input required type="password" value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 6 characters" minLength={6} />
        </div>
      </div>
      <button type="submit" className="btn btn-admin btn-lg" disabled={loading}>
        {loading ? 'Creating account…' : '🏢 Register as Admin'}
      </button>
    </form>
  );
}

// ── Main Register Page ────────────────────────────────────────────────────────
const TABS = [
  { key: 'user',   label: '🏠 Resident' },
  { key: 'driver', label: '🚛 Driver' },
  { key: 'admin',  label: '🏢 Admin' },
];

export default function Register() {
  const { register } = useAuth();
  const navigate     = useNavigate();
  const [tab,     setTab]     = useState('user');
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const handleSubmit = async (data, role) => {
    setError('');
    setLoading(true);
    try {
      const user = await register(data, role);
      if (user.role === 'driver') navigate('/driver');
      else if (user.role === 'admin') navigate('/admin');
      else navigate('/dashboard');
    } catch (err) {
      setError(err.response?.data?.message || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #1a3a1a 0%, #2d7a2d 100%)', padding: '80px 20px 40px' }}>
      <div style={{ maxWidth: 700, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ fontSize: 52, filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.3))' }}>♻️</div>
          <h1 style={{ color: '#fff', fontSize: 26, fontWeight: 800, margin: '8px 0 4px', letterSpacing: '-0.5px' }}>
            Create Account
          </h1>
          <p style={{ color: '#86efac', fontSize: 14 }}>Join EcoTrack Waste Disposal System</p>
        </div>

        <div className="card" style={{ padding: 32 }}>
          <div className="tab-bar" style={{ marginBottom: 24 }}>
            {TABS.map(t => (
              <button key={t.key} type="button"
                className={`tab-btn ${tab === t.key ? 'active' : ''}`}
                onClick={() => { setTab(t.key); setError(''); }}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'user'   && <UserForm   onSubmit={handleSubmit} loading={loading} error={error} />}
          {tab === 'driver' && <DriverForm onSubmit={handleSubmit} loading={loading} error={error} />}
          {tab === 'admin'  && <AdminForm  onSubmit={handleSubmit} loading={loading} error={error} />}

          <p style={{ textAlign: 'center', marginTop: 20, fontSize: 14, color: '#6b8f6b' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: '#2d7a2d', fontWeight: 700 }}>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
