import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import PublicNav from './PublicNav';
import { useAuth } from '../context/AuthContext';
import { ROLE_LABELS } from '../lib/shipora';
import { ChevronDown, Headset, History, LayoutDashboard, MapPin, Package, Route, Search, User, Zap } from 'lucide-react';
import { Ic } from './Icon';

// Quick-commerce style bar (Blinkit / Zepto): logo, "delivery in …" locator, a wide search bar (here: track by
// tracking number) and the account actions. Styles live in index.css under .nav-*.
function AppNav() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [cityOpen, setCityOpen] = useState(false);
  const cityRef = useRef(null);

  useEffect(() => {
    const close = (e) => { if (cityRef.current && !cityRef.current.contains(e.target)) setCityOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const handleLogout = () => { logout(); navigate('/login'); };
  const meta = user ? (ROLE_LABELS[user.role] || ROLE_LABELS.user) : null;
  const isCustomer = user?.role === 'user';
  const isAdmin = user?.role === 'admin';

  const onSearch = (e) => {
    e.preventDefault();
    const tn = query.trim().toUpperCase();
    navigate(tn ? `/track/${encodeURIComponent(tn)}` : '/track');
    setQuery('');
  };

  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link to="/" aria-label="Shipora home" className="nav-logo">
          <span className="nav-logo-mark"><Ic icon={Zap} size={20} strokeWidth={2.6} /></span>
          <span className="nav-logo-word">shipora</span>
        </Link>

        {isCustomer && (
          <>
        <div className="nav-locator" ref={cityRef}>
          <div className="nav-locator-top"><Ic icon={Zap} size={13} strokeWidth={2.6} /> Same-day delivery</div>
          <button type="button" className="nav-locator-city" onClick={() => setCityOpen(o => !o)} aria-expanded={cityOpen}>
            Bengaluru, Karnataka <Ic icon={ChevronDown} size={14} />
          </button>
          {cityOpen && (
            <div className="nav-pop" role="dialog" aria-label="Delivery area">
              <div className="nav-pop-title"><Ic icon={MapPin} size={15} /> Delivering in Bengaluru</div>
              <p>Pickup and drop must both be inside Bengaluru. More cities coming soon.</p>
            </div>
          )}
        </div>

        <form className="nav-search" onSubmit={onSearch} role="search">
          <Ic icon={Search} size={18} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder='Track a parcel — try "SHP48217390"'
            aria-label="Tracking number"
            autoComplete="off"
          />
          <button type="submit" className="nav-search-go">Track</button>
        </form>
          </>
        )}
        {!isCustomer && (
          <>
            <div className="nav-role" style={{ '--role': meta?.color }}>
              <span className="nav-role-ico"><Ic icon={meta?.icon} size={15} /></span>
              <div>
                <div className="nav-role-title">{isAdmin ? 'Operations console' : 'Delivery agent'}</div>
                <div className="nav-role-sub">{isAdmin ? (user.organization || 'Bengaluru network') : 'Bengaluru same-day'}</div>
              </div>
            </div>
            <div className="nav-spacer" />
          </>
        )}

        <div className="nav-actions">
          {user ? (
            <>
              {isCustomer && (
                <>
                  <Link to="/shipments/new" className="nav-btn nav-btn-primary"><Ic icon={Package} /> Send parcel</Link>
                  <Link to="/support" className="nav-btn"><Ic icon={Headset} /> <span className="nav-hide-sm">Support</span></Link>
                </>
              )}
              {user.role === 'driver' && (
                <>
                  <Link to="/driver" className="nav-btn nav-btn-primary"><Ic icon={Route} /> My route</Link>
                  <Link to="/agent/history" className="nav-btn"><Ic icon={History} /> <span className="nav-hide-sm">History</span></Link>
                </>
              )}
              {isAdmin && (
                <Link to="/admin" className="nav-btn nav-btn-primary"><Ic icon={LayoutDashboard} /> Dashboard</Link>
              )}
              <Link to="/profile" className="nav-btn"><Ic icon={User} /> <span className="nav-hide-sm">Profile</span></Link>
              <div className="nav-user">
                <div className="nav-user-name">{user.name}</div>
                <div className="nav-user-role" style={{ color: meta?.color }}>
                  <Ic icon={meta?.icon} size={12} /> {meta?.label}
                  {user.role === 'admin' && user.organization && <span style={{ color: 'var(--muted)', marginLeft: 4 }}>· {user.organization}</span>}
                </div>
              </div>
              <button onClick={handleLogout} className="nav-btn nav-btn-dark">Sign Out</button>
            </>
          ) : (
            <>
              <Link to="/login" className="nav-btn nav-btn-primary">Login</Link>
              <Link to="/register" className="nav-btn nav-btn-outline">Register</Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}

// Signed-out visitors get the marketing nav; the auth screens carry their own logo (split-screen layout), so no bar there.
const AUTH_PATHS = ['/login', '/register', '/forgot-password'];

export default function Navbar() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  if (user) return <AppNav />;
  if (AUTH_PATHS.includes(pathname)) return null;
  return <PublicNav />;
}
