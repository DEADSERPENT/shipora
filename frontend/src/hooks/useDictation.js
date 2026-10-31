import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { dictationError, hasRecorder, pickDictationEngine } from '../lib/speech';

const MAX_RECORD_MS = 30000;

// Speech -> text for the chat box. It only ever reports text through onText; it never sends anything. The person reviews and
// edits the text and presses Send themselves, so dictated messages go through the same chat endpoint, authorization and
// confirmation rules as typed ones.
//
//   engine 'browser': the browser's SpeechRecognition (live preview as you speak).
//   engine 'server' : record here, upload once to POST /api/voice/transcribe (Shipora's own speech-to-text), get text back.
//                     The recording lives in memory only until that upload; nothing is stored on either side.
export default function useDictation({ api, lang = 'en-IN', preference = 'auto', onText }) {
  const [state, setState] = useState('idle');          // idle | listening | processing | error
  const [error, setError] = useState('');
  const [engine, setEngine] = useState(null);
  const recRef = useRef(null);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const discardRef = useRef(false);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  const fail = useCallback((code, override) => {
    setError(override || dictationError(code).message);
    setState('error');
  }, []);

  const releaseStream = () => {
    clearTimeout(timerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  };

  const startServer = useCallback(async () => {
    setEngine('server');
    if (!hasRecorder()) { fail('unsupported'); return; }
    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      fail(err?.name || 'audio-capture');
      return;
    }
    let chunks = [];
    discardRef.current = false;
    const recorder = new window.MediaRecorder(streamRef.current);
    recorderRef.current = recorder;
    recorder.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      releaseStream();
      const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
      chunks = [];                                         // the recording is not kept: one upload, then it is gone
      if (discardRef.current || !blob.size) { setState('idle'); return; }
      setState('processing');
      try {
        const form = new FormData();
        form.append('audio', blob, 'dictation.webm');
        const { data } = await axios.post(`${api}/voice/transcribe`, form);
        onTextRef.current?.(data.text, true);
        setState('idle');
      } catch (err) {
        fail('transcribe-failed', err?.response?.data?.message);
      }
    };
    recorder.start();
    setState('listening');
    timerRef.current = setTimeout(() => recorder.state === 'recording' && recorder.stop(), MAX_RECORD_MS);
  }, [api, fail]);

  const startBrowser = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    setEngine('browser');
    const rec = new SR();
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let heard = false;
    rec.onresult = (e) => {
      heard = true;
      let text = '';
      let final = false;
      for (let i = 0; i < e.results.length; i++) { text += e.results[i][0].transcript; final = final || e.results[i].isFinal; }
      onTextRef.current?.(text.trim(), final);
    };
    rec.onerror = (e) => {
      if (e.error === 'aborted') return;
      const info = dictationError(e.error);
      recRef.current = null;
      if (info.fallback && preference !== 'browser-only' && hasRecorder()) { startServer(); return; }   // e.g. the speech service is unreachable
      fail(e.error);
    };
    rec.onend = () => {
      recRef.current = null;
      setState(s => (s === 'listening' ? 'idle' : s));
      if (!heard) setState(s => s);                          // 'no-speech' arrives through onerror
    };
    recRef.current = rec;
    try { rec.start(); setState('listening'); } catch { fail('unsupported'); }
  }, [lang, preference, startServer, fail]);

  const start = useCallback(() => {
    if (state === 'listening' || state === 'processing') return;
    setError('');
    const which = pickDictationEngine(preference);
    if (!which) { fail('unsupported'); return; }
    if (which === 'browser') startBrowser(); else startServer();
  }, [state, preference, startBrowser, startServer, fail]);

  const stop = useCallback(() => {
    if (recRef.current) { recRef.current.stop(); return; }
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
  }, []);

  const cancel = useCallback(() => {
    discardRef.current = true;
    recRef.current?.abort?.();
    recRef.current = null;
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop(); else releaseStream();
    setState('idle');
    setError('');
  }, []);

  useEffect(() => () => { discardRef.current = true; recRef.current?.abort?.(); releaseStream(); }, []);

  return { state, error, engine, listening: state === 'listening', processing: state === 'processing', start, stop, cancel };
}
