// Pure helpers behind the "live order" hero on the shipment page (components/LiveOrderHero.js).
// Kept free of React so the wording and the ETA maths are unit-tested (liveOrder.test.js).
import { statusMeta, isTerminal } from './shipora';

// The five stops a customer cares about; the seven-state backend lifecycle collapses onto them.
export const STEPS = [
  { key: 'booked',    label: 'Booked',         statuses: ['CREATED'] },
  { key: 'assigned',  label: 'Rider assigned', statuses: ['PICKUP_SCHEDULED'] },
  { key: 'picked',    label: 'Picked up',      statuses: ['PICKED_UP'] },
  { key: 'onway',     label: 'On the way',     statuses: ['IN_TRANSIT', 'OUT_FOR_DELIVERY'] },
  { key: 'delivered', label: 'Delivered',      statuses: ['DELIVERED'] },
];

const indexOfStatus = (status) => STEPS.findIndex(s => s.statuses.includes(status));

// Where on the stepper the shipment is. Exceptions (failed, cancelled, …) keep the last happy-path step from history.
export function stepIndex(shipment) {
  const direct = indexOfStatus(shipment.status);
  if (direct >= 0) return direct;
  const last = [...(shipment.statusHistory || [])].reverse().find(e => indexOfStatus(e.status) >= 0);
  return last ? indexOfStatus(last.status) : 0;
}

export function minutesLabel(minutes) {
  const m = Math.max(1, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

const clock = (iso) => new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }).replace(' am', ' am').replace(' pm', ' pm');

const ACTIVE_HEADLINE = {
  CREATED: 'Booked — assigning a rider',
  PICKUP_SCHEDULED: 'Rider assigned — pickup coming up',
  PICKED_UP: 'Picked up — heading out',
  IN_TRANSIT: 'On the way',
  OUT_FOR_DELIVERY: 'Your rider is on the way',
};

// What the hero says. tone: 'ok' | 'warn' | 'bad' | 'neutral'
export function etaSummary(shipment, now = Date.now()) {
  const meta = statusMeta(shipment.status);
  if (shipment.status === 'DELIVERED') {
    return { tone: 'ok', headline: 'Delivered', big: shipment.deliveredAt ? `at ${clock(shipment.deliveredAt)}` : 'Done', sub: meta.hint };
  }
  if (isTerminal(shipment.status)) {
    return { tone: 'neutral', headline: meta.label, big: meta.label, sub: meta.hint };
  }
  if (['DELIVERY_FAILED', 'CUSTOMER_UNAVAILABLE', 'ADDRESS_ISSUE', 'DAMAGED'].includes(shipment.status)) {
    return { tone: 'bad', headline: meta.label, big: 'Needs attention', sub: meta.hint };
  }
  const headline = ACTIVE_HEADLINE[shipment.status] || meta.label;
  if (!shipment.estimatedDelivery) return { tone: 'neutral', headline, big: 'Today', sub: meta.hint };
  const eta = new Date(shipment.estimatedDelivery).getTime();
  const diffMin = (eta - now) / 60000;
  if (diffMin >= 1) return { tone: 'ok', headline, big: `by ${clock(shipment.estimatedDelivery)}`, sub: `Arriving in about ${minutesLabel(diffMin)}` };
  return { tone: 'warn', headline, big: 'Running late', sub: `Expected by ${clock(shipment.estimatedDelivery)} — your rider is on it` };
}

export const initials = (name = '') => name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() || '').join('') || '?';
export const telHref = (phone = '') => `tel:${String(phone).replace(/[^\d+]/g, '')}`;
