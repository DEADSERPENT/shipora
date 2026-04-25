import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';

const API = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

const ROLES = [
  { key: 'user',   label: '🏠 Resident' },
  { key: 'driver', label: '🚛 Driver' },
  { key: 'admin',  label: '🏢 Admin' },
];

export default function ForgotPassword() {
  const navigate = useNavigate();

  const [step,        setStep]       = useState(1); // 1 = find account, 2 = set password
  const [role,        setRole]       = useState('user');
  const [email,       setEmail]      = useState('');
  const [newPassword, setNewPassword]= useState('');
  const [confirmPw,   setConfirmPw]  = useState('');
  const [showPw,      setShowPw]     = useState(false);
  const [loading,     setLoading]    = useState(false);
  const [error,       setError]      = useState('');
  const [success,     setSuccess]    = useState('');

  // Step 1: verify email exists
  const handleFindAccount = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await axios.post(`${API}/auth/forgot-password`, { email, role });
      setStep(2);
    } catch (err) {
      setError(err.response?.data?.message || 'Could not verify account. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: reset password
  const handleReset = async (e) => {
    e.preventDefault();
    setError('');
    if (newPassword.length < 6) { setError('Password must be at least 6 characters.'); return; }
    if (newPassword !== confirmPw) { setError('Passwords do not match.'); return; }
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/auth/reset-password`, { email, role, newPassword });
      setSuccess(data.message);
      setTimeout(() => navigate('/login'), 2500);
    } catch (err) {
      setError(err.response?.data?.message || 'Password reset failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-center">
      <div style={{ width: '100%', maxWidth: 440 }}>
        {/* Branding */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 60, marginBottom: 8, filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.3))' }}>♻️</div>
          <h1 style={{ color: '#fff', fontSize: 30, fontWeight: 800, marginBottom: 4, letterSpacing: '-0.5px' }}>
            EcoTrack
          </h1>
          <p style={{ color: '#86efac', fontSize: 14 }}>Daily Waste Disposal Management System</p>
        </div>

        <div className="card" style={{ padding: '32px 36px' }}>
          {/* Progress steps */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
            <StepDot n={1} active={step === 1} done={step > 1} label="Find Account" />
            <div style={{ flex: 1, height: 2, background: step > 1 ? 'var(--green-600)' : 'var(--border)', borderRadius: 2, transition: 'background 0.3s' }} />
            <StepDot n={2} active={step === 2} done={false} label="New Password" />
          </div>

          <h2 style={{ fontSize: 20, fontWeight: 700, color: '#1a3a1a', marginBottom: 6 }}>
            {step === 1 ? 'Forgot Password' : 'Set New Password'}
          </h2>
          <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 20 }}>
            {step === 1
              ? 'Select your role and enter your registered email.'
              : `Creating new password for ${email}`}
          </p>

          {error   && <div className="alert alert-error">{error}</div>}
          {success && <div className="alert alert-success">{success} Redirecting to login…</div>}

          {/* ── Step 1 ── */}
          {step === 1 && !success && (
            <form onSubmit={handleFindAccount}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
                {ROLES.map(r => (
                  <button key={r.key} type="button" onClick={() => setRole(r.key)}
                    style={{
                      flex: 1, padding: '9px 4px',
                      border: role === r.key ? '2px solid var(--green-700)' : '2px solid var(--border)',
                      borderRadius: 10,
                      background: role === r.key ? 'var(--green-50)' : '#fff',
                      color: role === r.key ? 'var(--green-700)' : 'var(--muted)',
                      fontWeight: 700, fontSize: 12, cursor: 'pointer', transition: 'all 0.18s',
                    }}
                  >
                    {r.label}
                  </button>
                ))}
              </div>

              <div className="form-group">
                <label>Registered Email</label>
                <input
                  type="email" required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com"
                />
              </div>

              <button type="submit" className="btn btn-primary btn-lg" style={{ marginTop: 8 }} disabled={loading}>
                {loading ? 'Verifying…' : 'Find My Account →'}
              </button>
            </form>
          )}

          {/* ── Step 2 ── */}
          {step === 2 && !success && (
            <form onSubmit={handleReset}>
              <div className="form-group">
                <label>New Password</label>
                <div style={{ position: 'relative' }}>
                  <input
                    required
                    type={showPw ? 'text' : 'password'}
                    minLength={6}
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    placeholder="At least 6 characters"
                    style={{ paddingRight: 44 }}
                  />
                  <button type="button" onClick={() => setShowPw(p => !p)}
                    style={{
                      position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
                      background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--muted)',
                    }}
                  >
                    {showPw ? '🙈' : '👁'}
                  </button>
                </div>
              </div>

              <div className="form-group">
                <label>Confirm New Password</label>
                <input
                  required
                  type={showPw ? 'text' : 'password'}
                  minLength={6}
                  value={confirmPw}
                  onChange={e => setConfirmPw(e.target.value)}
                  placeholder="Re-enter new password"
                  style={confirmPw && confirmPw !== newPassword ? { borderColor: 'var(--red)' } : {}}
                />
                {confirmPw && confirmPw !== newPassword && (
                  <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}>
                    ⚠ Passwords do not match
                  </span>
                )}
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
                <button type="button" className="btn btn-ghost" style={{ flex: 1 }}
                  onClick={() => { setStep(1); setError(''); setNewPassword(''); setConfirmPw(''); }}
                >
                  ← Back
                </button>
                <button type="submit" className="btn btn-primary" style={{ flex: 2 }} disabled={loading}>
                  {loading ? 'Resetting…' : 'Reset Password'}
                </button>
              </div>
            </form>
          )}

          <p style={{ textAlign: 'center', marginTop: 20, fontSize: 14, color: '#6b8f6b' }}>
            Remember your password?{' '}
            <Link to="/login" style={{ color: '#2d7a2d', fontWeight: 700 }}>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function StepDot({ n, active, done, label }) {
  const bg = done ? 'var(--green-600)' : active ? 'var(--green-700)' : 'var(--border)';
  const color = (done || active) ? '#fff' : 'var(--muted)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <div style={{
        width: 28, height: 28, borderRadius: '50%', background: bg, color,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 13, fontWeight: 700, transition: 'background 0.3s',
      }}>
        {done ? '✓' : n}
      </div>
      <span style={{ fontSize: 10, color: active ? 'var(--green-700)' : 'var(--muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>
        {label}
      </span>
    </div>
  );
}
