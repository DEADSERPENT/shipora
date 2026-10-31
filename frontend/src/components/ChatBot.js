import React, { useState, useRef, useReducer, useEffect, useCallback } from 'react';
import axios from 'axios';
import { io } from 'socket.io-client';
import { ArrowUp, AudioLines, ChartColumn, Clock, Hand, Headset, Hourglass, List, MapPin, Mic, Navigation, Package, Pause, Play, RotateCcw, Route, Settings, Shield, Square, Truck, TriangleAlert, User, Users, Volume1, Volume2, Wallet, Zap } from 'lucide-react';
import { API_URL } from '../lib/shipora';
import { useAuth } from '../context/AuthContext';
import useDictation from '../hooks/useDictation';
import useSpeaker from '../hooks/useSpeaker';
import { joinDictation, loadDictationPreference, loadSpeakReplies, pickDictationEngine, saveDictationPreference, saveSpeakReplies } from '../lib/speech';
import { Ic } from './Icon';
import {
  VOICE_STATES, voiceReducer, initialVoiceState, labelFor,
} from './voiceConversationMachine';
import {
  LANGUAGES, getRecognitionLang, buildLanguageDirective,
  detectLanguageSwitchCommand, pickVoiceForLanguage, hasNativeVoice,
  detectScriptLanguage, loadSettings, saveSettings,
} from './multilingual';

const API = API_URL;
const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000';

const css = `
@keyframes chatPop {
  from { opacity: 0; transform: scale(0.9) translateY(24px); transform-origin: bottom left; }
  to   { opacity: 1; transform: scale(1)   translateY(0);    transform-origin: bottom left; }
}
@keyframes botTyping {
  0%,80%,100% { transform: translateY(0) scale(0.7); opacity: 0.4; }
  40%         { transform: translateY(-4px) scale(1); opacity: 1; }
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes fabPulse {
  0%,100% { box-shadow: 0 5px 0 #d9a406, 0 10px 26px rgba(20,32,26,0.28), 0 0 0 0 rgba(248,203,70,0.65); }
  60%     { box-shadow: 0 5px 0 #d9a406, 0 10px 26px rgba(20,32,26,0.28), 0 0 0 14px rgba(248,203,70,0); }
}
@keyframes micPulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(226,55,68,0.55); }
  50%     { box-shadow: 0 0 0 9px rgba(226,55,68,0); }
}
@keyframes speakerPulse {
  0%,100% { opacity: 0.6; }
  50%     { opacity: 1; }
}
@keyframes livePing {
  0%   { box-shadow: 0 0 0 0 rgba(12,131,31,0.55); }
  100% { box-shadow: 0 0 0 7px rgba(12,131,31,0); }
}
.chat-fab      { animation: fabPulse 2.8s ease-in-out infinite; }
.chat-fab:hover{ animation: none !important; transform: translateY(-2px) !important; }
.chat-panel    { animation: chatPop 0.32s cubic-bezier(0.34,1.4,0.64,1) both; }
.chat-msg      { animation: msgIn 0.24s ease both; }
.dot1 { animation: botTyping 1.1s 0.0s infinite; }
.dot2 { animation: botTyping 1.1s 0.15s infinite; }
.dot3 { animation: botTyping 1.1s 0.3s infinite; }
.mic-btn-listening { animation: micPulse 1.2s ease-in-out infinite; }
.speaker-pill  { animation: speakerPulse 1.1s ease-in-out infinite; }

/* ── Launcher ── */
.cb-fab {
  position: fixed; bottom: 28px; left: 28px; z-index: 1000;
  display: inline-flex; align-items: center; gap: 8px;
  height: 56px; padding: 0 22px 0 18px; border: none; border-radius: 20px;
  background: var(--accent, #f8cb46); color: var(--ink, #14201a);
  font-family: var(--font-display, inherit); font-weight: 800; font-size: 15px; letter-spacing: -0.01em;
  cursor: pointer; outline: none; transition: transform .18s;
}
.cb-fab-x { font-size: 28px; line-height: 1; font-weight: 500; padding: 0 6px; }

/* ── Panel ── */
.cb-panel {
  position: fixed; bottom: 96px; left: 28px; z-index: 1000;
  width: 400px; height: min(640px, calc(100vh - 176px));
  display: flex; flex-direction: column; overflow: hidden;
  background: #fff; border-radius: 28px;
  border: 1px solid rgba(20,32,26,0.08);
  box-shadow: 0 30px 80px rgba(20,32,26,0.28), 0 4px 18px rgba(20,32,26,0.12);
  font-family: var(--font-body, inherit);
}
@media (max-width: 520px) {
  .cb-panel { left: 0; right: 0; bottom: 0; width: 100%; height: 88vh; border-radius: 28px 28px 0 0; }
  .cb-fab { left: 16px; bottom: 16px; }
}

/* header */
.cb-header {
  display: flex; align-items: center; gap: 12px; flex-shrink: 0;
  padding: 16px 16px 16px 18px; position: relative; overflow: hidden;
  background: var(--accent, #f8cb46);
}
.cb-header::after {
  content: ''; position: absolute; right: -34px; top: -46px; width: 150px; height: 150px; border-radius: 50%;
  background: rgba(255,255,255,0.35); pointer-events: none;
}
.cb-avatar-lg {
  width: 44px; height: 44px; border-radius: 15px; flex-shrink: 0; transform: rotate(-5deg);
  display: flex; align-items: center; justify-content: center;
  background: var(--ink, #14201a); color: var(--accent, #f8cb46);
  box-shadow: 0 3px 0 rgba(20,32,26,0.25);
}
.cb-title { flex: 1; min-width: 0; position: relative; z-index: 1; }
.cb-name { font-family: var(--font-display, inherit); font-weight: 800; font-size: 20px; letter-spacing: -0.03em; color: var(--ink, #14201a); line-height: 1.1; }
.cb-status { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: rgba(20,32,26,0.72); margin-top: 2px; }
.cb-live { width: 8px; height: 8px; border-radius: 50%; background: #0c831f; animation: livePing 1.8s ease-out infinite; }
.cb-icon-btn {
  position: relative; z-index: 1; width: 34px; height: 34px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; border: none; cursor: pointer;
  background: rgba(20,32,26,0.1); color: var(--ink, #14201a); font-size: 20px; line-height: 1; transition: background .15s;
}
.cb-icon-btn:hover { background: rgba(20,32,26,0.2); }
.cb-icon-btn.on { background: var(--ink, #14201a); color: var(--accent, #f8cb46); }

/* settings + voice bar */
.cb-settings { padding: 12px 16px; background: #fffbea; border-bottom: 1px solid #f3e6a8; display: flex; flex-direction: column; gap: 10px; }
.cb-setting-row { display: flex; gap: 10px; align-items: center; }
.cb-setting-row label { font-size: 12px; font-weight: 700; color: var(--ink, #14201a); width: 62px; flex-shrink: 0; }
.cb-setting-row select { flex: 1; font-size: 13px; padding: 7px 10px; border-radius: 10px; border: 1.5px solid #e9dca0; background: #fff; }
.cb-warn { font-size: 11.5px; color: #92400e; background: #fff7d6; border: 1px solid #fde68a; border-radius: 10px; padding: 6px 10px; }
.cb-voice-bar {
  display: flex; align-items: center; gap: 8px; padding: 8px 18px; font-size: 12.5px; font-weight: 700;
  background: #e8f7ec; color: #0a5c16; border-bottom: 1px solid #cdeed5;
}
.cb-voice-bar.err { background: #fdecee; color: #a3202c; border-bottom-color: #f7c7cc; }

/* messages */
.cb-messages {
  flex: 1; overflow-y: auto; padding: 16px 16px 8px; display: flex; flex-direction: column; gap: 14px;
  background:
    radial-gradient(rgba(20,32,26,0.055) 1px, transparent 1.2px) 0 0 / 18px 18px,
    #f7f8f4;
  scrollbar-width: thin; scrollbar-color: #cfd8cf transparent;
}
.cb-welcome {
  background: #fff; border: 1px solid var(--border, #e6eae3); border-radius: 22px; padding: 18px 18px 16px;
  box-shadow: 0 6px 20px rgba(20,32,26,0.06); animation: msgIn .4s ease both;
}
.cb-welcome-badge {
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 999px;
  background: #e8f7ec; color: #0a5c16; font-size: 11.5px; font-weight: 700; margin-bottom: 10px;
}
.cb-welcome-title { font-family: var(--font-display, inherit); font-size: 24px; font-weight: 800; letter-spacing: -0.03em; color: var(--ink, #14201a); line-height: 1.1; }
.cb-welcome-sub { margin-top: 6px; font-size: 13.5px; line-height: 1.5; color: var(--muted, #6b7a70); }

.cb-row { display: flex; gap: 8px; align-items: flex-end; }
.cb-row.me { justify-content: flex-end; }
.cb-avatar {
  width: 28px; height: 28px; border-radius: 10px; flex-shrink: 0; transform: rotate(-5deg);
  display: flex; align-items: center; justify-content: center; background: var(--ink, #14201a); color: var(--accent, #f8cb46);
}
.cb-col { display: flex; flex-direction: column; max-width: 82%; min-width: 0; }
.cb-row.me .cb-col { align-items: flex-end; }
.cb-bubble { padding: 11px 15px; font-size: 14px; line-height: 1.55; word-wrap: break-word; overflow-wrap: anywhere; }
.cb-bubble.bot {
  background: #fff; color: var(--ink, #14201a); border: 1px solid var(--border, #e6eae3);
  border-radius: 20px 20px 20px 6px; box-shadow: 0 2px 8px rgba(20,32,26,0.05);
}
.cb-bubble.me {
  background: linear-gradient(135deg, #12a02c 0%, #0c831f 100%); color: #fff;
  border-radius: 20px 20px 6px 20px; box-shadow: 0 6px 16px rgba(12,131,31,0.28); font-weight: 500;
}
.cb-bubble strong { font-weight: 700; }
.cb-gap { height: 6px; }
.cb-li { display: flex; gap: 9px; align-items: flex-start; margin: 3px 0; }
.cb-li-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent-600, #f2b705); margin-top: 8px; flex-shrink: 0; }
.cb-tn {
  display: inline-block; padding: 1px 8px; border-radius: 8px; background: #fff3c4; color: #5c4400;
  font-family: var(--font-display, inherit); font-weight: 800; font-size: 12.5px; letter-spacing: 0.02em; border: 1px solid #f3dc7a;
}
.cb-status-chip {
  display: inline-block; padding: 1px 9px; border-radius: 999px; background: #e3f6e8; color: #0a5c16;
  font-weight: 700; font-size: 12.5px; border: 1px solid #bfe8c7;
}
.cb-agent { font-size: 11px; font-weight: 700; color: var(--muted, #6b7a70); margin: 5px 0 0 4px; display: flex; align-items: center; gap: 5px; }
.cb-agent::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--brand-500, #2fb44a); }
.cb-typing { padding: 0; }
.cb-dots { display: flex; gap: 5px; align-items: center; padding: 15px 16px; }
.cb-dots span { width: 8px; height: 8px; border-radius: 50%; background: var(--brand-600, #159a2b); display: inline-block; }

/* quick actions */
.cb-quick { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 4px 16px 12px; background: #f7f8f4; }
.cb-quick-btn {
  display: flex; flex-direction: column; align-items: flex-start; gap: 8px; text-align: left; cursor: pointer;
  padding: 12px; border-radius: 16px; background: #fff; border: 1.5px solid var(--border, #e6eae3);
  font-family: inherit; font-size: 12.5px; font-weight: 700; line-height: 1.3; color: var(--ink, #14201a);
  transition: transform .15s, border-color .15s, box-shadow .15s;
}
.cb-quick-btn:hover { transform: translateY(-2px); border-color: var(--brand-600, #159a2b); box-shadow: 0 8px 18px rgba(12,131,31,0.14); }
.cb-quick-ico { width: 30px; height: 30px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--accent, #f8cb46); color: var(--ink, #14201a); }

/* input */
.cb-input-wrap { padding: 8px 14px 12px; background: #fff; border-top: 1px solid var(--border, #e6eae3); flex-shrink: 0; }
.cb-input {
  display: flex; align-items: center; gap: 6px; padding: 5px 5px 5px 16px; border-radius: 999px;
  background: #f3f5f1; border: 1.5px solid transparent; transition: border-color .15s, background .15s, box-shadow .15s;
}
.cb-input:focus-within { background: #fff; border-color: var(--brand-600, #159a2b); box-shadow: 0 0 0 4px rgba(12,131,31,0.12); }
.cb-input input { flex: 1; min-width: 0; border: none; outline: none; background: transparent; font-family: inherit; font-size: 14px; color: var(--ink, #14201a); padding: 8px 0; }
.cb-input input::placeholder { color: #8a978d; }
.cb-mic, .cb-send {
  width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0; border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center; transition: transform .15s, background .15s, box-shadow .15s;
}
.cb-mic { background: transparent; color: var(--brand-700, #0c831f); }
.cb-mic:hover { background: #e3f6e8; }
.cb-mic.active, .cb-mic.mic-btn-listening { background: var(--red, #e23744); color: #fff; }
.cb-mic:disabled { opacity: .45; cursor: not-allowed; }
.cb-speak { display: flex; align-items: center; gap: 4px; margin-top: 4px; font-size: 11.5px; color: var(--muted, #6b7a70); }
.cb-speak button { display: inline-flex; align-items: center; gap: 4px; border: 0; background: transparent; cursor: pointer; color: var(--brand-700, #0c831f); font: 600 11.5px inherit; padding: 3px 6px; border-radius: 8px; }
.cb-speak button:hover:not(:disabled) { background: #e3f6e8; }
.cb-speak button:disabled { opacity: .5; cursor: default; }
.cb-voice-note { min-height: 0; font-size: 11.5px; color: var(--muted, #6b7a70); padding: 0 4px; }
.cb-voice-note span { display: inline-flex; align-items: center; gap: 5px; padding-top: 5px; }
.cb-voice-err { margin: 6px 0 0; align-items: center; }
.cb-voice-err button { margin-left: auto; border: 0; background: none; cursor: pointer; font-size: 16px; color: inherit; }
@media (max-width: 480px) { .cb-speak button { padding: 6px 8px; } }
.cb-send { background: var(--brand-700, #0c831f); color: #fff; box-shadow: 0 3px 0 var(--brand-800, #0a5c16); }
.cb-send:hover:not(:disabled) { transform: translateY(-1px); }
.cb-send:active:not(:disabled) { transform: translateY(2px); box-shadow: none; }
.cb-send:disabled { background: #d9dfd9; color: #fff; box-shadow: none; cursor: default; }
.cb-foot { text-align: center; font-size: 10.5px; color: #98a49b; margin-top: 7px; }

@media (prefers-reduced-motion: reduce) {
  .chat-fab, .chat-panel, .chat-msg, .cb-live, .dot1, .dot2, .dot3, .speaker-pill { animation: none !important; }
}
`;

