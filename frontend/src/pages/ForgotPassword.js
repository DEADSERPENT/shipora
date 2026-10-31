import React, { useState } from 'react';
import AuthShell from '../components/AuthShell';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Check, Eye, EyeOff, TriangleAlert } from 'lucide-react';
import { Ic } from '../components/Icon';

const API = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

const ROLES = [
  { key: 'user',   label: 'Customer' },
  { key: 'driver', label: 'Delivery Agent' },
];

export default function ForgotPassword() {
  const navigate = useNavigate();

  const [step,        setStep]       = useState(1); // 1 = find account, 2 = set password
  const [role,        setRole]       = useState('user');
  const [email,       setEmail]      = useState('');
  const [resetToken,  setResetToken] = useState('');
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
      const { data } = await axios.post(`${API}/auth/forgot-password`, { email, role });
      if (data.resetToken) {
        setResetToken(data.resetToken);   // development: handed back directly (no e-mail service yet)
        setStep(2);
      } else {
        setSuccess(data.message);          // production: instructions go out by e-mail, nothing to continue with here
      }
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
      const { data } = await axios.post(`${API}/auth/reset-password`, { email, role, newPassword, resetToken });
      setSuccess(data.message);
      setTimeout(() => navigate('/login'), 2500);
    } catch (err) {
      setError(err.response?.data?.message || 'Password reset failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Reset your password" subtitle="We'll check your account, then let you choose a new password.">
        <div>
          {/* Progress steps */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
            <StepDot n={1} active={step === 1} done={step > 1} label="Find Account" />
            <div style={{ flex: 1, height: 2, background: step > 1 ? 'var(--brand-600)' : 'var(--border)', borderRadius: 2, transition: 'background 0.3s' }} />
            <StepDot n={2} active={step === 2} done={false} label="New Password" />
          </div>

          <h2 style={{ fontSize: 20, fontWeight: 700, color: '#0a3d14', marginBottom: 6 }}>
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
                      border: role === r.key ? '2px solid var(--brand-700)' : '2px solid var(--border)',
                      borderRadius: 10,
                      background: role === r.key ? 'var(--brand-50)' : '#fff',
                      color: role === r.key ? 'var(--brand-700)' : 'var(--muted)',
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
                    {showPw ? <Ic icon={EyeOff} /> : <Ic icon={Eye} />}
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
                    <Ic icon={TriangleAlert} /> Passwords do not match
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

          <p style={{ textAlign: 'center', marginTop: 20, fontSize: 14, color: '#64748b' }}>
            Remember your password?{' '}
            <Link to="/login" style={{ color: '#0c831f', fontWeight: 700 }}>Sign in</Link>
          </p>
        </div>
    </AuthShell>
  );
}

function StepDot({ n, active, done, label }) {
  const bg = done ? 'var(--brand-600)' : active ? 'var(--brand-700)' : 'var(--border)';
  const color = (done || active) ? '#fff' : 'var(--muted)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <div style={{
        width: 28, height: 28, borderRadius: '50%', background: bg, color,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 13, fontWeight: 700, transition: 'background 0.3s',
      }}>
        {done ? <Ic icon={Check} size={15} strokeWidth={3} /> : n}
      </div>
      <span style={{ fontSize: 10, color: active ? 'var(--brand-700)' : 'var(--muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>
        {label}
      </span>
    </div>
  );
}
