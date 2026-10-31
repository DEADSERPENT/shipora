// Multilingual support for ShipBot's 'browser' voice mode (SpeechRecognition +
// speechSynthesis + the assistant via the existing /api/chat endpoint). NO backend
// changes anywhere — language steering happens entirely by prefixing the
// outgoing message text with a directive the assistant reads as part of the user's
// turn; see buildLanguageDirective(). general_agent.py's system prompt
// (already conversational/no-markdown) is untouched.
//
// Real platform constraint, stated plainly: browser SpeechRecognition can't
// dynamically auto-detect and switch its own recognition language
// mid-utterance — .lang must be set before .start() and stays fixed for
// that utterance. "Auto Detect" therefore captures with a broad-tolerance
// locale (en-IN) and lets the assistant — not the STT layer — do the actual
// language understanding/matching from whatever text comes back.

export const LANGUAGES = {
  en: {
    key: 'en',
    label: 'English',
    speechLang: 'en-IN',
    languageClause: 'English',
    switchConfirmation: "Okay, I'll continue in English.",
  },
  hi: {
    key: 'hi',
    label: 'Hindi',
    speechLang: 'hi-IN',
    languageClause: 'Hindi (Devanagari script), even if the user mixes in other languages',
    switchConfirmation: 'ठीक है, अब मैं हिंदी में बात करूँगा।',
  },
  kn: {
    key: 'kn',
    label: 'Kannada',
    speechLang: 'kn-IN',
    languageClause: 'Kannada (ಕನ್ನಡ script), even if the user mixes in other languages',
    switchConfirmation: 'ಸರಿ, ಈಗ ನಾನು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡುತ್ತೇನೆ.',
  },
  auto: {
    key: 'auto',
    label: 'Auto Detect',
    speechLang: 'en-IN', // capture locale only — SpeechRecognition can't truly auto-detect; see module comment
    languageClause: 'the same language or mix of languages the user just used (English, Hindi, Kannada, or a mix) — do not force a translation into a single language',
    switchConfirmation: "Okay, I'll auto-detect the language.",
  },
};

export const DEFAULT_LANGUAGE = 'auto';

// Fixed-language script enforcement — NOT applied to 'auto', which is
// explicitly supposed to mirror whatever mix/style the user used. Without
// this, the assistant tends to mirror the user's own writing style: if the user
// types Romanized Kannada/Hindi (e.g. "kasavin garden hege madodu"), it
// often replies in Romanized "Kanglish"/"Hinglish" instead of native script,
// even though the selected language's languageClause already names the
// script. This is a stronger, explicit override: the selected language wins
// over whatever script the user typed in, every time.
const SCRIPT_ENFORCEMENT = {
  hi: `The user may type or speak Hindi using Roman/English letters (e.g. "aap kaise ho") — treat that as normal input. Regardless of the script the user writes in, you must ALWAYS reply in proper Unicode Hindi script (Devanagari) — never in Romanized Hindi ("Hinglish"), and never mirror the user's Romanized writing style. Only keep English for unavoidable technical terms or proper nouns (app names, "OTP", etc). The selected language always overrides the script the user typed in.`,
  kn: `The user may type or speak Kannada using Roman/English letters (e.g. "kasavin garden hege madodu") — treat that as normal input. Regardless of the script the user writes in, you must ALWAYS reply in proper Unicode Kannada script (ಕನ್ನಡ) — never in Romanized Kannada ("Kanglish"), and never mirror the user's Romanized writing style. Only keep English for unavoidable technical terms or proper nouns (app names, "OTP", etc). The selected language always overrides the script the user typed in.`,
};

/** Recognition capture locale. Fixed languages use their own locale. 'auto'
 * tries navigator.language first — NOTE this reflects the browser/OS UI
 * language setting, not the user's spoken language, so it's a more standard
 * fallback signal, not real auto-detection (SpeechRecognition can't do
 * that — see module comment). Falls back to en-IN if navigator.language is
 * unavailable or clearly not a locale string. */
