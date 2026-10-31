// Shipora domain constants + helpers shared by every page.
//
// The backend deliberately keeps its wire-level names (roles `user`/`driver`/`admin`,
// `/api/vehicles`, `/api/complaints`, `driver:*` socket events, `driverId` fields).
// This module is the ONE place that maps those technical names to user-facing
// Shipora terminology — pages should never print a wire name directly.
//
// Icons are lucide-react components. Anything rendered inside a native <option>
// (which cannot hold SVG) has a plain-text label only.
import {
  Bike, Building2, CalendarClock, CircleCheck, ClipboardList, DoorOpen, MapPin, Navigation,
  PackageCheck, PackageX, Rocket, Ban, Truck, TriangleAlert, Undo2, User, Van, CircleHelp,
} from 'lucide-react';

export const TOKEN_KEY = 'shipora_token';
export const authToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } };

// Socket.IO connection options. `auth` is a function so the CURRENT token is sent on every (re)connect —
// the server only gives the live fleet feed to, and only accepts positions from, authenticated sockets.
export const socketOptions = () => ({ transports: ['websocket', 'polling'], auth: (cb) => cb({ token: authToken() }) });

// An agent's app re-sends its last position this often even when standing still, so the server (which marks a
// vehicle stale after GPS_STALE_AFTER_SECONDS, default 90 s) keeps seeing a parked vehicle as live. Keep it well below that.
export const GPS_HEARTBEAT_MS = 30000;

export const API_URL    = process.env.REACT_APP_API_URL    || 'http://localhost:5000/api';
export const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000';

// ── Roles ────────────────────────────────────────────────────────────────────
export const ROLE_LABELS = {
  user:   { label: 'Customer',       icon: User,      color: '#0c831f', desc: 'Send parcels and track deliveries' },
  driver: { label: 'Delivery Agent', icon: Truck,     color: '#b45309', desc: 'Run your route and update shipments' },
  admin:  { label: 'Operations',     icon: Building2, color: '#6d28d9', desc: 'Manage the network, agents and shipments' },
};
export const roleLabel = (role) => (ROLE_LABELS[role] || ROLE_LABELS.user).label;
export const roleHome  = (role) => (role === 'driver' ? '/driver' : role === 'admin' ? '/admin' : '/dashboard');

