import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from 'recharts';
import { useAuth } from '../context/AuthContext';
import ChatAnalyticsTab from '../components/ChatAnalyticsTab';
import VehicleMap from '../components/VehicleMap';
import { EmptyState, Loading, StatusBadge } from '../components/ShipmentUI';
import { useShipmentRoom, useVehicleFeed } from '../hooks/useLive';
import { ArrowDownToLine, ArrowUpFromLine, Bot, Building2, ChartColumn, Check, ChevronDown, ChevronUp, CircleCheck, ClipboardList, Clock, Globe, Inbox, Mail, Map as MapIcon, Megaphone, MessageCircle, Package, Phone, RefreshCw, Satellite, Search, Settings, Target, Timer, TriangleAlert, Truck, User, Users, VenetianMask } from 'lucide-react';
import { Ic } from '../components/Icon';
import {
  FAILED_STATUSES, ISSUE_STATUS, STATUS_META, apiError, backendDateKey, fmtDate, isActive, isDelayed,
  issueCategoryLabel, serviceLabel, vehicleIcon,
} from '../lib/shipora';
import './admin.css';

const TONE_COLOR = { blue: '#2fb44a', indigo: '#0a5c16', orange: '#f2b705', green: '#0c831f', red: '#e23744', gray: '#9aa59d' };  // brand palette (green ramp + yellow)

