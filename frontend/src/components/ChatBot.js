import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';

const API = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

const css = `
@keyframes chatPop {
  from { opacity: 0; transform: scale(0.85) translateY(20px); transform-origin: bottom left; }
  to   { opacity: 1; transform: scale(1)    translateY(0);    transform-origin: bottom left; }
}
@keyframes botTyping {
  0%,80%,100% { transform: scale(0); opacity: 0.4; }
  40%         { transform: scale(1); opacity: 1; }
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes fabPulse {
  0%,100% { box-shadow: 0 6px 24px rgba(26,58,26,0.45), 0 0 0 0 rgba(45,122,45,0.5); }
  60%     { box-shadow: 0 6px 24px rgba(26,58,26,0.45), 0 0 0 12px rgba(45,122,45,0); }
}
.chat-fab      { animation: fabPulse 2.8s ease-in-out infinite; }
.chat-fab:hover{ animation: none !important; transform: scale(1.1) !important; }
.chat-panel    { animation: chatPop 0.28s cubic-bezier(0.34,1.56,0.64,1) both; }
.chat-msg      { animation: msgIn 0.22s ease both; }
.dot1 { animation: botTyping 1.2s 0.0s infinite; }
.dot2 { animation: botTyping 1.2s 0.2s infinite; }
.dot3 { animation: botTyping 1.2s 0.4s infinite; }
`;

function TypingDots() {
  return (
    <div style={{ display: 'flex', gap: 5, alignItems: 'center', padding: '10px 14px' }}>
      {['dot1','dot2','dot3'].map(c => (
        <span key={c} className={c} style={{
          width: 8, height: 8, borderRadius: '50%',
          background: '#4db84d', display: 'inline-block',
        }} />
      ))}
    </div>
  );
}

const SUGGESTIONS = [
  'How do I track the waste truck?',
  'How to submit a complaint?',
  'Change my pickup schedule',
  'What waste types are accepted?',
];

