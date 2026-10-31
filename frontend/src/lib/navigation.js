// Road routing, ETA and deadline maths for the delivery agent's navigation. Pure functions (tested in navigation.test.js)
// plus two network helpers: OSRM for the route and Nominatim for the street/area name. Neither needs an API key.
import { haversine } from './shipora';

const OSRM = 'https://router.project-osrm.org/route/v1/driving';
const ARRIVE_M = 60;              // inside this radius of the stop = arrived
const OFF_ROUTE_M = 80;           // further than this from the route line = re-route
const MAX_ACCURACY_M = 200;       // a fix less precise than this is Wi-Fi/IP-based, not GPS: never steer by it
const TIGHT_MIN = 10;             // inside this many minutes of the deadline = "tight"

export { ARRIVE_M, OFF_ROUTE_M, MAX_ACCURACY_M };

const turnText = (m, name) => {
  const road = name ? ` onto ${name}` : '';
  if (m.modifier === 'uturn') return `Make a U-turn${road}`;
  const dir = m.modifier || '';
  switch (m.type) {
    case 'depart': return `Head ${m.bearing_after != null ? compass(m.bearing_after) : 'out'}${name ? ` on ${name}` : ''}`;
    case 'arrive': return 'You have arrived';
    case 'roundabout': case 'rotary': return `At the roundabout take exit ${m.exit || ''}${road}`.trim();
    case 'merge': return `Merge ${dir}${road}`.trim();
    case 'fork': return `Keep ${dir || 'straight'}${road}`.trim();
    case 'end of road': return `At the end of the road turn ${dir}${road}`.trim();
    default: return dir && dir !== 'straight' ? `Turn ${dir}${road}` : `Continue${name ? ` on ${name}` : ' straight'}`;
  }
};
const compass = (b) => ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.round(b / 45) % 8];

// Route between two points: polyline, total distance (m) and duration (s), plus turn-by-turn steps.
export async function fetchRoute(from, to, signal) {
  const url = `${OSRM}/${from.lng},${from.lat};${to.lng},${to.lat}?overview=full&geometries=geojson&steps=true`;
  const res = await fetch(url, { signal });
  const data = await res.json();
  if (data.code !== 'Ok' || !data.routes?.[0]) throw new Error('No route found');
  const r = data.routes[0];
  return {
    coords: r.geometry.coordinates.map(([lng, lat]) => [lat, lng]),
    distanceM: r.distance,
    durationS: r.duration,
    steps: (r.legs?.[0]?.steps || []).map(s => ({
      text: turnText(s.maneuver, s.name),
      distanceM: s.distance,
      at: [s.maneuver.location[1], s.maneuver.location[0]],
    })),
  };
}

// Metres from a point to the nearest point of a polyline, and the index of the nearest vertex.
export function nearestOnRoute(pt, coords) {
  let best = { dist: Infinity, index: 0 };
  const k = Math.cos((pt.lat * Math.PI) / 180);
  for (let i = 0; i < coords.length - 1; i++) {
    const [aLat, aLng] = coords[i];
    const [bLat, bLng] = coords[i + 1];
    const ax = aLng * k, ay = aLat, bx = bLng * k, by = bLat, px = pt.lng * k, py = pt.lat;
    const dx = bx - ax, dy = by - ay;
    const t = dx || dy ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))) : 0;
    const d = haversine(pt.lat, pt.lng, ay + t * dy, (ax + t * dx) / k) * 1000;
    if (d < best.dist) best = { dist: d, index: t > 0.5 ? i + 1 : i };
  }
  return best;
}

// How much of the route is left from the rider's position (distance in m, time in s, scaled from the route's own duration).
export function remaining(pt, route) {
  const { coords, distanceM, durationS } = route;
  const { dist, index } = nearestOnRoute(pt, coords);
  let left = 0;
  for (let i = index; i < coords.length - 1; i++) left += haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]) * 1000;
  left += dist;                                  // getting back onto the line
  const frac = distanceM > 0 ? Math.min(1, left / distanceM) : 0;
  return { distanceM: left, durationS: durationS * frac, offRouteM: dist };
}

// The next manoeuvre still ahead of the rider.
export function nextStep(pt, route) {
  const { index } = nearestOnRoute(pt, route.coords);
  const ahead = route.steps.find(s => nearestOnRoute({ lat: s.at[0], lng: s.at[1] }, route.coords).index >= index && s.text !== 'You have arrived') || route.steps[route.steps.length - 1];
  if (!ahead) return null;
  return { text: ahead.text, distanceM: haversine(pt.lat, pt.lng, ahead.at[0], ahead.at[1]) * 1000 };
}

// On time / tight / late against a deadline. `etaMs` and `deadlineMs` are epoch milliseconds.
export function deadlineState(etaMs, deadlineMs) {
  if (!deadlineMs || !etaMs) return { state: 'none', diffMin: null };
  const diffMin = Math.round((deadlineMs - etaMs) / 60000);   // positive = minutes to spare
  if (diffMin < 0) return { state: 'late', diffMin };
  if (diffMin <= TIGHT_MIN) return { state: 'tight', diffMin };
  return { state: 'ontime', diffMin };
}

export const isArrived = (distanceM) => distanceM <= ARRIVE_M;
export const isPrecise = (accuracyM) => accuracyM == null || accuracyM <= MAX_ACCURACY_M;

export const fmtDistance = (m) => (m < 950 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`);
export const fmtDuration = (s) => {
  const min = Math.max(1, Math.round(s / 60));
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)} h ${min % 60} min`;
};
export const fmtClock = (ms) => new Date(ms).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });

// Walks `coords` and returns a point `metres` further along from `fromIndex` (used by the demo drive).
export function advanceAlong(coords, fromIndex, metres) {
  let i = fromIndex, left = metres;
  while (i < coords.length - 1) {
    const seg = haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]) * 1000;
    if (seg >= left) {
      const t = seg ? left / seg : 0;
      return { index: i, lat: coords[i][0] + (coords[i + 1][0] - coords[i][0]) * t, lng: coords[i][1] + (coords[i + 1][1] - coords[i][1]) * t, done: false };
    }
    left -= seg; i += 1;
  }
  const end = coords[coords.length - 1];
  return { index: coords.length - 1, lat: end[0], lng: end[1], done: true };
}

// Street / locality name for the rider's position, so nobody types "current area" by hand.
export async function areaName(lat, lng, signal) {
  const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=17&lat=${lat}&lon=${lng}`, { signal, headers: { 'Accept-Language': 'en' } });
  const a = (await res.json()).address || {};
  return [a.road, a.neighbourhood || a.suburb || a.city_district].filter(Boolean).join(', ') || a.suburb || a.city || '';
}
