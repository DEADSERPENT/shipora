import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { Search } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { ShipmentTimeline } from '../components/ShipmentUI';
import LiveOrderHero from '../components/LiveOrderHero';
import { useShipmentRoom } from '../hooks/useLive';
import { apiError, serviceLabel } from '../lib/shipora';
import { Ic } from '../components/Icon';

// Public tracking by tracking number — works signed-out and is the page a shared link opens. It uses the public endpoint,
// which returns status + timeline only (no names, phones or addresses), so the live-order hero shows ETA and progress
// but never a rider's or receiver's contact details.
export default function TrackShipment() {
  const { trackingNumber } = useParams();
  const { API, user } = useAuth();
  const navigate = useNavigate();
  const [input, setInput]   = useState(trackingNumber || '');
  const [result, setResult] = useState(null);
  const [error, setError]   = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (tn) => {
    if (!tn) return;
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/shipments/track/${encodeURIComponent(tn.trim())}`);
      setResult(data); setError('');
    } catch (err) {
      setResult(null);
      setError(apiError(err, 'Could not look up that tracking number.'));
    } finally { setLoading(false); }
  }, [API]);

  useEffect(() => { setInput(trackingNumber || ''); if (trackingNumber) load(trackingNumber); else { setResult(null); setError(''); } }, [trackingNumber, load]);
  useShipmentRoom(result?.trackingNumber, () => load(result.trackingNumber));

  const submit = (e) => {
    e.preventDefault();
    const tn = input.trim().toUpperCase();
    if (tn) navigate(`/track/${tn}`);
  };

  return (
    <div className="trackpage">
      <div className="trackpage-inner">
        <div className="trackpage-head">
          <h1>Track your parcel</h1>
          <p>Enter the tracking number you were given. It starts with SHP — no sign-in needed.</p>
        </div>

        <form onSubmit={submit} className="trackpage-form">
          <label className="lp-field lp-field-icon">
            <Ic icon={Search} size={18} />
            <input aria-label="Tracking number" value={input} onChange={e => setInput(e.target.value.toUpperCase())} placeholder="e.g. SHP48217390" />
          </label>
          <button className="lp-btn lp-btn-primary" type="submit" disabled={loading}>{loading ? 'Searching…' : 'Track'}</button>
        </form>

        {error && <div className="alert alert-error" role="alert">{error}</div>}

        {result && (
          <>
            <div className="trackpage-id">
              <span>Tracking number</span><b>{result.trackingNumber}</b><em>{serviceLabel(result.serviceType)} delivery</em>
            </div>
            <LiveOrderHero shipment={{ ...result, statusHistory: result.timeline }} role="public" />
            <div className="trackpage-timeline">
              <h2>Delivery timeline</h2>
              <ShipmentTimeline events={result.timeline} currentStatus={result.status} />
              {user && (
                <Link to={`/shipments/${result.trackingNumber}`} className="lp-textlink" style={{ color: 'var(--brand-700)', marginTop: 8 }}>
                  Open full shipment details →
                </Link>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
