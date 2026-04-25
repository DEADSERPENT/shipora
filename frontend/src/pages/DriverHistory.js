import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';

export default function DriverHistory() {
  const { API } = useAuth();
  const [logs,    setLogs]    = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  useEffect(() => {
    axios.get(`${API}/vehicles/history?days=30`)
      .then(({ data }) => setLogs(data))
      .catch(() => setError('Failed to load history.'))
      .finally(() => setLoading(false));
  }, [API]);

  const totalAreas   = logs.reduce((s, l) => s + (l.areasCompleted?.length || 0), 0);
  const activeDays   = logs.filter(l => l.areasCompleted?.length > 0).length;
  const todayStr     = new Date().toDateString();

  if (loading) return <div className="loading-screen"><div className="spinner" /><p style={{ color: '#6b8f6b', fontWeight: 600 }}>Loading history…</p></div>;

  return (
    <div className="page" style={{ maxWidth: 900, margin: '0 auto' }}>
      <BackButton to="/driver" label="Driver Dashboard" />

      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: 'var(--text)', marginBottom: 4 }}>📋 Collection History</h1>
        <p style={{ color: 'var(--muted)', fontSize: 14 }}>Your waste collection log for the past 30 days</p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Summary */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3,1fr)', marginBottom: 24 }}>
        {[
          { icon: '📅', value: activeDays,  label: 'Active Days',           color: '#2d7a2d' },
          { icon: '✅', value: totalAreas,  label: 'Total Areas Collected',  color: '#2563eb' },
          { icon: '📊', value: logs.length, label: 'Total Log Entries',      color: '#d97706' },
        ].map(s => (
          <div key={s.label} className="stat-card" style={{ borderLeft: `4px solid ${s.color}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div className="stat-value" style={{ color: s.color }}>{s.value}</div>
                <div className="stat-label">{s.label}</div>
              </div>
              <div style={{ fontSize: 28 }}>{s.icon}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Log entries */}
      {logs.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
          <div style={{ fontSize: 44 }}>📋</div>
          <p style={{ marginTop: 10, fontWeight: 600 }}>No collection logs in the past 30 days</p>
          <p style={{ fontSize: 13, marginTop: 4 }}>Logs are created when you share your location and mark areas as completed.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {logs.map(log => {
            const isToday = log.date === todayStr;
            return (
              <div key={log._id} className="card" style={{
                padding: '18px 22px',
                borderLeft: `4px solid ${isToday ? '#2d7a2d' : log.areasCompleted?.length ? '#3b82f6' : '#e2e8f0'}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>
                      {isToday ? '📅 Today' : `📅 ${log.date}`}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                      Last updated: {log.lastUpdated ? new Date(log.lastUpdated).toLocaleTimeString() : '—'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span className={`badge ${log.isActive ? 'badge-green' : 'badge-blue'}`}>
                      {log.isActive ? '● Active' : '✓ Completed'}
                    </span>
                    <span className="badge badge-blue">{log.areasCompleted?.length || 0} areas</span>
                  </div>
                </div>

                {log.areasCompleted?.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      Areas Collected
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {log.areasCompleted.map((a, i) => (
                        <span key={i} className="badge badge-green" style={{ fontSize: 12 }}>✓ {a}</span>
                      ))}
                    </div>
                  </div>
                )}

                {(log.currentArea || log.eta) && (
                  <div style={{ marginTop: 10, fontSize: 13, color: 'var(--muted)', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    {log.currentArea && <span>📍 Area: <strong>{log.currentArea}</strong></span>}
                    {log.eta         && <span>🕐 ETA: <strong>{log.eta}</strong></span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
