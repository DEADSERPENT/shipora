# EcoBot Voice-AI Architecture

EcoBot is EcoTrack's in-app assistant. It's a **Speech-to-Text → Multi-Agent LLM
→ Text-to-Speech "sandwich"** — three independent, swappable stages connected by
plain text, not an end-to-end speech-to-speech model. This document describes
that pipeline, how it's looped into a continuous conversation, and maps each of
six voice-AI architecture concepts onto the code that implements it.

## Why a sandwich, not an end-to-end model

Each stage (STT, the multi-agent LLM layer, TTS) is a separate API call with
text as the interface between them. That's a deliberate choice, not a
limitation: it lets each stage be inspected, logged, swapped, and unit-tested
independently — you can see the exact transcript STT produced, the exact
agent that handled it, and the exact text TTS spoke, at every turn. An
end-to-end speech-to-speech model would collapse all of that into one opaque
call. This document — and the whole `tools/`-backed, analytics-logged design
below — depends on that separability.

## Pipeline (single turn)

```
Mic (browser)
  │  MediaRecorder captures audio/webm (or audio/mp4 on Safari)
  ▼
POST /api/voice/chat  (frontend/src/components/ChatBot.js)
  │  multipart: audio blob + sessionId + speak flag
  ▼
voice/pipeline.py: run_voice_turn()
  │
  ├─▶ services/stt.py — OpenAI Whisper           [emits voice:stage "transcribing"]
  │     audio bytes -> transcript text
  │
  ├─▶ memory/conversation_memory.py.get_history(sessionId)   (MongoDB, see below)
  │
  ├─▶ agents/orchestrator.py: route_and_reply()   [emits voice:stage "thinking"]
  │     ONE Gemini forced-function-call, returns {agent, sentiment}
  │     falls back to keyword matching if GEMINI_API_KEY is unset
  │         │
  │         ▼
  │   ┌───────────────┬──────────────────┬────────────────┬────────────────┬───────────┐
  │   ▼               ▼                  ▼                ▼                ▼
  │ tracking_agent  complaints_agent  schedule_agent   support_agent    general_agent
  │ (tools/          (tools/           (tools/          (tools/          (tier 0: tools/
  │  tracking_       complaint_        schedule_        support_          knowledge_base_
  │  tools.py)        tools.py)         tools.py)        tools.py)         tools.py;
  │                                                                        tier 1: services/
  │                                                                        llm.py; tier 2:
  │                                                                        rule_based_reply)
  │   [tool-calling agents emit voice:stage "tool_execution" then "generating_response"]
  │         │               │                  │                │                │
  │         └───────────────┴──────────────────┴────────────────┴────────────────┘
  │                              │  (any specialist returning None falls through to
  │                              │   general_agent, logged honestly as agent="general")
  │                              ▼
  │                         reply text
  │
  ├─▶ memory/conversation_memory.py.append_turn() × 2  (user turn, assistant turn)
  │
  ├─▶ services/tts.py — OpenAI TTS  (skipped if speak=false)
  │     text -> MP3 bytes
  │
  └─▶ ChatAnalytics write (sidecar, non-blocking — voice/pipeline.py's
        log_analytics(), swallows errors so a logging failure never breaks
        the user's reply)
        │
        ▼
   base64 audio + reply JSON
        │
        ▼
   <audio> playback (browser) — see the Conversation State Machine section
   for how this fits into the continuous loop, not just one turn
```

## The six concepts, mapped to code

