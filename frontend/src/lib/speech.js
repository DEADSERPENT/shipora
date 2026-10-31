// Shared helpers for chat dictation (speech -> text in the input box) and read-aloud (reply -> speech).
// Capability checks are functions, not constants, so they reflect the browser at call time and can be tested.

export const hasSpeechRecognition = () => typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
export const hasRecorder = () => typeof window !== 'undefined' && !!window.MediaRecorder && !!navigator.mediaDevices?.getUserMedia;
export const hasSpeechSynthesis = () => typeof window !== 'undefined' && 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance !== 'undefined';

// Which way a mic press will capture speech. 'browser' = the browser's speech service (fast; the browser vendor may process
// the audio). 'server' = record here, transcribe with Shipora's own speech-to-text (audio goes to our server only, is not stored).
export function pickDictationEngine(preference = 'auto', caps = { recognition: hasSpeechRecognition(), recorder: hasRecorder() }) {
  if (preference === 'server') return caps.recorder ? 'server' : null;
  if (caps.recognition) return 'browser';
  return caps.recorder ? 'server' : null;
}

export const DICTATION_KEY = 'shipora_dictation_engine';
export const PLAYBACK_KEY = 'shipora_speak_replies';

const read = (k, fallback) => { try { return localStorage.getItem(k) ?? fallback; } catch { return fallback; } };
const write = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode: the setting just won't persist */ } };

// Spoken replies are OFF unless the person has switched them on.
export const loadSpeakReplies = () => read(PLAYBACK_KEY, 'false') === 'true';
export const saveSpeakReplies = (on) => write(PLAYBACK_KEY, on ? 'true' : 'false');
export const loadDictationPreference = () => (read(DICTATION_KEY, 'auto') === 'server' ? 'server' : 'auto');
export const saveDictationPreference = (v) => write(DICTATION_KEY, v === 'server' ? 'server' : 'auto');

// Reply text -> something that sounds right when spoken: no markdown, bullets or raw status codes.
export function stripForSpeech(text = '') {
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\b([A-Z]{2,}(?:_[A-Z]+)+)\b/g, (m) => m.toLowerCase().replace(/_/g, ' '))
    .replace(/^[\s]*[•*-]\s+/gm, '')
    .replace(/\n+/g, '. ')
    .replace(/[•·]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

// Recognition / recording error -> what the person should read, and whether trying the server engine could help.
export function dictationError(code) {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
    case 'NotAllowedError':
      return { message: 'Microphone access is blocked. Allow the microphone for this site in your browser settings, then try again.', fallback: false };
    case 'audio-capture':
    case 'NotFoundError':
      return { message: 'No microphone was found. Connect one, or type your message instead.', fallback: false };
    case 'no-speech':
      return { message: "I didn't hear anything. Tap the microphone and try again.", fallback: false };
    case 'network':
      return { message: "The browser's speech service couldn't be reached.", fallback: true };
    case 'language-not-supported':
      return { message: "That language isn't supported for dictation in this browser.", fallback: true };
    case 'unsupported':
      return { message: "Voice input isn't supported in this browser. You can type instead.", fallback: false };
    case 'transcribe-failed':
      return { message: "I couldn't turn that recording into text. Try again, or type your message.", fallback: false };
    default:
      return { message: 'Voice input stopped unexpectedly. Please try again, or type your message.', fallback: false };
  }
}

export function playbackError(code) {
  switch (code) {
    case 'unsupported': return "Spoken replies aren't supported in this browser.";
    case 'not-allowed': return 'The browser blocked audio playback. Tap the speaker again to allow it.';
    case 'unavailable': return "Spoken replies aren't available right now.";
    default: return "Couldn't play that reply aloud.";
  }
}

// Join what was already in the box with what was just dictated, without doubled spaces.
export const joinDictation = (prefix, spoken) => `${prefix}${prefix && spoken && !/\s$/.test(prefix) ? ' ' : ''}${spoken}`.trimStart();