const initials = (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?';

function Kpi({ icon, label, value, note, tone = 'ok' }) {
  return (
    <div className={`ad-kpi ${tone}`}>
      <div className="ad-kpi-top"><span>{label}</span><span className="ad-kpi-ico"><Ic icon={icon} size={15} /></span></div>
      <div className="ad-kpi-val">{value}</div>
      {note && <div className="ad-kpi-note">{note}</div>}
    </div>
  );
}

export default function AdminDashboard() {
  const { user, API } = useAuth();
  const { vehicles, connected } = useVehicleFeed();

  const [stats, setStats]         = useState(null);
  const [logs, setLogs]           = useState([]);
  const [shipments, setShipments] = useState([]);
  const [agents, setAgents]       = useState([]);
  const [issues, setIssues]       = useState([]);
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState('network');
  const [statusFilter, setStatusFilter] = useState('active');
  const [query, setQuery]         = useState('');
  const [assigning, setAssigning] = useState({});   // shipmentId -> chosen agentId
  const [rowMsg, setRowMsg]       = useState({ type: '', text: '' });

  const [expandedC,  setExpandedC]    = useState(null);
  const [replyText,  setReplyText]    = useState({});
  const [replyStatus, setReplyStatus] = useState({});

  const [supportForm,    setSupportForm]    = useState({ phone: '', email: '', whatsapp: '', officeAddress: '', officeHours: '' });
  const [supportSaving,  setSupportSaving]  = useState(false);
  const [supportMsg,     setSupportMsg]     = useState({ type: '', text: '' });

  const fetchAll = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    try {
      const [st, sh, ag, is] = await Promise.all([
        axios.get(`${API}/admin/stats`),
        axios.get(`${API}/shipments`),
        axios.get(`${API}/admin/drivers`),
        axios.get(`${API}/complaints`),
      ]);
      setStats(st.data); setLogs(st.data.todayLogs || []);
      setShipments(sh.data); setAgents(ag.data); setIssues(is.data);
    } catch (err) {
      console.error('Failed to fetch operations data:', err);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [API]);

  const fetchLogsByDate = useCallback(async (dateStr) => {
    try {
      const { data } = await axios.get(`${API}/admin/logs?date=${encodeURIComponent(dateStr)}`);
      setLogs(data);
    } catch (err) { console.error('Failed to fetch logs:', err); }
  }, [API]);

  const fetchSupportCfg = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/support/config`);
      setSupportForm({
        phone: data.phone || '', email: data.email || '', whatsapp: data.whatsapp || '',
        officeAddress: data.officeAddress || '', officeHours: data.officeHours || '',
      });
    } catch {}
  }, [API]);

  useEffect(() => {
    fetchAll(); fetchSupportCfg();
    const interval = setInterval(() => fetchAll(true), 30000);
    return () => clearInterval(interval);
  }, [fetchAll, fetchSupportCfg]);

  // Real-time: any status change on an active shipment refreshes the dashboard.
  const activeShipments = useMemo(() => shipments.filter(s => isActive(s.status)), [shipments]);
  useShipmentRoom(activeShipments.map(s => s.trackingNumber), () => fetchAll(true));

  const saveSupportCfg = async (e) => {
    e.preventDefault();
    setSupportSaving(true); setSupportMsg({ type: '', text: '' });
    try {
      await axios.put(`${API}/support/config`, supportForm);
      setSupportMsg({ type: 'success', text: 'Support contact details saved successfully.' });
      setTimeout(() => setSupportMsg({ type: '', text: '' }), 3000);
    } catch (err) {
      setSupportMsg({ type: 'error', text: apiError(err, 'Save failed.') });
    } finally { setSupportSaving(false); }
  };

  const updateIssue = async (id, status, reply) => {
    try {
      await axios.put(`${API}/complaints/${id}`, { status, adminReply: reply });
      const { data } = await axios.get(`${API}/complaints`);
      setIssues(data); setExpandedC(null);
    } catch {}
  };

  const assign = async (s) => {
    const agentId = assigning[s._id];
    if (!agentId) return;
    setRowMsg({ type: '', text: '' });
    try {
      await axios.put(`${API}/shipments/${s._id}/assign`, { agentId });
      setRowMsg({ type: 'success', text: `${s.trackingNumber} assigned.` });
      setAssigning(p => ({ ...p, [s._id]: '' }));
      fetchAll(true);
    } catch (err) {
      setRowMsg({ type: 'error', text: apiError(err, 'Assignment failed.') });
    }
  };

  // ── Derived operations metrics ────────────────────────────────────────────
  const m = useMemo(() => {
    const delayed = shipments.filter(isDelayed);
    const failed  = shipments.filter(s => FAILED_STATUSES.includes(s.status));
    const delivered = shipments.filter(s => s.status === 'DELIVERED');
    const onTime = delivered.filter(s => s.deliveredAt && s.estimatedDelivery && new Date(s.deliveredAt) <= new Date(s.estimatedDelivery));
    const attempts = delivered.reduce((n, s) => n + (s.deliveryAttempts || 0), 0);
    const byStatus = Object.keys(STATUS_META).map(k => ({
      key: k, name: STATUS_META[k].label, count: shipments.filter(s => s.status === k).length, color: TONE_COLOR[STATUS_META[k].tone],
    })).filter(r => r.count > 0);
    return {
      delayed, failed, delivered,
      unassigned: shipments.filter(s => !s.assignedAgentId && isActive(s.status)),
      onTimePct: delivered.length ? Math.round((onTime.length / delivered.length) * 100) : null,
      firstAttemptPct: delivered.length ? Math.round((delivered.filter(s => s.deliveryAttempts <= 1).length / delivered.length) * 100) : null,
      avgAttempts: delivered.length ? (attempts / delivered.length).toFixed(1) : null,
      byStatus,
    };
  }, [shipments]);

  if (loading) return <Loading text="Loading operations dashboard…" />;

  const liveList    = Object.values(vehicles);
  const activeCount = liveList.filter(d => d.isActive).length;
  const openIssues  = issues.filter(c => c.status === 'open').length;
  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  const filters = {
    active:    s => isActive(s.status),
    all:       () => true,
    delayed:   isDelayed,
    failed:    s => FAILED_STATUSES.includes(s.status),
    unassigned: s => !s.assignedAgentId && isActive(s.status),
    delivered: s => s.status === 'DELIVERED',
    closed:    s => ['CANCELLED', 'RETURN_TO_ORIGIN'].includes(s.status),
  };
  const filterLabels = { active: 'Active', all: 'All', delayed: 'Delayed', failed: 'Failed', unassigned: 'Unassigned', delivered: 'Delivered', closed: 'Cancelled / Returned' };
  const q = query.trim().toLowerCase();
  const rows = shipments.filter(filters[statusFilter] || filters.all)
    .filter(s => !q || `${s.trackingNumber} ${s.customerName || ''} ${s.recipient?.name || ''} ${s.assignedAgent?.name || ''}`.toLowerCase().includes(q));

  const attention = [...new Map([...m.failed, ...m.delayed, ...m.unassigned].map(s => [s._id, s])).values()].slice(0, 8);

  const nav = [
    { group: 'Monitor', items: [
      { key: 'network',   icon: Globe,         label: 'Live network' },
      { key: 'shipments', icon: Package,       label: 'Shipments', count: activeShipments.length },
      { key: 'agents',    icon: Truck,         label: 'Delivery agents', count: agents.length },
    ] },
    { group: 'Resolve', items: [
      { key: 'issues',    icon: Megaphone,     label: 'Delivery issues', count: openIssues, hot: openIssues > 0 },
      { key: 'logs',      icon: ClipboardList, label: 'Route logs' },
    ] },
    { group: 'Configure', items: [
      { key: 'analytics', icon: Bot,           label: 'AI assistant' },
      { key: 'settings',  icon: Settings,      label: 'Settings' },
    ] },
  ];
  const current = nav.flatMap(g => g.items).find(i => i.key === activeTab);

  const issueColor = { open: '#e23744', in_progress: '#d97706' };

  return (
    <div className="ad">
      {/* ───────────── SIDEBAR ───────────── */}
      <aside className="ad-side" aria-label="Operations navigation">
        <div className="ad-brand">
          <span className="ad-brand-mark"><Ic icon={Building2} size={18} /></span>
          <div>
            <div className="ad-brand-name">Operations</div>
            <div className="ad-brand-sub">{user?.organization || 'Shipora'}</div>
          </div>
        </div>
        {nav.map(g => (
          <React.Fragment key={g.group}>
            <div className="ad-nav-label">{g.group}</div>
            {g.items.map(t => (
              <button key={t.key} type="button" className={`ad-nav-btn ${activeTab === t.key ? 'on' : ''}`}
                aria-current={activeTab === t.key ? 'page' : undefined} onClick={() => setActiveTab(t.key)}>
                <Ic icon={t.icon} size={17} /> {t.label}
                {t.count > 0 && <span className={`ad-nav-count ${t.hot ? 'hot' : ''}`}>{t.count}</span>}
              </button>
            ))}
          </React.Fragment>
        ))}
        <div className="ad-side-foot">
          <span className="ad-live"><span className={`ad-dot ${connected ? '' : 'off'}`} />{connected ? `${activeCount} ${activeCount === 1 ? 'vehicle' : 'vehicles'} live` : 'Live feed offline'}</span>
          <span>Signed in as {user?.name}</span>
        </div>
      </aside>

      <main className="ad-main">
        {/* ───────────── HEADER ───────────── */}
        <header className="ad-head">
          <div>
            <div className="ad-crumb">Bengaluru same-day network</div>
            <h1 className="ad-title">{current?.label || 'Operations'}</h1>
            <div className="ad-sub">{today}</div>
          </div>
          <div className="ad-actions">
            <button type="button" className="ad-btn" onClick={() => fetchAll(true)} disabled={refreshing}>
              <Ic icon={RefreshCw} size={15} className={refreshing ? 'ad-spin' : ''} /> {refreshing ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </header>

        {/* ───────────── LIVE NETWORK ───────────── */}
        {activeTab === 'network' && <>
          <section className="ad-kpis" aria-label="Key figures">
            <Kpi icon={Package} label="Active shipments" value={activeShipments.length} note={`${shipments.length} total`} tone="info" />
            <Kpi icon={Timer} label="Delayed" value={m.delayed.length} note={m.delayed.length ? 'Past estimated time' : 'All on schedule'} tone={m.delayed.length ? 'warn' : 'mute'} />
            <Kpi icon={TriangleAlert} label="Exceptions" value={m.failed.length} note={m.failed.length ? 'Need follow-up' : 'None open'} tone={m.failed.length ? 'warn' : 'mute'} />
            <Kpi icon={Truck} label="Agents live" value={<>{activeCount}<small> / {stats?.totalDrivers || 0}</small></>} note="Sharing GPS now" tone="amber" />
            <Kpi icon={CircleCheck} label="Delivered today" value={stats?.deliveredToday || 0} note={`${m.delivered.length} all time`} tone="ok" />
            <Kpi icon={Users} label="Customers" value={stats?.totalCustomers ?? 0} note="Registered accounts" tone="mute" />
          </section>

          <div className="ad-two">
            <section className="ad-panel">
              <div className="ad-panel-head">
                <h2 className="ad-panel-title"><Ic icon={MapIcon} size={18} /> Live delivery network</h2>
                <small style={{ color: 'var(--ad-mute)', fontSize: 12.5, fontWeight: 600 }}>{activeCount} active vehicle{activeCount !== 1 ? 's' : ''}</small>
              </div>
              <div className="ad-map">
                {activeCount > 0
                  ? <VehicleMap role="admin" vehicles={vehicles} />
                  : <EmptyState icon={Satellite} title="No vehicles are sharing location">Vehicles appear here when delivery agents start sharing their GPS.</EmptyState>}
              </div>
            </section>

            <section className="ad-panel">
              <div className="ad-panel-head">
                <h2 className="ad-panel-title">Fleet feed</h2>
                <span className="ad-live" style={{ color: 'var(--ad-ink)' }}><span className={`ad-dot ${activeCount ? '' : 'off'}`} />{activeCount}/{liveList.length}</span>
              </div>
              <div className="ad-fleet">
                {liveList.length === 0 ? <p className="ad-empty-note">No vehicle has reported yet.</p> : liveList.map(d => (
                  <div key={d.driverId} className={`ad-fleet-item ${d.isActive ? 'on' : ''}`}>
                    <div className="ad-fleet-row">
                      <span className="ad-avatar">{initials(d.driverName)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="ad-fleet-name">{d.driverName}</div>
                        <div className="ad-fleet-meta">{d.vehicleNo}</div>
                      </div>
                      <span className={`badge ${d.isActive ? 'badge-green' : d.state === 'stale' ? 'badge-amber' : 'badge-red'}`}>
                        {d.isActive ? 'On route' : d.state === 'stale' ? 'Signal lost' : 'Offline'}
                      </span>
                    </div>
                    {d.isActive && (
                      <div className="ad-fleet-grid">
                        <div>Area<b>{d.currentArea || 'N/A'}</b></div>
                        <div>ETA<b>{d.eta || 'N/A'}</b></div>
                        <div>Zones done<b>{d.areasCompleted?.length || 0}</b></div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="ad-two">
            <section className="ad-panel">
              <div className="ad-panel-head"><h2 className="ad-panel-title"><Ic icon={ChartColumn} size={18} /> Shipments by status</h2></div>
              <div className="ad-panel-body">
                {m.byStatus.length === 0 ? <EmptyState icon={ChartColumn} title="No shipments yet" /> : (
                  <div style={{ height: 270 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={m.byStatus} margin={{ top: 4, right: 8, left: -22, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e4e9e2" vertical={false} />
                        <XAxis dataKey="name" interval={0} angle={-30} textAnchor="end" tick={{ fontSize: 11, fill: '#66766c' }} height={60} axisLine={false} tickLine={false} />
                        <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#66766c' }} axisLine={false} tickLine={false} />
                        <Tooltip cursor={{ fill: 'rgba(15,29,23,.05)' }} contentStyle={{ borderRadius: 12, border: '1px solid #e4e9e2', fontSize: 13 }} />
                        <Bar dataKey="count" name="Shipments" radius={[6, 6, 0, 0]}>
                          {m.byStatus.map(r => <Cell key={r.key} fill={r.color} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </section>

            <section className="ad-panel">
              <div className="ad-panel-head"><h2 className="ad-panel-title"><Ic icon={Target} size={18} /> Delivery performance</h2></div>
              <div className="ad-panel-body">
                <div className="ad-meter">
                  <div className="ad-meter-row">On-time delivery <b>{m.onTimePct === null ? '—' : `${m.onTimePct}%`}</b></div>
                  <div className="ad-bar"><i style={{ width: `${m.onTimePct || 0}%` }} /></div>
                </div>
                <div className="ad-meter">
                  <div className="ad-meter-row">First-attempt success <b>{m.firstAttemptPct === null ? '—' : `${m.firstAttemptPct}%`}</b></div>
                  <div className="ad-bar amber"><i style={{ width: `${m.firstAttemptPct || 0}%` }} /></div>
                </div>
                <div className="ad-meter">
                  <div className="ad-meter-row">Avg. attempts per delivery <b>{m.avgAttempts ?? '—'}</b></div>
                </div>
                <div className="ad-meter">
                  <div className="ad-meter-row">Unassigned shipments <b style={{ color: m.unassigned.length ? 'var(--red)' : undefined }}>{m.unassigned.length}</b></div>
                </div>
                <div className="ad-meter">
                  <div className="ad-meter-row">Delivered (all time) <b>{m.delivered.length}</b></div>
                </div>
              </div>
            </section>
          </div>

          {attention.length > 0 && (
            <section className="ad-panel">
              <div className="ad-panel-head">
                <h2 className="ad-panel-title"><Ic icon={TriangleAlert} size={18} /> Needs attention <small>{attention.length} shown</small></h2>
                <button type="button" className="ad-btn sm" onClick={() => { setStatusFilter('delayed'); setActiveTab('shipments'); }}>Open in shipments</button>
              </div>
              <div className="ad-table-wrap">
                <table className="ad-table">
                  <thead><tr><th>Tracking</th><th>Customer</th><th>Status</th><th>Est. delivery</th><th>Agent</th></tr></thead>
                  <tbody>
                    {attention.map(s => (
                      <tr key={s._id}>
                        <td><Link to={`/shipments/${s.trackingNumber}`} className="tracking-no">{s.trackingNumber}</Link></td>
                        <td>{s.customerName || '—'}</td>
                        <td><StatusBadge status={s.status} />{isDelayed(s) && <span className="pill pill-red" style={{ marginLeft: 6 }}><Ic icon={Timer} size={12} /> Delayed</span>}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(s.estimatedDelivery)}</td>
                        <td>{s.assignedAgent ? s.assignedAgent.name : <span className="pill pill-red">Unassigned</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>}

        {/* ───────────── SHIPMENTS ───────────── */}
        {activeTab === 'shipments' && (
          <section className="ad-panel">
            <div className="ad-toolbar">
              <div className="ad-chips" role="group" aria-label="Shipment filter">
                {Object.keys(filterLabels).map(k => (
                  <button key={k} type="button" className={`ad-chip ${statusFilter === k ? 'on' : ''}`} aria-pressed={statusFilter === k} onClick={() => setStatusFilter(k)}>
                    {filterLabels[k]}<b>{shipments.filter(filters[k]).length}</b>
                  </button>
                ))}
              </div>
              <label className="ad-search">
                <Ic icon={Search} size={15} />
                <input className="ad-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search tracking, customer, agent…" aria-label="Search shipments" />
              </label>
            </div>
            {rowMsg.text && <div className={`ad-alert ${rowMsg.type}`} style={{ margin: '14px 20px 0' }}>{rowMsg.text}</div>}
            {rows.length === 0 ? <div style={{ padding: 20 }}><EmptyState icon={Inbox} title="No shipments in this view" /></div> : (
              <div className="ad-table-wrap">
                <table className="ad-table">
                  <thead><tr><th>Tracking</th><th>Customer</th><th>Route</th><th>Service</th><th>Status</th><th>Est. delivery</th><th>Agent</th></tr></thead>
                  <tbody>
                    {rows.map(s => (
                      <tr key={s._id}>
                        <td><Link to={`/shipments/${s.trackingNumber}`} className="tracking-no">{s.trackingNumber}</Link></td>
                        <td className="ad-cell-main">{s.customerName || '—'}</td>
                        <td>
                          <div className="ad-route">
                            <span title={s.sender.address}><Ic icon={ArrowUpFromLine} size={13} /> {s.sender.address}</span>
                            <span title={s.recipient.address}><Ic icon={ArrowDownToLine} size={13} /> {s.recipient.address}</span>
                          </div>
                        </td>
                        <td>{serviceLabel(s.serviceType)}</td>
                        <td style={{ whiteSpace: 'nowrap' }}><StatusBadge status={s.status} />{isDelayed(s) && <span className="pill pill-red" style={{ marginLeft: 6 }}><Ic icon={Timer} size={12} /></span>}</td>
                        <td style={{ fontSize: 12.5, whiteSpace: 'nowrap' }}>{fmtDate(s.estimatedDelivery)}</td>
                        <td style={{ minWidth: 240 }}>
                          {s.assignedAgent && <div className="ad-cell-main" style={{ fontSize: 13 }}><Ic icon={Truck} size={14} /> {s.assignedAgent.name}</div>}
                          {isActive(s.status) && (
                            <div className="ad-assign">
                              <select className="ad-select" aria-label={`Agent for ${s.trackingNumber}`} value={assigning[s._id] || ''} onChange={e => setAssigning(p => ({ ...p, [s._id]: e.target.value }))}>
                                <option value="">{s.assignedAgent ? 'Reassign…' : 'Select agent…'}</option>
                                {agents.map(a => <option key={a._id} value={a._id}>{a.name} · {a.vehicleNo}</option>)}
                              </select>
                              <button type="button" className="ad-btn primary sm" disabled={!assigning[s._id]} onClick={() => assign(s)}>Assign</button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {/* ───────────── AGENTS ───────────── */}
        {activeTab === 'agents' && (
          agents.length === 0 ? <section className="ad-panel"><div className="ad-panel-body"><EmptyState icon={Truck} title="No delivery agents registered" /></div></section> : (
            <div className="ad-agents">
              {agents.map(a => {
                const pending = shipments.filter(s => s.assignedAgentId === a._id && isActive(s.status)).length;
                const live = vehicles[a._id]?.isActive;
                return (
                  <article key={a._id} className="ad-agent">
                    <div className="ad-agent-head">
                      <span className="ad-avatar lg">{initials(a.name)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="ad-cell-main">{a.name}</div>
                        <div className="ad-cell-sub">{a.phone}</div>
                      </div>
                      <span className={`badge ${live ? 'badge-green' : 'badge-amber'}`}>{live ? 'Live' : 'Offline'}</span>
                    </div>
                    <div className="ad-agent-stats">
                      <div>Pending<b>{pending}</b></div>
                      <div>Delivered today<b>{a.todayLog?.deliveredCount ?? 0}</b></div>
                      <div>Zone<b style={{ fontSize: 13, paddingTop: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.assignedArea || '—'}</b></div>
                    </div>
                    <div className="ad-agent-foot">
                      <span className="badge badge-blue"><Ic icon={vehicleIcon(a.vehicleType)} size={13} /> {a.vehicleNo}</span>
                      <span>{a.todayLog?.currentArea ? `Now: ${a.todayLog.currentArea}` : 'No location today'}</span>
                    </div>
                  </article>
                );
              })}
            </div>
          )
        )}

        {/* ───────────── ROUTE LOGS ───────────── */}
        {activeTab === 'logs' && (
          <section className="ad-panel">
            <div className="ad-toolbar">
              <h2 className="ad-panel-title">Route logs <small>{logs.length} record{logs.length !== 1 ? 's' : ''}</small></h2>
              <label style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 13, color: 'var(--ad-mute)', fontWeight: 700 }}>
                Date
                <input type="date" className="ad-input" defaultValue={new Date().toISOString().slice(0, 10)}
                  onChange={e => { if (e.target.value) fetchLogsByDate(backendDateKey(new Date(e.target.value + 'T12:00:00'))); }} />
              </label>
            </div>
            {logs.length === 0 ? (
              <div style={{ padding: 20 }}><EmptyState icon={ClipboardList} title="No route logs for this date">Delivery agents generate logs when they share location or update status.</EmptyState></div>
            ) : (
              <div className="ad-table-wrap">
                <table className="ad-table">
                  <thead><tr><th>Agent</th><th>Vehicle</th><th>Zone</th><th>Delivered</th><th>Areas covered</th><th>Current area</th><th>ETA</th><th>Status</th><th>Updated</th></tr></thead>
                  <tbody>
                    {logs.map(log => (
                      <tr key={log._id}>
                        <td><div className="ad-cell-main">{log.driverId?.name || 'Unknown'}</div><div className="ad-cell-sub">{log.driverId?.phone}</div></td>
                        <td><span className="badge badge-blue">{log.driverId?.vehicleNo || '—'}</span></td>
                        <td>{log.driverId?.assignedArea || '—'}</td>
                        <td className="num">{log.deliveredCount || 0}</td>
                        <td>
                          {log.areasCompleted?.length > 0
                            ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{log.areasCompleted.map((a, j) => <span key={j} className="badge badge-blue" style={{ fontSize: 11 }}>{a}</span>)}</div>
                            : <span className="ad-cell-sub">None yet</span>}
                        </td>
                        <td>{log.currentArea || '—'}</td>
                        <td>{log.eta || '—'}</td>
                        <td><span className={`badge ${log.isActive ? 'badge-green' : 'badge-amber'}`}>{log.isActive ? 'Active' : <><Ic icon={Check} size={12} /> Done</>}</span></td>
                        <td className="ad-cell-sub" style={{ whiteSpace: 'nowrap' }}>{log.lastUpdated ? new Date(log.lastUpdated).toLocaleTimeString() : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {/* ───────────── SETTINGS ───────────── */}
        {activeTab === 'settings' && (
          <section className="ad-panel" style={{ maxWidth: 720 }}>
            <div className="ad-panel-head">
              <h2 className="ad-panel-title"><Ic icon={Phone} size={18} /> Support contact details</h2>
            </div>
            <div className="ad-panel-body">
              <p className="ad-sub" style={{ marginBottom: 18 }}>Shown to every user on the Customer Support page. Only operations admins can edit them.</p>
              {supportMsg.text && <div className={`ad-alert ${supportMsg.type}`} style={{ marginBottom: 16 }}>{supportMsg.text}</div>}
              <form className="ad-form" onSubmit={saveSupportCfg}>
                <div className="ad-form-grid">
                  <label className="ad-field"><span><Ic icon={Phone} size={13} /> Helpline number</span>
                    <input className="ad-input" value={supportForm.phone} onChange={e => setSupportForm(p => ({ ...p, phone: e.target.value }))} placeholder="e.g. 1800-SHIPORA" /></label>
                  <label className="ad-field"><span><Ic icon={Mail} size={13} /> Support email</span>
                    <input className="ad-input" type="email" value={supportForm.email} onChange={e => setSupportForm(p => ({ ...p, email: e.target.value }))} placeholder="e.g. support@shipora.in" /></label>
                  <label className="ad-field"><span><Ic icon={MessageCircle} size={13} /> WhatsApp number</span>
                    <input className="ad-input" value={supportForm.whatsapp} onChange={e => setSupportForm(p => ({ ...p, whatsapp: e.target.value }))} placeholder="e.g. +91 98765 43210" /></label>
                  <label className="ad-field"><span><Ic icon={Clock} size={13} /> Office hours</span>
                    <input className="ad-input" value={supportForm.officeHours} onChange={e => setSupportForm(p => ({ ...p, officeHours: e.target.value }))} placeholder="e.g. Mon – Sat · 8 AM – 8 PM" /></label>
                </div>
                <label className="ad-field"><span><Ic icon={Building2} size={13} /> Office address</span>
                  <input className="ad-input" value={supportForm.officeAddress} onChange={e => setSupportForm(p => ({ ...p, officeAddress: e.target.value }))} placeholder="e.g. Shipora Operations Hub, Bengaluru" /></label>
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button type="submit" className="ad-btn primary" disabled={supportSaving} style={{ minWidth: 170, justifyContent: 'center' }}>
                    {supportSaving ? 'Saving…' : <><Ic icon={Check} size={15} /> Save details</>}
                  </button>
                </div>
              </form>
            </div>
          </section>
        )}

        {activeTab === 'analytics' && <ChatAnalyticsTab API={API} />}

        {/* ───────────── DELIVERY ISSUES ───────────── */}
        {activeTab === 'issues' && <>
          <section className="ad-kpis" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }} aria-label="Issue counts">
            <Kpi icon={Megaphone} label="Open" value={issues.filter(c => c.status === 'open').length} tone="warn" />
            <Kpi icon={Clock} label="In progress" value={issues.filter(c => c.status === 'in_progress').length} tone="amber" />
            <Kpi icon={CircleCheck} label="Resolved" value={issues.filter(c => c.status === 'resolved').length} tone="ok" />
            <Kpi icon={Inbox} label="Total" value={issues.length} tone="mute" />
          </section>

          {issues.length === 0 ? (
            <section className="ad-panel"><div className="ad-panel-body"><EmptyState icon={Inbox} title="No delivery issues reported yet" /></div></section>
          ) : (
            <div className="ad-list">
              {issues.map(c => {
                const meta = ISSUE_STATUS[c.status] || ISSUE_STATUS.open;
                const isOpen = expandedC === c._id;
                return (
                  <article key={c._id} className="ad-issue" style={{ '--s': issueColor[c.status] || '#15803d' }}>
                    <button type="button" className="ad-issue-head" aria-expanded={isOpen} onClick={() => setExpandedC(isOpen ? null : c._id)}>
                      <div>
                        <div className="ad-cell-main" style={{ fontSize: 14.5 }}>{c.subject}</div>
                        <div className="ad-cell-sub" style={{ marginTop: 3 }}>
                          {c.isAnonymous ? <span style={{ color: '#d97706', fontWeight: 700 }}><Ic icon={VenetianMask} size={13} /> Anonymous</span> : <span><Ic icon={User} size={13} /> {c.customerName || '—'}</span>}
                          {' · '}{issueCategoryLabel(c.category)}
                          {c.trackingNumber && <> · <Link to={`/shipments/${c.trackingNumber}`} className="tracking-no" onClick={e => e.stopPropagation()}>{c.trackingNumber}</Link></>}
                          {' · '}{fmtDate(c.createdAt)}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 10, alignItems: 'center', color: 'var(--ad-mute)' }}>
                        <span className={`badge ${meta.cls}`}>{meta.label}</span>
                        <Ic icon={isOpen ? ChevronUp : ChevronDown} size={18} />
                      </div>
                    </button>

                    {isOpen && (
                      <div className="ad-issue-body">
                        <p className="ad-quote">{c.description}</p>
                        <label className="ad-field" style={{ maxWidth: 260 }}>Update status
                          <select className="ad-select" defaultValue={c.status} onChange={e => setReplyStatus(prev => ({ ...prev, [c._id]: e.target.value }))}>
                            <option value="open">Open</option><option value="in_progress">In progress</option>
                            <option value="resolved">Resolved</option><option value="closed">Closed</option>
                          </select>
                        </label>
                        <label className="ad-field">Reply to customer
                          <textarea rows={3} placeholder="Write your response…" defaultValue={c.adminReply}
                            onChange={e => setReplyText(prev => ({ ...prev, [c._id]: e.target.value }))} />
                        </label>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                          <button type="button" className="ad-btn sm" onClick={() => setExpandedC(null)}>Cancel</button>
                          <button type="button" className="ad-btn primary sm"
                            onClick={() => updateIssue(c._id, replyStatus[c._id] || c.status, replyText[c._id] !== undefined ? replyText[c._id] : c.adminReply)}>
                            Save response
                          </button>
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </>}
      </main>
    </div>
  );
}
