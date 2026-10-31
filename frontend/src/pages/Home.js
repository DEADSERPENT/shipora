import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Bike, Clock, MapPin, PackageCheck, Search, ShieldCheck, Wallet, Zap } from 'lucide-react';
import { Ic } from '../components/Icon';
import EstimateCard from '../components/EstimateCard';
import { FareExamples, Faq, HeroOrderMock, RiderBand, SiteFooter } from '../components/HomeExtras';
import { BENGALURU_AREAS, findArea } from '../lib/areas';
import { MAX_PARCEL_KG, PROHIBITED_ITEMS, fmtINR, getEstimate } from '../lib/estimate';

// Public landing page (signed-out visitors). One clear promise, one primary action (get a fare), proof of the product
// (a live order, real prices), then riders. Styles: index.css, `.lp-*`.
const STEPS = [
  { icon: MapPin,       title: 'Pin pickup & drop', text: 'Choose two spots anywhere in Bengaluru. The fare and ETA are shown before you book.' },
  { icon: Bike,         title: 'A rider collects it', text: 'A nearby delivery partner picks the parcel up from your door within minutes.' },
  { icon: PackageCheck, title: 'Delivered today', text: 'Follow your rider live on the map and pay by cash or UPI when it arrives.' },
];

const FACTS = [
  { icon: Zap,         title: 'Same-day', text: 'Every parcel, inside Bengaluru' },
  { icon: Clock,       title: 'ETA upfront', text: 'Shown before you book' },
  { icon: Wallet,      title: 'Pay on delivery', text: 'Cash or UPI to the rider' },
  { icon: ShieldCheck, title: `Up to ${MAX_PARCEL_KG} kg`, text: 'Handled with care' },
];

const POPULAR = ['Koramangala', 'Indiranagar', 'HSR Layout', 'Whitefield', 'Jayanagar', 'JP Nagar', 'BTM Layout', 'Marathahalli',
  'Electronic City', 'Malleshwaram', 'Hebbal', 'Bellandur', 'MG Road', 'Yelahanka'];

