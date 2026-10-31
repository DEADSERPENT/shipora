import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function BackButton({ label = 'Back', to }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => to ? navigate(to) : navigate(-1)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: 'none', border: '1.5px solid var(--border)',
        borderRadius: 8, padding: '6px 14px', fontSize: 13,
        fontWeight: 600, color: 'var(--muted)', cursor: 'pointer',
        transition: 'all 0.18s', marginBottom: 20,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = 'var(--brand-600)';
        e.currentTarget.style.color = 'var(--brand-700)';
        e.currentTarget.style.background = 'var(--brand-50)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = 'var(--border)';
        e.currentTarget.style.color = 'var(--muted)';
        e.currentTarget.style.background = 'none';
      }}
    >
      ← {label}
    </button>
  );
}
