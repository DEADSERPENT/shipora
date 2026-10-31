import { act, renderHook, waitFor } from '@testing-library/react';

// Plain functions, not jest.fn: CRA's Jest config has resetMocks on, which would wipe jest.fn implementations between tests.
const mockPosts = [];
let mockPostImpl = async () => ({ data: {} });
jest.mock('axios', () => ({ __esModule: true, default: { post: (...a) => { mockPosts.push(a); return mockPostImpl(...a); } } }));

// eslint-disable-next-line import/first
import useDictation from './useDictation';
// eslint-disable-next-line import/first
import useSpeaker from './useSpeaker';

let recognizers;
class FakeRecognition {
  constructor() { this.started = false; recognizers.push(this); }
  start() { this.started = true; }
  stop() { this.started = false; this.onend?.(); }
  abort() { this.aborted = true; this.started = false; }
  say(text, isFinal) { this.onresult({ results: [Object.assign([{ transcript: text }], { isFinal })] }); }
}

beforeEach(() => {
  recognizers = [];
  mockPosts.length = 0;
  mockPostImpl = async () => ({ data: {} });
  localStorage.clear();
  delete window.SpeechRecognition; delete window.webkitSpeechRecognition; delete window.MediaRecorder;
  delete window.speechSynthesis; delete window.SpeechSynthesisUtterance;
  Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true });
});

// ── dictation ───────────────────────────────────────────────────────────────
test('browser dictation reports live text for review and never sends anything', () => {
  window.SpeechRecognition = FakeRecognition;
  const heard = [];
  const { result } = renderHook(() => useDictation({ api: '/api', onText: (t, final) => heard.push([t, final]) }));
  act(() => result.current.start());
  expect(result.current.state).toBe('listening');
  act(() => recognizers[0].say('where is my', false));
  act(() => recognizers[0].say('where is my parcel', true));
  expect(heard).toEqual([['where is my', false], ['where is my parcel', true]]);
  act(() => result.current.stop());
  expect(result.current.state).toBe('idle');
  expect(mockPosts).toHaveLength(0);                                 // dictation never calls the chat endpoint or any other
});

test('a blocked microphone is explained, not swallowed', () => {
  window.SpeechRecognition = FakeRecognition;
  const { result } = renderHook(() => useDictation({ api: '/api', onText: () => {} }));
  act(() => result.current.start());
  act(() => recognizers[0].onerror({ error: 'not-allowed' }));
  expect(result.current.state).toBe('error');
  expect(result.current.error).toMatch(/blocked/i);
});

test('no speech support and no recorder: a clear unsupported message', () => {
  const { result } = renderHook(() => useDictation({ api: '/api', onText: () => {} }));
  act(() => result.current.start());
  expect(result.current.state).toBe('error');
  expect(result.current.error).toMatch(/isn't supported/i);
});

function installRecorder(blobSize = 3) {
  const stopped = [];
  const track = { stop: () => stopped.push(1) };
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [track] }) } });
  window.MediaRecorder = class {
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({ data: { size: blobSize } }); this.onstop(); }
  };
  return stopped;
}

test('server dictation uploads once, returns text for review, releases the microphone and keeps no audio', async () => {
  const stopped = installRecorder();
  mockPostImpl = async () => ({ data: { text: 'file a complaint' } });
  const heard = [];
  const { result } = renderHook(() => useDictation({ api: '/api', onText: (t, f) => heard.push([t, f]) }));
  await act(async () => { await result.current.start(); });
  await waitFor(() => expect(result.current.state).toBe('listening'));
  await act(async () => { result.current.stop(); });
  await waitFor(() => expect(result.current.state).toBe('idle'));
  expect(mockPosts).toHaveLength(1);
  expect(mockPosts[0][0]).toBe('/api/voice/transcribe');             // transcribe only: not /chat, so nothing is sent to the assistant
  expect(heard).toEqual([['file a complaint', true]]);
  expect(stopped.length).toBeGreaterThan(0);                     // the microphone is released
});

