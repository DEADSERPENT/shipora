import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';
import { ISSUE_CATEGORIES, ISSUE_STATUS, apiError, fmtDate, issueCategoryLabel } from '../lib/shipora';
import { CircleAlert, CircleCheck, ClipboardList, Megaphone, MessageCircle, Plus, TriangleAlert, VenetianMask } from 'lucide-react';
import { Ic } from '../components/Icon';
import { ParcelIllustration } from '../components/Illustrations';

const BLANK = { subject: '', category: 'delayed_delivery', description: '', isAnonymous: false, trackingNumber: '' };

// Customer-facing delivery issues. The backend still serves these at /api/complaints.
export default function DeliveryIssues() {
  const { API } = useAuth();
  const [params] = useSearchParams();
  const prefillTn = (params.get('tn') || '').toUpperCase();

  const [issues,   setIssues]   = useState([]);
  const [shipments, setShipments] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [view,     setView]     = useState(prefillTn ? 'new' : 'list'); // list | new | detail
  const [selected, setSelected] = useState(null);

  const [form, setForm] = useState({ ...BLANK, trackingNumber: prefillTn });
  const [submitting, setSubmitting] = useState(false);
  const [formMsg,    setFormMsg]    = useState({ type: '', text: '' });

  const loadIssues = () => {
    axios.get(`${API}/complaints`)
      .then(({ data }) => setIssues(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadIssues();
    axios.get(`${API}/shipments`).then(({ data }) => setShipments(data)).catch(() => {});
  }, [API]); // eslint-disable-line

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (form.description.trim().length < 20) {
      setFormMsg({ type: 'error', text: 'Please describe the issue in at least 20 characters.' });
      return;
    }
    setSubmitting(true);
    setFormMsg({ type: '', text: '' });
    try {
      await axios.post(`${API}/complaints`, { ...form, trackingNumber: form.trackingNumber || null });
      setFormMsg({ type: 'success', text: form.isAnonymous
        ? 'Anonymous report submitted! You will not be able to track it, as it is anonymous.'
        : 'Issue reported! Our team will review it shortly.' });
      setForm({ ...BLANK });
      loadIssues();
      setTimeout(() => { setView('list'); setFormMsg({ type: '', text: '' }); }, 1800);
    } catch (err) {
      setFormMsg({ type: 'error', text: apiError(err, 'Submission failed.') });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="loading-screen"><div className="spinner" /><p style={{ color: 'var(--muted)', fontWeight: 600 }}>Loading…</p></div>;

  const openCount = issues.filter(c => c.status === 'open').length;
  const resolvedCount = issues.filter(c => c.status === 'resolved' || c.status === 'closed').length;

  return (
    <div className="page" style={{ maxWidth: 800, margin: '0 auto' }}>
      <BackButton to="/dashboard" label="Dashboard" />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}><Ic icon={Megaphone} /> Delivery Issues</h1>
          <p style={{ color: 'var(--muted)', fontSize: 14 }}>Report a problem with a parcel or delivery to the Shipora operations team</p>
        </div>
        <button className="btn btn-primary" onClick={() => { setView('new'); setFormMsg({ type: '', text: '' }); }}><Ic icon={Plus} /> Report an Issue</button>
      </div>

      <div className="stats-grid" style={{ marginBottom: 24 }}>
        {[
          { icon: ClipboardList, value: issues.length, label: 'Total Reported', color: '#0c831f' },
          { icon: CircleAlert, value: openCount,     label: 'Open',           color: '#ef4444' },
          { icon: CircleCheck, value: resolvedCount, label: 'Resolved',       color: '#15803d' },
        ].map(s => (
          <div key={s.label} className="stat-card" style={{ borderLeft: `4px solid ${s.color}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div className="stat-value" style={{ color: s.color }}>{s.value}</div>
                <div className="stat-label">{s.label}</div>
              </div>
              <div style={{ color: s.color, display: 'flex' }}><Ic icon={s.icon} size={28} /></div>
            </div>
          </div>
        ))}
      </div>

      {view === 'new' && (
        <div className="card" style={{ marginBottom: 24, padding: '28px 32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ fontSize: 17, fontWeight: 700 }}>Report a Delivery Issue</h3>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setView('list')}>← Cancel</button>
          </div>

          {formMsg.text && <div className={`alert alert-${formMsg.type}`}>{formMsg.text}</div>}

          <form onSubmit={submit}>
            <div className="form-row">
              <div className="form-group">
                <label>Shipment</label>
                <select value={form.trackingNumber} onChange={e => set('trackingNumber', e.target.value)}>
                  <option value="">Not about a specific shipment</option>
                  {shipments.map(s => <option key={s._id} value={s.trackingNumber}>{s.trackingNumber} → {s.recipient?.name}</option>)}
                  {form.trackingNumber && !shipments.some(s => s.trackingNumber === form.trackingNumber) && (
                    <option value={form.trackingNumber}>{form.trackingNumber}</option>
                  )}
                </select>
              </div>
              <div className="form-group">
                <label>Category</label>
                <select value={form.category} onChange={e => set('category', e.target.value)}>
                  {ISSUE_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
            </div>
            <div className="form-group">
              <label>Subject</label>
              <input required value={form.subject} onChange={e => set('subject', e.target.value)} placeholder="Brief summary of the issue" maxLength={100} />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea
                required rows={5}
                value={form.description}
                onChange={e => set('description', e.target.value)}
                placeholder="Describe what happened — include dates, times and any details that help (min 20 characters)"
                style={{ resize: 'vertical', minHeight: 100 }}
              />
              <span style={{ fontSize: 11, color: form.description.length < 20 && form.description.length > 0 ? 'var(--red)' : 'var(--muted)', marginTop: 4, display: 'block' }}>
                {form.description.length}/500 characters {form.description.length < 20 && form.description.length > 0 ? '(min 20)' : ''}
              </span>
            </div>

            <div style={{
              border: `1.5px solid ${form.isAnonymous ? '#f59e0b' : 'var(--border)'}`,
              borderRadius: 10, padding: '14px 16px', marginBottom: 20,
              background: form.isAnonymous ? '#fffbeb' : 'var(--brand-50)', transition: 'all 0.2s',
            }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', userSelect: 'none' }}>
                <input type="checkbox" checked={form.isAnonymous} onChange={e => set('isAnonymous', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#d97706', cursor: 'pointer' }} />
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14 }}><Ic icon={VenetianMask} /> Submit Anonymously</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>Your name and contact details will not be shared with operations</div>
                </div>
              </label>
              {form.isAnonymous && (
                <div style={{ marginTop: 10, padding: '8px 12px', background: '#fef3c7', borderRadius: 7, border: '1px solid #fcd34d' }}>
                  <p style={{ fontSize: 12, color: '#78350f', margin: 0 }}>
                    <Ic icon={TriangleAlert} /> Anonymous reports cannot be tracked after submission and will not appear in your list.
                  </p>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-ghost" onClick={() => setView('list')}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={submitting} style={{ minWidth: 160 }}>
                {submitting ? 'Submitting…' : form.isAnonymous ? <><Ic icon={VenetianMask} /> Submit Anonymously</> : <><Ic icon={Megaphone} /> Submit Issue</>}
              </button>
            </div>
          </form>
        </div>
      )}

      {view === 'detail' && selected && (
        <div className="card" style={{ marginBottom: 24, padding: '28px 32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, gap: 8 }}>
            <h3 style={{ fontSize: 17, fontWeight: 700 }}>{selected.subject}</h3>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setView('list')}>← Back</button>
          </div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className={`badge ${ISSUE_STATUS[selected.status]?.cls}`}>{ISSUE_STATUS[selected.status]?.label}</span>
            <span className="badge badge-blue">{issueCategoryLabel(selected.category)}</span>
            {selected.trackingNumber && <span className="pill pill-indigo tracking-no">{selected.trackingNumber}</span>}
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>Reported {fmtDate(selected.createdAt)}</span>
          </div>
          <div style={{ background: 'var(--brand-50)', borderRadius: 8, padding: '14px 16px', marginBottom: 16, fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
            {selected.description}
          </div>
          {selected.adminReply ? (
            <div style={{ borderLeft: '4px solid var(--brand-600)', paddingLeft: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--brand-700)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Operations Response</div>
              <p style={{ fontSize: 14, lineHeight: 1.6 }}>{selected.adminReply}</p>
            </div>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--muted)', fontStyle: 'italic' }}>No response yet. We typically respond within 48 hours.</p>
          )}
        </div>
      )}

      {view === 'list' && (
        <div className="card" style={{ padding: '4px 0' }}>
          {issues.length === 0 ? (
            <div className="empty-state">
              <div className="emoji"><ParcelIllustration size={110} /></div>
              <p style={{ marginTop: 10, fontWeight: 600 }}>No delivery issues reported</p>
              <p style={{ fontSize: 13, marginTop: 4 }}>If a parcel is late, damaged or lost, let us know here.</p>
              <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => setView('new')}><Ic icon={Plus} /> Report an Issue</button>
            </div>
          ) : (
            issues.map((c, i) => {
              const meta = ISSUE_STATUS[c.status] || ISSUE_STATUS.open;
              return (
                <div key={c._id}
                  style={{ padding: '16px 24px', cursor: 'pointer', borderBottom: i < issues.length - 1 ? '1px solid var(--border)' : 'none', transition: 'background 0.15s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--brand-50)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  onClick={() => { setSelected(c); setView('detail'); }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>{c.subject}</div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                        {issueCategoryLabel(c.category)}{c.trackingNumber ? ` · ${c.trackingNumber}` : ''} · {fmtDate(c.createdAt)}
                      </div>
                      {c.adminReply && <div style={{ fontSize: 12, color: 'var(--brand-700)', marginTop: 4, fontWeight: 600 }}><Ic icon={MessageCircle} /> Operations replied</div>}
                    </div>
                    <span className={`badge ${meta.cls}`}>{meta.label}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
