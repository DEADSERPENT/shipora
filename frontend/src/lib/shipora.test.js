import {
  HAPPY_PATH, STATUS_META, backendDateKey, isActive, isDelayed, issueCategoryLabel, progressOf,
  roleHome, roleLabel, statusMeta, vehicleIcon, apiError,
} from './shipora';

const hist = (...statuses) => statuses.map(status => ({ status, at: '2026-10-07T08:00:00Z' }));

test('wire roles map to Shipora terminology and home routes', () => {
  expect(roleLabel('user')).toBe('Customer');
  expect(roleLabel('driver')).toBe('Delivery Agent');
  expect(roleLabel('admin')).toBe('Operations');
  expect(roleHome('user')).toBe('/dashboard');
  expect(roleHome('driver')).toBe('/driver');
  expect(roleHome('admin')).toBe('/admin');
});

test('every backend lifecycle status has metadata with a label and an icon', () => {
  const backend = ['CREATED', 'PICKUP_SCHEDULED', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED',
    'DELIVERY_FAILED', 'CUSTOMER_UNAVAILABLE', 'ADDRESS_ISSUE', 'DAMAGED', 'CANCELLED', 'RETURN_TO_ORIGIN'];
  backend.forEach(s => {
    expect(STATUS_META[s]).toBeDefined();
    expect(STATUS_META[s].label).toBeTruthy();
    expect(STATUS_META[s].icon).toBeTruthy();
  });
  expect(HAPPY_PATH).toEqual(backend.slice(0, 6));
  expect(statusMeta('SOMETHING_NEW').label).toBe('SOMETHING NEW'); // unknown values never crash the UI
});

test('progress follows the happy path and exceptions keep the last happy step', () => {
  expect(progressOf({ status: 'CREATED' })).toBe(0);
  expect(progressOf({ status: 'DELIVERED' })).toBe(100);
  expect(progressOf({ status: 'OUT_FOR_DELIVERY' })).toBe(80);
  const failed = { status: 'CUSTOMER_UNAVAILABLE', statusHistory: hist('CREATED', 'PICKUP_SCHEDULED', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'CUSTOMER_UNAVAILABLE') };
  expect(progressOf(failed)).toBe(80);
});

test('delayed means active and past the estimated delivery', () => {
  const past = new Date(Date.now() - 86400000).toISOString();
  const future = new Date(Date.now() + 86400000).toISOString();
  expect(isDelayed({ status: 'IN_TRANSIT', estimatedDelivery: past })).toBe(true);
  expect(isDelayed({ status: 'IN_TRANSIT', estimatedDelivery: future })).toBe(false);
  expect(isDelayed({ status: 'DELIVERED', estimatedDelivery: past })).toBe(false);
  expect(isActive('RETURN_TO_ORIGIN')).toBe(false);
});

test('issue category labels fall back to Other for unknown values', () => {
  expect(issueCategoryLabel('delayed_delivery')).toBe('Delayed Delivery');
  expect(issueCategoryLabel('agent_behaviour')).toBe('Agent Behaviour');
  expect(issueCategoryLabel('totally_unknown')).toBe('Other');
});

test("backendDateKey matches the backend's un-padded day format", () => {
  expect(backendDateKey(new Date(2026, 9, 7))).toBe('Wed Oct 7 2026');   // JS toDateString() would say "Oct 07"
  expect(backendDateKey(new Date(2026, 9, 17))).toBe('Sat Oct 17 2026');
});

test('helpers fall back safely', () => {
  expect(vehicleIcon('van')).toBeTruthy();
  expect(vehicleIcon(undefined)).toBeTruthy();
  expect(apiError({ response: { data: { message: 'Nope' } } })).toBe('Nope');
  expect(apiError({}, 'fallback')).toBe('fallback');
});
