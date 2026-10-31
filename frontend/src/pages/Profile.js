import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import LocationPicker from '../components/LocationPicker';
import BackButton from '../components/BackButton';
import { CUSTOMER_TYPES, ROLE_LABELS, VEHICLE_TYPES, apiError } from '../lib/shipora';
import { Check, Eye, EyeOff, KeyRound, Lock, TriangleAlert } from 'lucide-react';
import { Ic } from '../components/Icon';

const PHONE_RE   = /^[6-9]\d{9}$/;
const cleanPhone = v => v.replace(/\D/g, '').slice(0, 10);

const AVAILABILITY = [
  { value: 'available',   label: 'Available' },
  { value: 'on_delivery', label: 'On delivery' },
  { value: 'off_duty',    label: 'Off duty' },
];

const ROLE_STYLE = {
  user:   { color: '#0c831f', bg: '#dff5e3' },
  driver: { color: '#c2410c', bg: '#ffedd5' },
  admin:  { color: '#6d28d9', bg: '#ede9fe' },
};
const ROLE_META = Object.fromEntries(Object.keys(ROLE_LABELS).map(k => [k, { ...ROLE_LABELS[k], ...ROLE_STYLE[k] }]));

// ── Locked field display ──────────────────────────────────────────────────────
function LockedField({ label, value, reason }) {
  return (
    <div className="form-group">
      <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {label}
        <span title={reason} style={{
          fontSize: 11, background: '#f1f5f9', color: '#64748b',
          padding: '1px 7px', borderRadius: 20, fontWeight: 600,
          textTransform: 'none', letterSpacing: 0, cursor: 'default',
        }}>
          <Ic icon={Lock} /> locked
        </span>
      </label>
      <div style={{
        padding: '10px 14px', border: '1.5px solid #e2e8f0', borderRadius: 8,
        background: '#f8fafc', color: '#64748b', fontSize: 14, fontFamily: 'monospace',
        letterSpacing: '0.03em',
      }}>
        {value || '—'}
      </div>
      {reason && <span style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, display: 'block' }}>{reason}</span>}
    </div>
  );
}

