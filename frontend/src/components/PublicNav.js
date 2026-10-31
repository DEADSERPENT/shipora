import React, { useEffect, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Menu, X, Zap } from 'lucide-react';
import { Ic } from './Icon';

// Navigation for signed-out visitors. A marketing site's nav answers "what is this, what does it cost, how do I start":
// a few destinations, one primary action. (The signed-in app keeps its own bar: search, send parcel, profile.)
const LINKS = [
  { to: '/#how',      label: 'How it works' },
  { to: '/#fares',    label: 'Pricing' },
  { to: '/track',     label: 'Track a parcel' },
  { to: '/support',   label: 'Support' },
];

export default function PublicNav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);

  return (
    <header className={`pnav ${scrolled || open ? 'pnav-solid' : ''}`}>
      <div className="pnav-inner">
        <Link to="/" className="pnav-logo" aria-label="Shipora home">
          <span className="pnav-mark"><Ic icon={Zap} size={18} strokeWidth={2.8} /></span>
          <span className="pnav-word">shipora</span>
        </Link>

        <nav className={`pnav-links ${open ? 'open' : ''}`} aria-label="Main">
          {LINKS.map(l => (
            l.to.includes('#')
              ? <Link key={l.to} to={l.to}>{l.label}</Link>
              : <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? 'active' : '')}>{l.label}</NavLink>
          ))}
          <div className="pnav-cta-mobile">
            <Link to="/login" className="pnav-login">Log in</Link>
            <Link to="/register" className="pnav-start">Get started</Link>
          </div>
        </nav>

        <div className="pnav-cta">
          <Link to="/login" className="pnav-login">Log in</Link>
          <Link to="/register" className="pnav-start">Get started</Link>
        </div>

        <button type="button" className="pnav-burger" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} onClick={() => setOpen(o => !o)}>
          <Ic icon={open ? X : Menu} size={22} />
        </button>
      </div>
    </header>
  );
}
