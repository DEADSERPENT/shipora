import React from 'react';
import { Link } from 'react-router-dom';
import { Check, MapPin, Phone, Zap } from 'lucide-react';
import { Ic } from './Icon';

// Split-screen layout for sign in / register / reset: a calm form on the left, the product on the right. The panel is
// the same live-order card the customer will see after booking, so the sign-up page already shows what they are signing up for.
const POINTS = ['See the fare before you book', 'Follow your rider live on the map', 'Pay by cash or UPI on delivery'];

export function BrandPanel() {
  return (
    <aside className="auth-panel" aria-hidden="true">
      <div className="auth-panel-inner">
        <h2>Same-day delivery,<br />across Bengaluru.</h2>
        <ul className="auth-points">
          {POINTS.map(p => <li key={p}><span><Ic icon={Check} size={13} strokeWidth={3} /></span>{p}</li>)}
        </ul>
        <div className="auth-mock">
          <div className="auth-mock-top"><span className="auth-mock-pill">Out for delivery</span><span className="auth-mock-id">SHP48217390</span></div>
          <div className="auth-mock-eta">Arriving in 12 min</div>
          <div className="auth-mock-route"><Ic icon={MapPin} size={14} /> Koramangala <i /> Indiranagar</div>
          <div className="auth-mock-bar"><div /></div>
          <div className="auth-mock-rider"><span>RK</span><div><b>Ravi K.</b><small>KA01 · bike</small></div><em><Ic icon={Phone} size={13} /> Call</em></div>
        </div>
        <p className="auth-panel-note">Illustrative example</p>
      </div>
    </aside>
  );
}

export default function AuthShell({ title, subtitle, children, wide = false, footer }) {
  return (
    <div className={`auth ${wide ? 'auth-wide' : ''}`}>
      <div className="auth-form-side">
        <div className="auth-form">
          <Link to="/" className="auth-logo" aria-label="Shipora home">
            <span className="pnav-mark"><Ic icon={Zap} size={18} strokeWidth={2.8} /></span>
            <span className="pnav-word">shipora</span>
          </Link>
          <h1 className="auth-title">{title}</h1>
          {subtitle && <p className="auth-sub">{subtitle}</p>}
          {children}
          {footer && <p className="auth-foot">{footer}</p>}
        </div>
      </div>
      {!wide && <BrandPanel />}
    </div>
  );
}
