import React, { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, Marker, Polyline, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import { renderToStaticMarkup } from 'react-dom/server';
import { ArrowDownToLine, ArrowUpFromLine, Clock, CornerUpRight, Crosshair, FlagTriangleRight, LocateFixed, MapPin, Navigation, Route, TriangleAlert } from 'lucide-react';
import { Ic } from './Icon';
import { BENGALURU } from '../lib/shipora';
import {
  OFF_ROUTE_M, advanceAlong, areaName, deadlineState, fetchRoute, fmtClock, fmtDistance, fmtDuration, isArrived, nextStep, remaining,
} from '../lib/navigation';
import './rider.css';

const makeIcon = (Icon, color, size = 38) => L.divIcon({
  className: '',
  html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center">${renderToStaticMarkup(<Icon size={Math.round(size * 0.5)} color="#fff" strokeWidth={2.4} />)}</div>`,
  iconSize: [size, size], iconAnchor: [size / 2, size / 2],
});
const riderIcon = makeIcon(Navigation, '#0c831f', 42);
const pickupIcon = makeIcon(ArrowUpFromLine, '#f59e0b');
const dropIcon = makeIcon(ArrowDownToLine, '#e23744');

function Camera({ position, target, follow }) {
  const map = useMap();
  const fitted = useRef('');
  const key = target ? `${target.lat},${target.lng}` : '';
  useEffect(() => {
    if (position && target && fitted.current !== key) {
      fitted.current = key;
      map.fitBounds([[position.lat, position.lng], [target.lat, target.lng]], { padding: [60, 60], maxZoom: 16 });
    }
  }, [key, position, target, map]);
  useEffect(() => { if (follow && position) map.setView([position.lat, position.lng], Math.max(map.getZoom(), 16), { animate: true }); }, [follow, position, map]);
  return null;
}

const STATE_COPY = {
  ontime: { cls: 'ok', label: 'On time' },
  tight: { cls: 'warn', label: 'Cutting it close' },
  late: { cls: 'bad', label: 'Running late' },
  none: { cls: 'mute', label: 'No deadline' },
};

// Turn-by-turn navigation for the delivery agent: picks the next stop (pickup or drop), draws the road route from the
// rider's real GPS position, re-routes if they leave it, and works out the arrival time against the delivery deadline.
// Reports the live ETA, distance and street name upward so customers and Operations see the same numbers.
export default function RiderNavigator({ shipments, position, mode, onStartGps, onStartDemo, onStop, onFix, onTelemetry, renderActions, gpsNote }) {
  const jobs = useMemo(() => shipments
    .map(s => ({ s, leg: s.status === 'PICKUP_SCHEDULED' ? 'pickup' : 'drop' }))
    .sort((a, b) => new Date(a.s.estimatedDelivery || 0) - new Date(b.s.estimatedDelivery || 0)), [shipments]);
  const [selId, setSelId] = useState(null);
  const job = jobs.find(j => j.s._id === selId) || jobs[0];
  const target = job ? (job.leg === 'pickup' ? job.s.sender?.location : job.s.recipient?.location) : null;
  const dropLoc = job?.s.recipient?.location;

  const [route, setRoute] = useState(null);         // rider -> next stop
  const [dropRoute, setDropRoute] = useState(null); // pickup -> drop (only needed while heading to the pickup)
  const [routeErr, setRouteErr] = useState('');
  const [area, setArea] = useState('');
  const [follow, setFollow] = useState(true);
  const [speed, setSpeed] = useState(30);          // demo drive runs this many times faster than real time
  const simStart = useRef(Date.now());
  const [, setTick] = useState(0);
  const lastFetch = useRef({ at: 0, key: '' });
  const lastArea = useRef({ at: 0, lat: 0, lng: 0 });
  const demoIdx = useRef({ index: 0, key: '' });

  useEffect(() => { const t = setInterval(() => setTick(n => n + 1), 15000); return () => clearInterval(t); }, []);

  // Route to the next stop: fetched when the stop changes, and again whenever the rider strays off the line.
  const targetKey = target ? `${job.s._id}:${job.leg}` : '';
  useEffect(() => {
    if (!position || !target) return undefined;
    const now = Date.now();
    const stray = route && remaining(position, route).offRouteM > OFF_ROUTE_M;
    const changed = lastFetch.current.key !== targetKey;
    if (!changed && !(stray && now - lastFetch.current.at > 8000) && route) return undefined;
    lastFetch.current = { at: now, key: targetKey };
    const ctl = new AbortController();
    fetchRoute(position, target, ctl.signal).then(r => { setRoute(r); setRouteErr(''); demoIdx.current = { index: 0, key: targetKey }; })
      .catch(e => { if (e.name !== 'AbortError') setRouteErr('Could not load the road route — check your connection.'); });
    return () => ctl.abort();
  }, [position, target, targetKey]); // eslint-disable-line

  useEffect(() => {
    setDropRoute(null);
    if (job?.leg !== 'pickup' || !target || !dropLoc) return undefined;
    const ctl = new AbortController();
    fetchRoute(target, dropLoc, ctl.signal).then(setDropRoute).catch(() => {});
    return () => ctl.abort();
  }, [targetKey]); // eslint-disable-line

  // Street name for the live position (throttled: Nominatim allows about one request a second).
  useEffect(() => {
    if (!position) return undefined;
    const last = lastArea.current;
    const moved = Math.hypot(position.lat - last.lat, position.lng - last.lng) * 111000;
    if (Date.now() - last.at < 6000 || (last.at && moved < 200)) return undefined;
    lastArea.current = { at: Date.now(), lat: position.lat, lng: position.lng };
    const ctl = new AbortController();
    areaName(position.lat, position.lng, ctl.signal).then(setArea).catch(() => {});
    return () => ctl.abort();
  }, [position]);

  const rem = position && route ? remaining(position, route) : null;
  const arrived = rem ? isArrived(rem.distanceM) : false;
  const step = position && route ? nextStep(position, route) : null;
  // In the simulated drive the whole clock runs `speed` times faster, so the ETA stays steady while the rider covers the route.
  const nowMs = mode === 'demo' ? simStart.current + (Date.now() - simStart.current) * speed : Date.now();
  const arriveMs = rem ? nowMs + rem.durationS * 1000 : null;
  // Heading to the pickup: the delivery is only on time if pickup + the pickup->drop drive (+ 5 min handover) still fits.
  const deliveryMs = arriveMs && job ? (job.leg === 'pickup' ? (dropRoute ? arriveMs + dropRoute.durationS * 1000 + 300000 : null) : arriveMs) : null;
  const deadline = job?.s.estimatedDelivery ? new Date(job.s.estimatedDelivery).getTime() : null;
  const ds = deadlineState(deliveryMs, deadline);
  const copy = STATE_COPY[ds.state];

  // Live numbers for customers and Operations.
  const telemetry = useMemo(() => (rem ? {
    eta: fmtClock(arriveMs), etaMinutes: Math.round(rem.durationS / 60), distanceKm: +(rem.distanceM / 1000).toFixed(2),
    currentArea: area, target: job?.s.trackingNumber, leg: job?.leg,
  } : { currentArea: area }), [rem?.distanceM && Math.round(rem.distanceM / 25), area, job?.s.trackingNumber]); // eslint-disable-line
  useEffect(() => { onTelemetry?.(telemetry); }, [telemetry]); // eslint-disable-line

  // Demo drive: moves a simulated GPS fix along the real route (development builds only).
  useEffect(() => {
    if (mode !== 'demo' || !route) return undefined;
    if (demoIdx.current.key !== targetKey) demoIdx.current = { index: 0, key: targetKey };
    let travelled = 0;
    const mps = (route.distanceM / Math.max(route.durationS, 1)) * speed;     // the route's real average speed, sped up
    const t = setInterval(() => {
      travelled += mps;
      const p = advanceAlong(route.coords, 0, travelled);
      onFix?.({ lat: p.lat, lng: p.lng, accuracy: 5, demo: true });
      if (p.done) clearInterval(t);
    }, 1000);
    return () => clearInterval(t);
  }, [mode, route, targetKey, speed]); // eslint-disable-line

  if (!job) {
    return (
      <div className="rn rn-empty">
        <Ic icon={Route} size={28} />
        <b>No active stops</b>
        <span>When Operations assigns you a parcel, your route to the pickup appears here.</span>
      </div>
    );
  }

  const stopName = job.leg === 'pickup' ? 'pickup' : 'drop-off';
  const addr = job.leg === 'pickup' ? job.s.sender?.address : job.s.recipient?.address;

  return (
    <div className="rn">
      <div className="rn-jobs" role="tablist" aria-label="Stops">
        {jobs.map(j => (
          <button key={j.s._id} type="button" role="tab" aria-selected={j.s._id === job.s._id} className={`rn-job ${j.s._id === job.s._id ? 'on' : ''}`} onClick={() => setSelId(j.s._id)}>
            <Ic icon={j.leg === 'pickup' ? ArrowUpFromLine : ArrowDownToLine} size={14} />
            <span>{j.s.trackingNumber}</span>
            <small>{j.leg === 'pickup' ? 'Pickup' : 'Drop'}</small>
          </button>
        ))}
      </div>

      <div className="rn-map">
        <MapContainer center={position ? [position.lat, position.lng] : [target.lat, target.lng]} zoom={15} minZoom={11} maxBounds={BENGALURU.bounds} maxBoundsViscosity={1} style={{ height: '100%', width: '100%' }}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap" />
          {route && <Polyline positions={route.coords} pathOptions={{ color: '#fff', weight: 10, opacity: 0.9 }} />}
          {route && <Polyline positions={route.coords} pathOptions={{ color: '#0c831f', weight: 6, opacity: 0.95 }} />}
          <Marker position={[target.lat, target.lng]} icon={job.leg === 'pickup' ? pickupIcon : dropIcon} />
          {position && <Marker position={[position.lat, position.lng]} icon={riderIcon} zIndexOffset={1000} />}
          <Camera position={position} target={target} follow={follow && !!position} />
        </MapContainer>
        <button type="button" className={`rn-follow ${follow ? 'on' : ''}`} onClick={() => setFollow(f => !f)} aria-pressed={follow}>
          <Ic icon={follow ? LocateFixed : Crosshair} size={16} /> {follow ? 'Following you' : 'Follow me'}
        </button>
        {mode === 'demo' && (
          <div className="rn-demo">
            <span>SIMULATED DRIVE</span>
            {[10, 30, 60].map(k => <button key={k} type="button" className={speed === k ? 'on' : ''} onClick={() => setSpeed(k)}>{k}×</button>)}
          </div>
        )}
      </div>

      <div className="rn-panel">
        <div className="rn-stop">
          <span className={`rn-stop-ico ${job.leg}`}><Ic icon={job.leg === 'pickup' ? ArrowUpFromLine : ArrowDownToLine} size={18} /></span>
          <div style={{ minWidth: 0 }}>
            <div className="rn-stop-kind">Next stop · {stopName}</div>
            <div className="rn-stop-addr">{addr}</div>
            <div className="rn-stop-sub">{job.leg === 'pickup' ? job.s.sender?.name : job.s.recipient?.name} · {job.leg === 'pickup' ? job.s.sender?.phone : job.s.recipient?.phone}</div>
          </div>
        </div>

        {!position && (
          <div className="rn-start">
            <p>Start the trip and Shipora finds the fastest road route to the {stopName}, drives it step by step, and keeps the customer and Operations updated with a live arrival time.</p>
            <div className="rn-start-btns">
              <button type="button" className="rn-btn primary" onClick={() => { simStart.current = Date.now(); onStartDemo(); onFix({ lat: target.lat - 0.02, lng: target.lng - 0.012, accuracy: 5, demo: true }); }}><Ic icon={Navigation} size={16} /> Start trip</button>
            </div>
            <button type="button" className="rn-link" onClick={onStartGps}>On a phone? Use this device's GPS instead</button>
          </div>
        )}

        {gpsNote && <div className="rn-warn"><Ic icon={TriangleAlert} size={16} /> {gpsNote}</div>}
        {routeErr && <div className="rn-warn"><Ic icon={TriangleAlert} size={16} /> {routeErr}</div>}

        {rem && (
          <>
            <div className="rn-kpis">
              <div><span>Arrive at {stopName}</span><b>{fmtClock(arriveMs)}</b></div>
              <div><span>Distance</span><b>{fmtDistance(rem.distanceM)}</b></div>
              <div><span>Drive time</span><b>{fmtDuration(rem.durationS)}</b></div>
            </div>

            <div className={`rn-deadline ${copy.cls}`}>
              <Ic icon={ds.state === 'late' ? TriangleAlert : ds.state === 'none' ? Clock : FlagTriangleRight} size={18} />
              <div>
                <b>{copy.label}{ds.diffMin != null ? (ds.diffMin >= 0 ? ` · ${ds.diffMin} min to spare` : ` · ${-ds.diffMin} min over`) : ''}</b>
                <small>{deadline ? `Deliver by ${fmtClock(deadline)}${deliveryMs ? ` · projected ${fmtClock(deliveryMs)}` : ''}` : 'No delivery deadline set'}</small>
              </div>
            </div>

            {step && !arrived && (
              <div className="rn-turn"><Ic icon={CornerUpRight} size={20} /><div><b>{step.text}</b><small>in {fmtDistance(step.distanceM)}</small></div></div>
            )}

            {arrived && (
              <div className="rn-arrived">
                <b><Ic icon={MapPin} size={16} /> You've arrived at the {stopName}</b>
                <span>Update the parcel below so the customer sees it straight away.</span>
              </div>
            )}

            <div className="rn-area"><Ic icon={MapPin} size={14} /> {area || 'Locating street…'}</div>
          </>
        )}

        {renderActions && <div className="rn-actions">{renderActions(job.s)}</div>}

        {position && (
          <button type="button" className="rn-btn danger" onClick={onStop}>End trip</button>
        )}
      </div>
    </div>
  );
}
