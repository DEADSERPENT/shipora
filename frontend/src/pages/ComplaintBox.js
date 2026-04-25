import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';

const CATEGORIES = [
  { value: 'missed_pickup',    label: '🚫 Missed Pickup' },
  { value: 'vehicle_issue',   label: '🔧 Vehicle Issue' },
  { value: 'timing',          label: '⏰ Wrong Timing' },
  { value: 'cleanliness',     label: '🧹 Cleanliness' },
  { value: 'driver_behaviour',label: '👷 Driver Behaviour' },
  { value: 'other',           label: '📝 Other' },
];

const STATUS_META = {
  open:        { label: 'Open',        class: 'badge-red' },
  in_progress: { label: 'In Progress', class: 'badge-amber' },
  resolved:    { label: 'Resolved',    class: 'badge-green' },
  closed:      { label: 'Closed',      class: 'badge-blue' },
};

export default function ComplaintBox() {
  const { API } = useAuth();
  const [complaints, setComplaints] = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [view,       setView]       = useState('list'); // list | new | detail
  const [selected,   setSelected]   = useState(null);

  const [form, setForm] = useState({
    subject: '', category: 'missed_pickup', description: '', isAnonymous: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [formMsg,    setFormMsg]    = useState({ type: '', text: '' });

  const loadComplaints = () => {
    axios.get(`${API}/complaints`)
      .then(({ data }) => setComplaints(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadComplaints(); }, [API]); // eslint-disable-line

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.description.trim() || form.description.trim().length < 20) {
      setFormMsg({ type: 'error', text: 'Please describe the issue in at least 20 characters.' });
      return;
    }
    setSubmitting(true);
    setFormMsg({ type: '', text: '' });
    try {
      await axios.post(`${API}/complaints`, form);
      setFormMsg({ type: 'success', text: form.isAnonymous
        ? 'Anonymous complaint submitted! You won\'t be able to track it as it is anonymous.'
        : 'Complaint submitted! We will review it shortly.' });
      setForm({ subject: '', category: 'missed_pickup', description: '', isAnonymous: false });
      loadComplaints();
      setTimeout(() => { setView('list'); setFormMsg({ type: '', text: '' }); }, 2000);
    } catch (err) {
      setFormMsg({ type: 'error', text: err.response?.data?.message || 'Submission failed.' });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="loading-screen"><div className="spinner" /><p style={{ color: '#6b8f6b', fontWeight: 600 }}>Loading…</p></div>;

  const openCount = complaints.filter(c => c.status === 'open').length;
  const resolvedCount = complaints.filter(c => c.status === 'resolved' || c.status === 'closed').length;

  return (
    <div className="page" style={{ maxWidth: 800, margin: '0 auto' }}>
      <BackButton to="/dashboard" label="Dashboard" />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: 'var(--text)', marginBottom: 4 }}>📣 Complaint Box</h1>
          <p style={{ color: 'var(--muted)', fontSize: 14 }}>Report issues directly to the waste management team</p>
        </div>
        <button className="btn btn-primary" onClick={() => { setView('new'); setFormMsg({ type: '', text: '' }); }}>
          + New Complaint
        </button>
      </div>

      {/* Summary */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3,1fr)', marginBottom: 24 }}>
        {[
          { icon: '📋', value: complaints.length, label: 'Total Submitted',  color: '#2563eb' },
          { icon: '🔴', value: openCount,          label: 'Open',             color: '#ef4444' },
          { icon: '✅', value: resolvedCount,       label: 'Resolved',         color: '#2d7a2d' },
        ].map(s => (
          <div key={s.label} className="stat-card" style={{ borderLeft: `4px solid ${s.color}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div className="stat-value" style={{ color: s.color }}>{s.value}</div>
                <div className="stat-label">{s.label}</div>
              </div>
              <div style={{ fontSize: 28 }}>{s.icon}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ── New Complaint Form ── */}
      {view === 'new' && (
        <div className="card" style={{ marginBottom: 24, padding: '28px 32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ fontSize: 17, fontWeight: 700 }}>New Complaint</h3>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setView('list')}>← Cancel</button>
          </div>

          {formMsg.text && <div className={`alert alert-${formMsg.type}`}>{formMsg.text}</div>}

          <form onSubmit={submit}>
            <div className="form-group">
              <label>Subject</label>
              <input required value={form.subject} onChange={e => set('subject', e.target.value)} placeholder="Brief summary of the issue" maxLength={100} />
            </div>
            <div className="form-group">
              <label>Category</label>
              <select value={form.category} onChange={e => set('category', e.target.value)}>
                {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea
                required rows={5}
                value={form.description}
                onChange={e => set('description', e.target.value)}
                placeholder="Describe the issue in detail — include date, time, location if relevant (min 20 characters)"
                style={{ resize: 'vertical', minHeight: 100 }}
              />
              <span style={{ fontSize: 11, color: form.description.length < 20 && form.description.length > 0 ? 'var(--red)' : 'var(--muted)', marginTop: 4, display: 'block' }}>
                {form.description.length}/500 characters {form.description.length < 20 && form.description.length > 0 ? '(min 20)' : ''}
              </span>
            </div>

            {/* Anonymous toggle */}
            <div style={{
              border: `1.5px solid ${form.isAnonymous ? '#f59e0b' : 'var(--border)'}`,
              borderRadius: 10, padding: '14px 16px', marginBottom: 20,
              background: form.isAnonymous ? '#fffbeb' : 'var(--green-50)',
              transition: 'all 0.2s',
            }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', userSelect: 'none' }}>
                <input
                  type="checkbox"
                  checked={form.isAnonymous}
                  onChange={e => set('isAnonymous', e.target.checked)}
                  style={{ width: 16, height: 16, accentColor: '#d97706', cursor: 'pointer' }}
                />
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: form.isAnonymous ? '#92400e' : 'var(--text)' }}>
                    🕵️ Submit Anonymously
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                    Your name and contact details will not be shared with the admin
                  </div>
                </div>
              </label>
              {form.isAnonymous && (
                <div style={{ marginTop: 10, padding: '8px 12px', background: '#fef3c7', borderRadius: 7, border: '1px solid #fcd34d' }}>
                  <p style={{ fontSize: 12, color: '#78350f', margin: 0 }}>
                    ⚠ Anonymous complaints cannot be tracked after submission. You won't see it in your complaint list.
                  </p>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-ghost" onClick={() => setView('list')}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={submitting} style={{ minWidth: 160 }}>
                {submitting ? 'Submitting…' : form.isAnonymous ? '🕵️ Submit Anonymously' : '📣 Submit Complaint'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── Detail View ── */}
      {view === 'detail' && selected && (
        <div className="card" style={{ marginBottom: 24, padding: '28px 32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
            <h3 style={{ fontSize: 17, fontWeight: 700 }}>{selected.subject}</h3>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setView('list')}>← Back</button>
          </div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
            <span className={`badge ${STATUS_META[selected.status]?.class}`}>{STATUS_META[selected.status]?.label}</span>
            <span className="badge badge-blue">{CATEGORIES.find(c => c.value === selected.category)?.label}</span>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              Submitted {new Date(selected.createdAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
            </span>
          </div>
          <div style={{ background: 'var(--green-50)', borderRadius: 8, padding: '14px 16px', marginBottom: 16, fontSize: 14, lineHeight: 1.6, color: 'var(--text)', whiteSpace: 'pre-wrap' }}>
            {selected.description}
          </div>
          {selected.adminReply ? (
            <div style={{ borderLeft: '4px solid var(--green-600)', paddingLeft: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--green-700)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Admin Response
              </div>
              <p style={{ fontSize: 14, color: 'var(--text)', lineHeight: 1.6 }}>{selected.adminReply}</p>
            </div>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--muted)', fontStyle: 'italic' }}>No admin response yet. We typically respond within 48 hours.</p>
          )}
        </div>
      )}

      {/* ── Complaints List ── */}
      {view === 'list' && (
        <div className="card" style={{ padding: '4px 0' }}>
          {complaints.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
              <div style={{ fontSize: 44 }}>📬</div>
              <p style={{ marginTop: 10, fontWeight: 600 }}>No complaints submitted yet</p>
              <p style={{ fontSize: 13, marginTop: 4 }}>Use the complaint box to report issues with waste collection.</p>
              <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => setView('new')}>
                + Submit First Complaint
              </button>
            </div>
          ) : (
            complaints.map((c, i) => {
              const meta = STATUS_META[c.status] || STATUS_META.open;
              return (
                <div key={c._id}
                  style={{
                    padding: '16px 24px', cursor: 'pointer',
                    borderBottom: i < complaints.length - 1 ? '1px solid var(--border)' : 'none',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--green-50)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  onClick={() => { setSelected(c); setView('detail'); }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>{c.subject}</div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                        {CATEGORIES.find(cat => cat.value === c.category)?.label} ·{' '}
                        {new Date(c.createdAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
                      </div>
                      {c.adminReply && (
                        <div style={{ fontSize: 12, color: 'var(--green-700)', marginTop: 4, fontWeight: 600 }}>
                          💬 Admin replied
                        </div>
                      )}
                    </div>
                    <span className={`badge ${meta.class}`}>{meta.label}</span>
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