| Concept | Where it lives | Design note |
|---|---|---|
| **Architecture of Voice Agents** | This document + `agents/orchestrator.py` + `voice/pipeline.py` | Router-classifies-then-dispatches: one cheap classification call picks a specialist, each specialist gets a scoped prompt + real tool(s) from `tools/`, with a shared 3-tier fallback (`general_agent`) so nothing ever produces a dead end. `voice/pipeline.py` is the one place the STT→memory→orchestrator→TTS sequence is assembled; `routes/chat.py`/`routes/voice.py` are thin HTTP wrappers around it. |
| **STT Models** | `services/stt.py` | **Only OpenAI Whisper (`whisper-1`) is implemented.** Structured as an `STTProvider` abstract base class with one concrete `OpenAIWhisperProvider` — adding a second provider (e.g. Deepgram) means writing one new class and adding it to `_PROVIDERS`, without touching `transcribe_audio()` or any caller. Do not read "provider interface" as "multiple providers already work." |
| **TTS Models** | `services/tts.py` | **Only OpenAI TTS (`tts-1`) is implemented**, same `TTSProvider` structure, same one-class-to-extend story. Replies are trimmed to 800 chars before synthesis. |
| **LLMs in Voice AI** | `services/llm.py` (Gemini-only) + `agents/base.py` (Gemini tool-calling) | Gemini is the only LLM anywhere in the codebase — `services/llm.py`'s *text-only* call (used by `general_agent`'s tier 1 fallback) and the specialist agents' *tool-calling* (`agents/base.py`, gated on `GEMINI_API_KEY`) both go through Gemini. `OPENAI_API_KEY` still exists but is only used by STT/TTS (`services/stt.py`/`services/tts.py`), a completely separate code path. |
| **Speech Analytics** | `models/chat_analytics.py`, `routes/analytics.py`, `frontend/src/components/ChatAnalyticsTab.js` | Every turn logs which agent handled it, sentiment, per-stage latency (STT/LLM/TTS/total), and whether the reply was AI-generated or a rule-based fallback — surfaced on an admin-only dashboard. |
| **Multi-Agent Orchestration** | `agents/orchestrator.py` + `agents/{tracking,complaints,schedule,support}_agent.py` + `tools/` | Real dispatch to specialists, each with its own system prompt and one-or-more DB-backed tools (see "Tools" below) — not prompt-stuffing. Capped at 2 Gemini calls per specialist turn (`agents/base.py`). |

## Tools (`tools/`)

Every specialist action is backed by a real Python function that hits the
database — the model is never trusted to state a fact or take an action
without calling a tool for it:

