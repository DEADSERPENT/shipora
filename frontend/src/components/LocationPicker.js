import React, { useState, useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, useMapEvents, useMap } from 'react-leaflet';

// ── Nominatim helpers ─────────────────────────────────────────────────────────
const NOM_HEADERS = { 'Accept-Language': 'en', 'User-Agent': 'EcoTrack/1.0' };

async function reverseGeocode(lat, lng) {
  try {
    const r = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`,
      { headers: NOM_HEADERS }
    );
    const d = await r.json();
    return {
      address: d.display_name || `${lat.toFixed(5)}, ${lng.toFixed(5)}`,
      pincode: d.address?.postcode || '',
    };
  } catch {
    return { address: `${lat.toFixed(5)}, ${lng.toFixed(5)}`, pincode: '' };
  }
}

async function forwardSearch(query) {
  const r = await fetch(
    `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=6&addressdetails=1&countrycodes=in`,
    { headers: NOM_HEADERS }
  );
  return r.json();
}

async function pincodeSearch(pin) {
  const r = await fetch(
    `https://nominatim.openstreetmap.org/search?postalcode=${pin}&country=in&format=json&limit=6&addressdetails=1`,
    { headers: NOM_HEADERS }
  );
  return r.json();
}

function shortName(result) {
  const a = result.address || {};
  return (
    a.neighbourhood || a.suburb || a.village || a.town ||
    a.city_district || a.city || result.display_name.split(',')[0]
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────
function ClickHandler({ onPick }) {
  useMapEvents({ click: e => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

function FlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo([target.lat, target.lng], 15, { animate: true, duration: 1.2 });
  }, [target, map]);
  return null;
}

// ── Main component ────────────────────────────────────────────────────────────
export default function LocationPicker({ value, onChange }) {
  const [center,       setCenter]      = useState([20.5937, 78.9629]);
  const [flyTarget,    setFlyTarget]   = useState(null);
  const [loading,      setLoading]     = useState(false);

  // Search
  const [searchQuery,  setSearchQuery] = useState('');
  const [searchResults,setResults]     = useState([]);
  const [searching,    setSearching]   = useState(false);
  const [searchError,  setSearchError] = useState('');
  const searchRef                      = useRef(null);

  // Pincode
  const [pincode,      setPincode]     = useState('');
  const [pinResults,   setPinResults]  = useState([]);
  const [pinSearching, setPinSearching]= useState(false);
  const [pinError,     setPinError]    = useState('');

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = e => {
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setResults([]);
        setPinResults([]);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (value?.lat) { setCenter([value.lat, value.lng]); return; }
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        pos => handlePick(pos.coords.latitude, pos.coords.longitude),
        () => {}
      );
    }
  }, []); // eslint-disable-line

  const handlePick = useCallback(async (lat, lng) => {
    setLoading(true);
    const { address, pincode: pin } = await reverseGeocode(lat, lng);
    onChange({ lat, lng, address });
    setCenter([lat, lng]);
    setFlyTarget({ lat, lng });
    if (pin) setPincode(pin);
    setLoading(false);
  }, [onChange]);

  const useGPS = () => {
    if (!navigator.geolocation) return alert('Geolocation not supported');
    navigator.geolocation.getCurrentPosition(
      pos => handlePick(pos.coords.latitude, pos.coords.longitude),
      () => alert('Could not get location. Please click the map or search.')
    );
  };

  // ── Address search ──────────────────────────────────────────────────────────
  const handleSearch = async (e) => {
    e?.preventDefault();
    if (!searchQuery.trim()) return;
    setSearchError('');
    setSearching(true);
    setResults([]);
    try {
      const data = await forwardSearch(searchQuery);
      if (!data.length) setSearchError('No results found. Try a different search.');
      else setResults(data);
    } catch {
      setSearchError('Search failed. Check your connection.');
    } finally {
      setSearching(false);
    }
  };

  const pickSearchResult = (r) => {
    const lat = parseFloat(r.lat), lng = parseFloat(r.lon);
    handlePick(lat, lng);
    setSearchQuery(shortName(r));
    setResults([]);
    setPinResults([]);
  };

  // ── Pincode search ──────────────────────────────────────────────────────────
  const handlePincodeSearch = async (e) => {
    e?.preventDefault();
    const pin = pincode.replace(/\D/g, '');
    if (pin.length !== 6) { setPinError('Enter a valid 6-digit pincode.'); return; }
    setPinError('');
    setPinSearching(true);
    setPinResults([]);
    try {
      const data = await pincodeSearch(pin);
      if (!data.length) setPinError('Pincode not found. Try clicking the map directly.');
      else setPinResults(data);
    } catch {
      setPinError('Search failed. Check your connection.');
    } finally {
      setPinSearching(false);
    }
  };

  const pickPinResult = (r) => {
    const lat = parseFloat(r.lat), lng = parseFloat(r.lon);
    handlePick(lat, lng);
    setPinResults([]);
  };

  return (
    <div ref={searchRef}>

      {/* ── Address Search ── */}
      <div style={{ marginBottom: 8 }}>
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 6 }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 15, pointerEvents: 'none' }}>🔍</span>
            <input
              type="text"
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); setSearchError(''); }}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search area, landmark, street…"
              style={{ width: '100%', paddingLeft: 32, paddingRight: 12, height: 38, border: '1.5px solid var(--border)', borderRadius: 8, fontSize: 13, outline: 'none' }}
            />
          </div>
          <button type="submit" className="btn btn-primary btn-sm" disabled={searching} style={{ whiteSpace: 'nowrap', height: 38 }}>
            {searching ? '…' : 'Search'}
          </button>
        </form>

        {/* Search results dropdown */}
        {(searchResults.length > 0 || searchError) && (
          <div style={{
            border: '1.5px solid var(--border)', borderRadius: 8, background: '#fff',
            boxShadow: '0 4px 16px rgba(0,0,0,0.1)', marginTop: 4, overflow: 'hidden', zIndex: 9999, position: 'relative',
          }}>
            {searchError && (
              <div style={{ padding: '10px 14px', fontSize: 13, color: 'var(--red)' }}>{searchError}</div>
            )}
            {searchResults.map((r, i) => (
              <button key={i} type="button" onClick={() => pickSearchResult(r)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '9px 14px', border: 'none', background: 'transparent',
                  cursor: 'pointer', borderBottom: i < searchResults.length - 1 ? '1px solid var(--border)' : 'none',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--green-50)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)' }}>📍 {shortName(r)}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, lineHeight: 1.4 }}>
                  {r.display_name}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Pincode Search ── */}
      <div style={{ marginBottom: 10 }}>
        <form onSubmit={handlePincodeSearch} style={{ display: 'flex', gap: 6 }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 14, pointerEvents: 'none' }}>📮</span>
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={pincode}
              onChange={e => { setPincode(e.target.value.replace(/\D/g, '').slice(0, 6)); setPinError(''); }}
              onKeyDown={e => e.key === 'Enter' && handlePincodeSearch()}
              placeholder="Enter 6-digit pincode"
              style={{
                width: '100%', paddingLeft: 32, paddingRight: 12, height: 38,
                border: pinError ? '1.5px solid var(--red)' : '1.5px solid var(--border)',
                borderRadius: 8, fontSize: 13, outline: 'none',
              }}
            />
          </div>
          <button type="submit" className="btn btn-ghost btn-sm" disabled={pinSearching} style={{ whiteSpace: 'nowrap', height: 38 }}>
            {pinSearching ? '…' : 'Find'}
          </button>
        </form>

        {pinError && (
          <span style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, display: 'block' }}>⚠ {pinError}</span>
        )}

        {/* Pincode results dropdown */}
        {pinResults.length > 0 && (
          <div style={{
            border: '1.5px solid var(--border)', borderRadius: 8, background: '#fff',
            boxShadow: '0 4px 16px rgba(0,0,0,0.1)', marginTop: 4, overflow: 'hidden', zIndex: 9999, position: 'relative',
          }}>
            <div style={{ padding: '6px 14px', fontSize: 11, fontWeight: 700, color: 'var(--muted)', borderBottom: '1px solid var(--border)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Areas in pincode {pincode}
            </div>
            {pinResults.map((r, i) => (
              <button key={i} type="button" onClick={() => pickPinResult(r)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '9px 14px', border: 'none', background: 'transparent',
                  cursor: 'pointer', borderBottom: i < pinResults.length - 1 ? '1px solid var(--border)' : 'none',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--green-50)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)' }}>📍 {shortName(r)}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{r.display_name}</div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Map ── */}
      <MapContainer
        center={center}
        zoom={13}
        style={{ height: 260, width: '100%', borderRadius: 10, border: '1.5px solid var(--border)' }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='© <a href="https://www.openstreetmap.org">OpenStreetMap</a>'
        />
        <ClickHandler onPick={handlePick} />
        <FlyTo target={flyTarget} />
        {value?.lat && <Marker position={[value.lat, value.lng]} />}
      </MapContainer>

      {/* ── Status bar ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
          {loading ? '⏳ Getting address…' : value?.lat
            ? `📍 ${value.lat.toFixed(4)}, ${value.lng.toFixed(4)}`
            : 'Click the map, search, or enter a pincode'}
        </span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={useGPS}>
          📡 GPS
        </button>
      </div>
    </div>
  );
}
