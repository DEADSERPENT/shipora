// Formal finite state machine for the EcoBot voice conversation, replacing
// separate isListening/isSpeaking/isThinking/isRecording/isProcessing
// booleans. Booleans grow combinatorially and can represent impossible
// states (e.g. isListening && isSpeaking both true); a single enum with an
// explicit transition table makes impossible states unrepresentable and
// gives one place (STATE_UI) that decides what the UI shows.
//
// TRANSCRIBING/THINKING/TOOL_EXECUTION/GENERATING_RESPONSE are driven by
// real backend "voice:stage" Socket.IO events (see sockets.py /
// voice/pipeline.py), not client-side guessed timing — see
// docs/VOICE_ARCHITECTURE.md.

export const VOICE_STATES = {
  IDLE: 'IDLE',
  LISTENING: 'LISTENING',
  TRANSCRIBING: 'TRANSCRIBING',
  THINKING: 'THINKING',
  TOOL_EXECUTION: 'TOOL_EXECUTION',
  GENERATING_RESPONSE: 'GENERATING_RESPONSE',
  SPEAKING: 'SPEAKING',
  WAITING_FOR_NEXT_INPUT: 'WAITING_FOR_NEXT_INPUT',
  ERROR: 'ERROR',
  END: 'END',
};

// from-state -> allowed "normal" to-states (the happy-path transitions).
// ERROR and END are deliberately NOT listed per-state here: per the spec
// ("At any point -> ERROR", "From any state -> END") they're universal
// escape hatches, enforced separately in voiceReducer below rather than
// duplicated into every row of this table. This table is the single
// source of truth for the happy-path transitions; docs/VOICE_ARCHITECTURE.md's
// transition table mirrors it exactly so the two can't silently drift apart.
export const TRANSITIONS = {
  [VOICE_STATES.IDLE]: [VOICE_STATES.LISTENING],
  [VOICE_STATES.LISTENING]: [VOICE_STATES.TRANSCRIBING],
  [VOICE_STATES.TRANSCRIBING]: [VOICE_STATES.THINKING],
  [VOICE_STATES.THINKING]: [VOICE_STATES.TOOL_EXECUTION, VOICE_STATES.GENERATING_RESPONSE],
  [VOICE_STATES.TOOL_EXECUTION]: [VOICE_STATES.GENERATING_RESPONSE],
  // WAITING_FOR_NEXT_INPUT is reachable directly (skipping SPEAKING) when
  // the "speak replies" toggle is off, so no TTS audio was requested.
  // LISTENING is also reachable directly (skipping SPEAKING): speakReplyBrowser
  // only dispatches SPEAKING from inside utterance.onstart, which fires
  // asynchronously — a button-press or barge-in interrupt can land in the
  // brief GENERATING_RESPONSE window before that callback fires (most
  // noticeable on short utterances, e.g. local language-switch confirmations,
  // where that window is a large fraction of the total reply). Without this,
  // interruptSpeech()'s LISTENING dispatch was silently rejected by this
  // table and the FSM got stuck in GENERATING_RESPONSE. 'browser' voice mode
  // only, see ChatBot.js's interruptSpeech()/toggleConversation().
  [VOICE_STATES.GENERATING_RESPONSE]: [VOICE_STATES.SPEAKING, VOICE_STATES.WAITING_FOR_NEXT_INPUT, VOICE_STATES.LISTENING],
  // LISTENING is barge-in: the user interrupted playback (button press or
  // starting to talk) — 'browser' voice mode only, see ChatBot.js's
  // interruptSpeech(). Server voice mode never dispatches this transition.
  [VOICE_STATES.SPEAKING]: [VOICE_STATES.WAITING_FOR_NEXT_INPUT, VOICE_STATES.LISTENING],
  [VOICE_STATES.WAITING_FOR_NEXT_INPUT]: [VOICE_STATES.LISTENING],
  [VOICE_STATES.ERROR]: [VOICE_STATES.LISTENING],
  [VOICE_STATES.END]: [],
};

