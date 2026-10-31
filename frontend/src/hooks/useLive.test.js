import { act, renderHook } from '@testing-library/react';

// A tiny in-memory stand-in for a socket.io client: records handlers/emits and lets the test fire events.
const mockSockets = [];
// Plain functions, not jest.fn: CRA's Jest config has resetMocks on, which would wipe jest.fn implementations between tests.
jest.mock('socket.io-client', () => ({
  io: (url, opts) => {
    const handlers = {};
    const sock = {
      url, opts, emitted: [], disconnected: false,
      on: (evt, fn) => { (handlers[evt] = handlers[evt] || []).push(fn); },
      emit: (evt, payload) => { sock.emitted.push([evt, payload]); },
      disconnect: () => { sock.disconnected = true; },
      fire: (evt, payload) => (handlers[evt] || []).forEach(fn => fn(payload)),
      handlerCount: (evt) => (handlers[evt] || []).length,
    };
    mockSockets.push(sock);
    return sock;
  },
}));

// eslint-disable-next-line import/first
import { useShipmentRoom, useVehicleFeed } from './useLive';

beforeEach(() => { mockSockets.length = 0; localStorage.clear(); });

test('sockets send the current JWT on every (re)connect', () => {
  renderHook(() => useVehicleFeed());
  const { auth } = mockSockets[0].opts;
  let sent;
  localStorage.setItem('shipora_token', 'token-one');
  auth(d => { sent = d; });
  expect(sent).toEqual({ token: 'token-one' });
  localStorage.setItem('shipora_token', 'token-two');           // refreshed between reconnects
  auth(d => { sent = d; });
  expect(sent).toEqual({ token: 'token-two' });
  localStorage.clear();
  auth(d => { sent = d; });
  expect(sent).toEqual({ token: '' });                           // signed out -> anonymous, never throws
});

test('vehicle feed registers each listener exactly once and cleans up', () => {
  const { result, rerender, unmount } = renderHook(() => useVehicleFeed());
  const s = mockSockets[0];
  rerender(); rerender();                                        // re-renders must not add listeners or sockets
  expect(mockSockets).toHaveLength(1);
  expect(s.handlerCount('vehicles:update')).toBe(1);
  expect(s.handlerCount('vehicles:initial')).toBe(1);
  act(() => s.fire('connect'));
  act(() => s.fire('vehicles:initial', { a1: { isActive: true } }));
  expect(result.current.connected).toBe(true);
  expect(result.current.vehicles).toEqual({ a1: { isActive: true } });
  act(() => s.fire('vehicles:update', { a1: { isActive: false, state: 'stale' } }));
  expect(result.current.vehicles.a1.state).toBe('stale');
  act(() => s.fire('disconnect'));
  expect(result.current.connected).toBe(false);
  unmount();
  expect(s.disconnected).toBe(true);
});

test('shipment room is joined on connect AND re-joined after every reconnect, with no duplicate handlers', () => {
  const onUpdate = jest.fn();
  const { rerender, unmount } = renderHook(({ cb }) => useShipmentRoom('shp0123456789', cb), { initialProps: { cb: onUpdate } });
  const s = mockSockets[0];
  expect(s.handlerCount('shipment:update')).toBe(1);
  act(() => s.fire('connect'));
  expect(s.emitted.filter(([e]) => e === 'shipment:join')).toEqual([['shipment:join', { trackingNumber: 'SHP0123456789' }]]);
  act(() => { s.fire('disconnect'); s.fire('connect'); });        // network blip: the server forgot our room membership
  expect(s.emitted.filter(([e]) => e === 'shipment:join')).toHaveLength(2);
  rerender({ cb: onUpdate });                                     // same tracking number -> same socket, same single handler
  expect(mockSockets).toHaveLength(1);
  expect(s.handlerCount('shipment:update')).toBe(1);

  act(() => s.fire('shipment:update', { trackingNumber: 'SHP0123456789', status: 'PICKED_UP' }));
  act(() => s.fire('shipment:update', { trackingNumber: 'SHPOTHER00000', status: 'DELIVERED' }));   // someone else's shipment
  expect(onUpdate).toHaveBeenCalledTimes(1);

  unmount();
  expect(s.emitted.filter(([e]) => e === 'shipment:leave')).toHaveLength(1);
  expect(s.disconnected).toBe(true);
});

test('the latest callback is used without re-joining', () => {
  const first = jest.fn(); const second = jest.fn();
  const { rerender } = renderHook(({ cb }) => useShipmentRoom('SHP0123456789', cb), { initialProps: { cb: first } });
  const s = mockSockets[0];
  act(() => s.fire('connect'));
  rerender({ cb: second });
  act(() => s.fire('shipment:update', { trackingNumber: 'SHP0123456789' }));
  expect(first).not.toHaveBeenCalled();
  expect(second).toHaveBeenCalledTimes(1);
  expect(mockSockets).toHaveLength(1);
  expect(s.emitted.filter(([e]) => e === 'shipment:join')).toHaveLength(1);
});

test('changing the set of tracked shipments swaps rooms on a fresh socket and tears the old one down', () => {
  const { rerender } = renderHook(({ ids }) => useShipmentRoom(ids, () => {}), { initialProps: { ids: ['SHPAAAAAAAAAA'] } });
  const old = mockSockets[0];
  act(() => old.fire('connect'));
  rerender({ ids: ['SHPAAAAAAAAAA', 'SHPBBBBBBBBBB'] });
  expect(old.disconnected).toBe(true);
  expect(old.emitted.filter(([e]) => e === 'shipment:leave')).toHaveLength(1);
  const fresh = mockSockets[1];
  act(() => fresh.fire('connect'));
  expect(fresh.emitted.filter(([e]) => e === 'shipment:join').map(([, p]) => p.trackingNumber)).toEqual(['SHPAAAAAAAAAA', 'SHPBBBBBBBBBB']);
});

test('no tracking numbers -> no socket at all', () => {
  renderHook(() => useShipmentRoom([], () => {}));
  renderHook(() => useShipmentRoom(undefined, () => {}));
  expect(mockSockets).toHaveLength(0);
});