// ── Shipment lifecycle ───────────────────────────────────────────────────────
// `step` positions a status on the happy-path progress bar (0–6); exceptions have step=null.
export const STATUS_META = {
  CREATED:              { label: 'Created',              icon: ClipboardList, tone: 'blue',   step: 0,    hint: 'Shipment booked — waiting for pickup to be scheduled.' },
  PICKUP_SCHEDULED:     { label: 'Pickup Scheduled',     icon: CalendarClock, tone: 'blue',   step: 1,    hint: 'A delivery agent is assigned to collect the parcel.' },
  PICKED_UP:            { label: 'Picked Up',            icon: PackageCheck,  tone: 'indigo', step: 2,    hint: 'The parcel has been collected from the sender.' },
  IN_TRANSIT:           { label: 'In Transit',           icon: Truck,         tone: 'indigo', step: 3,    hint: 'The rider is carrying the parcel to the drop location.' },
  OUT_FOR_DELIVERY:     { label: 'Out for Delivery',     icon: Navigation,    tone: 'orange', step: 4,    hint: 'The delivery agent is on the way to the receiver.' },
  DELIVERED:            { label: 'Delivered',            icon: CircleCheck,   tone: 'green',  step: 5,    hint: 'Delivered to the receiver.' },
  DELIVERY_FAILED:      { label: 'Delivery Failed',      icon: TriangleAlert, tone: 'red',    step: null, hint: 'The delivery attempt failed. A retry or return will follow.' },
  CUSTOMER_UNAVAILABLE: { label: 'Receiver Unavailable', icon: DoorOpen,      tone: 'red',    step: null, hint: 'Nobody was available to receive the parcel.' },
  ADDRESS_ISSUE:        { label: 'Address Issue',        icon: MapPin,        tone: 'red',    step: null, hint: 'The address could not be found or is incomplete.' },
  DAMAGED:              { label: 'Damaged',              icon: PackageX,      tone: 'red',    step: null, hint: 'The parcel was reported damaged.' },
  CANCELLED:            { label: 'Cancelled',            icon: Ban,           tone: 'gray',   step: null, hint: 'This shipment was cancelled.' },
  RETURN_TO_ORIGIN:     { label: 'Returned to Sender',   icon: Undo2,         tone: 'gray',   step: null, hint: 'The parcel is being / has been returned to the sender.' },
};
export const HAPPY_PATH = ['CREATED', 'PICKUP_SCHEDULED', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED'];
export const EXCEPTION_STATUSES = ['DELIVERY_FAILED', 'CUSTOMER_UNAVAILABLE', 'ADDRESS_ISSUE'];
export const TERMINAL_STATUSES  = ['DELIVERED', 'CANCELLED', 'RETURN_TO_ORIGIN'];
export const FAILED_STATUSES    = [...EXCEPTION_STATUSES, 'DAMAGED'];

export const statusMeta = (s) => STATUS_META[s] || { label: String(s || 'Unknown').replace(/_/g, ' '), icon: CircleHelp, tone: 'gray', step: null, hint: '' };
export const isTerminal = (s) => TERMINAL_STATUSES.includes(s);
export const isActive   = (s) => !isTerminal(s);

// Progress (0–100) along the happy path. Exceptions inherit the last happy-path step from history.
export function progressOf(shipment) {
  const meta = statusMeta(shipment.status);
  let step = meta.step;
  if (step === null) {
    const last = [...(shipment.statusHistory || [])].reverse().find(e => statusMeta(e.status).step !== null);
    step = last ? statusMeta(last.status).step : 0;
  }
  return Math.round((step / (HAPPY_PATH.length - 1)) * 100);
}

export const isDelayed = (s) =>
  isActive(s.status) && s.estimatedDelivery && new Date(s.estimatedDelivery).getTime() < Date.now();

// ── Service area & service ───────────────────────────────────────────────────
// Shipora is a same-day, Bengaluru-only service (Dunzo/Porter style). Keep this box in sync with
// backend-fastapi/services/geo.py, which enforces it on the server.
export const BENGALURU = {
  center: [12.9716, 77.5946],
  bounds: [[12.70, 77.35], [13.25, 77.85]],   // [[south, west], [north, east]]
  viewbox: '77.35,13.25,77.85,12.70',          // Nominatim "left,top,right,bottom"
};
export const inBengaluru = (lat, lng) =>
  lat >= BENGALURU.bounds[0][0] && lat <= BENGALURU.bounds[1][0] &&
  lng >= BENGALURU.bounds[0][1] && lng <= BENGALURU.bounds[1][1];
export const OUTSIDE_BENGALURU_MSG = 'Shipora delivers within Bengaluru only — please choose a spot inside Bengaluru.';

export const SERVICE_TYPES = [
  { value: 'same_day', label: 'Same-day',  icon: Rocket,  eta: 'within hours',  desc: 'Picked up and delivered today, anywhere in Bengaluru' },
];
export const serviceLabel = (v) => (SERVICE_TYPES.find(s => s.value === v) || { label: v }).label;

// ── Parcel ───────────────────────────────────────────────────────────────────
export const PARCEL_CATEGORIES = [
  { value: 'documents',   label: 'Documents' },
  { value: 'electronics', label: 'Electronics' },
  { value: 'clothing',    label: 'Clothing' },
  { value: 'food',        label: 'Food' },
  { value: 'fragile',     label: 'Fragile' },
  { value: 'other',       label: 'Other' },
];
export const parcelLabel = (v) => (PARCEL_CATEGORIES.find(c => c.value === v) || { label: v }).label;

export const CUSTOMER_TYPES = [
  { value: 'individual', label: 'Individual', icon: User },
  { value: 'business',   label: 'Business',   icon: Building2 },
];
export const VEHICLE_TYPES = [
  { value: 'bike',  label: 'Bike',  icon: Bike },
  { value: 'van',   label: 'Van',   icon: Van },
  { value: 'truck', label: 'Truck', icon: Truck },
];
// Lucide component for a vehicle type (falls back to a generic truck).
export const vehicleIcon = (t) => (VEHICLE_TYPES.find(v => v.value === t) || { icon: Truck }).icon;

// ── Delivery issues (backend path: /complaints) ──────────────────────────────
export const ISSUE_CATEGORIES = [
  { value: 'delayed_delivery', label: 'Delayed Delivery' },
  { value: 'lost_parcel',      label: 'Lost Parcel' },
  { value: 'damaged_parcel',   label: 'Damaged Parcel' },
  { value: 'wrong_address',    label: 'Wrong Address' },
  { value: 'agent_behaviour',  label: 'Agent Behaviour' },
  { value: 'failed_delivery',  label: 'Failed Delivery' },
  { value: 'other',            label: 'Other' },
];
export const ISSUE_STATUS = {
  open:        { label: 'Open',        cls: 'badge-red' },
  in_progress: { label: 'In Progress', cls: 'badge-amber' },
  resolved:    { label: 'Resolved',    cls: 'badge-green' },
  closed:      { label: 'Closed',      cls: 'badge-blue' },
};
export const issueCategoryLabel = (v) => (ISSUE_CATEGORIES.find(c => c.value === v) || {}).label || 'Other';

// ── Formatting ───────────────────────────────────────────────────────────────
export const fmtDate = (iso, opts = { day: 'numeric', month: 'short', year: 'numeric' }) =>
  iso ? new Date(iso).toLocaleDateString('en-IN', opts) : '—';
export const fmtDateTime = (iso) =>
  iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';

// The backend keys daily tracking logs by "Wed Oct 7 2026" (day NOT zero-padded), whereas
// Date#toDateString() gives "Wed Oct 07 2026" — so always build the key with this helper.
export function backendDateKey(d = new Date()) {
  const [wd, mon, , year] = d.toDateString().split(' ');
  return `${wd} ${mon} ${d.getDate()} ${year}`;
}

// 8–128 chars of [A-Za-z0-9_-:.] — what the backend accepts for an Idempotency-Key.
export const newIdempotencyKey = () => (
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
);

export const apiError = (err, fallback = 'Something went wrong.') =>
  err?.response?.data?.message || (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : null) || fallback;

export function haversine(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
