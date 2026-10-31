import { STEPS, etaSummary, initials, minutesLabel, stepIndex, telHref } from './liveOrder';

const at = (iso) => new Date(iso).getTime();
const base = { status: 'OUT_FOR_DELIVERY', estimatedDelivery: '2026-10-27T14:00:00Z', statusHistory: [] };

describe('stepIndex', () => {
  test('maps the seven-state lifecycle onto five stops', () => {
    expect(STEPS).toHaveLength(5);
    expect(stepIndex({ status: 'CREATED' })).toBe(0);
    expect(stepIndex({ status: 'PICKUP_SCHEDULED' })).toBe(1);
    expect(stepIndex({ status: 'PICKED_UP' })).toBe(2);
    expect(['IN_TRANSIT', 'OUT_FOR_DELIVERY'].map(status => stepIndex({ status }))).toEqual([3, 3]);
    expect(stepIndex({ status: 'DELIVERED' })).toBe(4);
  });

  test('an exception keeps the last happy-path stop from history', () => {
    const failed = { status: 'DELIVERY_FAILED', statusHistory: [{ status: 'CREATED' }, { status: 'IN_TRANSIT' }, { status: 'OUT_FOR_DELIVERY' }, { status: 'DELIVERY_FAILED' }] };
    expect(stepIndex(failed)).toBe(3);
    expect(stepIndex({ status: 'CANCELLED', statusHistory: [{ status: 'CREATED' }, { status: 'CANCELLED' }] })).toBe(0);
  });
});

describe('etaSummary', () => {
  test('counts down to the estimate', () => {
    const out = etaSummary(base, at('2026-10-27T12:30:00Z'));
    expect(out.tone).toBe('ok');
    expect(out.headline).toBe('Your rider is on the way');
    expect(out.sub).toBe('Arriving in about 1 h 30 min');
    expect(out.big).toMatch(/^by /);
  });

  test('past the estimate is "running late", never a negative countdown', () => {
    const out = etaSummary(base, at('2026-10-27T15:00:00Z'));
    expect(out.tone).toBe('warn');
    expect(out.big).toBe('Running late');
    expect(out.sub).not.toMatch(/-/);
  });

  test('delivered, cancelled and failed each say something different', () => {
    expect(etaSummary({ status: 'DELIVERED', deliveredAt: '2026-10-27T09:00:00Z' }).tone).toBe('ok');
    expect(etaSummary({ status: 'CANCELLED' }).tone).toBe('neutral');
    const failed = etaSummary({ status: 'ADDRESS_ISSUE' });
    expect(failed.tone).toBe('bad');
    expect(failed.big).toBe('Needs attention');
  });

  test('no estimate yet still renders', () => {
    expect(etaSummary({ status: 'CREATED' }).big).toBe('Today');
  });
});

describe('small helpers', () => {
  test('minutesLabel', () => {
    expect(minutesLabel(0.2)).toBe('1 min');
    expect(minutesLabel(45)).toBe('45 min');
    expect(minutesLabel(60)).toBe('1 h');
    expect(minutesLabel(125)).toBe('2 h 5 min');
  });
  test('initials and tel links', () => {
    expect(initials('Suresh Babu')).toBe('SB');
    expect(initials('')).toBe('?');
    expect(telHref('+91 98800-00002')).toBe('tel:+919880000002');
  });
});
