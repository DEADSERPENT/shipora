import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Bike, Check, ChevronDown, MapPin, Navigation, Phone } from 'lucide-react';
import { Ic } from './Icon';
import { findArea } from '../lib/areas';
import { fmtEta, fmtINR, getEstimate } from '../lib/estimate';

// ── Hero product shot ────────────────────────────────────────────────────────────────────────────────
// A static illustration of the live order screen (components/LiveOrderHero.js) — shows what booking gets you.
export function HeroOrderMock() {
  const steps = ['Booked', 'Assigned', 'Picked up', 'On the way', 'Delivered'];
  return (
    <div className="lp-mock" aria-hidden="true">
      <div className="lp-mock-map">
        <svg viewBox="0 0 400 190" preserveAspectRatio="xMidYMid slice">
          <rect width="400" height="190" fill="#eef3ea" />
          <g stroke="#dfe7da" strokeWidth="10" fill="none" strokeLinecap="round">
            <path d="M-10 150 L120 120 L230 140 L410 60" /><path d="M60 -10 L90 90 L70 200" /><path d="M250 -10 L240 90 L300 200" /><path d="M-10 60 L200 70 L410 120" />
          </g>
          <g fill="#d9e9d3"><rect x="140" y="20" width="70" height="36" rx="8" /><rect x="300" y="110" width="64" height="40" rx="8" /><rect x="14" y="96" width="44" height="34" rx="8" /></g>
          <path d="M70 150 C 130 120, 170 130, 235 96 S 320 50, 345 44" stroke="#0c831f" strokeWidth="5" fill="none" strokeLinecap="round" strokeDasharray="1 11" />
          <path d="M70 150 C 130 120, 170 130, 205 112" stroke="#0c831f" strokeWidth="5" fill="none" strokeLinecap="round" />
          <circle cx="70" cy="150" r="8" fill="#fff" stroke="#14201a" strokeWidth="4" />
          <g transform="translate(345 44)"><circle r="11" fill="#14201a" /><circle r="4" fill="#f8cb46" /></g>
          <g transform="translate(205 112)"><circle r="16" fill="#f8cb46" opacity=".35" /><circle r="11" fill="#f8cb46" stroke="#14201a" strokeWidth="3" /></g>
        </svg>
        <span className="lp-mock-tag">Live tracking · example</span>
      </div>
      <div className="lp-mock-body">
        <div className="lp-mock-row"><span className="lp-mock-pill">Out for delivery</span><span className="lp-mock-id">SHP48217390</span></div>
        <div className="lp-mock-eta">Arriving in 12 min</div>
        <div className="lp-mock-route"><Ic icon={MapPin} size={14} /> Koramangala <Ic icon={ArrowRight} size={13} /> Indiranagar</div>
        <ol className="lp-mock-steps">
          {steps.map((s, i) => (
            <li key={s} className={i < 3 ? 'done' : i === 3 ? 'now' : ''}><span>{i < 3 ? <Ic icon={Check} size={11} strokeWidth={3.2} /> : i === 3 ? <Ic icon={Navigation} size={11} strokeWidth={3} /> : null}</span><em>{s}</em></li>
          ))}
        </ol>
        <div className="lp-mock-rider"><span className="lp-mock-av">RK</span><div><b>Ravi K.</b><small>KA01 · bike</small></div><span className="lp-mock-call"><Ic icon={Phone} size={13} /> Call</span></div>
      </div>
    </div>
  );
}

// ── Live fares ───────────────────────────────────────────────────────────────────────────────────────
// Real quotes from the pricing endpoint, not copy someone has to remember to update.
const ROUTES = [
  { from: 'Koramangala', to: 'Indiranagar', kg: 1, what: 'Documents' },
  { from: 'HSR Layout',  to: 'BTM Layout',  kg: 2, what: 'A forgotten charger' },
  { from: 'Jayanagar',   to: 'Whitefield',  kg: 5, what: 'A gift box' },
];

export function FareExamples({ onPick }) {
  const [quotes, setQuotes] = useState([]);
  useEffect(() => {
    let live = true;
    Promise.allSettled(ROUTES.map(async (r) => {
      const a = findArea(r.from), b = findArea(r.to);
      if (!a || !b) throw new Error('unknown area');
      return { ...r, quote: await getEstimate(a, b, r.kg) };
    })).then(res => { if (live) setQuotes(res.filter(x => x.status === 'fulfilled').map(x => x.value)); });
    return () => { live = false; };
  }, []);

  if (!quotes.length) return null;     // the section simply doesn't appear if the API is unreachable
  return (
    <div className="lp-fares">
      {quotes.map(({ from, to, kg, what, quote }) => (
        <button type="button" key={from + to} className="lp-fare" onClick={() => onPick && onPick(from, to, kg)}>
          <span className="lp-fare-what">{what} · {kg} kg</span>
          <span className="lp-fare-route">{from} <Ic icon={ArrowRight} size={14} /> {to}</span>
          <span className="lp-fare-price">{fmtINR(quote.fare)}</span>
          <span className="lp-fare-meta">{quote.distanceKm} km · about {fmtEta(quote.etaMinutes)}</span>
        </button>
      ))}
    </div>
  );
}

// ── Riders ───────────────────────────────────────────────────────────────────────────────────────────
export function RiderBand() {
  return (
    <div className="lp-rider">
      <span className="lp-rider-ico"><Ic icon={Bike} size={28} /></span>
      <div>
        <h3>Ride with Shipora</h3>
        <p>Got a bike and a smartphone? Deliver parcels around Bengaluru on your own schedule, with live navigation and one-tap status updates.</p>
      </div>
      <Link to="/register" className="lp-btn lp-btn-dark">Become a delivery partner <Ic icon={ArrowRight} size={16} strokeWidth={2.6} /></Link>
    </div>
  );
}

// ── FAQ ──────────────────────────────────────────────────────────────────────────────────────────────
export function Faq({ items }) {
  const [open, setOpen] = useState(0);
  return (
    <div className="lp-faq">
      {items.map((f, i) => (
        <div key={f.q} className={`lp-faq-item ${open === i ? 'open' : ''}`}>
          <button type="button" aria-expanded={open === i} onClick={() => setOpen(open === i ? -1 : i)}>
            <span>{f.q}</span><Ic icon={ChevronDown} size={18} />
          </button>
          {open === i && <div className="lp-faq-a">{f.a}</div>}
        </div>
      ))}
    </div>
  );
}

// ── Footer ───────────────────────────────────────────────────────────────────────────────────────────
export function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-footer-grid">
        <div>
          <div className="lp-footer-brand">shipora</div>
          <p>Same-day parcel delivery across Bengaluru. Book in a minute, follow your rider live, pay on delivery.</p>
        </div>
        <nav aria-label="Product">
          <h4>Product</h4>
          <Link to="/register">Send a parcel</Link>
          <Link to="/track">Track a parcel</Link>
          <Link to="/#fares">Pricing</Link>
        </nav>
        <nav aria-label="Company">
          <h4>Company</h4>
          <Link to="/register">Become a delivery partner</Link>
          <Link to="/support">Support</Link>
          <Link to="/login">Log in</Link>
        </nav>
      </div>
      <div className="lp-footer-base">© {new Date().getFullYear()} Shipora · Same-day parcel delivery in Bengaluru</div>
    </footer>
  );
}
