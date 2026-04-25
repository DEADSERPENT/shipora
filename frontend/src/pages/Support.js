import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';

const API = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

const FAQS = [
  { q: 'Why didn\'t the waste collection vehicle come today?',
    a: 'Vehicles may be delayed due to traffic, route changes, or higher volumes. Check the Live Tracking map on your dashboard to see real-time vehicle positions. If missed completely, please raise a complaint.' },
  { q: 'How do I know when the vehicle will arrive near my house?',
    a: 'Open your Resident Dashboard — you\'ll see the nearest active vehicle and its estimated arrival time. You\'ll also see a proximity alert when a truck is within 3 km of your home.' },
  { q: 'What waste types are accepted?',
    a: 'Household waste, recyclables (paper, plastic, glass, metal), organic/kitchen waste, and mixed waste. Hazardous items (batteries, chemicals, e-waste) are NOT accepted via regular pickup.' },
  { q: 'How do I change my pickup schedule?',
    a: 'Go to Profile → Collection Preferences. You can switch between Daily, Alternate Days, or Weekly pickup. Changes take effect from the next collection cycle.' },
  { q: 'Can I update my home location?',
    a: 'Yes — go to Profile → Home Location on Map. Use the search bar, pincode lookup, or GPS to update your location. This ensures vehicles know your exact address.' },
  { q: 'How do I track the driver\'s route?',
    a: 'The dashboard map shows all active vehicles in real time. When a vehicle comes within 3 km of your location, a route line appears showing the road path to your home.' },
  { q: 'What happens to my complaint after I submit it?',
    a: 'Your complaint is sent directly to the admin team. They will review it and respond within 48 hours. You can track the status (Open → In Progress → Resolved) in the Complaint Box.' },
  { q: 'How do I separate waste before collection?',
    a: 'Use separate bins for: Green bin (organic/wet waste), Blue bin (dry recyclables), Black bin (non-recyclable). Label bags clearly. Drivers appreciate pre-sorted waste.' },
];

function FAQ({ q, a }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <button type="button" onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', padding: '14px 20px',
        background: 'none', border: 'none', cursor: 'pointer',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        transition: 'background 0.15s',
      }}
        onMouseEnter={e => e.currentTarget.style.background = 'var(--green-50)'}
        onMouseLeave={e => e.currentTarget.style.background = 'none'}
      >
        <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', paddingRight: 16 }}>{q}</span>
        <span style={{ fontSize: 18, color: 'var(--green-600)', transition: 'transform 0.2s', transform: open ? 'rotate(45deg)' : 'none', flexShrink: 0 }}>+</span>
      </button>
      {open && (
        <div style={{ padding: '0 20px 16px', fontSize: 14, color: 'var(--muted)', lineHeight: 1.7, background: 'var(--green-50)' }}>
          {a}
        </div>
      )}
    </div>
  );
}

