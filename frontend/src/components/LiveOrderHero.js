import React, { useEffect, useState } from 'react';
import { Check, ClipboardList, Navigation, PackageCheck, Phone, Share2, UserCheck, CircleCheck } from 'lucide-react';
import { Ic } from './Icon';
import { STEPS, etaSummary, initials, stepIndex, telHref } from '../lib/liveOrder';
import { vehicleIcon } from '../lib/shipora';

const STEP_ICONS = [ClipboardList, UserCheck, PackageCheck, Navigation, CircleCheck];

// The first thing a customer sees on a parcel: when it arrives, where it is, who is bringing it, and how to call them —
// the layout food-delivery and Porter-style apps converged on, because it answers the only questions people have.
export default function LiveOrderHero({ shipment: s, role, liveArea, liveEta }) {
  const [now, setNow] = useState(Date.now());
  const [copied, setCopied] = useState(false);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(t); }, []);

  const summary = etaSummary(s, now);
  const current = stepIndex(s);
  const failed = summary.tone === 'bad';
  const agent = s.assignedAgent;
  // A rider calls the receiver; everyone else calls the rider.
  const contact = role === 'driver'
    ? { title: 'Receiver', name: s.recipient?.name, phone: s.recipient?.phone, sub: s.recipient?.address }
    : agent && { title: 'Your rider', name: agent.name, phone: agent.phone, sub: agent.vehicleNo, icon: vehicleIcon(agent.vehicleType) };

  const share = async () => {
    const url = `${window.location.origin}/track/${s.trackingNumber}`;
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { window.prompt('Copy this tracking link', url); }
  };

  return (
    <section className={`live-hero live-${summary.tone}`} aria-label="Live order status">
      <div className="live-hero-top">
        <div>
          <div className="live-kicker">{summary.headline}</div>
          <div className="live-eta">{summary.big}</div>
          <div className="live-sub">{summary.sub}</div>
        </div>
        <button type="button" className="live-share" onClick={share}>
          <Ic icon={copied ? Check : Share2} size={15} /> {copied ? 'Link copied' : 'Share tracking'}
        </button>
      </div>

      <ol className="stepper" aria-label="Delivery progress">
        {STEPS.map((step, i) => {
          const state = i < current || (i === current && s.status === 'DELIVERED') ? 'done' : i === current ? (failed ? 'fail' : 'now') : 'todo';
          return (
            <li key={step.key} className={`step step-${state}`} aria-current={i === current ? 'step' : undefined}>
              <span className="step-dot"><Ic icon={state === 'done' ? Check : STEP_ICONS[i]} size={15} strokeWidth={2.4} /></span>
              <span className="step-label">{step.label}</span>
            </li>
          );
        })}
      </ol>

      {contact && contact.name && (
        <div className="rider-card">
          <span className="rider-avatar" aria-hidden="true">{initials(contact.name)}</span>
          <div className="rider-meta">
            <div className="rider-title">{contact.title}</div>
            <div className="rider-name">{contact.name}</div>
            <div className="rider-sub">
              {contact.icon && <Ic icon={contact.icon} size={13} />} {contact.sub}
              {liveArea && <span className="rider-live"> · <span className="live-dot" /> {liveArea}{liveEta ? ` · ETA ${liveEta}` : ''}</span>}
            </div>
          </div>
          {contact.phone && (
            <a className="call-btn" href={telHref(contact.phone)} aria-label={`Call ${contact.name}`}>
              <Ic icon={Phone} size={16} /> Call
            </a>
          )}
        </div>
      )}
    </section>
  );
}
