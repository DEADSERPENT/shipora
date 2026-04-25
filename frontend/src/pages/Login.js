import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ROLES = [
  { key: 'user',   label: '🏠 Resident',     desc: 'Track waste pickup near your home' },
  { key: 'driver', label: '🚛 Driver',        desc: 'Log your route and share location' },
  { key: 'admin',  label: '🏢 Admin',         desc: 'Monitor all drivers and collections' },
];

export default function Login() {
  const { login }   = useAuth();
  const navigate    = useNavigate();
  const [role,      setRole]     = useState('user');
  const [email,     setEmail]    = useState('');
  const [password,  setPassword] = useState('');
  const [error,     setError]    = useState('');
  const [loading,   setLoading]  = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const user = await login(email, password, role);
      if (user.role === 'driver') navigate('/driver');
      else if (user.role === 'admin') navigate('/admin');
      else navigate('/dashboard');
    } catch (err) {
      setError(err.response?.data?.message || 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const active = ROLES.find(r => r.key === role);

  return (
    <div className="page-center">
      <div style={{ width: '100%', maxWidth: 460 }}>
        {/* Branding */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 60, marginBottom: 8, filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.3))' }}>♻️</div>
          <h1 style={{ color: '#fff', fontSize: 30, fontWeight: 800, marginBottom: 4, letterSpacing: '-0.5px' }}>
            EcoTrack
          </h1>
          <p style={{ color: '#86efac', fontSize: 14 }}>Daily Waste Disposal Management System</p>
        </div>

        <div className="card" style={{ padding: '32px 36px' }}>
          <h2 style={{ marginBottom: 20, fontSize: 20, fontWeight: 700, color: '#1a3a1a' }}>Sign In</h2>

          {/* Role Selector */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 22 }}>
            {ROLES.map(r => (
              <button
                key={r.key}
                type="button"
                onClick={() => setRole(r.key)}
                style={{
                  flex: 1,
                  padding: '9px 4px',
                  border: role === r.key ? '2px solid var(--green-700)' : '2px solid var(--border)',
                  borderRadius: 10,
                  background: role === r.key ? 'var(--green-50)' : '#fff',
                  color: role === r.key ? 'var(--green-700)' : 'var(--muted)',
                  fontWeight: 700,
                  fontSize: 12,
                  cursor: 'pointer',
                  transition: 'all 0.18s',
                }}
              >
                {r.label}
              </button>
            ))}
          </div>

          {active && (
            <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16, marginTop: -12,
              background: 'var(--green-50)', borderRadius: 8, padding: '7px 12px' }}>
              {active.desc}
            </p>
          )}

          {error && <div className="alert alert-error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Email Address</label>
              <input
                type="email" required
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input
                type="password" required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-lg"
              style={{ marginTop: 8 }}
              disabled={loading}
            >
              {loading ? 'Signing in…' : `Sign in as ${active?.label || role}`}
            </button>

            <div style={{ textAlign: 'right', marginTop: 10 }}>
              <Link to="/forgot-password" style={{ fontSize: 13, color: 'var(--muted)', textDecoration: 'none' }}
                onMouseEnter={e => e.target.style.color = 'var(--green-700)'}
                onMouseLeave={e => e.target.style.color = 'var(--muted)'}
              >
                Forgot password?
              </Link>
            </div>
          </form>

          <p style={{ textAlign: 'center', marginTop: 20, fontSize: 14, color: '#6b8f6b' }}>
            Don't have an account?{' '}
            <Link to="/register" style={{ color: '#2d7a2d', fontWeight: 700 }}>Register here</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
