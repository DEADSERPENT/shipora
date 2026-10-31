import React from 'react';
import { Banknote, Clock, Route } from 'lucide-react';
import { Ic } from './Icon';
import { fmtEta, fmtINR } from '../lib/estimate';

// The "Get an estimate" result: fare, distance and ETA — shown on the home page and live on the booking form.
export default function EstimateCard({ estimate, loading, error }) {
  if (error) return <div className="est est-err" role="alert">{error}</div>;
  if (loading && !estimate) return <div className="est est-loading">Calculating your fare…</div>;
  if (!estimate) return null;
  return (
    <div className={`est ${loading ? 'est-stale' : ''}`} aria-live="polite">
      <div className="est-fare">
        <span className="est-label"><Ic icon={Banknote} size={14} /> Estimated fare</span>
        <span className="est-amount">{fmtINR(estimate.fare)}</span>
      </div>
      <div className="est-meta">
        <span><Ic icon={Route} size={15} /> {estimate.distanceKm} km</span>
        <span><Ic icon={Clock} size={15} /> ~{fmtEta(estimate.etaMinutes)}</span>
      </div>
      <div className="est-note">
        Base {fmtINR(estimate.baseFare)} covers the first {estimate.includedKm} km, then {fmtINR(estimate.perKm)}/km
        {estimate.weightSurcharge > 0
          ? <> + {fmtINR(estimate.weightSurcharge)} for weight above {estimate.freeWeightKg} kg</>
          : <> (weight is free up to {estimate.freeWeightKg} kg, then {fmtINR(estimate.perExtraKg)}/kg)</>}. Pay the rider in cash or UPI.
      </div>
    </div>
  );
}