const mediaRecorderSupported = typeof window !== 'undefined' && !!window.MediaRecorder && !!navigator.mediaDevices;
const AudioContextCls = typeof window !== 'undefined' && (window.AudioContext || window.webkitAudioContext);

// Dev-only voice I/O switch — see frontend/.env. 'server' (default): MediaRecorder
// + OpenAI Whisper/TTS via /api/voice/chat. 'browser': the free Web Speech API
// (SpeechRecognition + speechSynthesis) + the existing /api/chat text endpoint —
// no OpenAI key needed. Everything else (the FSM, error recovery, UI) is shared;
// only capture/playback branch on this flag. Temporary, for development.
const VOICE_MODE = process.env.REACT_APP_VOICE_MODE === 'browser' ? 'browser' : 'server';
const SpeechRecognitionAPI = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);
const speechRecognitionSupported = !!SpeechRecognitionAPI;
const speechSynthesisSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;
const voiceSupported = VOICE_MODE === 'browser' ? speechRecognitionSupported : mediaRecorderSupported;

function stripForSpeech(text) {
  return text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\n+/g, '. ').replace(/[•·]/g, '');
}

// VAD tuning — amplitude-threshold silence detection over the Web Audio
// API (AnalyserNode + requestAnimationFrame). No new dependency, no
// realtime framework; see docs/VOICE_ARCHITECTURE.md.
const SPEECH_RMS_THRESHOLD = 0.035;
const SILENCE_MS = 1100;
const MAX_UTTERANCE_MS = 20000;
const RESUME_DELAY_MS = 400;
const MAX_CONSECUTIVE_ERRORS = 3;