export function getRecognitionLang(langKey) {
  const lang = LANGUAGES[langKey] || LANGUAGES[DEFAULT_LANGUAGE];
  if (langKey !== 'auto') return lang.speechLang;
  if (typeof navigator !== 'undefined' && navigator.language && navigator.language.length >= 2) {
    return navigator.language;
  }
  return lang.speechLang;
}

// The "real-time voice conversation" framing and hard length cap only make
// sense when the user is actually listening, not reading — applying it to
// typed text chat would be both misleading to the assistant (it isn't a voice
// conversation) and an unwanted UX change for text users. mode='text' gets
// language steering + script enforcement + formatting rules only; mode='voice'
// additionally gets the short-spoken-reply framing.
const VOICE_ONLY_INSTRUCTION = `This is a real-time SPOKEN voice conversation — the user is listening, not reading.
Keep responses conversational and natural, like a helpful human assistant speaking out loud.
Keep replies to about 3-4 spoken sentences.
Avoid long explanations unless the user explicitly asks for more detail.
End naturally instead of reading a long block of text.`;

/** Prepends a language/formatting instruction block the assistant reads as part of
 * the user's turn — the mechanism for language steering AND (in 'voice'
 * mode) spoken-style tone, without any backend change (general_agent.py's
 * system prompt is untouched). The chat UI displays only the clean
 * `transcript`; this wrapped form is only ever sent over the wire.
 * `mode`: 'voice' (browser voice conversation) or 'text' (typed chat) —
 * text chat never gets the spoken-length constraint. */
export function buildLanguageDirective(langKey, transcript, mode = 'voice') {
  const lang = LANGUAGES[langKey] || LANGUAGES[DEFAULT_LANGUAGE];
  let instruction = `Reply naturally in ${lang.languageClause}.
Do not use markdown.
Do not use bullet points.
Do not use numbered lists.
Avoid repeating the user's question.
Avoid sounding like documentation.`;
  if (mode === 'voice') {
    instruction += `\n${VOICE_ONLY_INSTRUCTION}`;
  }
  if (SCRIPT_ENFORCEMENT[langKey]) {
    instruction += `\n\n${SCRIPT_ENFORCEMENT[langKey]}`;
  }
  return `${instruction}\n\nUser's message: ${transcript}`;
}

// ── In-conversation language-switch commands ────────────────────────────
// Requires BOTH a trigger word/phrase AND a language name in the same
// utterance, to avoid false positives on sentences that merely mention a
// language in passing (e.g. "I studied Hindi in school"). Native-script
// language names are included since switch requests can themselves be
// spoken in Hindi/Kannada, per the spec's own examples.
// Includes Latin AND native-script transliterations of the same loanwords,
// since SpeechRecognition transcribes into whatever script its active `.lang`
// uses — e.g. with recognition.lang='hi-IN', a spoken English "Switch to
// English" is very often transcribed as "स्विच टू इंग्लिश", not the Latin
// word "switch". Missing the Devanagari/Kannada transliteration of "switch"
// itself (not just of the language name) was the root cause of switch
// commands silently falling through to the assistant.
const SWITCH_TRIGGER_WORDS = [
  'switch', 'continue', 'speak', 'talk', 'change to',
  'स्विच', 'बात', 'बदल', 'कंटिन्यू', // Hindi: "switch", "talk"/"speak", "change", "continue"
  'ಸ್ವಿಚ್', 'ಮಾತಾಡ', 'ಮಾತನಾಡ', 'ಬದಲಾ', // Kannada: "switch", "talk"/"speak" (two verb forms), "change"
];
const LANGUAGE_NAME_HINTS = {
  // 'अंग्रेज़ी'/'अंग्रेजी' are the same word (nukta vs. no-nukta spelling of
  // "English") — both spellings occur in the wild, confirmed directly from
  // the assistant's own reply text ("...अब अंग्रेज़ी में...") which the previous
  // hint list didn't cover at all.
  en: ['english', 'इंग्लिश', 'अंग्रेज़ी', 'अंग्रेजी', 'ಇಂಗ್ಲಿಷ್'],
  hi: ['hindi', 'हिंदी', 'हिन्दी', 'ಹಿಂದಿ'],
  kn: ['kannada', 'कन्नड़', 'कन्नड', 'ಕನ್ನಡ'],
};

