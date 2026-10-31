import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LocationPicker from '../components/LocationPicker';
import AuthShell from '../components/AuthShell';
import { CUSTOMER_TYPES, ROLE_LABELS, VEHICLE_TYPES, apiError, roleHome } from '../lib/shipora';
import { Building2, TriangleAlert, Truck, User } from 'lucide-react';
import { Ic } from '../components/Icon';
import PasswordInput from '../components/PasswordInput';

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
  return <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}><Ic icon={TriangleAlert} /> {text}</span>;
}

// ── Customer Form ─────────────────────────────────────────────────────────────────
function UserForm({ onSubmit, loading, error }) {
  const [form, setForm] = useState({
    name: '', email: '', password: '', phone: '',
    address: '', customerType: 'individual', deliveryInstructions: '',
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
    if (!location) { setFormError('Please select your address location on the map.'); return; }
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
          <PasswordInput required value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 6 characters" minLength={6} />
        </div>
      </div>
      <div className="form-group">
        <label>Account Type</label>
        <div style={{ display: 'flex', gap: 12, marginTop: 4, flexWrap: 'wrap' }}>
          {CUSTOMER_TYPES.map(r => (
            <label key={r.value} style={{
              flex: '1 1 160px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
              padding: '10px 14px', borderRadius: 8,
              border: `1.5px solid ${form.customerType === r.value ? 'var(--brand-600)' : 'var(--border)'}`,
              background: form.customerType === r.value ? 'var(--brand-50)' : '#fff',
              transition: 'all 0.15s',
            }}>
              <input
                type="radio" name="customerType" value={r.value}
                checked={form.customerType === r.value}
                onChange={() => set('customerType', r.value)}
                style={{ accentColor: 'var(--brand-600)' }}
              />
              <span style={{ fontSize: 14, fontWeight: 600 }}><Ic icon={r.icon} /> {r.label}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="form-group">
        <label>Delivery Instructions (optional)</label>
        <input value={form.deliveryInstructions} onChange={e => set('deliveryInstructions', e.target.value)} placeholder="e.g. Call on arrival, leave with security" maxLength={200} />
      </div>
      <div className="form-group">
        <label>Saved Address (default pickup)</label>
        <input value={form.address} onChange={e => set('address', e.target.value)} placeholder="Auto-filled when you pick location" />
      </div>
      <div className="form-group">
        <label>Address Location on Map *</label>
        <LocationPicker value={location} onChange={({ lat, lng, address }) => {
          setLocation({ lat, lng });
          if (address) set('address', address);
        }} />
      </div>
      <button type="submit" className="btn btn-primary btn-lg" disabled={loading}>
        {loading ? 'Creating account…' : <><Ic icon={User} /> Register as Customer</>}
      </button>
    </form>
  );
}

// ── Delivery Agent Form ───────────────────────────────────────────────────────────────
function DriverForm({ onSubmit, loading, error }) {
  const [form, setForm] = useState({
    name: '', email: '', password: '', phone: '',
    vehicleNo: '', vehicleType: 'van', licenseNo: '', assignedArea: '',
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
          <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Agent name" />
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
          <input required type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="agent@example.com" />
        </div>
        <div className="form-group">
          <label>Password</label>
          <PasswordInput required value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 6 characters" minLength={6} />
        </div>
      </div>
      <div className="form-group">
        <label>Vehicle Type</label>
        <select value={form.vehicleType} onChange={e => set('vehicleType', e.target.value)}>
          {VEHICLE_TYPES.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
        </select>
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
        <label>Delivery Zone / Area</label>
        <input required value={form.assignedArea} onChange={e => set('assignedArea', e.target.value)} placeholder="e.g. Zone A – Sector 12" />
      </div>
      <button type="submit" className="btn btn-secondary btn-lg" disabled={loading}>
        {loading ? 'Creating account…' : <><Ic icon={Truck} /> Register as Delivery Agent</>}
      </button>
    </form>
  );
}

// ── Admin Form ────────────────────────────────────────────────────────────────
function AdminForm({ onSubmit, loading, error }) {
  const [form, setForm] = useState({ name: '', email: '', password: '', organization: '', inviteCode: '' });
  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  return (
    <form onSubmit={e => { e.preventDefault(); onSubmit({ ...form, inviteCode: form.inviteCode.trim() || undefined }, 'admin'); }}>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="alert alert-info" style={{ marginBottom: 16 }}>
        Operations accounts can see every shipment, assign delivery agents and monitor the live fleet.
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Full Name</label>
          <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Admin Name" />
        </div>
        <div className="form-group">
          <label>Organization</label>
          <input value={form.organization} onChange={e => set('organization', e.target.value)} placeholder="e.g. Shipora Operations" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Email Address</label>
          <input required type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="admin@org.com" />
        </div>
        <div className="form-group">
          <label>Password</label>
          <PasswordInput required value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 6 characters" minLength={6} />
        </div>
      </div>
      <div className="form-group">
        <label>Invite Code</label>
        <input value={form.inviteCode} onChange={e => set('inviteCode', e.target.value)} placeholder="Required on production deployments" autoComplete="off" />
        <span style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, display: 'block' }}>Operations accounts are created by invitation. Ask your administrator for the code.</span>
      </div>
      <button type="submit" className="btn btn-admin btn-lg" disabled={loading}>
        {loading ? 'Creating account…' : <><Ic icon={Building2} /> Register for Operations</>}
      </button>
    </form>
  );
}

// ── Main Register Page ────────────────────────────────────────────────────────
const TABS = ['user', 'driver', 'admin'].map(key => ({ key, ...ROLE_LABELS[key] }));

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
      navigate(roleHome(user.role));
    } catch (err) {
      setError(apiError(err, 'Registration failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell wide title="Create your account" subtitle="Join Shipora — same-day delivery across Bengaluru."
      footer={<>Already have an account? <Link to="/login">Sign in</Link></>}>
      <div className="tab-bar" style={{ marginBottom: 22 }}>
        {TABS.map(t => (
          <button key={t.key} type="button"
            className={`tab-btn ${tab === t.key ? 'active' : ''}`}
            onClick={() => { setTab(t.key); setError(''); }}
          >
            <Ic icon={t.icon} /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'user'   && <UserForm   onSubmit={handleSubmit} loading={loading} error={error} />}
      {tab === 'driver' && <DriverForm onSubmit={handleSubmit} loading={loading} error={error} />}
      {tab === 'admin'  && <AdminForm  onSubmit={handleSubmit} loading={loading} error={error} />}
    </AuthShell>
  );
}
