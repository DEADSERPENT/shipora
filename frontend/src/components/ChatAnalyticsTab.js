import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, LabelList, ResponsiveContainer,
} from 'recharts';
import { StatCard } from '../pages/AdminDashboard';

// Fixed categorical order, validated with the dataviz skill's palette
// validator (5-slot set, worst adjacent CVD ∆E 12.9 — clears the ≥12
// target). Green/red are deliberately excluded — reserved for
// SENTIMENT_META below, so "which agent" is never visually confused with
// "how the user felt."
const AGENT_META = {
  tracking:   { label: 'Tracking',   color: '#2a78d6' },
  complaints: { label: 'Complaints', color: '#eda100' },
  schedule:   { label: 'Schedule',   color: '#e87ba4' },
  support:    { label: 'Support',    color: '#1baf7a' },
  general:    { label: 'General',    color: '#4a3aa7' },
};
const SENTIMENT_META = {
  positive: { label: '🙂 Positive', color: '#0ca30c' },
  neutral:  { label: '😐 Neutral',  color: '#898781' },
  negative: { label: '🙁 Negative', color: '#d03b3b' },
};
const CHANNEL_ICON = { text: '💬', voice: '🎙️' };

function fmtMs(ms) {
  return ms == null ? '—' : `${ms} ms`;
}

export default function ChatAnalyticsTab({ API }) {
  const [data, setData]             = useState(null);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]           = useState(false);

  const fetchOverview = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const { data } = await axios.get(`${API}/analytics/overview`);
      setData(data);
      setError(false);
    } catch (err) {
      console.error('Failed to fetch chat analytics:', err);
      setError(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [API]);

  useEffect(() => {
    fetchOverview();
    const interval = setInterval(() => fetchOverview(true), 30000);
    return () => clearInterval(interval);
  }, [fetchOverview]);

  if (loading) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
        <div className="spinner" style={{ margin: '0 auto' }} />
        <p style={{ marginTop: 12, fontWeight: 600 }}>Loading chat analytics…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--muted)' }}>
        <div style={{ fontSize: 44 }}>🎙️</div>
        <p style={{ marginTop: 10, fontWeight: 600 }}>Couldn't load chat analytics</p>
      </div>
    );
  }

  const aiTotal = (data.sourceBreakdown.ai || 0) + (data.sourceBreakdown.builtin || 0);
  const aiRate = aiTotal > 0 ? Math.round((data.sourceBreakdown.ai / aiTotal) * 100) : 0;

  const agentChartData = data.agentDistribution.map(d => ({
    ...d,
    label: AGENT_META[d.agent]?.label || d.agent,
    color: AGENT_META[d.agent]?.color || '#888',
  }));
  const sentimentChartData = data.sentimentDistribution.map(d => ({
    ...d,
    label: SENTIMENT_META[d.sentiment]?.label || d.sentiment,
    color: SENTIMENT_META[d.sentiment]?.color || '#888',
  }));

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={() => fetchOverview(true)} disabled={refreshing}>
          {refreshing ? '⟳ Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {/* KPI row */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', marginBottom: 24 }}>
        <StatCard icon="💬" value={data.totalConversations} label="Total Conversations" color="green" />
        <StatCard icon="🤖" value={`${aiRate}%`}             label="AI Reply Rate"       color="blue" />
        <StatCard icon="⚡" value={fmtMs(data.avgLatencyMs.total)} label="Avg Total Latency" color="amber" />
        <StatCard icon="🎙️" value={fmtMs(data.avgLatencyMs.stt ?? data.avgLatencyMs.tts)} label="Avg STT/TTS Latency" color="purple" />
      </div>

      {/* Charts */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 20, marginBottom: 24 }}>
        <div className="card">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14, color: 'var(--text)' }}>Agent Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={agentChartData} layout="vertical" margin={{ left: 8, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="label" width={80} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {agentChartData.map(d => <Cell key={d.agent} fill={d.color} />)}
                <LabelList dataKey="count" position="right" style={{ fontSize: 12, fontWeight: 600 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14, color: 'var(--text)' }}>Sentiment</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={sentimentChartData} layout="vertical" margin={{ left: 8, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="label" width={90} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {sentimentChartData.map(d => <Cell key={d.sentiment} fill={d.color} />)}
                <LabelList dataKey="count" position="right" style={{ fontSize: 12, fontWeight: 600 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent conversations */}
      <div className="card">
        <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 14, color: 'var(--text)' }}>Recent Conversations</h3>
        {data.recentConversations.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 20px', color: 'var(--muted)' }}>
            <p style={{ fontWeight: 600 }}>No conversations logged yet</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Channel</th>
                  <th>Agent</th>
                  <th>Sentiment</th>
                  <th>Transcript</th>
                  <th>Reply</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {data.recentConversations.map((c, i) => (
                  <tr key={`${c.sessionId}-${i}`} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--green-50)' }}>
                    <td style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                      {c.createdAt ? new Date(c.createdAt).toLocaleTimeString() : '—'}
                    </td>
                    <td>{CHANNEL_ICON[c.channel] || c.channel}</td>
                    <td>
                      <span className="badge badge-blue">{AGENT_META[c.agent]?.label || c.agent}</span>
                    </td>
                    <td>{SENTIMENT_META[c.sentiment]?.label || c.sentiment}</td>
                    <td style={{ maxWidth: 220, fontSize: 12 }}>{c.transcript}</td>
                    <td style={{ maxWidth: 260, fontSize: 12, color: 'var(--muted)' }}>{c.reply}</td>
                    <td>
                      <span className={`badge ${c.source === 'ai' ? 'badge-green' : 'badge-blue'}`}>
                        {c.source === 'ai' ? 'AI' : 'Builtin'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
