import React from 'react';

// Hand-drawn (inline SVG) brand illustrations — no image files, so they stay crisp and on-palette.
// Palette: yellow #f8cb46, green #0c831f, ink #14201a.

/** Delivery rider on a scooter carrying a parcel, with a floating map pin. Used on the home hero. */
export function RiderIllustration({ className, style }) {
  return (
    <svg className={className} style={style} viewBox="0 0 540 400" role="img" aria-label="Delivery rider on a scooter carrying a parcel" xmlns="http://www.w3.org/2000/svg">
      {/* soft backdrop blobs */}
      <circle cx="300" cy="190" r="170" fill="#fff" opacity="0.38" />
      <circle cx="450" cy="90" r="46" fill="#fff" opacity="0.5" />
      {/* city skyline */}
      <g fill="#14201a" opacity="0.08">
        <rect x="40" y="200" width="46" height="130" rx="6" /><rect x="94" y="160" width="40" height="170" rx="6" />
        <rect x="142" y="215" width="52" height="115" rx="6" /><rect x="420" y="190" width="50" height="140" rx="6" />
        <rect x="478" y="225" width="40" height="105" rx="6" />
      </g>
      {/* road */}
      <rect x="14" y="336" width="512" height="44" rx="22" fill="#14201a" opacity="0.9" />
      <g fill="#f8cb46"><rect x="50" y="354" width="54" height="6" rx="3" /><rect x="170" y="354" width="54" height="6" rx="3" /><rect x="290" y="354" width="54" height="6" rx="3" /><rect x="410" y="354" width="54" height="6" rx="3" /></g>
      <ellipse cx="270" cy="338" rx="170" ry="7" fill="#000" opacity="0.2" />

      {/* speed lines */}
      <g stroke="#14201a" strokeWidth="6" strokeLinecap="round" opacity="0.45">
        <path d="M40 250h56" /><path d="M20 276h60" /><path d="M52 302h44" />
      </g>

      {/* route + pin */}
      <path d="M330 150 C 360 110, 400 120, 428 90" fill="none" stroke="#14201a" strokeWidth="3" strokeDasharray="2 9" strokeLinecap="round" opacity="0.5" />
      <g transform="translate(428 36)">
        <path d="M0 0c-18 0-32 14-32 31 0 23 32 51 32 51s32-28 32-51C32 14 18 0 0 0z" fill="#0c831f" />
        <circle cx="0" cy="31" r="12" fill="#fff" />
        <circle cx="0" cy="31" r="5" fill="#f8cb46" />
      </g>

      {/* scooter */}
      <g>
        <circle cx="150" cy="300" r="38" fill="#14201a" /><circle cx="150" cy="300" r="16" fill="#e8ece6" /><circle cx="150" cy="300" r="5" fill="#14201a" />
        <circle cx="380" cy="300" r="38" fill="#14201a" /><circle cx="380" cy="300" r="16" fill="#e8ece6" /><circle cx="380" cy="300" r="5" fill="#14201a" />
        {/* rear body */}
        <path d="M118 298c0-42 34-52 74-52h110v40H196c-26 0-30 8-30 22z" fill="#0c831f" />
        {/* floorboard */}
        <rect x="190" y="284" width="170" height="18" rx="9" fill="#0a5c16" />
        {/* leg shield + fork */}
        <path d="M336 290c20-60 14-92-4-128l36-6c18 44 26 90 14 134z" fill="#0c831f" />
        <path d="M376 160l8 140" stroke="#14201a" strokeWidth="9" strokeLinecap="round" />
        {/* handlebar + light */}
        <path d="M326 150h52" stroke="#14201a" strokeWidth="10" strokeLinecap="round" />
        <circle cx="392" cy="206" r="10" fill="#f8cb46" stroke="#14201a" strokeWidth="3" />
        {/* seat */}
        <rect x="176" y="238" width="124" height="26" rx="13" fill="#14201a" />
      </g>

      {/* parcel on the back */}
      <g>
        <rect x="150" y="128" width="96" height="86" rx="12" fill="#f8cb46" stroke="#14201a" strokeWidth="4" />
        <path d="M198 128v86" stroke="#14201a" strokeWidth="4" opacity="0.35" />
        <path d="M205 150l-14 22h13l-6 20 20-26h-13l8-16z" fill="#14201a" />
      </g>

      {/* rider */}
      <g>
        {/* leg */}
        <path d="M258 252l62 24v24" fill="none" stroke="#14201a" strokeWidth="18" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="306" y="292" width="34" height="14" rx="7" fill="#14201a" />
        {/* torso */}
        <path d="M228 246c-8-52 0-92 22-104l38 8c10 28 6 70-6 100z" fill="#0c831f" stroke="#14201a" strokeWidth="4" strokeLinejoin="round" />
        {/* arm */}
        <path d="M276 172l52-20" fill="none" stroke="#0a5c16" strokeWidth="16" strokeLinecap="round" />
        <circle cx="332" cy="150" r="9" fill="#e9b88a" />
        {/* head + helmet */}
        <circle cx="268" cy="112" r="24" fill="#e9b88a" />
        <path d="M242 112a26 26 0 0152 0v6h-52z" fill="#f8cb46" stroke="#14201a" strokeWidth="4" strokeLinejoin="round" />
        <path d="M268 112h28v14c-8 4-20 4-28-2z" fill="#14201a" opacity="0.85" />
      </g>
    </svg>
  );
}

/** A parcel box, for empty states. */
export function ParcelIllustration({ size = 120, className, style }) {
  return (
    <svg className={className} style={style} width={size} height={size} viewBox="0 0 120 120" role="img" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="60" cy="104" rx="38" ry="7" fill="#14201a" opacity="0.12" />
      <path d="M60 18L16 38v46l44 20 44-20V38z" fill="#f8cb46" stroke="#14201a" strokeWidth="4" strokeLinejoin="round" />
      <path d="M16 38l44 20 44-20" fill="none" stroke="#14201a" strokeWidth="4" strokeLinejoin="round" />
      <path d="M60 58v46" stroke="#14201a" strokeWidth="4" />
      <path d="M38 28l44 20" stroke="#14201a" strokeWidth="4" strokeLinecap="round" />
      <path d="M60 70l-7 11h6.5l-3 10 10-13h-6.5l4-8z" fill="#14201a" transform="translate(12 -8)" />
      <circle cx="96" cy="22" r="5" fill="#0c831f" /><circle cx="22" cy="18" r="3.5" fill="#0c831f" opacity="0.6" />
    </svg>
  );
}

/** Pin + dotted route between two points, for "how it works". */
export function RouteIllustration({ size = 120, className, style }) {
  return (
    <svg className={className} style={style} width={size} height={size} viewBox="0 0 120 120" role="img" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <circle cx="60" cy="60" r="52" fill="#f8cb46" opacity="0.35" />
      <path d="M30 88C30 60 90 78 90 40" fill="none" stroke="#14201a" strokeWidth="3" strokeDasharray="2 7" strokeLinecap="round" />
      <circle cx="30" cy="88" r="9" fill="#14201a" /><circle cx="30" cy="88" r="3.5" fill="#f8cb46" />
      <path d="M90 14c-11 0-19 8-19 19 0 14 19 31 19 31s19-17 19-31c0-11-8-19-19-19z" fill="#0c831f" />
      <circle cx="90" cy="33" r="7.5" fill="#fff" />
    </svg>
  );
}
