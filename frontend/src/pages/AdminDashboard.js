import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { io } from 'socket.io-client';
import { useAuth } from '../context/AuthContext';
import ChatAnalyticsTab from '../components/ChatAnalyticsTab';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

const COMPLAINT_STATUS = {
  open:        { label: 'Open',        cls: 'badge-red' },
  in_progress: { label: 'In Progress', cls: 'badge-amber' },
  resolved:    { label: 'Resolved',    cls: 'badge-green' },
  closed:      { label: 'Closed',      cls: 'badge-blue' },
};
const COMPLAINT_CATEGORIES = {
  missed_pickup:'Missed Pickup', vehicle_issue:'Vehicle Issue',
  timing:'Wrong Timing', cleanliness:'Cleanliness',
  driver_behaviour:'Driver Behaviour', other:'Other',
};

const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000';

export function StatCard({ icon, value, label, color }) {
  const palette = {
    green:  { accent: '#2d7a2d', bg: '#e8f5e8' },
    blue:   { accent: '#2563eb', bg: '#eff6ff' },
    amber:  { accent: '#d97706', bg: '#fffbeb' },
    purple: { accent: '#7c3aed', bg: '#f3e8ff' },
  };
  const c = palette[color] || palette.green;
  return (
    <div className="stat-card" style={{ borderLeft: `4px solid ${c.accent}`, transition: 'transform 0.2s, box-shadow 0.2s' }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 8px 24px rgba(0,0,0,0.12)'; }}
      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div className="stat-value" style={{ color: c.accent, fontSize: 28 }}>{value}</div>
          <div className="stat-label">{label}</div>
        </div>
        <div style={{ fontSize: 30, background: c.bg, borderRadius: 10, padding: '8px 10px' }}>{icon}</div>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const { user, API } = useAuth();
  const [stats, setStats]             = useState(null);
  const [logs, setLogs]               = useState([]);
  const [liveDrivers, setLiveDrivers] = useState({});
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [activeTab, setActiveTab]     = useState('overview');
  const [complaints, setComplaints]   = useState([]);
  const [expandedC,  setExpandedC]    = useState(null);
  const [replyText,  setReplyText]    = useState({});
  const [replyStatus, setReplyStatus] = useState({});

  // Support config state
  const [supportCfg,     setSupportCfg]     = useState(null);
  const [supportForm,    setSupportForm]     = useState({ phone: '', email: '', whatsapp: '', officeAddress: '', officeHours: '' });
  const [supportSaving,  setSupportSaving]  = useState(false);
  const [supportMsg,     setSupportMsg]     = useState({ type: '', text: '' });

  const fetchStats = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const { data } = await axios.get(`${API}/admin/stats`);
      setStats(data);
      setLogs(data.todayLogs || []);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [API]);

  const fetchLogsByDate = useCallback(async (dateStr) => {
    try {
      const { data } = await axios.get(`${API}/admin/logs?date=${encodeURIComponent(dateStr)}`);
      setLogs(data);
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    }
  }, [API]);

  const fetchComplaints = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/complaints`);
      setComplaints(data);
    } catch {}
  }, [API]);

  const fetchSupportCfg = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/support/config`);
      setSupportCfg(data);
      setSupportForm({
        phone:         data.phone         || '',
        email:         data.email         || '',
        whatsapp:      data.whatsapp      || '',
        officeAddress: data.officeAddress || '',
        officeHours:   data.officeHours   || '',
      });
    } catch {}
  }, []);

  const saveSupportCfg = async (e) => {
    e.preventDefault();
    setSupportSaving(true);
    setSupportMsg({ type: '', text: '' });
    try {
      await axios.put(`${API_BASE}/support/config`, supportForm);
      setSupportMsg({ type: 'success', text: 'Support contact details saved successfully.' });
      setTimeout(() => setSupportMsg({ type: '', text: '' }), 3000);
    } catch (err) {
      setSupportMsg({ type: 'error', text: err.response?.data?.message || 'Save failed.' });
    } finally {
      setSupportSaving(false);
    }
  };

  useEffect(() => {
    fetchStats();
    fetchComplaints();
    fetchSupportCfg();
    const interval = setInterval(() => { fetchStats(true); fetchComplaints(); }, 30000);
    return () => clearInterval(interval);
  }, [fetchStats, fetchComplaints, fetchSupportCfg]);

  const updateComplaint = async (id, status, reply) => {
    try {
      await axios.put(`${API}/complaints/${id}`, { status, adminReply: reply });
      fetchComplaints();
      setExpandedC(null);
    } catch {}
  };

  useEffect(() => {
    const socket = io(SOCKET_URL, { transports: ['websocket', 'polling'] });
    socket.on('vehicles:initial', data => setLiveDrivers(data));
    socket.on('vehicles:update',  data => setLiveDrivers(data));
    return () => socket.disconnect();
  }, []);

  if (loading) return (
    <div className="loading-screen">
      <div className="spinner" />
      <p style={{ color: '#6b8f6b', fontWeight: 600 }}>Loading admin panel...</p>
    </div>
  );

  const liveList    = Object.values(liveDrivers);
  const activeCount = liveList.filter(d => d.isActive).length;
  const today = new Date().toLocaleDateString('en-IN', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
  });

  return (
    <div className="page" style={{ maxWidth: 1280, margin: '0 auto' }}>

      {/* ── Tab Bar ── */}
      <div className="tab-bar" style={{ marginBottom: 24 }}>
        {[
          { key: 'overview',   label: '📊 Overview' },
          { key: 'logs',       label: '📋 Collection Logs' },
          { key: 'complaints', label: `📣 Complaints${complaints.filter(c=>c.status==='open').length > 0 ? ` (${complaints.filter(c=>c.status==='open').length})` : ''}` },
          { key: 'analytics',  label: '🎙️ Chat Analytics' },
          { key: 'settings',   label: '⚙️ Settings' },
        ].map(t => (
          <button key={t.key} type="button"
            className={`tab-btn ${activeTab === t.key ? 'active' : ''}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Header ── */}
      <div className="admin-header">
        <div>
          <h1 className="admin-title">Admin Dashboard</h1>
          <p className="admin-subtitle">
            Welcome, <strong>{user?.name}</strong>
            {user?.organization && ` · ${user.organization}`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          {activeCount > 0 && (
            <span className="badge badge-green" style={{ fontSize: 13, padding: '5px 14px' }}>
              <span className="pulse-dot" /> {activeCount} Live
            </span>
          )}
          <span style={{ fontSize: 13, color: 'var(--muted)' }}>{today}</span>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => fetchStats(true)}
            disabled={refreshing}
          >
            {refreshing ? '⟳ Refreshing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {activeTab === 'overview' && <>
      {/* ── Stat Cards ── */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', marginBottom: 28 }}>
        <StatCard icon="🚛" value={activeCount}                      label="Drivers Active Now"      color="green"  />
        <StatCard icon="✅" value={stats?.totalAreasCompleted || 0}  label="Areas Completed Today"   color="blue"   />
        <StatCard icon="👷" value={stats?.totalDrivers || 0}         label="Total Drivers"           color="amber"  />
        <StatCard icon="🏠" value={stats?.totalResidents || 0}       label="Registered Residents"    color="purple" />
      </div>

      {/* ── Live Driver Feed ── */}
      {liveList.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>Live Driver Feed</h3>
            <span className="badge badge-green">
              <span className="pulse-dot" /> {activeCount} / {liveList.length} Active
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(270px, 1fr))', gap: 12 }}>
            {liveList.map(d => (
              <div key={d.driverId} className={`driver-card ${d.isActive ? 'driver-active' : 'driver-offline'}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>🚛 {d.driverName}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{d.vehicleNo}</div>
                  </div>
                  <span className={`badge ${d.isActive ? 'badge-green' : 'badge-red'}`}>
                    {d.isActive ? '● On Route' : '○ Offline'}
                  </span>
                </div>
                {d.isActive ? (
                  <div style={{ fontSize: 13, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px' }}>
                    <div><span style={{ color: 'var(--muted)' }}>Area:</span> {d.currentArea || 'N/A'}</div>
                    <div><span style={{ color: 'var(--muted)' }}>ETA:</span> {d.eta || 'N/A'}</div>
                    <div><span style={{ color: 'var(--muted)' }}>Done:</span> {d.areasCompleted?.length || 0} zones</div>
                    <div style={{ color: 'var(--muted)', fontSize: 11 }}>
                      {new Date(d.lastUpdated).toLocaleTimeString()}
                    </div>
                  </div>
                ) : (
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    Last seen {new Date(d.lastUpdated).toLocaleTimeString()}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      </>}

      {activeTab === 'logs' && <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <h3 style={{ fontSize: 16, fontWeight: 700 }}>
            Collection Logs
            <span style={{ marginLeft: 8, fontSize: 13, color: 'var(--muted)', fontWeight: 400 }}>
              ({logs.length} records)
            </span>
          </h3>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 600 }}>Date:</label>
            <input
              type="date"
              defaultValue={new Date().toISOString().slice(0, 10)}
              style={{
                padding: '6px 10px', border: '1.5px solid var(--border)',
                borderRadius: 8, fontSize: 13, outline: 'none',
              }}
              onChange={e => {
                if (e.target.value) {
                  fetchLogsByDate(new Date(e.target.value).toDateString());
                }
              }}
            />
          </div>
        </div>

        {logs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
            <div style={{ fontSize: 44 }}>📋</div>
            <p style={{ marginTop: 10, fontWeight: 600 }}>No collection logs for this date</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>Drivers must be active to generate logs</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Driver</th>
                  <th>Vehicle</th>
                  <th>Assigned Zone</th>
                  <th>Areas Completed</th>
                  <th>Current Area</th>
                  <th>ETA</th>
                  <th>Status</th>
                  <th>Last Updated</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log, i) => (
                  <tr key={log._id} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--green-50)' }}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{log.driverId?.name || 'Unknown'}</div>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{log.driverId?.phone}</div>
                    </td>
                    <td>
                      <span className="badge badge-blue">{log.driverId?.vehicleNo || '—'}</span>
                    </td>
                    <td>{log.driverId?.assignedArea || '—'}</td>
                    <td>
                      {log.areasCompleted?.length > 0 ? (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {log.areasCompleted.map((a, j) => (
                            <span key={j} className="badge badge-green" style={{ fontSize: 11 }}>{a}</span>
                          ))}
                        </div>
                      ) : (
                        <span style={{ color: 'var(--muted)', fontSize: 12 }}>None yet</span>
                      )}
                    </td>
                    <td>{log.currentArea || '—'}</td>
                    <td>{log.eta || '—'}</td>
                    <td>
                      <span className={`badge ${log.isActive ? 'badge-green' : 'badge-amber'}`}>
                        {log.isActive ? '● Active' : '✓ Done'}
                      </span>
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                      {log.lastUpdated ? new Date(log.lastUpdated).toLocaleTimeString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>}

      {/* ── Complaints Tab ── */}
      {/* ── Settings Tab ── */}
      {activeTab === 'settings' && (
        <div style={{ maxWidth: 600 }}>
          <div className="card" style={{ padding: '28px 32px' }}>
            <h3 style={{ fontSize: 17, fontWeight: 700, marginBottom: 6, color: 'var(--text)', borderBottom: '1px solid var(--border)', paddingBottom: 12 }}>
              📞 Support Contact Details
            </h3>
            <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 20 }}>
              These details are shown to all users on the Customer Support page. Only admins can edit them.
            </p>

            {supportMsg.text && (
              <div className={`alert alert-${supportMsg.type}`} style={{ marginBottom: 16 }}>
                {supportMsg.text}
              </div>
            )}

            <form onSubmit={saveSupportCfg}>
              <div className="form-row">
                <div className="form-group">
                  <label>📞 Helpline Number</label>
                  <input
                    value={supportForm.phone}
                    onChange={e => setSupportForm(p => ({ ...p, phone: e.target.value }))}
                    placeholder="e.g. 1800-ECO-TRACK"
                  />
                </div>
                <div className="form-group">
                  <label>📧 Support Email</label>
                  <input
                    type="email"
                    value={supportForm.email}
                    onChange={e => setSupportForm(p => ({ ...p, email: e.target.value }))}
                    placeholder="e.g. support@ecotrack.in"
                  />
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>💬 WhatsApp Number</label>
                  <input
                    value={supportForm.whatsapp}
                    onChange={e => setSupportForm(p => ({ ...p, whatsapp: e.target.value }))}
                    placeholder="e.g. +91 98765 43210"
                  />
                </div>
                <div className="form-group">
                  <label>🕐 Office Hours</label>
                  <input
                    value={supportForm.officeHours}
                    onChange={e => setSupportForm(p => ({ ...p, officeHours: e.target.value }))}
                    placeholder="e.g. Mon – Fri · 9 AM – 5 PM"
                  />
                </div>
              </div>
              <div className="form-group">
                <label>🏢 Office Address</label>
                <input
                  value={supportForm.officeAddress}
                  onChange={e => setSupportForm(p => ({ ...p, officeAddress: e.target.value }))}
                  placeholder="e.g. City Municipal Office, Ground Floor"
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                <button type="submit" className="btn btn-primary" disabled={supportSaving} style={{ minWidth: 160 }}>
                  {supportSaving ? 'Saving…' : '✓ Save Contact Details'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {activeTab === 'analytics' && <ChatAnalyticsTab API={API} />}

      {activeTab === 'complaints' && (
        <div>
          <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)', marginBottom: 24 }}>
            {[
              { label: 'Open',        value: complaints.filter(c=>c.status==='open').length,        color: '#ef4444' },
              { label: 'In Progress', value: complaints.filter(c=>c.status==='in_progress').length, color: '#d97706' },
              { label: 'Resolved',    value: complaints.filter(c=>c.status==='resolved').length,    color: '#2d7a2d' },
              { label: 'Total',       value: complaints.length,                                     color: '#2563eb' },
            ].map(s => (
              <div key={s.label} className="stat-card" style={{ borderLeft: `4px solid ${s.color}` }}>
                <div className="stat-value" style={{ color: s.color }}>{s.value}</div>
                <div className="stat-label">{s.label}</div>
              </div>
            ))}
          </div>

          {complaints.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
              <div style={{ fontSize: 44 }}>📬</div>
              <p style={{ marginTop: 10, fontWeight: 600 }}>No complaints submitted yet</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {complaints.map(c => {
                const meta = COMPLAINT_STATUS[c.status] || COMPLAINT_STATUS.open;
                const isOpen = expandedC === c._id;
                return (
                  <div key={c._id} className="card" style={{ padding: '18px 22px', borderLeft: `4px solid ${c.status==='open'?'#ef4444':c.status==='in_progress'?'#d97706':'#2d7a2d'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8, cursor: 'pointer' }}
                      onClick={() => setExpandedC(isOpen ? null : c._id)}>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>{c.subject}</div>
                        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                          {c.isAnonymous
                            ? <span style={{ color: '#d97706', fontWeight: 600 }}>🕵️ Anonymous</span>
                            : <span>👤 {c.residentName}</span>
                          } · {COMPLAINT_CATEGORIES[c.category] || c.category} ·{' '}
                          {new Date(c.createdAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span className={`badge ${meta.cls}`}>{meta.label}</span>
                        <span style={{ fontSize: 16, color: 'var(--muted)' }}>{isOpen ? '▲' : '▼'}</span>
                      </div>
                    </div>

                    {isOpen && (
                      <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                        <p style={{ fontSize: 14, color: 'var(--text)', lineHeight: 1.7, marginBottom: 16, background: 'var(--green-50)', borderRadius: 8, padding: '12px 14px' }}>
                          {c.description}
                        </p>
                        <div className="form-row">
                          <div className="form-group">
                            <label>Update Status</label>
                            <select defaultValue={c.status}
                              onChange={e => setReplyStatus(prev => ({ ...prev, [c._id]: e.target.value }))}
                            >
                              <option value="open">Open</option>
                              <option value="in_progress">In Progress</option>
                              <option value="resolved">Resolved</option>
                              <option value="closed">Closed</option>
                            </select>
                          </div>
                        </div>
                        <div className="form-group">
                          <label>Reply to Resident</label>
                          <textarea rows={3} placeholder="Write your response…"
                            defaultValue={c.adminReply}
                            onChange={e => setReplyText(prev => ({ ...prev, [c._id]: e.target.value }))}
                            style={{ resize: 'vertical' }}
                          />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpandedC(null)}>Cancel</button>
                          <button type="button" className="btn btn-primary btn-sm"
                            onClick={() => updateComplaint(c._id, replyStatus[c._id] || c.status, replyText[c._id] !== undefined ? replyText[c._id] : c.adminReply)}
                          >
                            Save Response
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