export default function Home() {
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [pickup, setPickup] = useState('');
  const [drop, setDrop] = useState('');
  const [weight, setWeight] = useState('1');
  const [estimate, setEstimate] = useState(null);
  const [estError, setEstError] = useState('');
  const [estLoading, setEstLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [tn, setTn] = useState('');

  // /#how, /#fares … from the nav and footer
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  }, [hash]);

  // Live quote: re-priced (debounced) whenever the pickup area, drop area or weight changes — no button press needed.
  useEffect(() => {
    const from = findArea(pickup), to = findArea(drop), kg = parseFloat(weight);
    if (!from || !to) { setEstimate(null); setEstError(''); return undefined; }
    if (!(kg > 0)) return undefined;
    if (kg > MAX_PARCEL_KG) { setEstimate(null); setEstError(`Parcels can weigh at most ${MAX_PARCEL_KG} kg for same-day bike delivery.`); return undefined; }
    let live = true;
    setEstLoading(true); setEstError('');
    const timer = setTimeout(() => {
      getEstimate(from, to, kg)
        .then(q => { if (live) setEstimate(q); })
        .catch(err => { if (live) { setEstimate(null); setEstError(err.message); } })
        .finally(() => { if (live) setEstLoading(false); });
    }, 300);
    return () => { live = false; clearTimeout(timer); };
  }, [pickup, drop, weight]);

  const goBook = () => {
    const q = new URLSearchParams({ type: 'other' });
    if (findArea(pickup)) q.set('pickup', findArea(pickup).name);
    if (findArea(drop)) q.set('drop', findArea(drop).name);
    if (parseFloat(weight) > 0) q.set('weight', String(parseFloat(weight)));
    navigate(`/shipments/new?${q.toString()}`);
  };

  const getQuote = async (e) => {
    e.preventDefault();
    const from = findArea(pickup), to = findArea(drop), kg = parseFloat(weight);
    if (!from || !to) { setEstimate(null); return setEstError('Pick the pickup and drop from the Bengaluru areas in the list.'); }
    if (kg > MAX_PARCEL_KG) { setEstimate(null); return setEstError(`Parcels can weigh at most ${MAX_PARCEL_KG} kg for same-day bike delivery.`); }
    setEstError(''); setEstLoading(true);
    try { setEstimate(await getEstimate(from, to, kg)); }
    catch (err) { setEstimate(null); setEstError(err.message); }
    finally { setEstLoading(false); }
  };

  const track = (e) => { e.preventDefault(); const v = tn.trim().toUpperCase(); navigate(v ? `/track/${encodeURIComponent(v)}` : '/track'); };

  const FAQS = [
    { q: 'How much does a delivery cost?', a: estimate
      ? `Your estimate above is ${fmtINR(estimate.fare)}. The base fare of ${fmtINR(estimate.baseFare)} covers the first ${estimate.includedKm} km, then ${fmtINR(estimate.perKm)} for every extra km. Parcels above ${estimate.freeWeightKg} kg add ${fmtINR(estimate.perExtraKg)} for every extra kg.`
      : 'A base fare covers the first kilometre, then a fixed rate applies per extra km, and heavier parcels add a small per-kg charge. Enter a pickup, drop and weight above to see your exact fare before you book.' },
    { q: 'How fast is delivery?', a: 'Every parcel is delivered the same day, inside Bengaluru. Your ETA depends on the distance and is shown before you book.' },
    { q: 'How much can a parcel weigh?', a: `Up to ${MAX_PARCEL_KG} kg — we deliver by bike so parcels stay quick and safe.` },
    { q: 'How do I pay?', a: 'Pay the rider on delivery, in cash or by UPI. There is nothing to pay upfront.' },
    { q: 'Can I track my parcel?', a: 'Yes. You get a tracking number starting with SHP the moment you book. Enter it on the Track page to see live status and the rider on the map — no sign-in needed.' },
    { q: 'What can’t I send?', a: `We can’t carry: ${PROHIBITED_ITEMS.join('; ').toLowerCase()}.` },
    { q: 'Do you deliver outside Bengaluru?', a: 'Not yet. Both the pickup and the drop must be inside Bengaluru.' },
  ];

  const popular = POPULAR.map(findArea).filter(Boolean);
  const rest = BENGALURU_AREAS.filter(a => !popular.includes(a));
  const pickDrop = (name) => { setDrop(name); document.getElementById('book')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); };

  return (
    <div className="lp">
      {/* ── Hero ── */}
      <section className="lp-hero">
        <div className="lp-wrap lp-hero-grid">
          <div className="lp-hero-copy">
            <span className="lp-eyebrow"><Ic icon={Zap} size={13} strokeWidth={2.8} /> Same-day delivery · Bengaluru</span>
            <h1>Send anything across Bengaluru. <span>Delivered today.</span></h1>
            <p className="lp-lead">Book a rider in under a minute. See the fare upfront, follow your parcel live, and pay when it arrives.</p>

            <form className="lp-book" id="book" onSubmit={getQuote}>
              <datalist id="bengaluru-areas">{BENGALURU_AREAS.map(a => <option key={a.name} value={a.name} />)}</datalist>
              <label className="lp-field">
                <span>Pickup</span>
                <input list="bengaluru-areas" value={pickup} onChange={e => setPickup(e.target.value)} placeholder="Pickup area" aria-label="Pickup area" autoComplete="off" />
              </label>
              <label className="lp-field">
                <span>Drop</span>
                <input list="bengaluru-areas" value={drop} onChange={e => setDrop(e.target.value)} placeholder="Drop area" aria-label="Drop area" autoComplete="off" />
              </label>
              <label className="lp-field lp-field-kg">
                <span>Weight (kg)</span>
                <input type="number" min="0.1" max={MAX_PARCEL_KG} step="0.1" value={weight} onChange={e => setWeight(e.target.value)} aria-label="Weight in kg" />
              </label>
              <button type="submit" className="lp-btn lp-btn-primary lp-book-go" disabled={estLoading}>
                {estLoading ? 'Calculating…' : <>Get fare <Ic icon={ArrowRight} size={17} strokeWidth={2.6} /></>}
              </button>
            </form>

            <EstimateCard estimate={estimate} loading={estLoading} error={estError} />
            {estimate && (
              <div className="lp-book-actions">
                <button type="button" className="lp-btn lp-btn-primary" onClick={goBook}>Book now · {fmtINR(estimate.fare)} <Ic icon={ArrowRight} size={17} strokeWidth={2.6} /></button>
                <span>You’ll sign in to confirm. Pay the rider on delivery.</span>
              </div>
            )}

            <div className="lp-hero-links">
              <Link to="/track">Track a parcel <Ic icon={ArrowRight} size={14} /></Link>
            </div>
          </div>
          <HeroOrderMock />
        </div>
      </section>

      {/* ── Facts ── */}
      <section className="lp-strip" aria-label="Service at a glance">
        <div className="lp-wrap lp-strip-grid">
          {FACTS.map(f => (
            <div key={f.title} className="lp-fact"><span><Ic icon={f.icon} size={18} /></span><div><b>{f.title}</b><small>{f.text}</small></div></div>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="lp-section" id="how">
        <div className="lp-wrap">
          <div className="lp-head"><span className="lp-eyebrow">How it works</span><h2>From doorstep to doorstep in three steps</h2></div>
          <div className="lp-steps">
            {STEPS.map((s, i) => (
              <div className="lp-step" key={s.title}>
                <div className="lp-step-top"><span className="lp-step-ico"><Ic icon={s.icon} size={22} /></span><span className="lp-step-n">0{i + 1}</span></div>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section className="lp-section lp-alt" id="fares">
        <div className="lp-wrap">
          <div className="lp-head"><span className="lp-eyebrow">Pricing</span><h2>Know the fare before you book</h2><p>Live quotes from our pricing engine. Pay the rider on delivery.</p></div>
          <FareExamples onPick={(from, to, kg) => { setPickup(from); setDrop(to); setWeight(String(kg)); document.getElementById('book')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }} />
        </div>
      </section>

      {/* ── Track ── */}
      <section className="lp-section">
        <div className="lp-wrap lp-track">
          <div>
            <span className="lp-eyebrow">Tracking</span>
            <h2>Already sent something?</h2>
            <p>Enter the tracking number you were given (it starts with SHP). No sign-in needed.</p>
          </div>
          <form onSubmit={track} className="lp-track-form">
            <label className="lp-field lp-field-icon">
              <Ic icon={Search} size={18} />
              <input value={tn} onChange={e => setTn(e.target.value)} placeholder="e.g. SHP48217390" aria-label="Tracking number" />
            </label>
            <button type="submit" className="lp-btn lp-btn-dark">Track parcel</button>
          </form>
        </div>
      </section>

      {/* ── Riders ── */}
      <section className="lp-section" style={{ paddingTop: 0 }}>
        <div className="lp-wrap"><RiderBand /></div>
      </section>

      {/* ── Coverage ── */}
      <section className="lp-section lp-alt" id="coverage">
        <div className="lp-wrap">
          <div className="lp-head"><span className="lp-eyebrow">Coverage</span><h2>All of Bengaluru</h2><p>Pickup and drop must both be inside the city. Tap an area to use it as your drop.</p></div>
          <div className="lp-areas">
            {(showAll ? [...popular, ...rest] : popular).map(a => (
              <button type="button" key={a.name} className={drop === a.name ? 'on' : ''} onClick={() => pickDrop(a.name)}><Ic icon={MapPin} size={13} /> {a.name}</button>
            ))}
            <button type="button" className="lp-areas-more" onClick={() => setShowAll(v => !v)}>{showAll ? 'Show fewer' : `Show all ${BENGALURU_AREAS.length} areas`}</button>
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="lp-section" id="faq">
        <div className="lp-wrap lp-faq-wrap">
          <div className="lp-head"><span className="lp-eyebrow">FAQ</span><h2>Questions, answered</h2><p>Still stuck? <Link to="/support">Contact support</Link>.</p></div>
          <Faq items={FAQS} />
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section className="lp-cta">
        <div className="lp-wrap">
          <h2>Your city, delivered — same day.</h2>
          <div className="lp-cta-actions">
            <Link to="/register" className="lp-btn lp-btn-primary">Get started <Ic icon={ArrowRight} size={17} strokeWidth={2.6} /></Link>
            <Link to="/login" className="lp-btn lp-btn-ghost">Log in</Link>
          </div>
        </div>
      </section>
      <SiteFooter />
    </div>
  );
}
