import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';
import { API_URL as API } from '../lib/shipora';
import { Archive, Building2, ChartColumn, ClipboardList, Headset, Mail, Map as MapIcon, Megaphone, MessageCircle, Package, Phone, User } from 'lucide-react';
import { Ic } from '../components/Icon';


const FAQS = [
  { q: 'How do I track my parcel?',
    a: 'Use the Track page (or your dashboard) and enter the tracking number that starts with SHP. You will see the current status, estimated delivery date and the full timeline. Once the parcel is out for delivery, the delivery vehicle is shown live on the map.' },
  { q: 'What do the shipment statuses mean?',
    a: 'Created → Pickup Scheduled → Picked Up → In Transit → Out for Delivery → Delivered. If something goes wrong you may also see Delivery Failed, Receiver Unavailable, Address Issue, Damaged, Cancelled or Returned to Sender.' },
  { q: 'How do I create a shipment?',
    a: 'Sign in as a customer and choose Create Shipment. Enter the pickup address, the receiver and delivery address, the parcel type and weight, and both locations must be inside Bengaluru. Delivery is same-day, and you get a tracking number immediately.' },
  { q: 'Can I cancel a shipment?',
    a: 'Yes — open the shipment and choose Cancel shipment. This is possible until the parcel has been picked up. After pickup, contact support and operations can arrange a return to sender.' },
  { q: 'What happens if nobody is home or the address is wrong?',
    a: 'The delivery agent marks the attempt as Receiver Unavailable or Address Issue. A delivery is attempted up to 3 times; after that the parcel is returned to the sender.' },
  { q: 'How much does a delivery cost, and how do I pay?',
    a: 'The fare is based on distance: a base fare covers the first kilometre, then a fixed rate per extra km, plus a small charge per kg for heavier parcels. You see the exact fare and ETA before you book (on the home page and on the booking form). You pay the rider on delivery, in cash or by UPI.' },
  { q: 'What can I send, and how heavy can it be?',
    a: 'Parcels up to 20 kg, delivered by bike. We cannot carry flammables, alcohol, medicines, cash, cards, jewellery, live animals, leaking liquids or anything illegal.' },
  { q: 'How long does delivery take?',
    a: 'Every Shipora delivery is same-day, anywhere inside Bengaluru. We do not deliver outside Bengaluru. The estimated delivery date is shown on every shipment.' },
  { q: 'My parcel is late, damaged or lost. What now?',
    a: 'Open Delivery Issues, choose the category, link the shipment\'s tracking number and describe what happened. Operations reviews every issue and replies within 48 hours; you can follow the status (Open → In Progress → Resolved).' },
  { q: 'Can I update my saved address?',
    a: 'Yes — go to Profile and update your address and map location. This becomes the default pickup address for new shipments.' },
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
        onMouseEnter={e => e.currentTarget.style.background = 'var(--brand-50)'}
        onMouseLeave={e => e.currentTarget.style.background = 'none'}
      >
        <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', paddingRight: 16 }}>{q}</span>
        <span style={{ fontSize: 18, color: 'var(--brand-600)', transition: 'transform 0.2s', transform: open ? 'rotate(45deg)' : 'none', flexShrink: 0 }}>+</span>
      </button>
      {open && (
        <div style={{ padding: '0 20px 16px', fontSize: 14, color: 'var(--muted)', lineHeight: 1.7, background: 'var(--brand-50)' }}>
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

  const phone         = config?.phone         || '1800-SHIPORA';
  const email         = config?.email         || 'support@shipora.in';
  const whatsapp      = config?.whatsapp      || '+91 98765 43210';
  const officeAddress = config?.officeAddress || 'Shipora Customer Care, Operations Hub';
  const officeHours   = config?.officeHours   || 'Mon – Sat · 8 AM – 8 PM';

  return (
    <div className="page" style={{ maxWidth: 860, margin: '0 auto' }}>
      <BackButton />

      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 36 }}>
        <div style={{ fontSize: 52, marginBottom: 10 }}><Ic icon={Headset} /></div>
        <h1 style={{ fontSize: 26, fontWeight: 800, color: 'var(--text)', marginBottom: 6 }}>Customer Care & Support</h1>
        <p style={{ color: 'var(--muted)', fontSize: 14, maxWidth: 480, margin: '0 auto' }}>
          We're here to help. Find answers below or reach us directly through one of our support channels.
        </p>
      </div>

      {/* Contact Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 32 }}>
        {[
          { icon: Phone, title: 'Helpline (24/7)',  detail: phone,         sub: 'Toll free · Always available',    color: '#0c831f', bg: '#dff5e3' },
          { icon: Mail, title: 'Email Support',    detail: email,         sub: 'Reply within 24 hours',           color: '#159a2b', bg: '#f2fbf4' },
          { icon: MessageCircle, title: 'WhatsApp',         detail: whatsapp,      sub: 'Mon – Sat · 8 AM – 8 PM',        color: '#16a34a', bg: '#f0fdf4' },
          { icon: Building2, title: 'Customer Care Office', detail: officeAddress, sub: officeHours,                       color: '#7c3aed', bg: '#f3e8ff' },
        ].map(c => (
          <div key={c.title} className="card" style={{ borderTop: `4px solid ${c.color}`, textAlign: 'center', padding: '20px 16px', transition: 'transform 0.2s, box-shadow 0.2s' }}
            onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.boxShadow = '0 8px 24px rgba(0,0,0,0.12)'; }}
            onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}
          >
            <div style={{ marginBottom: 8, color: c.color, display: 'flex', justifyContent: 'center' }}><Ic icon={c.icon} size={30} /></div>
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
              <Link to="/shipments/new" className="btn btn-ghost btn-sm"><Ic icon={Package} /> Create Shipment</Link>
              <Link to="/issues" className="btn btn-ghost btn-sm"><Ic icon={Megaphone} /> Report Delivery Issue</Link>
              <Link to="/shipments/history" className="btn btn-ghost btn-sm"><Ic icon={Archive} /> Delivery History</Link>
              <Link to="/profile" className="btn btn-ghost btn-sm"><Ic icon={User} /> Update Profile</Link>
              <Link to="/dashboard" className="btn btn-ghost btn-sm"><Ic icon={MapIcon} /> Live Tracking</Link>
            </>}
            {user.role === 'driver' && <>
              <Link to="/agent/history" className="btn btn-ghost btn-sm"><Ic icon={ClipboardList} /> Delivery History</Link>
              <Link to="/profile" className="btn btn-ghost btn-sm"><Ic icon={User} /> My Profile</Link>
            </>}
            {user.role === 'admin' && <>
              <Link to="/admin" className="btn btn-ghost btn-sm"><Ic icon={ChartColumn} /> Operations Dashboard</Link>
              <Link to="/profile" className="btn btn-ghost btn-sm"><Ic icon={User} /> My Profile</Link>
            </>}
          </div>
        </div>
      )}

      {/* Working Hours */}
      <div className="card" style={{ marginBottom: 28, padding: '20px 24px' }}>
        <h3 style={{ fontWeight: 700, fontSize: 15, marginBottom: 14, color: 'var(--text)' }}>Delivery Service Hours</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { day: 'Monday – Saturday', time: '8:00 AM – 8:00 PM', note: 'Pickups and deliveries' },
            { day: 'Same-day service',  time: 'Book before 12:00 PM', note: 'Same-day cut-off' },
            { day: 'Sunday',            time: 'Reduced service',      note: 'Limited routes' },
            { day: 'Public Holidays',   time: 'Reduced service',      note: 'Check app for updates' },
          ].map(h => (
            <div key={h.day} style={{ background: 'var(--brand-50)', borderRadius: 8, padding: '12px 14px', border: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--text)' }}>{h.day}</div>
              <div style={{ fontSize: 14, color: 'var(--brand-700)', fontWeight: 600, margin: '3px 0' }}>{h.time}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>{h.note}</div>
            </div>
          ))}
        </div>
      </div>

      {/* FAQ */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
          <h3 style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>Frequently Asked Questions</h3>
        </div>
        {FAQS.map((f, i) => <FAQ key={i} q={f.q} a={f.a} />)}
      </div>

      <p style={{ textAlign: 'center', marginTop: 28, fontSize: 13, color: 'var(--muted)' }}>
        Shipora — Parcel Delivery &amp; Fleet Management Platform · Version 1.0
      </p>
    </div>
  );
}
