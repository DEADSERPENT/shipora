import React, { useState, useRef, useReducer, useEffect } from 'react';
import axios from 'axios';
import { io } from 'socket.io-client';
import {
  VOICE_STATES, voiceReducer, initialVoiceState, labelFor,
} from './voiceConversationMachine';
import {
  LANGUAGES, getRecognitionLang, buildLanguageDirective,
  detectLanguageSwitchCommand, pickVoiceForLanguage, hasNativeVoice,
  detectScriptLanguage, loadSettings, saveSettings,
} from './multilingual';

const API = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';
const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || 'http://localhost:5000';

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
@keyframes micPulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.55); }
  50%     { box-shadow: 0 0 0 9px rgba(220,38,38,0); }
}
@keyframes speakerPulse {
  0%,100% { opacity: 0.55; }
  50%     { opacity: 1; }
}
.chat-fab      { animation: fabPulse 2.8s ease-in-out infinite; }
.chat-fab:hover{ animation: none !important; transform: scale(1.1) !important; }
.chat-panel    { animation: chatPop 0.28s cubic-bezier(0.34,1.56,0.64,1) both; }
.chat-msg      { animation: msgIn 0.22s ease both; }
.dot1 { animation: botTyping 1.2s 0.0s infinite; }
.dot2 { animation: botTyping 1.2s 0.2s infinite; }
.dot3 { animation: botTyping 1.2s 0.4s infinite; }
.mic-btn-listening { animation: micPulse 1.2s ease-in-out infinite; background: #dc2626 !important; }
.speaker-pill  { animation: speakerPulse 1.1s ease-in-out infinite; }
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
  complaints: 'Complaints Agent',
  schedule: 'Schedule Agent',
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
  const key = 'eco_chat_session_id';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

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
  const [sending, setSending] = useState(false); // text-send spinner only; independent of the voice FSM
  const [history, setHistory] = useState([
    { role: 'assistant', content: 'Hi! I\'m **EcoBot** 🌿\nI can help you with EcoTrack features — tracking, schedules, complaints, and more. What can I help you with?' }
  ]);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [voiceState, dispatch] = useReducer(voiceReducer, initialVoiceState);
  const [settings, setSettings] = useState(loadSettings); // { language, voiceURI, rate, pitch } — see multilingual.js
  const [showSettings, setShowSettings] = useState(false);
  const [voiceOptions, setVoiceOptions] = useState([]); // populated once speechSynthesis voices load, for the voice <select>

  useEffect(() => { saveSettings(settings); }, [settings]);

  const bottomRef        = useRef(null);
  const inputRef         = useRef(null);
  const panelRef         = useRef(null);
  const sessionIdRef     = useRef(getSessionId());

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
    form.append('speak', speakReplies ? 'true' : 'false');

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
    // mid-utterance, see multilingual.js's module comment.
    recognition.lang = getRecognitionLang(settings.language);
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
    if (!targetLang || targetLang === settings.language) return null;
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
      if (speakReplies && speechSynthesisSupported) {
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
      // replies.
      const { data } = await axios.post(`${API}/chat`, {
        message: buildLanguageDirective(settings.language, transcript, 'voice'),
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
      if (speakReplies && speechSynthesisSupported) {
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
  // tryHandleLanguageSwitch's caller in sendBrowserTranscript.
  const speakReplyBrowser = (text, langKeyOverride) => {
    const langKey = langKeyOverride || settings.language;
    const utterance = new SpeechSynthesisUtterance(stripForSpeech(text));
    // pickVoiceForLanguage: manual override (settings.voiceURI) if still
    // installed, else the best match for the current language, else a
    // graceful fallback chain — see multilingual.js.
    const voice = pickVoiceForLanguage(langKey, voiceOptions, settings.voiceURI);
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

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || sending) return;
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
        message: buildLanguageDirective(settings.language, msg, 'text'),
        history: historyForApi(),
        sessionId: sessionIdRef.current,
      });
      setHistory(h => [...h, { role: 'assistant', content: data.reply, agent: data.agent }]);
    } catch {
      setHistory(h => [...h, { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' }]);
    } finally {
      setSending(false);
    }
  };

  const renderContent = (text) => {
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
            {VOICE_MODE === 'browser' && (
              <button
                onClick={() => setShowSettings(s => !s)}
                title="Voice settings (language, voice, rate, pitch)"
                style={{
                  background: showSettings ? 'rgba(134,239,172,0.35)' : 'rgba(255,255,255,0.12)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff', width: 30, height: 30, borderRadius: '50%',
                  cursor: 'pointer', fontSize: 14, lineHeight: 1,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'background 0.15s', flexShrink: 0,
                }}
              >⚙️</button>
            )}
            <button
              onClick={() => setSpeakReplies(s => !s)}
              title={speakReplies ? 'Turn off spoken replies' : 'Turn on spoken replies'}
              style={{
                background: speakReplies ? 'rgba(134,239,172,0.35)' : 'rgba(255,255,255,0.12)',
                border: '1px solid rgba(255,255,255,0.2)',
                color: '#fff', width: 30, height: 30, borderRadius: '50%',
                cursor: 'pointer', fontSize: 14, lineHeight: 1,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'background 0.15s', flexShrink: 0,
              }}
            >{speakReplies ? '🔊' : '🔈'}</button>
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

          {/* Voice settings panel — language/voice/rate/pitch, persisted to localStorage */}
          {showSettings && VOICE_MODE === 'browser' && (
            <div style={{
              padding: '12px 16px', background: '#f0faf0', borderBottom: '1px solid #e8f5e8',
              display: 'flex', flexDirection: 'column', gap: 10,
            }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <label style={{ fontSize: 11.5, fontWeight: 700, color: '#1a5c1a', width: 62, flexShrink: 0 }}>Language</label>
                <select
                  value={settings.language}
                  onChange={e => setSettings(s => ({ ...s, language: e.target.value }))}
                  style={{ flex: 1, fontSize: 12.5, padding: '5px 8px', borderRadius: 8, border: '1.5px solid #c8e6c8' }}
                >
                  {Object.values(LANGUAGES).map(l => (
                    <option key={l.key} value={l.key}>{l.label}</option>
                  ))}
                </select>
              </div>

              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <label style={{ fontSize: 11.5, fontWeight: 700, color: '#1a5c1a', width: 62, flexShrink: 0 }}>Voice</label>
                <select
                  value={settings.voiceURI || ''}
                  onChange={e => setSettings(s => ({ ...s, voiceURI: e.target.value || null }))}
                  style={{ flex: 1, fontSize: 12.5, padding: '5px 8px', borderRadius: 8, border: '1.5px solid #c8e6c8' }}
                >
                  <option value="">Auto (best match for language)</option>
                  {/* Real installed voice names (e.g. "Google हिन्दी", "Microsoft Heera") — not generic labels. */}
                  {voiceOptions.map(v => (
                    <option key={v.voiceURI} value={v.voiceURI}>{v.name} ({v.lang})</option>
                  ))}
                </select>
              </div>

              {voiceFallbackNotice && (
                <div style={{ fontSize: 11, color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '6px 10px' }}>
                  ⚠️ {voiceFallbackNotice}
                </div>
              )}
            </div>
          )}

          {/* Voice conversation status bar — reads purely off the FSM state */}
          {voiceStatusLabel && (
            <div className={isBusy || isSpeakingNow ? 'speaker-pill' : ''} style={{
              padding: '6px 16px', fontSize: 11.5, fontWeight: 700,
              background: voiceState.current === VOICE_STATES.ERROR ? '#fef2f2' : '#f0faf0',
              color: voiceState.current === VOICE_STATES.ERROR ? '#991b1b' : '#1a5c1a',
              borderBottom: '1px solid #e8f5e8', display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span>{isListeningNow ? '🎙️' : isSpeakingNow ? '🔊' : voiceState.current === VOICE_STATES.ERROR ? '⚠️' : '⏳'}</span>
              {voiceStatusLabel}
            </div>
          )}

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
                  display: 'flex', flexDirection: 'column',
                  alignItems: isBot ? 'flex-start' : 'flex-end',
                }}>
                  <div style={{
                    display: 'flex', justifyContent: isBot ? 'flex-start' : 'flex-end',
                    gap: 8, alignItems: 'flex-end', width: '100%',
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
                  {isBot && msg.agent && AGENT_LABELS[msg.agent] && (
                    <div style={{ fontSize: 10.5, color: '#7a9b7a', margin: '3px 0 0 36px', fontWeight: 600 }}>
                      {AGENT_LABELS[msg.agent]}
                    </div>
                  )}
                </div>
              );
            })}

            {sending && (
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
              disabled={sending}
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
            {voiceSupported && (
              <button
                onClick={toggleConversation}
                title={isActive ? 'End conversation' : 'Start conversation'}
                className={isListeningNow ? 'mic-btn-listening' : ''}
                style={{
                  width: 38, height: 38, borderRadius: '50%', flexShrink: 0,
                  background: isActive ? '#dc2626' : '#e8f5e8',
                  border: 'none', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'background 0.2s',
                }}
              >
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                  <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" fill={isActive ? '#fff' : '#2d7a2d'} />
                  <path d="M3 7.5a5 5 0 0010 0" stroke={isActive ? '#fff' : '#2d7a2d'} strokeWidth="1.4" strokeLinecap="round" fill="none" />
                  <path d="M8 12.5v2" stroke={isActive ? '#fff' : '#2d7a2d'} strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              </button>
            )}
            <button
              onClick={() => send()}
              disabled={!input.trim() || sending}
              style={{
                width: 38, height: 38, borderRadius: '50%', flexShrink: 0,
                background: input.trim() && !sending
                  ? 'linear-gradient(135deg, #2d7a2d, #1a3a1a)'
                  : '#e8f5e8',
                border: 'none', cursor: input.trim() && !sending ? 'pointer' : 'default',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s', boxShadow: input.trim() && !sending ? '0 3px 10px rgba(26,58,26,0.3)' : 'none',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M14 8L2 2l3 6-3 6 12-6z"
                  fill={input.trim() && !sending ? '#86efac' : '#9aab9a'}
                  stroke={input.trim() && !sending ? '#86efac' : '#9aab9a'}
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