// 'browser' mode auto barge-in tuning (see monitorBargeIn): self-calibrating
// amplitude threshold, no secondary verification step — this is a portfolio
// POC, so responsiveness is prioritized over perfectly filtering every false
// positive. A short ignore window right after an utterance starts (the AI's
// own audio hasn't had time to settle yet, so early samples aren't a
// representative "bleed" baseline) is used to calibrate a per-utterance
// baseline; sound clearly louder than that baseline, sustained briefly, is
// treated as the user talking and cuts the reply off immediately.
const BARGE_IN_IGNORE_MS = 600; // ignore mic input for this long right after an utterance starts
const BARGE_IN_MARGIN = 0.05; // candidate must clear baseline + this margin
const BARGE_IN_MIN_THRESHOLD = 0.05; // floor, for a near-silent baseline (e.g. headphones, no bleed at all)
const BARGE_IN_SUSTAIN_MS = 180; // amplitude must stay above threshold this long — filters out brief pops/clicks

const AGENT_LABELS = {
  tracking: 'Tracking Agent',
  complaints: 'Delivery Issues Agent',
  schedule: 'Shipment Schedule Agent',
  support: 'Support Agent',
  general: 'General Assistant',
};

// Backend voice:stage values -> FSM states (see sockets.py / voice/pipeline.py).
const STAGE_TO_STATE = {
  transcribing: VOICE_STATES.TRANSCRIBING,
  thinking: VOICE_STATES.THINKING,
  tool_execution: VOICE_STATES.TOOL_EXECUTION,
  generating_response: VOICE_STATES.GENERATING_RESPONSE,
};

