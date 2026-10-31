import axios from 'axios';
import { API_URL, apiError } from './shipora';

export const MAX_PARCEL_KG = 20;  // a two-wheeler's carrying limit — keep in sync with MAX_PARCEL_KG in backend config

export const PAYMENT_METHODS = [
  { value: 'cash', label: 'Cash',  desc: 'Pay the rider on delivery' },
  { value: 'upi',  label: 'UPI',   desc: 'Pay the rider by UPI on delivery' },
];

export const PROHIBITED_ITEMS = [
  'Flammables and explosives', 'Alcohol and tobacco', 'Medicines and drugs', 'Cash, cards and jewellery',
  'Live animals', 'Liquids that can leak', 'Weapons and anything illegal', 'Sensitive documents (passports, originals)',
];

export const fmtINR = (n) => (n == null ? '—' : `₹${Math.round(n).toLocaleString('en-IN')}`);
export const fmtEta = (min) => {
  if (min == null) return '—';
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  return m ? `${h} hr ${m} min` : `${h} hr`;
};

/** POST /shipments/estimate (public). Resolves to the quote, or throws an Error with a customer-facing message. */
export async function getEstimate(pickup, drop, weightKg) {
  try {
    const body = { pickup: { lat: pickup.lat, lng: pickup.lng }, drop: { lat: drop.lat, lng: drop.lng } };
    if (weightKg > 0) body.weightKg = weightKg;
    const { data } = await axios.post(`${API_URL}/shipments/estimate`, body);
    return data;
  } catch (err) {
    throw new Error(apiError(err, 'Could not get an estimate right now.'));
  }
}
