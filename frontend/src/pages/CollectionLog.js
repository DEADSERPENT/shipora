import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import BackButton from '../components/BackButton';

export default function CollectionLog() {
  const { user, API } = useAuth();
  const [logs,    setLogs]    = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');
  const [filter,  setFilter]  = useState('all'); // all | nearby

  useEffect(() => {
    axios.get(`${API}/vehicles/history?days=30`)
      .then(({ data }) => setLogs(data))
      .catch(() => setError('Failed to load collection log.'))
      .finally(() => setLoading(false));
  }, [API]);

  const todayStr   = new Date().toDateString();
  const userArea   = (user?.address || '').toLowerCase();

  // Group logs by date
  const grouped = logs.reduce((acc, log) => {
    if (!acc[log.date]) acc[log.date] = [];
    acc[log.date].push(log);
    return acc;
  }, {});

  // Fuzzy match: does any completed area touch the resident's address words?
  const isNearResident = (log) => {
    if (!userArea) return false;
    const words = userArea.split(/[\s,]+/).filter(w => w.length > 3);
    return log.areasCompleted?.some(a =>
      words.some(w => a.toLowerCase().includes(w))
    );
  };

  const dates = Object.keys(grouped).sort((a, b) => new Date(b) - new Date(a));

  if (loading) return <div className="loading-screen"><div className="spinner" /><p style={{ color: '#6b8f6b', fontWeight: 600 }}>Loading logs…</p></div>;

  const totalCollections = logs.reduce((s, l) => s + (l.areasCompleted?.length || 0), 0);
  const activeDates      = dates.filter(d => grouped[d].some(l => l.areasCompleted?.length > 0));

  return (
    <div className="page" style={{ maxWidth: 900, margin: '0 auto' }}>
      <BackButton to="/dashboard" label="Dashboard" />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: 'var(--text)', marginBottom: 4 }}>🗓️ Collection Log</h1>
          <p style={{ color: 'var(--muted)', fontSize: 14 }}>Waste collection history in your area — last 30 days</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['all', 'nearby'].map(f => (
            <button key={f} type="button"
              onClick={() => setFilter(f)}
              style={{
                padding: '6px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                border: filter === f ? '2px solid var(--green-700)' : '2px solid var(--border)',
                background: filter === f ? 'var(--green-50)' : '#fff',
                color: filter === f ? 'var(--green-700)' : 'var(--muted)',
                cursor: 'pointer', transition: 'all 0.18s',
              }}
            >
              {f === 'all' ? '🌐 All Areas' : '📍 Near Me'}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Summary */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3,1fr)', marginBottom: 24 }}>
        {[
          { icon: '📅', value: activeDates.length, label: 'Days with Collection', color: '#2d7a2d' },
          { icon: '✅', value: totalCollections,   label: 'Areas Collected Total', color: '#2563eb' },
          { icon: '🚛', value: new Set(logs.map(l => l.driverId?._id)).size, label: 'Drivers Active', color: '#d97706' },
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

      {filter === 'nearby' && !userArea && (
        <div className="alert alert-warning" style={{ marginBottom: 16 }}>
          No address set on your profile. Showing all collections. Update your profile to filter by your area.
        </div>
      )}

      {dates.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
          <div style={{ fontSize: 44 }}>🗓️</div>
          <p style={{ marginTop: 10, fontWeight: 600 }}>No collection data for the past 30 days</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {dates.map(date => {
            const dayLogs = grouped[date];
            const isToday = date === todayStr;
            const hasNearby = dayLogs.some(isNearResident);

            if (filter === 'nearby' && !hasNearby && userArea) return null;

            const allAreas = [...new Set(dayLogs.flatMap(l => l.areasCompleted || []))];

            return (
              <div key={date} className="card" style={{
                padding: '18px 22px',
                borderLeft: `4px solid ${isToday ? '#2d7a2d' : allAreas.length ? '#3b82f6' : '#e2e8f0'}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>
                    {isToday ? '📅 Today' : `📅 ${date}`}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <span className="badge badge-blue">{dayLogs.length} driver{dayLogs.length !== 1 ? 's' : ''}</span>
                    <span className="badge badge-green">{allAreas.length} areas</span>
                    {isToday && <span className="badge badge-green"><span className="pulse-dot" />Live</span>}
                  </div>
                </div>

                {dayLogs.map((log, i) => (
                  <div key={i} style={{
                    background: isNearResident(log) ? '#f0fdf4' : 'var(--green-50)',
                    border: `1px solid ${isNearResident(log) ? '#bbf7d0' : 'var(--border)'}`,
                    borderRadius: 8, padding: '10px 14px', marginBottom: i < dayLogs.length - 1 ? 8 : 0,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, flexWrap: 'wrap', gap: 6 }}>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>
                        🚛 {log.driverId?.name || 'Driver'} · {log.driverId?.vehicleNo || '—'}
                      </span>
                      {isNearResident(log) && (
                        <span className="badge badge-green" style={{ fontSize: 11 }}>📍 Near your area</span>
                      )}
                    </div>
                    {log.areasCompleted?.length > 0 ? (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                        {log.areasCompleted.map((a, j) => (
                          <span key={j} className="badge badge-green" style={{ fontSize: 11 }}>✓ {a}</span>
                        ))}
                      </div>
                    ) : (
                      <span style={{ fontSize: 12, color: 'var(--muted)' }}>No areas marked yet</span>
                    )}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