// ── Flash message ─────────────────────────────────────────────────────────────
function Flash({ type, msg, onClose }) {
  if (!msg) return null;
  return (
    <div className={`alert alert-${type}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span>{msg}</span>
      <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'inherit', padding: 0 }}>×</button>
    </div>
  );
}

export default function Profile() {
  const { user, updateProfile, API } = useAuth();
  const role = user?.role || 'user';
  const meta = ROLE_META[role] || ROLE_META.user;

  // Full profile fetched from server (has phone, address etc. not in JWT)
  const [profile, setProfile]   = useState(null);
  const [loadingProfile, setLP] = useState(true);

  // Edit form state (populated once profile loads)
  const [form, setForm]         = useState({});
  const [location, setLocation] = useState(null);
  const [saving, setSaving]     = useState(false);
  const [flash, setFlash]       = useState({ type: '', msg: '' });

  // Change password state
  const [pwForm, setPwForm]     = useState({ current: '', next: '', confirm: '' });
  const [showPw, setShowPw]     = useState(false);
  const [pwSaving, setPwSaving] = useState(false);
  const [pwFlash, setPwFlash]   = useState({ type: '', msg: '' });

  useEffect(() => {
    axios.get(`${API}/auth/profile`)
      .then(({ data }) => {
        setProfile(data);
        if (role === 'user') {
          setForm({
            name: data.name || '', phone: data.phone || '',
            address: data.address || '', customerType: data.customerType || 'individual',
            deliveryInstructions: data.deliveryInstructions || '',
          });
          if (data.location?.lat) setLocation(data.location);
        } else if (role === 'driver') {
          setForm({ name: data.name || '', phone: data.phone || '', assignedArea: data.assignedArea || '', vehicleType: data.vehicleType || 'van', availability: data.availability || 'available' });
        } else {
          setForm({ name: data.name || '', organization: data.organization || '' });
        }
      })
      .catch(() => setFlash({ type: 'error', msg: 'Failed to load profile.' }))
      .finally(() => setLP(false));
  }, [API, role]);

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const handleSave = async (e) => {
    e.preventDefault();
    if (form.phone && !PHONE_RE.test(form.phone)) {
      setFlash({ type: 'error', msg: 'Phone must be exactly 10 digits starting with 6–9.' });
      return;
    }
    setSaving(true);
    setFlash({ type: '', msg: '' });
    try {
      const payload = { ...form };
      if (role === 'user' && location) payload.location = location;
      await updateProfile(payload);
      setFlash({ type: 'success', msg: 'Profile updated successfully.' });
    } catch (err) {
      setFlash({ type: 'error', msg: apiError(err, 'Update failed.') });
    } finally {
      setSaving(false);
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setPwFlash({ type: '', msg: '' });
    if (pwForm.next.length < 6) { setPwFlash({ type: 'error', msg: 'New password must be at least 6 characters.' }); return; }
    if (pwForm.next !== pwForm.confirm) { setPwFlash({ type: 'error', msg: 'Passwords do not match.' }); return; }
    setPwSaving(true);
    try {
      const { data } = await axios.post(`${API}/auth/change-password`, {
        currentPassword: pwForm.current,
        newPassword: pwForm.next,
      });
      setPwFlash({ type: 'success', msg: data.message });
      setPwForm({ current: '', next: '', confirm: '' });
    } catch (err) {
      setPwFlash({ type: 'error', msg: err.response?.data?.message || 'Password change failed.' });
    } finally {
      setPwSaving(false);
    }
  };

  if (loadingProfile) return (
    <div className="loading-screen">
      <div className="spinner" />
      <p style={{ color: '#64748b', fontWeight: 600 }}>Loading profile…</p>
    </div>
  );

  const memberSince = profile?.createdAt
    ? new Date(profile.createdAt).toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' })
    : null;

  return (
    <div className="page" style={{ maxWidth: 760, margin: '0 auto' }}>
      <BackButton />

      {/* ── Profile Header Card ── */}
      <div className="card" style={{ marginBottom: 24, padding: '28px 32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: meta.bg, border: `3px solid ${meta.color}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 34, flexShrink: 0,
          }}>
            <Ic icon={meta.icon} size={28} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text)', marginBottom: 4 }}>
              {profile?.name || user?.name}
            </h2>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span className="badge" style={{ background: meta.bg, color: meta.color, fontSize: 12 }}>
                <Ic icon={meta.icon} size={13} /> {meta.label}
              </span>
              <span style={{ fontSize: 13, color: 'var(--muted)' }}>{user?.email}</span>
              {user?.role === 'admin' && user?.organization && (
                <span style={{ fontSize: 13, color: 'var(--muted)' }}>· {user.organization}</span>
              )}
            </div>
            {memberSince && (
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>Member since {memberSince}</p>
            )}
          </div>
        </div>
      </div>

      {/* ── Edit Profile Card ── */}
      <div className="card" style={{ marginBottom: 24, padding: '28px 32px' }}>
        <h3 style={{ fontSize: 17, fontWeight: 700, marginBottom: 20, color: 'var(--text)', borderBottom: '1px solid var(--border)', paddingBottom: 12 }}>
          Profile Details
        </h3>

        <Flash type={flash.type} msg={flash.msg} onClose={() => setFlash({ type: '', msg: '' })} />

        <form onSubmit={handleSave}>

          {/* ── Customer fields ── */}
          {role === 'user' && (
            <>
              <div className="form-row">
                <div className="form-group">
                  <label>Full Name</label>
                  <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Your name" />
                </div>
                <div className="form-group">
                  <label>Phone Number</label>
                  <input
                    inputMode="numeric" maxLength={10}
                    value={form.phone}
                    onChange={e => set('phone', cleanPhone(e.target.value))}
                    placeholder="9876543210"
                    style={form.phone && !PHONE_RE.test(form.phone) ? { borderColor: 'var(--red)' } : {}}
                  />
                  {form.phone && !PHONE_RE.test(form.phone) && (
                    <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}>
                      <Ic icon={TriangleAlert} /> Must be 10 digits starting with 6–9
                    </span>
                  )}
                </div>
              </div>
              <LockedField label="Email Address" value={profile?.email} reason="Email is your login ID and cannot be changed." />
              <div className="form-group">
                <label>Saved Address (default pickup)</label>
                <input value={form.address} onChange={e => set('address', e.target.value)} placeholder="Your address" />
              </div>

              <div className="profile-section-label">Shipping Preferences</div>
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
                <label>Delivery Instructions</label>
                <input value={form.deliveryInstructions} onChange={e => set('deliveryInstructions', e.target.value)} placeholder="e.g. Call on arrival, leave with security" maxLength={200} />
              </div>

              <div className="form-group">
                <label>Address Location on Map</label>
                <LocationPicker value={location} onChange={({ lat, lng, address }) => {
                  setLocation({ lat, lng });
                  if (address && !form.address) set('address', address);
                }} />
              </div>
            </>
          )}

          {/* ── Delivery agent fields ── */}
          {role === 'driver' && (
            <>
              <div className="form-row">
                <div className="form-group">
                  <label>Full Name</label>
                  <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Your name" />
                </div>
                <div className="form-group">
                  <label>Phone Number</label>
                  <input
                    inputMode="numeric" maxLength={10}
                    value={form.phone}
                    onChange={e => set('phone', cleanPhone(e.target.value))}
                    placeholder="9876543210"
                    style={form.phone && !PHONE_RE.test(form.phone) ? { borderColor: 'var(--red)' } : {}}
                  />
                  {form.phone && !PHONE_RE.test(form.phone) && (
                    <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}>
                      <Ic icon={TriangleAlert} /> Must be 10 digits starting with 6–9
                    </span>
                  )}
                </div>
              </div>
              <LockedField label="Email Address" value={profile?.email} reason="Email is your login ID and cannot be changed." />
              <div className="form-row">
                <LockedField label="Vehicle Number" value={profile?.vehicleNo} reason="Vehicle registration is an official record. Contact admin to update." />
                <LockedField label="Driving Licence No." value={profile?.licenseNo} reason="Official document — contact admin to correct." />
              </div>

              <div className="profile-section-label">Vehicle &amp; Availability</div>
              <div className="form-row">
                <div className="form-group">
                  <label>Vehicle Type</label>
                  <select value={form.vehicleType} onChange={e => set('vehicleType', e.target.value)}>
                    {VEHICLE_TYPES.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label>Availability</label>
                  <select value={form.availability} onChange={e => set('availability', e.target.value)}>
                    {AVAILABILITY.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
                  </select>
                </div>
              </div>

              <div className="profile-section-label">Today's Assignment</div>
              <div className="form-group">
                <label>
                  Delivery Zone / Area
                  <span style={{ marginLeft: 8, fontSize: 11, background: '#fef9c3', color: '#854d0e',
                    padding: '2px 8px', borderRadius: 20, fontWeight: 600 }}>
                    Update daily
                  </span>
                </label>
                <input
                  required value={form.assignedArea}
                  onChange={e => set('assignedArea', e.target.value)}
                  placeholder="e.g. Zone B – Sector 14"
                />
                <span style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, display: 'block' }}>
                  Set the area you are covering today so customers and operations can see your assignment.
                </span>
              </div>
            </>
          )}

          {/* ── Admin fields ── */}
          {role === 'admin' && (
            <>
              <div className="form-row">
                <div className="form-group">
                  <label>Full Name</label>
                  <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="Your name" />
                </div>
                <div className="form-group">
                  <label>Organization</label>
                  <input value={form.organization} onChange={e => set('organization', e.target.value)} placeholder="e.g. Shipora Operations" />
                </div>
              </div>
              <LockedField label="Email Address" value={profile?.email} reason="Email is your login ID and cannot be changed." />
            </>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            <button type="submit" className="btn btn-primary" disabled={saving} style={{ minWidth: 140 }}>
              {saving ? 'Saving…' : <><Ic icon={Check} /> Save Changes</>}
            </button>
          </div>
        </form>
      </div>

      {/* ── Change Password Card ── */}
      <div className="card" style={{ padding: '28px 32px' }}>
        <h3 style={{ fontSize: 17, fontWeight: 700, marginBottom: 6, color: 'var(--text)', borderBottom: '1px solid var(--border)', paddingBottom: 12 }}>
          Change Password
        </h3>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 20 }}>
          You must enter your current password to set a new one.
        </p>

        <Flash type={pwFlash.type} msg={pwFlash.msg} onClose={() => setPwFlash({ type: '', msg: '' })} />

        <form onSubmit={handlePasswordChange}>
          <div className="form-group">
            <label>Current Password</label>
            <div style={{ position: 'relative' }}>
              <input
                required type={showPw ? 'text' : 'password'}
                value={pwForm.current}
                onChange={e => setPwForm(p => ({ ...p, current: e.target.value }))}
                placeholder="Enter current password"
                style={{ paddingRight: 44 }}
              />
              <button type="button" onClick={() => setShowPw(v => !v)} style={{
                position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
                background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--muted)',
              }}>
                {showPw ? <Ic icon={EyeOff} /> : <Ic icon={Eye} />}
              </button>
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>New Password</label>
              <input
                required type={showPw ? 'text' : 'password'} minLength={6}
                value={pwForm.next}
                onChange={e => setPwForm(p => ({ ...p, next: e.target.value }))}
                placeholder="At least 6 characters"
              />
            </div>
            <div className="form-group">
              <label>Confirm New Password</label>
              <input
                required type={showPw ? 'text' : 'password'} minLength={6}
                value={pwForm.confirm}
                onChange={e => setPwForm(p => ({ ...p, confirm: e.target.value }))}
                placeholder="Re-enter new password"
                style={pwForm.confirm && pwForm.confirm !== pwForm.next ? { borderColor: 'var(--red)' } : {}}
              />
              {pwForm.confirm && pwForm.confirm !== pwForm.next && (
                <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}><Ic icon={TriangleAlert} /> Passwords do not match</span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button type="submit" className="btn btn-ghost" disabled={pwSaving} style={{ minWidth: 160 }}>
              {pwSaving ? 'Updating…' : <><Ic icon={KeyRound} /> Change Password</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