// Human-readable phrase shown during TOOL_EXECUTION, keyed by the real tool
// name the backend reports via voice:stage — grounded in what's actually
// running, not a guess.
export const TOOL_LABELS = {
  get_vehicle_status: 'Checking vehicle location…',
  get_complaint_status: 'Checking complaint status…',
  create_complaint: 'Filing your complaint…',
  get_collection_schedule: 'Checking your schedule…',
  get_support_info: 'Looking up support info…',
  search_knowledge_base: 'Searching knowledge base…',
};

export const STATE_UI = {
  [VOICE_STATES.IDLE]: { label: 'Press Start to talk', indicator: 'idle' },
  [VOICE_STATES.LISTENING]: { label: 'Listening…', indicator: 'mic' },
  [VOICE_STATES.TRANSCRIBING]: { label: 'Transcribing…', indicator: 'thinking' },
  [VOICE_STATES.THINKING]: { label: 'Thinking…', indicator: 'thinking' },
  [VOICE_STATES.TOOL_EXECUTION]: { label: null, indicator: 'thinking' }, // resolved via labelFor()
  [VOICE_STATES.GENERATING_RESPONSE]: { label: 'Generating response…', indicator: 'thinking' },
  [VOICE_STATES.SPEAKING]: { label: 'Speaking…', indicator: 'speaker' },
  [VOICE_STATES.WAITING_FOR_NEXT_INPUT]: { label: 'One moment…', indicator: 'thinking' },
  [VOICE_STATES.ERROR]: { label: null, indicator: 'error' }, // label supplied by the error message itself
  [VOICE_STATES.END]: { label: 'Conversation ended', indicator: 'idle' },
};

/** Resolves the label to display for a given state, using `detail` (a tool
 * name, or an error message) where the state alone isn't enough. */
export function labelFor(state, detail) {
  if (state === VOICE_STATES.TOOL_EXECUTION) return TOOL_LABELS[detail] || 'Checking…';
  if (state === VOICE_STATES.ERROR) return detail || 'Something went wrong.';
  return STATE_UI[state]?.label || '';
}

/** action = { type: <VOICE_STATES value> | 'RESET' | 'FORCE', detail?: string, target?: string }
 * RESET force-sets IDLE regardless of current state (used when starting a
 * fresh conversation). FORCE force-sets `action.target` regardless of
 * current state — used exactly once in ChatBot.js, when the HTTP response
 * for a voice turn arrives: that's stronger ground truth than any
 * intermediate voice:stage socket event (which can be delayed or dropped,
 * and never fires at all on the zero-API-key fallback path), so jumping
 * straight to GENERATING_RESPONSE at that point is correct regardless of
 * which stage events did or didn't arrive first. Both RESET and FORCE are
 * meta-operations, not domain transitions, so they deliberately bypass
 * TRANSITIONS. ERROR and END are always allowed regardless of current
 * state (see the TRANSITIONS comment above); every other target must be
 * listed in TRANSITIONS[state.current]. */
export function voiceReducer(state, action) {
  if (action.type === 'RESET') {
    return { current: VOICE_STATES.IDLE, detail: null };
  }
  if (action.type === 'FORCE') {
    return { current: action.target, detail: action.detail ?? null };
  }
  const target = action.type;
  if (target === VOICE_STATES.ERROR || target === VOICE_STATES.END) {
    return { current: target, detail: action.detail ?? null };
  }
  const allowed = TRANSITIONS[state.current] || [];
  if (!allowed.includes(target)) {
    // eslint-disable-next-line no-console
    console.warn(`[voiceConversationMachine] invalid transition ${state.current} -> ${target}, ignoring`);
    return state;
  }
  return { current: target, detail: action.detail ?? null };
}

export const initialVoiceState = { current: VOICE_STATES.IDLE, detail: null };
