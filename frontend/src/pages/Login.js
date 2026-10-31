import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import AuthShell from '../components/AuthShell';
import { ROLE_LABELS, apiError, roleHome } from '../lib/shipora';
import { Ic } from '../components/Icon';
import PasswordInput from '../components/PasswordInput';

const ROLES = ['user', 'driver', 'admin'].map(key => ({ key, ...ROLE_LABELS[key] }));
const SHORT = { user: 'Customer', driver: 'Rider', admin: 'Operations' };

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
      navigate(roleHome(user.role));
    } catch (err) {
      setError(apiError(err, 'Login failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  const active = ROLES.find(r => r.key === role);

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to send parcels and track your deliveries."
      footer={<>New to Shipora? <Link to="/register">Create an account</Link></>}
    >
      <div className="auth-seg" role="radiogroup" aria-label="Sign in as">
        {ROLES.map(r => (
          <button key={r.key} type="button" role="radio" aria-checked={role === r.key}
            className={role === r.key ? 'on' : ''} onClick={() => setRole(r.key)}>
            <Ic icon={r.icon} size={15} /> {SHORT[r.key]}
          </button>
        ))}
      </div>
      {role !== 'user' && <p className="auth-hint">{active.desc}</p>}

      {error && <div className="alert alert-error" role="alert">{error}</div>}

      <form onSubmit={handleSubmit} className="auth-fields">
        <div className="form-group">
          <label htmlFor="login-email">Email</label>
          <input id="login-email" type="email" required autoComplete="email" value={email}
            onChange={e => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <div className="form-group">
          <div className="auth-label-row">
            <label htmlFor="login-password">Password</label>
            <Link to="/forgot-password">Forgot password?</Link>
          </div>
          <PasswordInput id="login-password" required autoComplete="current-password" value={password}
            onChange={e => setPassword(e.target.value)} placeholder="Your password" />
        </div>
        <button type="submit" className="auth-submit" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthShell>
  );
}
