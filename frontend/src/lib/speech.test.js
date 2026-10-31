import {
  dictationError, joinDictation, loadDictationPreference, loadSpeakReplies, pickDictationEngine, playbackError, saveDictationPreference,
  saveSpeakReplies, stripForSpeech,
} from './speech';

beforeEach(() => localStorage.clear());

test('spoken replies are off by default and only on when the person turned them on', () => {
  expect(loadSpeakReplies()).toBe(false);
  saveSpeakReplies(true);
  expect(loadSpeakReplies()).toBe(true);
  saveSpeakReplies(false);
  expect(loadSpeakReplies()).toBe(false);
});

test('dictation engine: browser when it can recognise speech, our server otherwise, none when neither works', () => {
  expect(pickDictationEngine('auto', { recognition: true, recorder: true })).toBe('browser');
  expect(pickDictationEngine('auto', { recognition: false, recorder: true })).toBe('server');
  expect(pickDictationEngine('auto', { recognition: false, recorder: false })).toBeNull();
  expect(pickDictationEngine('server', { recognition: true, recorder: true })).toBe('server');   // the private option is honoured
  expect(pickDictationEngine('server', { recognition: true, recorder: false })).toBeNull();
});

test('the dictation preference survives and only accepts known values', () => {
  expect(loadDictationPreference()).toBe('auto');
  saveDictationPreference('server');
  expect(loadDictationPreference()).toBe('server');
  localStorage.setItem('shipora_dictation_engine', 'garbage');
  expect(loadDictationPreference()).toBe('auto');
});

test('permission, no-microphone, silence and network errors each get a clear message', () => {
  expect(dictationError('not-allowed').message).toMatch(/blocked/i);
  expect(dictationError('NotAllowedError').message).toMatch(/blocked/i);
  expect(dictationError('audio-capture').message).toMatch(/no microphone/i);
  expect(dictationError('no-speech').message).toMatch(/didn't hear/i);
  expect(dictationError('unsupported').message).toMatch(/not supported|isn't supported/i);
  expect(dictationError('network').fallback).toBe(true);          // worth retrying through the server engine
  expect(dictationError('not-allowed').fallback).toBe(false);     // retrying cannot fix a blocked microphone
  expect(dictationError('something-new').message).toBeTruthy();
});

test('playback errors are explained', () => {
  expect(playbackError('unsupported')).toMatch(/aren't supported/);
  expect(playbackError('not-allowed')).toMatch(/blocked/i);
  expect(playbackError('unavailable')).toMatch(/aren't available/);
});

test('text is cleaned up for speaking', () => {
  expect(stripForSpeech('Your parcel **SHP123** is OUT_FOR_DELIVERY.\n• Pay by cash')).toBe('Your parcel SHP123 is out for delivery.. Pay by cash');
  expect(stripForSpeech('')).toBe('');
});

test('dictated text joins what was already typed', () => {
  expect(joinDictation('', 'where is my parcel')).toBe('where is my parcel');
  expect(joinDictation('Hi, ', 'where is my parcel')).toBe('Hi, where is my parcel');
  expect(joinDictation('Hi,', 'where is my parcel')).toBe('Hi, where is my parcel');
});
