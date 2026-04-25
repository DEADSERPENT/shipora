import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ROLE_META = {
  user:   { label: '🏠 Resident', color: '#4db84d' },
  driver: { label: '🚛 Driver',   color: '#f59e0b' },
  admin:  { label: '🏢 Admin',    color: '#7c3aed' },
};

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate('/login'); };
  const meta = user ? (ROLE_META[user.role] || ROLE_META.user) : null;

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000,
      background: 'linear-gradient(90deg, #1a3a1a 0%, #2d7a2d 100%)',
      boxShadow: '0 2px 16px rgba(0,0,0,0.25)',
      height: 64, display: 'flex', alignItems: 'center',
    }}>
      <div style={{
        maxWidth: 1280, margin: '0 auto', padding: '0 20px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        width: '100%',
      }}>
        {/* Logo */}
        <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
          <span style={{ fontSize: 28, filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' }}>♻️</span>
          <div>
            <div style={{ color: '#fff', fontWeight: 800, fontSize: 20, letterSpacing: '-0.5px' }}>EcoTrack</div>
            <div style={{ color: '#86efac', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Waste Disposal System
            </div>
          </div>
        </Link>

        {/* Right */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {user ? (
            <>
              <div style={{ textAlign: 'right' }}>
                <div style={{ color: '#fff', fontWeight: 700, fontSize: 14 }}>{user.name}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: meta?.color, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  {meta?.label}
                  {user.role === 'admin' && user.organization && (
                    <span style={{ color: '#86efac', marginLeft: 4 }}>· {user.organization}</span>
                  )}
                </div>
              </div>
              <Link to="/support" style={{
                background: 'rgba(255,255,255,0.12)', color: '#86efac',
                textDecoration: 'none', padding: '7px 14px', borderRadius: 8,
                fontSize: 13, fontWeight: 600, border: '1px solid rgba(134,239,172,0.3)',
                transition: 'background 0.2s',
              }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.22)'}
                onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.12)'}
              >
                🎧 Support
              </Link>
              <Link to="/profile" style={{
                background: 'rgba(255,255,255,0.12)', color: '#fff',
                textDecoration: 'none', padding: '7px 14px', borderRadius: 8,
                fontSize: 13, fontWeight: 600, border: '1px solid rgba(255,255,255,0.2)',
                transition: 'background 0.2s',
              }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.22)'}
                onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.12)'}
              >
                👤 Profile
              </Link>
              <button
                onClick={handleLogout}
                style={{
                  background: 'rgba(239,68,68,0.85)', color: '#fff',
                  border: 'none', padding: '7px 16px', borderRadius: 8,
                  fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  transition: 'background 0.2s',
                }}
                onMouseEnter={e => e.target.style.background = 'rgba(220,38,38,0.95)'}
                onMouseLeave={e => e.target.style.background = 'rgba(239,68,68,0.85)'}
              >
                Sign Out
              </button>
            </>
          ) : (
            <>
              <Link to="/login" style={{
                background: '#4db84d', color: '#fff', textDecoration: 'none',
                padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600,
              }}>
                Login
              </Link>
              <Link to="/register" style={{
                background: 'transparent', color: '#4db84d', textDecoration: 'none',
                padding: '7px 17px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                border: '1.5px solid #4db84d',
              }}>
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