function getSessionId() {
  const key = 'shipora_chat_session_id';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

function TypingDots() {
  return (
    <div className="cb-dots">
      {['dot1', 'dot2', 'dot3'].map(c => <span key={c} className={c} />)}
    </div>
  );
}

// What the widget shows (greeting, suggestions, placeholder) comes from GET /api/chat/profile, which the backend builds per
// signed-in role (agents/roles.py). This is only the fallback while that loads or if it fails.
const ICONS = {
  'map-pin': MapPin, package: Package, clock: Clock, alert: TriangleAlert, wallet: Wallet, user: User, headset: Headset,
  route: Route, navigation: Navigation, list: List, chart: ChartColumn, truck: Truck, users: Users,
};
const DEFAULT_PROFILE = {
  badge: 'Same-day · Bengaluru', title: "Hi, I'm ShipBot",
  subtitle: 'Track a parcel, book a delivery or report an issue — ask me anything.',
  placeholder: 'Ask about Shipora…',
  greeting: "Hi! I'm **ShipBot**\nI can help you with Shipora — tracking parcels, creating shipments, delivery issues, and more. What can I help you with?",
  suggestions: [
    { text: 'Where is my parcel?', icon: 'map-pin' },
    { text: 'How do I create a shipment?', icon: 'package' },
    { text: 'When will my parcel arrive?', icon: 'clock' },
    { text: 'How do I report a damaged parcel?', icon: 'alert' },
  ],
};

const STATUS_NAMES = 'CREATED|PICKUP_SCHEDULED|PICKED_UP|IN_TRANSIT|OUT_FOR_DELIVERY|DELIVERED|DELIVERY_FAILED|CUSTOMER_UNAVAILABLE|ADDRESS_ISSUE|DAMAGED|CANCELLED|RETURNED_TO_ORIGIN';
const STATUS_RE = new RegExp(`^(?:${STATUS_NAMES})$`);
const INLINE_TOKEN = new RegExp(String.raw`(\*\*[^*]+\*\*|\b(?:${STATUS_NAMES})\b|\bSHP[0-9A-Z]{6,14}\b)`, 'g');

export default function ChatBot() {
  const [open,    setOpen]    = useState(false);
  const [input,   setInput]   = useState('');
  const [sending, setSending] = useState(false); // text-send spinner only; independent of the voice FSM
  const { user } = useAuth();
  const [profile, setProfile] = useState(DEFAULT_PROFILE);
  const [history, setHistory] = useState([{ role: 'assistant', content: DEFAULT_PROFILE.greeting }]);
  const [speakReplies, setSpeakReplies] = useState(loadSpeakReplies);     // off by default; the choice is remembered
  const [voicePref, setVoicePref] = useState(loadDictationPreference);       // 'auto' (browser) | 'server' (Shipora's own, private)
  const [dictated, setDictated] = useState(false);
  useEffect(() => { saveSpeakReplies(speakReplies); }, [speakReplies]);
  useEffect(() => { saveDictationPreference(voicePref); }, [voicePref]);
  const [voiceState, dispatch] = useReducer(voiceReducer, initialVoiceState);
  const [settings, setSettings] = useState(loadSettings); // { language, voiceURI, rate, pitch } — see multilingual.js
  const [showSettings, setShowSettings] = useState(false);
  const [voiceOptions, setVoiceOptions] = useState([]); // populated once speechSynthesis voices load, for the voice <select>

  useEffect(() => { saveSettings(settings); }, [settings]);

  const bottomRef        = useRef(null);
  const dictationBase    = useRef('');
  const inputRef         = useRef(null);
  const panelRef         = useRef(null);
  const sessionIdRef     = useRef(getSessionId());
  const lastIdentity     = useRef(undefined);

  // Signing in, out or switching role starts a fresh conversation with that role's setup: no memory, session id or
  // suggestions carry over from whoever used the assistant before.
  useEffect(() => {
    const identity = user ? `${user.role}:${user.id || user._id}` : 'anonymous';
    if (lastIdentity.current === identity) return;
    const first = lastIdentity.current === undefined;
    lastIdentity.current = identity;
    if (!first) {
      sessionIdRef.current = crypto.randomUUID();
      try { sessionStorage.setItem('shipora_chat_session_id', sessionIdRef.current); } catch {}
    }
    let cancelled = false;
    axios.get(`${API}/chat/profile`)
      .then(({ data }) => {
        if (cancelled) return;
        setProfile(data);
        setHistory([{ role: 'assistant', content: data.greeting }]);
      })
      .catch(() => {
        if (cancelled) return;
        setProfile(DEFAULT_PROFILE);
        setHistory([{ role: 'assistant', content: DEFAULT_PROFILE.greeting }]);
      });
    return () => { cancelled = true; };
  }, [user]);

  // Voice conversation plumbing
  const activeRef          = useRef(false);
  const micStreamRef       = useRef(null);
  const audioContextRef    = useRef(null);
  const analyserRef        = useRef(null);
  const mediaRecorderRef   = useRef(null);
  const audioChunksRef     = useRef([]);
  const vadRafRef          = useRef(null);
  const hasSpokenRef       = useRef(false);
  const lastLoudTimeRef    = useRef(0);
  const utteranceTimeoutRef = useRef(null);
  const resumeTimeoutRef   = useRef(null);
  const errorTimeoutRef    = useRef(null);
  const socketRef          = useRef(null);
  const consecutiveErrorsRef = useRef(0);
  const currentAudioRef    = useRef(null);
  const recognitionRef     = useRef(null); // 'browser' mode only
  const currentUtteranceRef = useRef(null); // 'browser' mode only
  const speechKeepAliveRef = useRef(null); // 'browser' mode only — resume() interval while speaking
  const voiceStateRef      = useRef(initialVoiceState.current); // live mirror of voiceState.current, for handlers created in async callbacks
  const settingsRef        = useRef(settings); // live mirror of settings, for the same reason as voiceStateRef — see its useEffect below
  const speechInterruptedRef = useRef(false); // 'browser' mode only — barge-in guard, see interruptSpeech()
  const bargeInRafRef      = useRef(null); // 'browser' mode only — monitorBargeIn's requestAnimationFrame id
  const bargeInLoudStartRef = useRef(null); // 'browser' mode only — timestamp the amplitude first crossed the calibrated trigger threshold
  const bargeInBaselineRef = useRef(0); // 'browser' mode only — self-calibrated per-utterance speaker-bleed baseline RMS
  const bargeInSpeakingStartRef = useRef(0); // 'browser' mode only — performance.now() when the current utterance started, for the calibration window
  // Internal per-turn language metadata (script-detected, see multilingual.js)
  // — not sent to the backend, not shown in the UI, no analytics. Purely
  // internal state for possible future use.
  const detectedLanguageLogRef = useRef([]);

  useEffect(() => { voiceStateRef.current = voiceState.current; }, [voiceState]);
  // Long-lived closures (recognition.onresult -> sendBrowserTranscript ->
  // speakReplyBrowser -> onDone -> scheduleResume -> beginListeningBrowser ->
  // a NEW recognition.onresult, and so on) get created once and then re-invoke
  // each other by name across many renders during the continuous voice loop.
  // Each of those functions is re-created fresh every render, but a callback
  // bound INTO a live object (recognition.onresult, utterance.onend) stays
  // pinned to whichever render created it — so if a language switch triggers
  // a re-render in the middle of that chain, the already-in-flight closure
  // keeps reading the OLD `settings` from its own render forever, never the
  // updated one, even though React state itself is correctly updated. This
  // was silently breaking language persistence across turns. Reading
  // settingsRef.current instead of `settings` in those handlers fixes it,
  // since a ref is a single mutable object shared by every closure.
  useEffect(() => { settingsRef.current = settings; }, [settings]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 120);
  }, [open]);

  useEffect(() => () => teardownConversation(), []); // eslint-disable-line react-hooks/exhaustive-deps

  // Voice list loads asynchronously in most browsers — prime it on mount and
  // re-list whenever it (re)populates, both for the settings panel's voice
  // <select> and so pickVoiceForLanguage (called in speakReplyBrowser) has a
  // populated list ready by the time there's something to say.
  useEffect(() => {
    if (VOICE_MODE !== 'browser' || !speechSynthesisSupported) return;
    const refreshVoices = () => setVoiceOptions(window.speechSynthesis.getVoices());
    refreshVoices();
    window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', refreshVoices);
  }, []);

  // ── Socket.IO: real backend stage events drive TRANSCRIBING/THINKING/
  // TOOL_EXECUTION/GENERATING_RESPONSE, not client-side guessed timing.
  const connectSocket = () => {
    const socket = io(SOCKET_URL, { transports: ['websocket', 'polling'] });
    socket.emit('voice:join', { sessionId: sessionIdRef.current });
    socket.on('voice:stage', ({ stage, detail }) => {
      const target = STAGE_TO_STATE[stage];
      if (target) dispatch({ type: target, detail });
    });
    socketRef.current = socket;
  };

  const disconnectSocket = () => {
    if (socketRef.current) {
      socketRef.current.emit('voice:leave', { sessionId: sessionIdRef.current });
      socketRef.current.disconnect();
      socketRef.current = null;
    }
  };

  const teardownConversation = () => {
    activeRef.current = false;
    cancelAnimationFrame(vadRafRef.current);
    cancelAnimationFrame(bargeInRafRef.current);
    bargeInLoudStartRef.current = null;
    bargeInBaselineRef.current = 0;
    bargeInSpeakingStartRef.current = 0;
    clearTimeout(utteranceTimeoutRef.current);
    clearTimeout(resumeTimeoutRef.current);
    clearTimeout(errorTimeoutRef.current);
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.onstop = null;
      mediaRecorderRef.current.stop();
    }
    micStreamRef.current?.getTracks().forEach(t => t.stop());
    micStreamRef.current = null;
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    if (recognitionRef.current) {
      recognitionRef.current.onresult = null;
      recognitionRef.current.onerror = null;
      recognitionRef.current.onend = null;
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }
    if (speechSynthesisSupported) window.speechSynthesis.cancel();
    clearInterval(speechKeepAliveRef.current);
    currentUtteranceRef.current = null;
    speechInterruptedRef.current = false;
    disconnectSocket();
  };

  // ── Voice Activity Detection: amplitude-threshold silence => end of turn
  const monitorVad = () => {
    if (!activeRef.current || !analyserRef.current) return;
    const analyser = analyserRef.current;
    const buffer = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buffer);
    let sumSquares = 0;
    for (let i = 0; i < buffer.length; i++) {
      const norm = (buffer[i] - 128) / 128;
      sumSquares += norm * norm;
    }
    const rms = Math.sqrt(sumSquares / buffer.length);
    const now = performance.now();
    if (rms > SPEECH_RMS_THRESHOLD) {
      hasSpokenRef.current = true;
      lastLoudTimeRef.current = now;
    }
    if (hasSpokenRef.current && now - lastLoudTimeRef.current > SILENCE_MS) {
      stopListeningAndSend();
      return;
    }
    vadRafRef.current = requestAnimationFrame(monitorVad);
  };

  const beginListening = () => {
    if (!activeRef.current || !micStreamRef.current) return;
    const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
    const recorder = new MediaRecorder(micStreamRef.current, { mimeType });
    audioChunksRef.current = [];
    recorder.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
    mediaRecorderRef.current = recorder;
    recorder.start();
    hasSpokenRef.current = false;
    lastLoudTimeRef.current = performance.now();
    dispatch({ type: VOICE_STATES.LISTENING });
    vadRafRef.current = requestAnimationFrame(monitorVad);
    utteranceTimeoutRef.current = setTimeout(stopListeningAndSend, MAX_UTTERANCE_MS);
  };

  const stopListeningAndSend = () => {
    cancelAnimationFrame(vadRafRef.current);
    clearTimeout(utteranceTimeoutRef.current);
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    recorder.onstop = () => {
      const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
      if (!activeRef.current) return;
      if (blob.size === 0 || !hasSpokenRef.current) {
        beginListening(); // nothing was actually said — just keep listening
        return;
      }
      dispatch({ type: VOICE_STATES.TRANSCRIBING });
      sendUtterance(blob);
    };
    recorder.stop();
  };

  const sendUtterance = async (blob) => {
    const form = new FormData();
    form.append('audio', blob, blob.type.includes('webm') ? 'recording.webm' : 'recording.m4a');
    form.append('sessionId', sessionIdRef.current);
    form.append('speak', (speakReplies || activeRef.current) ? 'true' : 'false');

    try {
      const { data } = await axios.post(`${API}/voice/chat`, form);
      if (!activeRef.current) return;
      consecutiveErrorsRef.current = 0;
      setHistory(h => [
        ...h,
        { role: 'user', content: data.transcript },
        { role: 'assistant', content: data.reply, agent: data.agent },
      ]);
      // The HTTP response is stronger ground truth than any voice:stage
      // event (which never fires at all on the zero-API-key fallback path,
      // and can race/drop) — force straight to GENERATING_RESPONSE.
      dispatch({ type: 'FORCE', target: VOICE_STATES.GENERATING_RESPONSE });
      if (data.audioBase64) {
        playReply(data.audioBase64, data.audioMimeType);
      } else {
        dispatch({ type: VOICE_STATES.WAITING_FOR_NEXT_INPUT });
        scheduleResume();
      }
    } catch (err) {
      handleVoiceError(err);
    }
  };

  const playReply = (base64, mimeType) => {
    const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: mimeType || 'audio/mpeg' }));
    const audio = new Audio(url);
    currentAudioRef.current = audio;
    dispatch({ type: VOICE_STATES.SPEAKING });
    const onDone = () => {
      URL.revokeObjectURL(url);
      if (currentAudioRef.current === audio) currentAudioRef.current = null;
      if (!activeRef.current) return;
      dispatch({ type: VOICE_STATES.WAITING_FOR_NEXT_INPUT });
      scheduleResume();
    };
    audio.addEventListener('ended', onDone);
    audio.play().catch(onDone);
  };

  const scheduleResume = () => {
    resumeTimeoutRef.current = setTimeout(() => {
      if (!activeRef.current) return;
      if (VOICE_MODE === 'browser') beginListeningBrowser();
      else beginListening();
    }, RESUME_DELAY_MS);
  };

  // ── 'browser' voice mode: Web Speech API instead of MediaRecorder/OpenAI ──
  // SpeechRecognition has its own built-in end-of-speech detection, so there's
  // no VAD step and no TRANSCRIBING network round-trip — the browser already
  // produced text, so it's dispatched straight through to keep the FSM's
  // transition table satisfied (LISTENING -> TRANSCRIBING -> THINKING).
  //
  // This particular recognizer is only ever armed during LISTENING, never
  // while TTS is playing. Talk-over-it barge-in during playback goes through
  // monitorBargeIn's amplitude-threshold VAD instead (self-calibrated per
  // utterance against the AI's own speaker-bleed level) — arming a
  // continuous recognizer for the whole reply would pick up the TTS audio
  // itself and self-trigger.
  const beginListeningBrowser = () => {
    if (!activeRef.current) return;
    const recognition = new SpeechRecognitionAPI();
    // Fixed language -> its locale; 'auto' -> broad-tolerance en-IN capture,
    // with Gemini (not the STT layer) doing the actual language matching —
    // SpeechRecognition can't dynamically auto-detect/switch language
    // mid-utterance, see multilingual.js's module comment. settingsRef (not
    // settings) because this function can be invoked from a stale closure
    // captured before a language switch — see settingsRef's own comment.
    recognition.lang = getRecognitionLang(settingsRef.current.language);
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onstart = () => dispatch({ type: VOICE_STATES.LISTENING });
    recognition.onerror = (e) => {
      if (!activeRef.current) return;
      if (e.error === 'no-speech' || e.error === 'aborted') {
        beginListeningBrowser(); // not a real error — just keep listening
        return;
      }
      handleVoiceError({ message: e.error });
    };
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript;
      if (!activeRef.current) return;
      if (!transcript || !transcript.trim()) {
        beginListeningBrowser();
        return;
      }
      dispatch({ type: VOICE_STATES.TRANSCRIBING });
      dispatch({ type: VOICE_STATES.THINKING });
      sendBrowserTranscript(transcript.trim());
    };
    recognitionRef.current = recognition;
    // Some Chrome/Edge versions throw InvalidStateError (or otherwise fail)
    // if .start() is called before the browser's speech service has fully
    // released a just-aborted previous session — most likely right after
    // interruptSpeech()'s abort()-then-immediately-restart. Uncaught, this
    // would silently leave the UI showing "Listening" while nothing is
    // actually capturing. Retry once after a short delay rather than
    // dropping the turn entirely.
    try {
      recognition.start();
    } catch (err) {
      recognitionRef.current = null;
      setTimeout(() => { if (activeRef.current) beginListeningBrowser(); }, 150);
    }
  };

  // Self-calibrating amplitude barge-in — no secondary verification step.
  // This is a portfolio POC, so responsiveness is prioritized over
  // perfectly filtering every false positive (e.g. the AI's own voice
  // occasionally bleeding into the mic loud enough to self-trigger). Wired
  // to run whenever the FSM enters SPEAKING — see startConversation.
  const monitorBargeIn = () => {
    if (!activeRef.current || !analyserRef.current) return;
    if (voiceStateRef.current !== VOICE_STATES.SPEAKING) {
      bargeInLoudStartRef.current = null;
      bargeInRafRef.current = requestAnimationFrame(monitorBargeIn);
      return;
    }
    const analyser = analyserRef.current;
    const buffer = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buffer);
    let sumSquares = 0;
    for (let i = 0; i < buffer.length; i++) {
      const norm = (buffer[i] - 128) / 128;
      sumSquares += norm * norm;
    }
    const rms = Math.sqrt(sumSquares / buffer.length);
    const now = performance.now();
    const elapsedSinceSpeechStart = now - bargeInSpeakingStartRef.current;

    if (elapsedSinceSpeechStart < BARGE_IN_IGNORE_MS) {
      // Ignore window: establish the AI's own speaker-bleed baseline, don't trigger yet.
      bargeInBaselineRef.current = Math.max(bargeInBaselineRef.current, rms);
      bargeInRafRef.current = requestAnimationFrame(monitorBargeIn);
      return;
    }

    const triggerThreshold = Math.max(bargeInBaselineRef.current + BARGE_IN_MARGIN, BARGE_IN_MIN_THRESHOLD);
    if (rms > triggerThreshold) {
      if (bargeInLoudStartRef.current == null) bargeInLoudStartRef.current = now;
      if (now - bargeInLoudStartRef.current > BARGE_IN_SUSTAIN_MS) {
        bargeInLoudStartRef.current = null;
        interruptSpeech();
      }
    } else {
      bargeInLoudStartRef.current = null;
    }
    bargeInRafRef.current = requestAnimationFrame(monitorBargeIn);
  };

  // Barge-in: triggered automatically by monitorBargeIn (sustained loud mic
  // input while SPEAKING) or by pressing the Start/End Conversation button
  // (see toggleConversation) — cancels TTS immediately, discards the
  // unfinished utterance, and starts a fresh listener. 'browser' voice mode
  // only; server mode's button/SPEAKING behavior is untouched.
  const interruptSpeech = () => {
    if (!activeRef.current) return;
    speechInterruptedRef.current = true; // tells speakReplyBrowser's onEnd/onError to no-op — see there for why
    clearInterval(speechKeepAliveRef.current);
    currentUtteranceRef.current = null; // discard the unfinished utterance
    bargeInLoudStartRef.current = null;
    forceStopSpeaking();
    // Also catches GENERATING_RESPONSE: speakReplyBrowser only dispatches
    // SPEAKING from utterance.onstart, which is async, so an interrupt can
    // land just before that fires — this is the same for Gemini replies and
    // local switch confirmations (speakReplyBrowser is the one shared speech
    // path either way), just far more likely to be hit on confirmations
    // since their whole utterance is short relative to that startup window.
    if (voiceStateRef.current === VOICE_STATES.SPEAKING || voiceStateRef.current === VOICE_STATES.GENERATING_RESPONSE) {
      dispatch({ type: VOICE_STATES.LISTENING });
    }
    // Always (re)start a fresh listener — recognitionRef.current can still
    // hold a reference to the PREVIOUS utterance's recognition session (it's
    // never nulled out when a session finishes naturally after producing a
    // result), so checking truthiness alone doesn't reliably tell us whether
    // something is actually listening right now. abort() on an already-
    // stopped instance is a safe no-op.
    if (recognitionRef.current) {
      recognitionRef.current.onresult = null;
      recognitionRef.current.onerror = null;
      recognitionRef.current.onstart = null;
      try { recognitionRef.current.abort(); } catch { /* already stopped */ }
      recognitionRef.current = null;
    }
    // A short delay before restarting gives the browser's speech service a
    // moment to actually release the just-aborted session — starting a new
    // one in the exact same tick is what most likely caused "not taking
    // input after interrupting" (see beginListeningBrowser's try/catch for
    // the same race, which this reduces but doesn't fully eliminate).
    setTimeout(() => { if (activeRef.current) beginListeningBrowser(); }, 100);
  };

  // Chrome/Edge have a long-standing bug (especially with Windows SAPI voices,
  // which is what the female-voice picker usually selects) where cancel()
  // silently no-ops on an utterance that's already partway through playing —
  // the queue clears but the current utterance keeps speaking to the end.
  // pause() -> cancel() -> a delayed second cancel() (some report needing
  // cancel() called twice) is the most reliable known workaround; the retry
  // also catches the case where cancel() raced with the queue and lost.
  const forceStopSpeaking = () => {
    window.speechSynthesis.pause();
    window.speechSynthesis.cancel();
    setTimeout(() => {
      if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
        window.speechSynthesis.cancel();
      }
    }, 50);
  };

  // ── Multilingual: in-conversation language-switch commands ("Switch to
  // Kannada", "अब हिंदी में बात करो", ...) are handled 100% locally — no
  // /api/chat call — so switching is instant and never depends on Gemini
  // correctly interpreting a meta-request. Shared by both the voice
  // transcript path and the typed-text path (see send() below), per the
  // "reusable helper, no duplication" requirement. Returns
  // {confirmation, targetLang} if `text` was a switch command (and updates
  // settings + history as a side effect), else null.
  const tryHandleLanguageSwitch = (text) => {
    const targetLang = detectLanguageSwitchCommand(text);
    if (!targetLang || targetLang === settingsRef.current.language) return null;
    const confirmation = LANGUAGES[targetLang].switchConfirmation;
    setSettings(s => ({ ...s, language: targetLang }));
    setHistory(h => [
      ...h,
      { role: 'user', content: text },
      { role: 'assistant', content: confirmation },
    ]);
    return { confirmation, targetLang };
  };

  const sendBrowserTranscript = async (transcript) => {
    detectedLanguageLogRef.current.push({ text: transcript, language: detectScriptLanguage(transcript), at: Date.now() });
    const switchResult = tryHandleLanguageSwitch(transcript);
    if (switchResult) {
      dispatch({ type: 'FORCE', target: VOICE_STATES.GENERATING_RESPONSE });
      if ((speakReplies || activeRef.current) && speechSynthesisSupported) {
        // Pass targetLang explicitly rather than relying on settings.language
        // — setSettings() above is async, so this closure's `settings` is
        // still the OLD value until the next render; speaking the confirmation
        // in the wrong voice would defeat the point of switching.
        speakReplyBrowser(switchResult.confirmation, switchResult.targetLang);
      } else {
        dispatch({ type: VOICE_STATES.WAITING_FOR_NEXT_INPUT });
        scheduleResume();
      }
      return;
    }

    try {
      // buildLanguageDirective wraps the transcript with a bracketed language
      // instruction Gemini reads as part of the user's turn — the mechanism
      // for language steering without any backend change. Only the wire
      // payload carries it; the displayed/stored history entry (below) stays
      // the clean transcript. mode: 'voice' additionally caps replies to
      // ~3-4 spoken sentences — this is the browser voice conversation path,
      // text chat (see send() below) uses mode: 'text' and keeps full-length
      // replies. settingsRef (not settings): this function can run from a
      // closure captured before a language switch — see settingsRef's comment.
      const { data } = await axios.post(`${API}/chat`, {
        message: buildLanguageDirective(settingsRef.current.language, transcript, 'voice'),
        history: historyForApi(),
        sessionId: sessionIdRef.current,
      });
      if (!activeRef.current) return;
      consecutiveErrorsRef.current = 0;
      setHistory(h => [
        ...h,
        { role: 'user', content: transcript },
        { role: 'assistant', content: data.reply, agent: data.agent },
      ]);
      // No voice:stage events fire for the text endpoint — same FORCE
      // fallback already used for the zero-API-key case.
      dispatch({ type: 'FORCE', target: VOICE_STATES.GENERATING_RESPONSE });
      if ((speakReplies || activeRef.current) && speechSynthesisSupported) {
        // Talk-over-it barge-in runs automatically here via monitorBargeIn's
        // self-calibrating amplitude VAD. Button-triggered interruptSpeech()
        // (toggleConversation) remains available as a reliable fallback either way.
        speakReplyBrowser(data.reply);
      } else {
        dispatch({ type: VOICE_STATES.WAITING_FOR_NEXT_INPUT });
        scheduleResume();
      }
    } catch (err) {
      handleVoiceError(err);
    }
  };

  // langKeyOverride: used right after a language switch, where settings.language
  // is still the OLD value in this closure (setSettings() is async) — see
  // tryHandleLanguageSwitch's caller in sendBrowserTranscript. Falls back to
  // settingsRef (not settings) for the same stale-closure reason.
  const speakReplyBrowser = (text, langKeyOverride) => {
    const langKey = langKeyOverride || settingsRef.current.language;
    const utterance = new SpeechSynthesisUtterance(stripForSpeech(text));
    // pickVoiceForLanguage: manual override (settings.voiceURI) if still
    // installed, else the best match for the current language, else a
    // graceful fallback chain — see multilingual.js.
    const voice = pickVoiceForLanguage(langKey, voiceOptions, settingsRef.current.voiceURI);
    if (voice) {
      utterance.voice = voice;
      utterance.lang = voice.lang;
    } else {
      utterance.lang = getRecognitionLang(langKey); // no voice installed at all — at least set the right locale
    }
    // rate/pitch controls were removed — utterance uses the browser's own defaults (1.0/1.0)
    currentUtteranceRef.current = utterance;
    const onDone = () => {
      clearInterval(speechKeepAliveRef.current);
      if (currentUtteranceRef.current === utterance) currentUtteranceRef.current = null;
      if (!activeRef.current) return;
      // speechSynthesis.cancel() (called by interruptSpeech() on a button-press
      // barge-in) triggers onend/onerror asynchronously in some browsers —
      // interruptSpeech() already moved the FSM to LISTENING and started a
      // fresh listener itself, so running the "speech ended naturally" path
      // here too would fight it (double-dispatch). This flag guards that race.
      if (speechInterruptedRef.current) {
        speechInterruptedRef.current = false;
        return;
      }
      dispatch({ type: VOICE_STATES.WAITING_FOR_NEXT_INPUT });
      scheduleResume();
    };
    utterance.onstart = () => {
      dispatch({ type: VOICE_STATES.SPEAKING });
      // Reset monitorBargeIn's per-utterance calibration — each reply gets
      // its own fresh speaker-bleed baseline measurement.
      bargeInLoudStartRef.current = null;
      bargeInBaselineRef.current = 0;
      bargeInSpeakingStartRef.current = performance.now();
      // Chrome/Edge silently pause speechSynthesis after ~15s of continuous
      // speech unless nudged — this keeps longer replies from stalling
      // partway through instead of actually being a fixed startup delay.
      speechKeepAliveRef.current = setInterval(() => {
        if (window.speechSynthesis.speaking) window.speechSynthesis.resume();
      }, 10000);
    };
    utterance.onend = onDone;
    utterance.onerror = onDone;
    // Only cancel when something is actually queued/speaking — calling
    // cancel() right before speak() on an already-empty queue is a known
    // source of a multi-second startup stall in Chrome/Edge (this is very
    // likely the exact delay being reported: text renders instantly since
    // that's just a state dispatch, but audio start was being held up here).
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
      window.speechSynthesis.cancel();
    }
    window.speechSynthesis.speak(utterance);
  };

  // Dispatching ERROR immediately followed by END in the same tick would
  // get batched into a single render (React 18 auto-batching) and the
  // error message would never actually be visible before END's static
  // "Conversation ended" replaces it — so the END/resume transition is
  // deliberately delayed a beat, giving the user a chance to read why.
  const handleVoiceError = (err) => {
    const hardFailure = err.response?.status === 422; // "voice not configured" — retrying identically fails every time
    const message = hardFailure
      ? "Voice isn't configured right now — please type your question instead."
      : 'Sorry, something went wrong. Please try again.';
    dispatch({ type: VOICE_STATES.ERROR, detail: message });

    if (hardFailure) {
      errorTimeoutRef.current = setTimeout(endConversation, 2000);
      return;
    }
    consecutiveErrorsRef.current += 1;
    if (consecutiveErrorsRef.current >= MAX_CONSECUTIVE_ERRORS) {
      dispatch({ type: VOICE_STATES.ERROR, detail: 'Too many errors in a row — ending the conversation.' });
      errorTimeoutRef.current = setTimeout(endConversation, 2000);
      return;
    }
    errorTimeoutRef.current = setTimeout(() => {
      if (activeRef.current) beginListening();
    }, 1200);
  };

  const startConversation = async () => {
    if (VOICE_MODE === 'browser') {
      if (!speechRecognitionSupported) {
        dispatch({ type: VOICE_STATES.ERROR, detail: 'Voice conversation is not supported in this browser.' });
        return;
      }
      try {
        // A separate raw mic stream (alongside SpeechRecognition's own
        // internal one) feeds an amplitude VAD used only to detect barge-in
        // while SPEAKING — SpeechRecognition's built-in speech detection has
        // no adjustable sensitivity, so it can't tell the user's voice apart
        // from the AI's own voice leaking from the speakers into the mic.
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        micStreamRef.current = stream;
        const audioCtx = new AudioContextCls();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        audioContextRef.current = audioCtx;
        analyserRef.current = analyser;

        activeRef.current = true;
        consecutiveErrorsRef.current = 0;
        dispatch({ type: 'RESET' });
        dispatch({ type: VOICE_STATES.LISTENING }); // IDLE -> LISTENING, valid
        beginListeningBrowser();
        // Self-calibrating amplitude VAD for talk-over-it barge-in — see the
        // constants/comments above monitorBargeIn for the tuning rationale.
        // Button-triggered interruptSpeech() (toggleConversation) remains
        // available as a reliable fallback either way.
        bargeInRafRef.current = requestAnimationFrame(monitorBargeIn);
      } catch {
        dispatch({ type: VOICE_STATES.ERROR, detail: 'Microphone access was denied.' });
        errorTimeoutRef.current = setTimeout(() => dispatch({ type: 'RESET' }), 2000);
      }
      return;
    }

    if (!mediaRecorderSupported) {
      dispatch({ type: VOICE_STATES.ERROR, detail: 'Voice conversation is not supported in this browser.' });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micStreamRef.current = stream;
      const audioCtx = new AudioContextCls();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      audioContextRef.current = audioCtx;
      analyserRef.current = analyser;

      activeRef.current = true;
      consecutiveErrorsRef.current = 0;
      connectSocket();
      dispatch({ type: 'RESET' });
      dispatch({ type: VOICE_STATES.LISTENING }); // IDLE -> LISTENING, valid
      beginListening();
    } catch {
      // Nothing was actually started (activeRef never flips true), so this
      // resolves back to IDLE rather than END — there's no conversation to
      // "end". Delayed so the error message is visible for a beat first.
      dispatch({ type: VOICE_STATES.ERROR, detail: 'Microphone access was denied.' });
      errorTimeoutRef.current = setTimeout(() => dispatch({ type: 'RESET' }), 2000);
    }
  };

  const endConversation = () => {
    teardownConversation();
    dispatch({ type: VOICE_STATES.END });
  };

  const toggleConversation = () => {
    if (!activeRef.current) {
      startConversation();
      return;
    }
    // Barge-in via button press: interrupt, don't end the conversation.
    // Also treated as interruptible during GENERATING_RESPONSE (the brief
    // async window before utterance.onstart flips state to SPEAKING — see
    // interruptSpeech()) so a fast button-press right as a reply — Gemini or
    // a local switch confirmation — starts doesn't fall through to ending
    // the whole conversation instead of just stopping this one reply.
    // 'browser' mode only — server mode's button-while-SPEAKING behavior
    // (end the conversation) is unchanged.
    if (
      VOICE_MODE === 'browser' &&
      (voiceStateRef.current === VOICE_STATES.SPEAKING || voiceStateRef.current === VOICE_STATES.GENERATING_RESPONSE)
    ) {
      interruptSpeech();
      return;
    }
    endConversation();
  };

  // ── Text send path (unchanged flow, decoupled from the voice FSM) ──────
  const historyForApi = () => history.filter(h => h.role !== 'assistant' || h !== history[0]);

  const getPlaybackVoice = useCallback(() => pickVoiceForLanguage(settings.language, voiceOptions, settings.voiceURI), [settings.language, settings.voiceURI, voiceOptions]);
  const speaker = useSpeaker({ api: API, lang: getRecognitionLang(settings.language), getVoice: getPlaybackVoice, preference: voicePref });
  // Dictation fills the box and stops there: the person reads it, edits it, and presses Send themselves.
  const dictation = useDictation({
    api: API, lang: getRecognitionLang(settings.language), preference: voicePref,
    onText: (text, final) => { setInput(joinDictation(dictationBase.current, text)); setDictated(true); if (final) inputRef.current?.focus(); },
  });
  const toggleDictation = () => {
    if (dictation.listening) { dictation.stop(); return; }
    speaker.stop();                                   // don't listen to our own voice
    dictationBase.current = input;
    dictation.start();
  };
  useEffect(() => { if (!open) { speaker.stop(); dictation.cancel(); } }, [open]); // eslint-disable-line

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || sending) return;
    dictation.cancel();
    setDictated(false);
    setInput('');

    detectedLanguageLogRef.current.push({ text: msg, language: detectScriptLanguage(msg), at: Date.now() });
    // Same local, deterministic language-switch handling as the voice path
    // (see tryHandleLanguageSwitch) — typed "switch to Hindi" works too, no
    // /api/chat call, no dependency on Gemini interpreting a meta-request.
    if (tryHandleLanguageSwitch(msg)) return;

    const userMsg = { role: 'user', content: msg };
    setHistory(h => [...h, userMsg]);
    setSending(true);

    try {
      // mode: 'text' — language steering + script enforcement only, NOT the
      // spoken-length framing ("3-4 sentences") applied to the voice path
      // below; typed chat should keep getting full-length replies.
      const { data } = await axios.post(`${API}/chat`, {
        message: buildLanguageDirective(settingsRef.current.language, msg, 'text'),
        history: historyForApi(),
        sessionId: sessionIdRef.current,
      });
      setHistory(h => [...h, { role: 'assistant', content: data.reply, agent: data.agent }]);
      if (speakReplies) speaker.speak(`m${history.length + 1}`, data.reply);     // only when the person has switched spoken replies on
    } catch {
      setHistory(h => [...h, { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' }]);
    } finally {
      setSending(false);
    }
  };

  // Bot text -> rich rows: bullets, **bold**, tracking numbers (SHP…) and shipment statuses as chips.
  const renderInline = (line, key, rich) => line.split(INLINE_TOKEN).map((part, j) => {
    if (j % 2 === 0) return part;
    if (!rich) return part.startsWith('**') ? part.slice(2, -2) : part;  // the user's own text stays plain
    if (part.startsWith('**')) return <strong key={`${key}-${j}`}>{part.slice(2, -2)}</strong>;
    if (STATUS_RE.test(part)) return <span key={`${key}-${j}`} className="cb-status-chip">{part.toLowerCase().split('_').map(w => w[0].toUpperCase() + w.slice(1)).join(' ')}</span>;
    return <span key={`${key}-${j}`} className="cb-tn">{part}</span>;
  });

  const renderContent = (text, rich = true) => text.split('\n').map((line, i) => {
    if (!line.trim()) return <div key={i} className="cb-gap" />;
    const bullet = line.match(/^\s*[•*-]\s+(.*)$/);
    return bullet
      ? <div key={i} className="cb-li"><span className="cb-li-dot" /><span>{renderInline(bullet[1], i, rich)}</span></div>
      : <div key={i}>{renderInline(line, i, rich)}</div>;
  });

  const isActive = voiceState.current !== VOICE_STATES.IDLE && voiceState.current !== VOICE_STATES.END;
  const isListeningNow = voiceState.current === VOICE_STATES.LISTENING;
  const isSpeakingNow = voiceState.current === VOICE_STATES.SPEAKING;
  const isBusy = isActive && !isListeningNow && !isSpeakingNow && voiceState.current !== VOICE_STATES.ERROR;
  const voiceStatusLabel = isActive || voiceState.current === VOICE_STATES.ERROR
    ? labelFor(voiceState.current, voiceState.detail)
    : null;

  // Requirement: don't silently substitute a missing Hindi/Kannada voice —
  // say so. Not meaningful for 'auto' (no single target language).
  const voiceFallbackNotice = (
    VOICE_MODE === 'browser' && settings.language !== 'auto' &&
    voiceOptions.length > 0 && !hasNativeVoice(settings.language, voiceOptions)
  ) ? `No native ${LANGUAGES[settings.language].label} voice is installed on this browser. Using the closest available voice.`
    : null;

  return (
    <>
      <style>{css}</style>

      {/* ── Chat Panel ── */}
      {open && (
        <div ref={panelRef} className="chat-panel cb-panel" role="dialog" aria-label="ShipBot chat">

          {/* Header */}
          <div className="cb-header">
            <div className="cb-avatar-lg"><Ic icon={Zap} size={22} strokeWidth={2.6} /></div>
            <div className="cb-title">
              <div className="cb-name">ShipBot</div>
              <div className="cb-status"><span className="cb-live" />Online · Shipora Assistant</div>
            </div>
            {VOICE_MODE === 'browser' && (
              <button className={`cb-icon-btn ${showSettings ? 'on' : ''}`} onClick={() => setShowSettings(s => !s)}
                title="Voice settings (language, voice, rate, pitch)"><Ic icon={Settings} size={16} /></button>
            )}
            <button className={`cb-icon-btn ${voicePref === 'server' ? 'on' : ''}`} onClick={() => setVoicePref(v => (v === 'server' ? 'auto' : 'server'))}
              aria-pressed={voicePref === 'server'}
              title={voicePref === 'server' ? "Private voice: speech is processed by Shipora's own server (on)" : "Private voice: use Shipora's own server instead of your browser's speech service"}>
              <Ic icon={Shield} size={16} />
            </button>
            <button className={`cb-icon-btn ${speakReplies ? 'on' : ''}`} onClick={() => { setSpeakReplies(s => !s); speaker.stop(); }}
              aria-pressed={speakReplies}
              title={speakReplies ? 'Spoken replies are on — click to turn off' : 'Spoken replies are off — click to read every reply aloud'}>
              {speakReplies ? <Ic icon={Volume2} size={16} /> : <Ic icon={Volume1} size={16} />}
            </button>
            <button className="cb-icon-btn" onClick={() => setOpen(false)} title="Close">×</button>
          </div>

          {/* Voice settings panel — language/voice/rate/pitch, persisted to localStorage */}
          {showSettings && VOICE_MODE === 'browser' && (
            <div className="cb-settings">
              <div className="cb-setting-row">
                <label>Language</label>
                <select value={settings.language} onChange={e => setSettings(s => ({ ...s, language: e.target.value }))}>
                  {Object.values(LANGUAGES).map(l => (
                    <option key={l.key} value={l.key}>{l.label}</option>
                  ))}
                </select>
              </div>
              <div className="cb-setting-row">
                <label>Voice</label>
                <select value={settings.voiceURI || ''} onChange={e => setSettings(s => ({ ...s, voiceURI: e.target.value || null }))}>
                  <option value="">Auto (best match for language)</option>
                  {/* Real installed voice names (e.g. "Google हिन्दी", "Microsoft Heera") — not generic labels. */}
                  {voiceOptions.map(v => (
                    <option key={v.voiceURI} value={v.voiceURI}>{v.name} ({v.lang})</option>
                  ))}
                </select>
              </div>
              {voiceFallbackNotice && (
                <div className="cb-warn"><Ic icon={TriangleAlert} size={13} /> {voiceFallbackNotice}</div>
              )}
            </div>
          )}

          {/* Voice conversation status bar — reads purely off the FSM state */}
          {voiceStatusLabel && (
            <div className={`cb-voice-bar ${voiceState.current === VOICE_STATES.ERROR ? 'err' : ''} ${isBusy || isSpeakingNow ? 'speaker-pill' : ''}`}>
              <Ic icon={isListeningNow ? Mic : isSpeakingNow ? Volume2 : voiceState.current === VOICE_STATES.ERROR ? TriangleAlert : Hourglass} size={14} />
              {voiceStatusLabel}
            </div>
          )}

          {/* Messages */}
          <div className="cb-messages">
            {history.length === 1 && (
              <div className="cb-welcome">
                <div className="cb-welcome-badge"><Ic icon={Zap} size={13} strokeWidth={2.6} /> {profile.badge}</div>
                <div className="cb-welcome-title">{profile.title} <Ic icon={Hand} size={20} style={{ color: 'var(--accent-600)', verticalAlign: '-3px' }} /></div>
                <div className="cb-welcome-sub">{profile.subtitle}</div>
              </div>
            )}

            {history.map((msg, i) => {
              if (history.length === 1 && i === 0) return null;  // the welcome card replaces the initial greeting bubble
              const isBot = msg.role === 'assistant';
              return (
                <div key={i} className={`chat-msg cb-row ${isBot ? 'bot' : 'me'}`}>
                  {isBot && <div className="cb-avatar"><Ic icon={Zap} size={14} strokeWidth={2.6} /></div>}
                  <div className="cb-col">
                    <div className={`cb-bubble ${isBot ? 'bot' : 'me'}`}>{renderContent(msg.content, isBot)}</div>
                    {isBot && msg.agent && AGENT_LABELS[msg.agent] && (
                      <div className="cb-agent">{AGENT_LABELS[msg.agent]}</div>
                    )}
                    {isBot && i > 0 && (
                      <div className="cb-speak" role="group" aria-label="Read this reply aloud">
                        {speaker.activeId === `m${i}` ? (
                          <>
                            {speaker.status === 'paused'
                              ? <button type="button" onClick={speaker.resume} title="Resume" aria-label="Resume"><Ic icon={Play} size={13} /></button>
                              : <button type="button" onClick={speaker.pause} disabled={speaker.status === 'loading'} title="Pause" aria-label="Pause"><Ic icon={Pause} size={13} /></button>}
                            <button type="button" onClick={speaker.stop} title="Stop" aria-label="Stop"><Ic icon={Square} size={12} /></button>
                            <button type="button" onClick={() => speaker.speak(`m${i}`, msg.content)} title="Replay from the start" aria-label="Replay"><Ic icon={RotateCcw} size={13} /></button>
                            <span>{speaker.status === 'loading' ? 'Preparing voice…' : speaker.status === 'paused' ? 'Paused' : 'Speaking…'}</span>
                          </>
                        ) : (
                          <button type="button" onClick={() => speaker.speak(`m${i}`, msg.content)} title="Read this reply aloud" aria-label="Read this reply aloud"><Ic icon={Volume2} size={13} /> Listen</button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {sending && (
              <div className="cb-row bot chat-msg">
                <div className="cb-avatar"><Ic icon={Zap} size={14} strokeWidth={2.6} /></div>
                <div className="cb-bubble bot cb-typing"><TypingDots /></div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Quick actions (only before the first question) */}
          {history.length === 1 && (
            <div className="cb-quick">
              {profile.suggestions.map(s => (
                <button key={s.text} className="cb-quick-btn" onClick={() => send(s.text)}>
                  <span className="cb-quick-ico"><Ic icon={ICONS[s.icon] || MapPin} size={16} /></span>
                  <span>{s.text}</span>
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div className="cb-input-wrap">
            <div className="cb-input">
              <input
                ref={inputRef}
                value={input}
                onChange={e => { setInput(e.target.value); if (dictation.listening) dictation.stop(); }}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
                placeholder={profile.placeholder}
                disabled={sending}
              />
              {pickDictationEngine(voicePref) && !isActive && (
                <button
                  type="button"
                  onClick={toggleDictation}
                  disabled={sending || dictation.processing}
                  aria-pressed={dictation.listening}
                  aria-label={dictation.listening ? 'Stop dictation' : 'Dictate your message'}
                  title={dictation.listening ? 'Stop — then check the text and press Send' : 'Speak your message (you can edit it before sending)'}
                  className={`cb-mic ${dictation.listening ? 'mic-btn-listening active' : ''}`}
                >
                  {dictation.processing ? <Ic icon={Hourglass} size={17} /> : <Ic icon={Mic} size={17} />}
                </button>
              )}
              {voiceSupported && (
                <button
                  onClick={toggleConversation}
                  aria-label={isActive ? 'End hands-free conversation' : 'Start hands-free conversation'}
                  title={isActive ? 'End hands-free conversation' : 'Hands-free conversation (replies are spoken)'}
                  className={`cb-mic ${isActive ? 'active' : ''} ${isListeningNow ? 'mic-btn-listening' : ''}`}
                >
                  <Ic icon={AudioLines} size={17} />
                </button>
              )}
              <button className="cb-send" onClick={() => send()} disabled={!input.trim() || sending} title="Send" aria-label="Send">
                <Ic icon={ArrowUp} size={18} strokeWidth={2.8} />
              </button>
            </div>
            <div className="cb-voice-note" role="status" aria-live="polite">
              {dictation.listening && <span><Ic icon={Mic} size={12} /> Listening… tap the microphone to stop.</span>}
              {dictation.processing && <span><Ic icon={Hourglass} size={12} /> Turning your recording into text…</span>}
              {!dictation.listening && !dictation.processing && dictated && input.trim() && <span>Check the text, change anything, then press Send.</span>}
            </div>
            {(dictation.error || speaker.error) && (
              <div className="cb-warn cb-voice-err" role="alert">
                <Ic icon={TriangleAlert} size={13} /> {dictation.error || speaker.error}
                <button type="button" onClick={() => { dictation.cancel(); speaker.clearError(); }} aria-label="Dismiss">×</button>
              </div>
            )}
            <div className="cb-foot">ShipBot can make mistakes — check tracking details on the shipment page.</div>
          </div>
        </div>
      )}

      {/* ── Launcher ── */}
      <button className="chat-fab cb-fab" onClick={() => setOpen(o => !o)} title="Chat with ShipBot" aria-label="Chat with ShipBot">
        {open ? <span className="cb-fab-x">×</span> : <><Ic icon={Zap} size={20} strokeWidth={2.6} /><span className="cb-fab-label">Ask ShipBot</span></>}
      </button>
    </>
  );
}
