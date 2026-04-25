import React, { useState, useEffect } from 'react';

const css = `
@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(16px) scale(0.85); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}
@keyframes ripple {
  0%   { box-shadow: 0 0 0 0   rgba(45,122,45,0.45); }
  70%  { box-shadow: 0 0 0 14px rgba(45,122,45,0); }
  100% { box-shadow: 0 0 0 0   rgba(45,122,45,0); }
}
.stt-btn {
  animation: fadeSlideIn 0.3s cubic-bezier(0.34,1.56,0.64,1) both,
             ripple 2.2s ease-out 0.4s infinite;
}
.stt-btn:hover {
  animation: none !important;
  transform: translateY(-4px) scale(1.08) !important;
  box-shadow: 0 12px 32px rgba(26,58,26,0.45), 0 0 0 4px rgba(45,122,45,0.18) !important;
}
.stt-btn:active {
  transform: translateY(-1px) scale(0.97) !important;
}
`;

export default function ScrollToTopButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 280);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  if (!visible) return null;

  return (
    <>
      <style>{css}</style>
      <button
        className="stt-btn"
        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        title="Back to top"
        style={{
          position: 'fixed', bottom: 32, right: 32, zIndex: 999,
          width: 52, height: 52, borderRadius: '50%',
          background: 'linear-gradient(145deg, #3a9a3a 0%, #1a3a1a 100%)',
          color: '#fff', border: '2px solid rgba(134,239,172,0.35)',
          cursor: 'pointer',
          boxShadow: '0 6px 20px rgba(26,58,26,0.4), inset 0 1px 0 rgba(255,255,255,0.15)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 1,
          transition: 'transform 0.22s cubic-bezier(0.34,1.56,0.64,1), box-shadow 0.22s ease',
          outline: 'none',
        }}
      >
        {/* Double chevron arrow */}
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" style={{ display: 'block' }}>
          <path d="M4 13l5-5 5 5"  stroke="#86efac" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M4 8.5l5-5 5 5" stroke="rgba(134,239,172,0.5)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <span style={{ fontSize: 9, fontWeight: 800, color: '#86efac', letterSpacing: '0.06em', lineHeight: 1, textTransform: 'uppercase' }}>
          TOP
        </span>
      </button>
    </>
  );
}
