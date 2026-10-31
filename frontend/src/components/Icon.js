import React from 'react';

// Thin wrapper so every lucide icon in the app lines up with surrounding text:
//   <Ic icon={Package} /> Create Shipment
// Pass the lucide component itself (not a string) — keeps imports tree-shakeable.
export function Ic({ icon: Icon, size = 16, strokeWidth = 2, className = '', ...rest }) {
  if (!Icon) return null;
  return <Icon size={size} strokeWidth={strokeWidth} className={`ico ${className}`.trim()} aria-hidden="true" focusable="false" {...rest} />;
}

export default Ic;