| Tool | File | What it does |
|---|---|---|
| `get_vehicle_status` | `tools/tracking_tools.py` | Live `VehicleLog` + `Driver` lookup for today's active vehicles; optional `area` or `vehicleNo` filter — `vehicleNo` lets a follow-up like "when was **it** last updated?" re-verify via a narrow tool call instead of answering from memory. |
| `get_complaint_status` | `tools/complaint_tools.py` | The logged-in resident's own complaints from `Complaint`. |
| `create_complaint` | `tools/complaint_tools.py` | **Writes** a new `Complaint` row — shares `insert_complaint()` with `routes/complaints.py`'s REST endpoint, so the voice tool and the REST API never diverge on how a complaint gets written. |
| `list_complaints_admin` | `tools/complaint_tools.py` | Admin-only cross-resident complaint listing/counts, filterable by status/category/day-window — checks `current_user["role"]=="admin"` itself and returns an honest `{"note": ...}"}` if not, rather than the model refusing on its own assumption. |
| `get_collection_schedule` | `tools/schedule_tools.py` | The logged-in resident's own `pickupSchedule`/`wasteType`/`residentType` from `User` — real per-user data, not the static "what schedules exist" text. |
| `get_support_info` | `tools/support_tools.py` | Current `SupportConfig` contact details. |
| `search_knowledge_base` | `tools/knowledge_base_tools.py` | Wraps the same KB-matching logic `rule_based_reply()` uses (`agents/general_agent.py`'s `_best_kb_match()`), so even the zero-key fallback and the tool-calling tier agree on one scoring implementation. |
| `get_operations_summary` | `tools/analytics.py` | Cross-cutting complaint stats (by status/category, avg resolution time) + today's vehicle/collection activity — plain-Python aggregation over `Complaint`/`VehicleLog`, same demo-scale style `routes/analytics.py` already uses. Bound into `general_agent` since it spans multiple domains rather than one specialist. |

**`create_complaint` requires a confirmation turn.** `agents/complaints_agent.py`'s
system prompt instructs the model to summarize the complaint (subject,
category, description) and explicitly ask "Should I file this?" before ever
calling `create_complaint`, and to only call it after the user confirms in a
later turn. **This is a prompt-level guarantee, not a code-enforced state
machine** — there's no server-side flag that blocks the tool call; it relies
on conversation memory (below) plus instruction-following. Worth knowing if
you're evaluating how hard this guarantee actually is.

## Gemini owns classification, tool-calling, and summarization

Both LLM surfaces go through Gemini exclusively:

- The **text** LLM path (`services/llm.py`, used by `general_agent`'s tier 1
  fallback) calls `_gemini_reply` directly — no provider branching anymore.
- The **tool-calling / multi-agent** path (`agents/base.py`,
  `agents/orchestrator.py`) also uses Gemini's native function-calling
  (`google-generativeai`'s `tools=`/`tool_config` params), gated on
  `GEMINI_API_KEY`.

`OPENAI_API_KEY` still exists in `config.py`, but only for STT/TTS
(`services/stt.py`/`services/tts.py`, Whisper) — a completely separate code
path with no bearing on reasoning/classification/tool-calling.

Tool schemas in `tools/*.py` stay in the original `{"name", "description",
"input_schema"}` shape everywhere — only `agents/base.py`'s call boundary
renames `input_schema` to Gemini's `parameters` key; Gemini's
`FunctionDeclaration` recursively converts the JSON-Schema body itself
(`type` → `type_`, etc.), so no tool file needed reshaping.

`agents/base.py:run_tool_agent()` accepts a *list* of tools and an
`executors` dict keyed by tool name (not one fixed tool) — `complaints_agent`
offers `get_complaint_status`, `create_complaint`, and `list_complaints_admin`
in a single call and lets the model pick. The loop is capped at exactly 2
Gemini calls per turn: one to decide+invoke a tool (or answer directly), one
to produce the final grounded text answer after the tool result comes back.

The classifier (`agents/orchestrator.py:_classify_sync`) forces a single
function call via `tool_config={"function_calling_config": {"mode": "ANY",
"allowed_function_names": ["classify"]}}` — Gemini's closest equivalent to
Anthropic's old `tool_choice={"type": "tool", "name": ...}`. `_keyword_classify`
remains the fallback when `GEMINI_API_KEY` is unset or the call errors.

## Conversation memory (`memory/`)

`memory/conversation_memory.py` + `models/conversation_turn.py` — every
turn (user and assistant) is written to a `ConversationTurn` MongoDB
document keyed by `sessionId`. **This is MongoDB-backed, not an in-process
dict**, so it survives a backend restart and works correctly across
multiple workers — a follow-up like:

```
User: Track my truck.
AI:   Which truck number?
User: KA01AB1234
AI:   Truck found...
```

resolves correctly regardless of which worker process handles the second
request. `voice/pipeline.py` loads history from MongoDB (not from a
client-sent `history` field) before calling the orchestrator, and appends
both new turns after — **the backend is the source of truth for context**
once a `sessionId` exists, not the client's own local message list.

## Conversation State Machine

The continuous voice loop (press Start, talk back-and-forth freely, press
End) is driven by a single finite state machine
(`frontend/src/components/voiceConversationMachine.js`), not a set of
independent boolean flags (`isListening`, `isSpeaking`, `isThinking`,
`isRecording`, `isProcessing`, …).

### Why a state machine over boolean flags

Independent booleans grow combinatorially — five flags is 32 theoretical
combinations — and most of them are **impossible states that can still be
represented in code**: nothing stops `isListening && isSpeaking` both being
`true` at once, or `isThinking` staying `true` after an error already fired.
Debugging then means reasoning about which flag combinations can actually
occur versus which the type system merely allows. A single enum with an
explicit transition table makes impossible states **unrepresentable** — the
UI can only ever be in exactly one of ten named states — and gives one
place (`STATE_UI`/`labelFor()`) that decides what's shown, instead of a
scatter of `{cond1 && !cond2 && cond3 ? … : …}` expressions across the
render function.

### States

| State | Trigger | UI shown |
|---|---|---|
| `IDLE` | Initial / after Start fails | "Press Start to talk" |
| `LISTENING` | Mic actively recording, VAD watching for silence | Pulsing mic animation, "Listening…" |
| `TRANSCRIBING` | Backend received the audio, running Whisper | "Transcribing…" |
| `THINKING` | Backend's orchestrator is classifying intent + sentiment | "Thinking…" |
| `TOOL_EXECUTION` | A specialist agent is calling a real tool | The tool's own phrase, e.g. "Checking complaint status…" |
| `GENERATING_RESPONSE` | Waiting on the final LLM call (or the zero-key fallback) | "Generating response…" |
| `SPEAKING` | Client is playing the returned TTS audio | Speaker animation, "Speaking…" |
| `WAITING_FOR_NEXT_INPUT` | Reply finished; about to auto-resume listening | Brief "One moment…", then auto → `LISTENING` |
| `ERROR` | STT/TTS/LLM/tool failure, mic permission denial, network error | Red error banner with the specific message |
| `END` | User pressed End Conversation, or an unrecoverable error | "Conversation ended" |

### State diagram

```
                         ┌─────────────────────────────────────────┐
                         │        (from ANY state)                  │
                         │   ───────────────▶  ERROR                │
                         │   ───────────────▶  END                  │
                         └─────────────────────────────────────────┘

  IDLE ──(Start)──▶ LISTENING ──(silence detected)──▶ TRANSCRIBING
                        ▲                                   │
                        │                            (Whisper done)
                        │                                   ▼
              WAITING_FOR_NEXT_INPUT                    THINKING
                        ▲                                   │
                   (short delay)                 (classification done)
                        │                            ┌──────┴──────┐
                    SPEAKING                          ▼             ▼
                        ▲                     TOOL_EXECUTION   GENERATING_RESPONSE
                        │                             │             ▲
                (TTS audio arrives,          (tool result ready)    │
                 speak=true)                          └─────────────┘
                        │
              GENERATING_RESPONSE ──(speak=false, skip playback)──▶ WAITING_FOR_NEXT_INPUT

  ERROR ──(transient, auto-retry)──▶ LISTENING
  ERROR ──(hard failure / 3 strikes)──▶ END
```

### Transition rules

This table (from-state → allowed to-states) is the same data as
`voiceConversationMachine.js`'s `TRANSITIONS` object — if this table and the
code ever disagree, the code is correct and this table is stale; open an
issue rather than trusting the doc.

| From | Allowed to |
|---|---|
| `IDLE` | `LISTENING` |
| `LISTENING` | `TRANSCRIBING` |
| `TRANSCRIBING` | `THINKING` |
| `THINKING` | `TOOL_EXECUTION`, `GENERATING_RESPONSE` |
| `TOOL_EXECUTION` | `GENERATING_RESPONSE` |
| `GENERATING_RESPONSE` | `SPEAKING`, `WAITING_FOR_NEXT_INPUT` (the latter when `speak=false`) |
| `SPEAKING` | `WAITING_FOR_NEXT_INPUT` |
| `WAITING_FOR_NEXT_INPUT` | `LISTENING` |
| `ERROR` | `LISTENING` (transient — auto-resumes) |
| *(any state)* | `ERROR`, `END` — universal, enforced separately from the table above, not listed per-row |

An attempted transition not in this table is a no-op (logged as a console
warning) rather than a crash — defensive against a stray or duplicate
`voice:stage` socket event.

### Backend stage visibility (real, not simulated)

`TRANSCRIBING`/`THINKING`/`TOOL_EXECUTION`/`GENERATING_RESPONSE` are states
the backend actually enters and reports over the **existing Socket.IO
connection** (`sockets.py`, already used for live vehicle tracking) — not
client-side guessed timing. `voice/pipeline.py` emits `voice:stage` events
scoped to a `voice:{sessionId}` room (never broadcast), and
`agents/base.py:run_tool_agent()` accepts an `on_stage(stage, detail)`
callback threaded down from the orchestrator, called right when a tool is
about to execute (with the real tool name) and right before the final LLM
call. Because `_run_sync` runs inside `asyncio.to_thread` (a worker thread
with no event loop), `on_stage`'s implementation in `voice/pipeline.py`
bridges back via `asyncio.run_coroutine_threadsafe` — the one non-obvious
wiring detail in the whole feature, commented inline where it happens.

**One nuance:** on the zero-`GEMINI_API_KEY` fallback path, no
`tool_execution`/`generating_response` events fire at all (the tool-calling
attempt returns `None` before ever touching the Gemini API). The frontend
handles this by treating the HTTP response itself as stronger ground truth
than any socket event: when `/api/voice/chat` resolves, `ChatBot.js` force-
transitions straight to `GENERATING_RESPONSE` (bypassing the normal
transition table via a `FORCE` action) regardless of which stage events did
or didn't arrive — because having the reply text in hand is definitive
proof generation is complete.

## Degradation matrix

| `GEMINI_API_KEY` | `OPENAI_API_KEY` | Text chat | Voice chat |
|---|---|---|---|
| unset | unset | Keyword-routed, rule-based KB reply (`source: "builtin"`) — unchanged from the original zero-key behavior | `422` — "voice isn't available right now" |
| set | unset | Full multi-agent routing + tool-calling works | `422` — STT can't run (Whisper needs `OPENAI_API_KEY`) |
| unset | set | Keyword-routed, rule-based KB replies only (no tool-calling) | STT works, reply is rule-based text, TTS speaks it |
| set | set | Full pipeline: classify → specialist (with tool) or general → reply | Full pipeline including STT + TTS + live stage events |

Every Gemini call site (`agents/orchestrator.py:classify()`,
`agents/base.py:run_tool_agent()`, `services/llm.py:_gemini_reply()`) checks
`config.GEMINI_API_KEY in config.PLACEHOLDER_VALUES` before attempting a
call — the same convention used throughout. `OPENAI_API_KEY` only gates
STT/TTS now, not any reasoning path.
