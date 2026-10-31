import { useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import { SOCKET_URL, socketOptions } from '../lib/shipora';

const connect = () => io(SOCKET_URL, socketOptions());

// Live delivery-vehicle feed. Event names are the backend's wire names
// (`vehicles:initial` / `vehicles:update`) — unchanged by the Shipora conversion.
export function useVehicleFeed() {
  const [vehicles,   setVehicles]   = useState({});
  const [connected,  setConnected]  = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

  useEffect(() => {
    const socket = connect();
    const onData = (data) => { setVehicles(data || {}); setLastUpdate(new Date()); };
    socket.on('connect',    () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));
    socket.on('vehicles:initial', onData);
    socket.on('vehicles:update',  onData);
    return () => socket.disconnect();
  }, []);

  return { vehicles, connected, lastUpdate };
}

// Joins the per-shipment room(s), keyed by tracking number (one string or an array),
// and calls onUpdate whenever the backend pushes `shipment:update`. The latest callback
// is always used without re-joining.
export function useShipmentRoom(trackingNumbers, onUpdate) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onUpdate);
  cb.current = onUpdate;
  const list = [].concat(trackingNumbers || []).filter(Boolean).map(t => t.toUpperCase());
  const key = list.join(',');

  useEffect(() => {
    if (!key) return undefined;
    const rooms = key.split(',');
    const socket = connect();
    socket.on('connect', () => {
      setConnected(true);
      rooms.forEach(trackingNumber => socket.emit('shipment:join', { trackingNumber }));
    });
    socket.on('disconnect', () => setConnected(false));
    socket.on('shipment:update', (evt) => {
      if (evt && rooms.includes(evt.trackingNumber)) cb.current?.(evt);
    });
    return () => {
      rooms.forEach(trackingNumber => socket.emit('shipment:leave', { trackingNumber }));
      socket.disconnect();
    };
  }, [key]);

  return connected;
}