// A bare-or-near-bare language name ("English", "Kannada please") is treated
// as an implicit switch command even without a trigger word — at this token
// count a language name is essentially never an incidental mention (compare
// "I studied Hindi in school", which is well above this length).
const SHORT_UTTERANCE_MAX_WORDS = 3;

// Plain .includes() would let 'speak' match inside 'speaking', turning e.g.
// "what's the weather in hindi speaking regions" into a false-positive
// switch command, so Latin-script hints get a word-boundary check via
// \p{L}/\p{N} lookarounds (script-agnostic, unlike \b which only understands
// ASCII word chars). Devanagari/Kannada hints deliberately stay plain
// substring matches instead: both are agglutinative scripts where case
// suffixes attach directly with no space (e.g. "ಕನ್ನಡಕ್ಕೆ" = "ಕನ್ನಡ" + "ಕ್ಕೆ"
// dative suffix, "to Kannada") — a word-boundary check would reject exactly
// the inflected forms real speech naturally produces.
const ASCII_ONLY = /^[\x20-\x7e]+$/; // printable ASCII only — hint words are letters/spaces, never control chars
function containsWord(haystack, word) {
  if (!ASCII_ONLY.test(word)) return haystack.includes(word);
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?<![\\p{L}\\p{N}])${escaped}(?![\\p{L}\\p{N}])`, 'u').test(haystack);
}

/** Returns the target language key ('en'|'hi'|'kn') if `transcript` is a
 * language-switch command, else null. Deliberately conservative (trigger +
 * language name both required, except for very short utterances) — false
 * negatives just mean the turn goes to the assistant as a normal message, which is
 * the safe failure mode. */
export function detectLanguageSwitchCommand(transcript) {
  const lower = (transcript || '').toLowerCase();
  const trimmed = lower.trim();
  if (!trimmed) return null;
  const wordCount = trimmed.split(/\s+/).length;
  for (const [langKey, hints] of Object.entries(LANGUAGE_NAME_HINTS)) {
    const mentionsLanguage = hints.some(hint => containsWord(lower, hint.toLowerCase()));
    if (!mentionsLanguage) continue;
    if (wordCount <= SHORT_UTTERANCE_MAX_WORDS) return langKey;
    const hasTrigger = SWITCH_TRIGGER_WORDS.some(word => containsWord(lower, word.toLowerCase()));
    if (hasTrigger) return langKey;
  }
  return null;
}

// ── Voice selection ──────────────────────────────────────────────────────
// Extends the existing female-voice-name heuristic (SpeechSynthesisVoice has
// no gender field) with a per-language lang-prefix filter and a graceful
// fallback chain — Kannada (and often Hindi) voices are frequently just not
// installed on a given system, which is a real environment fact, not
// something this code can paper over.
const FEMALE_VOICE_HINTS = [
  'female', 'zira', 'hazel', 'susan', 'samantha', 'victoria', 'karen', 'moira',
  'tessa', 'fiona', 'joanna', 'kendra', 'kimberly', 'salli', 'ivy', 'nova',
  'shimmer', 'veena', 'heera', 'aria', 'jenny', 'libby', 'maisie', 'sonia',
  'swara', 'kalpana', // common Hindi female voice names (Windows/Edge)
];

function byLangPrefix(voices, prefix) {
  return voices.filter(v => v.lang && v.lang.toLowerCase().startsWith(prefix));
}

function preferFemale(voices) {
  if (!voices.length) return null;
  return voices.find(v => FEMALE_VOICE_HINTS.some(hint => v.name.toLowerCase().includes(hint))) || voices[0];
}

/** Resolves the voice to use: an explicit manual override if still present,
 * else the best automatic match for `langKey`, else a graceful fallback
 * chain (same-language -> Kannada-only: Hindi -> any Indian-locale voice ->
 * English -> whatever's first). Never returns undefined; returns null only
 * if the system has zero voices installed at all. */
export function pickVoiceForLanguage(langKey, voices, preferredVoiceURI) {
  if (!voices || !voices.length) return null;

  if (preferredVoiceURI) {
    const manual = voices.find(v => v.voiceURI === preferredVoiceURI);
    if (manual) return manual;
  }

  const lang = LANGUAGES[langKey] || LANGUAGES[DEFAULT_LANGUAGE];
  const prefix = lang.speechLang.split('-')[0]; // e.g. 'kn' from 'kn-IN'
  const exact = byLangPrefix(voices, prefix);
  if (exact.length) return preferFemale(exact);

  if (langKey === 'kn') {
    const hi = byLangPrefix(voices, 'hi');
    if (hi.length) return preferFemale(hi);
  }
  const indian = voices.filter(v => v.lang && v.lang.toLowerCase().endsWith('-in'));
  if (indian.length) return preferFemale(indian);

  const en = byLangPrefix(voices, 'en');
  if (en.length) return preferFemale(en);

  return preferFemale(voices);
}

/** True if at least one installed voice actually matches langKey's locale —
 * i.e. pickVoiceForLanguage would return a real native match, not a
 * fallback. Used to show an honest "using the closest available voice"
 * notice instead of silently substituting one (Kannada voices in particular
 * are frequently just not installed on a given system). Not meaningful for
 * 'auto' (no single target language), so callers should skip the check then. */
export function hasNativeVoice(langKey, voices) {
  if (!voices || !voices.length) return false;
  const lang = LANGUAGES[langKey] || LANGUAGES[DEFAULT_LANGUAGE];
  const prefix = lang.speechLang.split('-')[0];
  return byLangPrefix(voices, prefix).length > 0;
}

// ── Internal per-turn language metadata (script-based heuristic) ────────
// Tracked only for internal state / future extensibility, per requirement —
// never sent to the backend, never shown in the UI, no analytics involved.
// This detects SCRIPT, not language: romanized/transliterated Hindi or
// Kannada written in Latin characters (e.g. "complaint register karna hai")
// reads as English here, since there's no non-Latin script to detect. An
// honest limitation of a lightweight client-side heuristic, not hidden.
const DEVANAGARI_RE = /[ऀ-ॿ]/; // Hindi
const KANNADA_RE = /[ಀ-೿]/;

export function detectScriptLanguage(text) {
  const hasDevanagari = DEVANAGARI_RE.test(text);
  const hasKannada = KANNADA_RE.test(text);
  const hasLatin = /[a-zA-Z]/.test(text);
  const scriptsPresent = [hasDevanagari, hasKannada, hasLatin].filter(Boolean).length;
  if (scriptsPresent > 1) return 'Mixed';
  if (hasDevanagari) return 'Hindi';
  if (hasKannada) return 'Kannada';
  return 'English';
}

// ── Settings persistence (language, voice) ───────────────────────────────
// Rate/pitch controls were removed from the UI — old persisted settings
// objects may still have those keys from before, but loadSettings() only
// ever reads language/voiceURI back out, so they're harmlessly ignored.
const SETTINGS_KEY = 'shipora_voice_settings';
const DEFAULT_SETTINGS = { language: DEFAULT_LANGUAGE, voiceURI: null };

export function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // localStorage unavailable (private browsing, quota) — settings just won't persist this session
  }
}