test("the browser's speech service being unreachable falls back to the server engine", async () => {
  window.SpeechRecognition = FakeRecognition;
  installRecorder();
  const { result } = renderHook(() => useDictation({ api: '/api', onText: () => {} }));
  act(() => result.current.start());
  await act(async () => { recognizers[0].onerror({ error: 'network' }); });
  await waitFor(() => expect(result.current.engine).toBe('server'));
  expect(result.current.state).toBe('listening');
});

test('cancelling dictation discards the recording without uploading it', async () => {
  installRecorder();
  const { result } = renderHook(() => useDictation({ api: '/api', onText: () => {} }));
  await act(async () => { await result.current.start(); });
  await waitFor(() => expect(result.current.state).toBe('listening'));
  await act(async () => { result.current.cancel(); });
  expect(result.current.state).toBe('idle');
  expect(mockPosts).toHaveLength(0);
});

test('the server refusing a recording shows the server message', async () => {
  installRecorder();
  mockPostImpl = async () => { const e = new Error('x'); e.response = { data: { message: "I couldn't make out any speech." } }; throw e; };
  const { result } = renderHook(() => useDictation({ api: '/api', onText: () => {} }));
  await act(async () => { await result.current.start(); });
  await waitFor(() => expect(result.current.state).toBe('listening'));
  await act(async () => { result.current.stop(); });
  await waitFor(() => expect(result.current.state).toBe('error'));
  expect(result.current.error).toMatch(/couldn't make out/i);
});

// ── playback ────────────────────────────────────────────────────────────────
function installSynthesis() {
  const spoken = [];
  window.SpeechSynthesisUtterance = function (text) { this.text = text; };
  window.speechSynthesis = { speak: (u) => { spoken.push(u); }, cancel: () => { spoken.cancelled = (spoken.cancelled || 0) + 1; }, pause: () => {}, resume: () => {} };
  return spoken;
}

test('a reply is spoken only when asked, cleaned of markdown, and can be stopped', () => {
  const spoken = installSynthesis();
  const { result } = renderHook(() => useSpeaker({ api: '/api' }));
  expect(spoken).toHaveLength(0);                                // nothing plays on its own
  act(() => result.current.speak('m1', 'Your parcel **SHP123** is OUT_FOR_DELIVERY.'));
  expect(spoken[0].text).toBe('Your parcel SHP123 is out for delivery.');
  act(() => spoken[0].onstart());
  expect(result.current.status).toBe('speaking');
  expect(result.current.activeId).toBe('m1');
  act(() => result.current.stop());
  expect(result.current.status).toBe('idle');
  expect(spoken.cancelled).toBeGreaterThan(0);
});

test('replaying starts again from the beginning and a newer reply replaces an older one', () => {
  const spoken = installSynthesis();
  const { result } = renderHook(() => useSpeaker({ api: '/api' }));
  act(() => result.current.speak('m1', 'First reply.'));
  act(() => result.current.speak('m1', 'First reply.'));
  act(() => result.current.speak('m2', 'Second reply.'));
  expect(spoken.map(u => u.text)).toEqual(['First reply.', 'First reply.', 'Second reply.']);
  expect(result.current.activeId).toBe('m2');
});

test('with no browser voice the server voice is used, and an unavailable one is reported', async () => {
  mockPostImpl = async () => { const e = new Error('x'); e.response = { status: 503 }; throw e; };
  const { result } = renderHook(() => useSpeaker({ api: '/api' }));
  await act(async () => { result.current.speak('m1', 'Hello there'); });
  await waitFor(() => expect(result.current.error).toMatch(/aren't available/i));
  expect(mockPosts[0][0]).toBe('/api/voice/speak');
  expect(mockPosts[0][1]).toEqual({ text: 'Hello there' });
  expect(result.current.status).toBe('idle');
});

test("the person's choice of the server voice is honoured even when the browser has one", async () => {
  installSynthesis();
  mockPostImpl = async () => { throw new Error('x'); };
  const { result } = renderHook(() => useSpeaker({ api: '/api', preference: 'server' }));
  await act(async () => { result.current.speak('m1', 'Hello'); });
  await waitFor(() => expect(mockPosts).toHaveLength(1));
});
