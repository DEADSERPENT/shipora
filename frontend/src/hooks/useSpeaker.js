import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { hasSpeechSynthesis, playbackError, stripForSpeech } from '../lib/speech';

// Read-aloud for one reply at a time. Browser speech synthesis when it exists, otherwise (or when the person prefers it)
// Shipora's own text-to-speech through POST /api/voice/speak. Nothing is stored; the audio is a throw-away blob URL.
export default function useSpeaker({ api, lang = 'en-IN', getVoice, preference = 'auto' }) {
  const [activeId, setActiveId] = useState(null);
  const [status, setStatus] = useState('idle');        // idle | loading | speaking | paused
  const [error, setError] = useState('');
  const audioRef = useRef(null);
  const urlRef = useRef(null);
  const tokenRef = useRef(0);                          // a newer request cancels an older one that is still loading

  const cleanup = () => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null; }
    if (hasSpeechSynthesis()) window.speechSynthesis.cancel();
  };

  const finish = useCallback((token) => {
    if (token !== tokenRef.current) return;
    setStatus('idle');
    setActiveId(null);
  }, []);

  const speakServer = useCallback(async (token, text) => {
    setStatus('loading');
    try {
      const { data } = await axios.post(`${api}/voice/speak`, { text }, { responseType: 'blob' });
      if (token !== tokenRef.current) return;
      urlRef.current = URL.createObjectURL(data);
      const audio = new Audio(urlRef.current);
      audioRef.current = audio;
      audio.onended = () => { cleanup(); finish(token); };
      audio.onerror = () => { cleanup(); setError(playbackError('unavailable')); finish(token); };
      await audio.play();
      if (token === tokenRef.current) setStatus('speaking');
    } catch (err) {
      if (token !== tokenRef.current) return;
      cleanup();
      setError(playbackError(err?.name === 'NotAllowedError' ? 'not-allowed' : 'unavailable'));
      finish(token);
    }
  }, [api, finish]);

  const speak = useCallback((id, text) => {
    tokenRef.current += 1;
    const token = tokenRef.current;
    cleanup();
    setError('');
    const clean = stripForSpeech(text).slice(0, 800);
    if (!clean) return;
    setActiveId(id);
    const useBrowser = preference !== 'server' && hasSpeechSynthesis();
    if (!useBrowser) {
      speakServer(token, clean);
      return;
    }
    const u = new window.SpeechSynthesisUtterance(clean);
    const voice = getVoice?.();
    if (voice) { u.voice = voice; u.lang = voice.lang; } else { u.lang = lang; }
    u.onstart = () => { if (token === tokenRef.current) setStatus('speaking'); };
    u.onend = () => finish(token);
    u.onerror = (e) => {
      if (token !== tokenRef.current) return;
      if (e.error === 'canceled' || e.error === 'interrupted') { finish(token); return; }
      speakServer(token, clean);                       // this browser's voice failed: try Shipora's own
    };
    setStatus('loading');
    window.speechSynthesis.speak(u);
  }, [preference, lang, getVoice, speakServer, finish]);

  const stop = useCallback(() => {
    tokenRef.current += 1;
    cleanup();
    setStatus('idle');
    setActiveId(null);
  }, []);

  const pause = useCallback(() => {
    if (audioRef.current) audioRef.current.pause(); else if (hasSpeechSynthesis()) window.speechSynthesis.pause();
    setStatus('paused');
  }, []);

  const resume = useCallback(() => {
    if (audioRef.current) audioRef.current.play(); else if (hasSpeechSynthesis()) window.speechSynthesis.resume();
    setStatus('speaking');
  }, []);

  useEffect(() => () => { tokenRef.current += 1; cleanup(); }, []);

  return { activeId, status, error, speak, stop, pause, resume, clearError: () => setError('') };
}