export default function Support() {
  const { user } = useAuth();
  const [config, setConfig] = useState(null);

  useEffect(() => {
    axios.get(`${API}/support/config`)
      .then(({ data }) => setConfig(data))
      .catch(() => {});
  }, []);

  const phone         = config?.phone         || '1800-ECO-TRACK';
  const email         = config?.email         || 'support@ecotrack.in';
  const whatsapp      = config?.whatsapp      || '+91 98765 43210';
  const officeAddress = config?.officeAddress || 'City Municipal Office, Ground Floor';
  const officeHours   = config?.officeHours   || 'Mon – Fri · 9 AM – 5 PM';

  return (
    <div className="page" style={{ maxWidth: 860, margin: '0 auto' }}>
      <BackButton />

      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 36 }}>
        <div style={{ fontSize: 52, marginBottom: 10 }}>🎧</div>
        <h1 style={{ fontSize: 26, fontWeight: 800, color: 'var(--text)', marginBottom: 6 }}>Customer Care & Support</h1>
        <p style={{ color: 'var(--muted)', fontSize: 14, maxWidth: 480, margin: '0 auto' }}>
          We're here to help. Find answers below or reach us directly through one of our support channels.
        </p>
      </div>

      {/* Contact Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 32 }}>
        {[
          { icon: '📞', title: 'Helpline (24/7)',  detail: phone,         sub: 'Toll free · Always available',    color: '#2d7a2d', bg: '#e8f5e8' },
          { icon: '📧', title: 'Email Support',    detail: email,         sub: 'Reply within 24 hours',           color: '#2563eb', bg: '#eff6ff' },
          { icon: '💬', title: 'WhatsApp',         detail: whatsapp,      sub: 'Mon – Sat · 8 AM – 8 PM',        color: '#16a34a', bg: '#f0fdf4' },
          { icon: '🏢', title: 'Municipal Office', detail: officeAddress, sub: officeHours,                       color: '#7c3aed', bg: '#f3e8ff' },
        ].map(c => (
          <div key={c.title} className="card" style={{ borderTop: `4px solid ${c.color}`, textAlign: 'center', padding: '20px 16px', transition: 'transform 0.2s, box-shadow 0.2s' }}
            onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.boxShadow = '0 8px 24px rgba(0,0,0,0.12)'; }}
            onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}
          >
            <div style={{ fontSize: 32, marginBottom: 8 }}>{c.icon}</div>
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>{c.title}</div>
            <div style={{ fontWeight: 700, color: c.color, fontSize: 14, marginBottom: 4, wordBreak: 'break-word' }}>{c.detail}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      {user && (
        <div className="card" style={{ marginBottom: 28, padding: '20px 24px' }}>
          <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 14, color: 'var(--text)' }}>Quick Actions</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {user.role === 'user' && <>
              <Link to="/complaints" className="btn btn-ghost btn-sm">📣 Submit Complaint</Link>
              <Link to="/collection-log" className="btn btn-ghost btn-sm">🗓️ Collection Log</Link>
              <Link to="/profile" className="btn btn-ghost btn-sm">👤 Update Profile</Link>
              <Link to="/dashboard" className="btn btn-ghost btn-sm">🗺️ Live Tracking</Link>
            </>}
            {user.role === 'driver' && <>
              <Link to="/driver-history" className="btn btn-ghost btn-sm">📋 Collection History</Link>
              <Link to="/profile" className="btn btn-ghost btn-sm">👤 My Profile</Link>
            </>}
            {user.role === 'admin' && <>
              <Link to="/admin" className="btn btn-ghost btn-sm">📊 Admin Dashboard</Link>
              <Link to="/profile" className="btn btn-ghost btn-sm">👤 My Profile</Link>
            </>}
          </div>
        </div>
      )}

      {/* Working Hours */}
      <div className="card" style={{ marginBottom: 28, padding: '20px 24px' }}>
        <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 14, color: 'var(--text)' }}>🕐 Collection Service Hours</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { day: 'Monday – Friday',  time: '6:00 AM – 12:00 PM', note: 'Regular routes' },
            { day: 'Saturday',         time: '6:00 AM – 10:00 AM', note: 'Half day' },
            { day: 'Sunday',           time: 'Emergency only',      note: 'Call helpline' },
            { day: 'Public Holidays',  time: 'Reduced service',     note: 'Check app for updates' },
          ].map(h => (
            <div key={h.day} style={{ background: 'var(--green-50)', borderRadius: 8, padding: '12px 14px', border: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--text)' }}>{h.day}</div>
              <div style={{ fontSize: 14, color: 'var(--green-700)', fontWeight: 600, margin: '3px 0' }}>{h.time}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>{h.note}</div>
            </div>
          ))}
        </div>
      </div>

      {/* FAQ */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
          <h3 style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>❓ Frequently Asked Questions</h3>
        </div>
        {FAQS.map((f, i) => <FAQ key={i} q={f.q} a={f.a} />)}
      </div>

      <p style={{ textAlign: 'center', marginTop: 28, fontSize: 13, color: 'var(--muted)' }}>
        EcoTrack Waste Disposal System · Version 1.0 · Made with ♻️
      </p>
    </div>
  );
}
