import { advanceAlong, deadlineState, fmtDistance, fmtDuration, isArrived, isPrecise, nearestOnRoute, remaining } from './navigation';

// A straight ~2.2 km road heading north from Koramangala.
const coords = [[12.9300, 77.6200], [12.9400, 77.6200], [12.9500, 77.6200]];
const route = { coords, distanceM: 2224, durationS: 400, steps: [] };

test('a point on the road is ~0 m from it; a point to the side is measured from the nearest part of the line', () => {
  expect(nearestOnRoute({ lat: 12.935, lng: 77.62 }, coords).dist).toBeLessThan(2);
  const side = nearestOnRoute({ lat: 12.935, lng: 77.6209 }, coords).dist;       // ~0.0009° of longitude ≈ 97 m
  expect(side).toBeGreaterThan(80);
  expect(side).toBeLessThan(115);
});

test('remaining distance and time shrink as the rider moves along the route', () => {
  const start = remaining({ lat: 12.93, lng: 77.62 }, route);
  const half = remaining({ lat: 12.94, lng: 77.62 }, route);
  const end = remaining({ lat: 12.95, lng: 77.62 }, route);
  expect(start.distanceM).toBeGreaterThan(2100);
  expect(half.distanceM).toBeGreaterThan(1050);
  expect(half.distanceM).toBeLessThan(1150);
  expect(half.durationS).toBeLessThan(start.durationS);
  expect(end.distanceM).toBeLessThan(5);
});

test('deadline state is on time, tight, or late, with minutes to spare', () => {
  const now = Date.now(), min = 60000;
  expect(deadlineState(now + 5 * min, now + 40 * min)).toEqual({ state: 'ontime', diffMin: 35 });
  expect(deadlineState(now + 35 * min, now + 40 * min).state).toBe('tight');
  expect(deadlineState(now + 50 * min, now + 40 * min)).toEqual({ state: 'late', diffMin: -10 });
  expect(deadlineState(now, null).state).toBe('none');
});

test('arrival and GPS-precision thresholds', () => {
  expect(isArrived(40)).toBe(true);
  expect(isArrived(200)).toBe(false);
  expect(isPrecise(15)).toBe(true);
  expect(isPrecise(1500)).toBe(false);      // an IP/Wi-Fi style fix is never used to steer
  expect(isPrecise(undefined)).toBe(true);
});

test('the demo drive advances along the road and stops at the end', () => {
  const a = advanceAlong(coords, 0, 500);
  expect(a.done).toBe(false);
  expect(a.lat).toBeGreaterThan(12.93);
  expect(a.lat).toBeLessThan(12.94);
  expect(advanceAlong(coords, 0, 99999).done).toBe(true);
});

test('formatting', () => {
  expect(fmtDistance(420)).toBe('420 m');
  expect(fmtDistance(2300)).toBe('2.3 km');
  expect(fmtDuration(30)).toBe('1 min');
  expect(fmtDuration(3900)).toBe('1 h 5 min');
});
