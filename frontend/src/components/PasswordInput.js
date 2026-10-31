import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { Ic } from './Icon';

// Password field with a show/hide toggle. Takes any <input> prop.
export default function PasswordInput({ style, ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <input {...props} type={show ? 'text' : 'password'} style={{ ...style, paddingRight: 44 }} />
      <button type="button" onClick={() => setShow(s => !s)}
        aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}
        style={{
          position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
          background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--muted)',
        }}>
        {show ? <Ic icon={EyeOff} /> : <Ic icon={Eye} />}
      </button>
    </div>
  );
}