export default function ChatBot() {
  const [open,    setOpen]    = useState(false);
  const [input,   setInput]   = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState([
    { role: 'assistant', content: 'Hi! I\'m **EcoBot** 🌿\nI can help you with EcoTrack features — tracking, schedules, complaints, and more. What can I help you with?' }
  ]);

  const bottomRef  = useRef(null);
  const inputRef   = useRef(null);
  const panelRef   = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history, loading]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 120);
  }, [open]);

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || loading) return;
    setInput('');

    const userMsg = { role: 'user', content: msg };
    setHistory(h => [...h, userMsg]);
    setLoading(true);

    try {
      const { data } = await axios.post(`${API}/chat`, {
        message: msg,
        history: history.filter(h => h.role !== 'assistant' || h !== history[0]),
      });
      setHistory(h => [...h, { role: 'assistant', content: data.reply }]);
    } catch {
      setHistory(h => [...h, { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' }]);
    } finally {
      setLoading(false);
    }
  };

  const renderContent = (text) => {
    // Bold **text**, line breaks
    return text.split('\n').map((line, i) => {
      const parts = line.split(/\*\*(.*?)\*\*/g);
      return (
        <span key={i}>
          {parts.map((p, j) => j % 2 === 1 ? <strong key={j}>{p}</strong> : p)}
          {i < text.split('\n').length - 1 && <br />}
        </span>
      );
    });
  };

  return (
    <>
      <style>{css}</style>

      {/* ── Chat Panel ── */}
      {open && (
        <div ref={panelRef} className="chat-panel" style={{
          position: 'fixed', bottom: 100, left: 28, zIndex: 1000,
          width: 360, maxHeight: 540,
          background: '#fff', borderRadius: 20,
          boxShadow: '0 20px 60px rgba(0,0,0,0.18), 0 4px 16px rgba(0,0,0,0.1)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
          border: '1px solid rgba(45,122,45,0.15)',
        }}>

          {/* Header */}
          <div style={{
            background: 'linear-gradient(135deg, #1a3a1a 0%, #2d7a2d 100%)',
            padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 12,
            flexShrink: 0,
          }}>
            <div style={{
              width: 38, height: 38, borderRadius: '50%',
              background: 'rgba(134,239,172,0.2)', border: '2px solid rgba(134,239,172,0.5)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
              flexShrink: 0,
            }}>🌿</div>
            <div style={{ flex: 1 }}>
              <div style={{ color: '#fff', fontWeight: 800, fontSize: 15, letterSpacing: '-0.3px' }}>EcoBot</div>
              <div style={{ color: '#86efac', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#4ade80', display: 'inline-block' }} />
                Online · EcoTrack Assistant
              </div>
            </div>
            <button onClick={() => setOpen(false)} style={{
              background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.2)',
              color: '#fff', width: 30, height: 30, borderRadius: '50%',
              cursor: 'pointer', fontSize: 16, lineHeight: 1,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'background 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.22)'}
              onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.12)'}
            >×</button>
          </div>

          {/* Messages */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '14px 14px 8px',
            display: 'flex', flexDirection: 'column', gap: 10,
            scrollbarWidth: 'thin', scrollbarColor: '#d1e7d1 transparent',
          }}>
            {history.map((msg, i) => {
              const isBot = msg.role === 'assistant';
              return (
                <div key={i} className="chat-msg" style={{
                  display: 'flex', justifyContent: isBot ? 'flex-start' : 'flex-end',
                  gap: 8, alignItems: 'flex-end',
                }}>
                  {isBot && (
                    <div style={{
                      width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                      background: 'linear-gradient(135deg, #1a3a1a, #2d7a2d)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
                    }}>🌿</div>
                  )}
                  <div style={{
                    maxWidth: '78%', padding: '9px 13px', borderRadius: isBot ? '16px 16px 16px 4px' : '16px 16px 4px 16px',
                    background: isBot ? '#f0faf0' : 'linear-gradient(135deg, #2d7a2d, #1a3a1a)',
                    color: isBot ? '#1a3a1a' : '#fff',
                    fontSize: 13.5, lineHeight: 1.55,
                    border: isBot ? '1px solid #d1e7d1' : 'none',
                    boxShadow: isBot ? '0 2px 8px rgba(0,0,0,0.06)' : '0 4px 12px rgba(26,58,26,0.3)',
                  }}>
                    {renderContent(msg.content)}
                  </div>
                </div>
              );
            })}

            {loading && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: 'linear-gradient(135deg, #1a3a1a, #2d7a2d)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, flexShrink: 0,
                }}>🌿</div>
                <div style={{
                  background: '#f0faf0', border: '1px solid #d1e7d1',
                  borderRadius: '16px 16px 16px 4px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
                }}>
                  <TypingDots />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Suggestions (show only when 1 message) */}
          {history.length === 1 && (
            <div style={{ padding: '0 12px 8px', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => send(s)} style={{
                  fontSize: 11.5, padding: '5px 10px', borderRadius: 20,
                  border: '1.5px solid #c8e6c8', background: '#f0faf0',
                  color: '#1a5c1a', cursor: 'pointer', fontWeight: 600,
                  transition: 'all 0.15s',
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = '#2d7a2d'; e.currentTarget.style.color = '#fff'; e.currentTarget.style.borderColor = '#2d7a2d'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = '#f0faf0'; e.currentTarget.style.color = '#1a5c1a'; e.currentTarget.style.borderColor = '#c8e6c8'; }}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div style={{
            padding: '10px 12px', borderTop: '1px solid #e8f5e8',
            display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0,
            background: '#fafffe',
          }}>
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
              placeholder="Ask about EcoTrack…"
              disabled={loading}
              style={{
                flex: 1, padding: '9px 14px', borderRadius: 22,
                border: '1.5px solid #d1e7d1', outline: 'none',
                fontSize: 13.5, background: '#fff',
                transition: 'border-color 0.15s',
                color: '#1a3a1a',
              }}
              onFocus={e => e.target.style.borderColor = '#2d7a2d'}
              onBlur={e => e.target.style.borderColor = '#d1e7d1'}
            />
            <button
              onClick={() => send()}
              disabled={!input.trim() || loading}
              style={{
                width: 38, height: 38, borderRadius: '50%', flexShrink: 0,
                background: input.trim() && !loading
                  ? 'linear-gradient(135deg, #2d7a2d, #1a3a1a)'
                  : '#e8f5e8',
                border: 'none', cursor: input.trim() && !loading ? 'pointer' : 'default',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s', boxShadow: input.trim() && !loading ? '0 3px 10px rgba(26,58,26,0.3)' : 'none',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M14 8L2 2l3 6-3 6 12-6z"
                  fill={input.trim() && !loading ? '#86efac' : '#9aab9a'}
                  stroke={input.trim() && !loading ? '#86efac' : '#9aab9a'}
                  strokeWidth="0.5" strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* ── FAB Button ── */}
      <button
        className="chat-fab"
        onClick={() => setOpen(o => !o)}
        title="Chat with EcoBot"
        style={{
          position: 'fixed', bottom: 32, left: 32, zIndex: 1000,
          width: 58, height: 58, borderRadius: '50%',
          background: 'linear-gradient(145deg, #3a9a3a 0%, #1a3a1a 100%)',
          border: '2px solid rgba(134,239,172,0.35)',
          color: '#fff', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'transform 0.2s, box-shadow 0.2s',
          outline: 'none',
        }}
      >
        {open ? (
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <path d="M5 5l12 12M17 5L5 17" stroke="#86efac" strokeWidth="2.5" strokeLinecap="round"/>
          </svg>
        ) : (
          <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
            <path d="M3 6a3 3 0 013-3h14a3 3 0 013 3v9a3 3 0 01-3 3H9l-5 4V6z"
              fill="none" stroke="#86efac" strokeWidth="2" strokeLinejoin="round"/>
            <circle cx="9"  cy="10.5" r="1.4" fill="#86efac"/>
            <circle cx="13" cy="10.5" r="1.4" fill="#86efac"/>
            <circle cx="17" cy="10.5" r="1.4" fill="#86efac"/>
          </svg>
        )}
      </button>
    </>
  );
}
