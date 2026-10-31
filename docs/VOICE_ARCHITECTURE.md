# ShipBot Voice-AI Architecture

ShipBot is Shipora's in-app assistant. It's a **Speech-to-Text → Multi-Agent LLM
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
  ├─▶ services/stt.py — OpenAI Whisper, local faster-whisper or ONNX Whisper           [emits voice:stage "transcribing"]
  │     audio bytes -> transcript text
  │
  ├─▶ memory/conversation_memory.py.get_history(sessionId)   (MongoDB, see below)
  │
  ├─▶ agents/orchestrator.py: route_and_reply()   [emits voice:stage "thinking"]
  │     ONE structured Ollama call (JSON schema), returns {agent, sentiment}
  │     falls back to keyword matching if Ollama is unreachable
  │         │
  │         ▼
  │   ┌───────────────┬──────────────────┬────────────────┬────────────────┬───────────┐
  │   ▼               ▼                  ▼                ▼                ▼
  │ tracking_agent  complaints_agent  schedule_agent   support_agent    general_agent
  │ (tools/          (tools/           (tools/          (tools/          (tier 0: tools/
  │  tracking_ +     complaint_        schedule_        support_          knowledge_base_
  │  shipment_        tools.py)         tools.py)        tools.py)         tools.py;
  │  tools.py)
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
  ├─▶ services/tts.py — OpenAI TTS or local Piper  (skipped if speak=false)
  │     reply text -> speech_text() (markdown/bullets stripped, line breaks -> pauses)
  │     -> audio bytes: MP3 (openai) or WAV (piper); the route reports which in audioMimeType
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
| **STT Models** | `services/stt.py` | **Three providers**, chosen by `STT_PROVIDER`: `openai` (default, `whisper-1`), `faster_whisper` (local, CTranslate2) and `onnx_local` (local Whisper on ONNX Runtime — for machines where CTranslate2 can't load); the local ones need no API key and are an optional install, see `docs/LOCAL_VOICE.md`. Structured as an `STTProvider` abstract base class; adding another provider means writing one new class and adding it to `_PROVIDERS`, without touching `transcribe_audio()` or any caller. `onnx_local` has been run end to end on real audio on one machine; `faster_whisper` is tested with mocks only. No accuracy benchmark exists for either. |
| **TTS Models** | `services/tts.py` | **Two providers**, chosen by `TTS_PROVIDER`: `openai` (default, `tts-1`, returns MP3) and `piper` (local, no API key, returns WAV — English is the tested language). Same `TTSProvider` structure and one-class-to-extend story. `/api/voice/chat` reports the real format in `audioMimeType`. Replies are trimmed to 800 chars before synthesis. |
| **LLMs in Voice AI** | `services/ollama_client.py` (+ `services/llm.py`, `agents/base.py`) | A local Ollama model is the only LLM anywhere in the codebase: classification, the specialist agents' *tool-calling* (`agents/base.py`) and the text-only fallback tier (`services/llm.py`) all go through it. No cloud LLM and no LLM API key. `OPENAI_API_KEY` exists only for the optional OpenAI STT/TTS providers (`services/stt.py`/`services/tts.py`) — a completely separate code path. |
| **Speech Analytics** | `models/chat_analytics.py`, `routes/analytics.py`, `frontend/src/components/ChatAnalyticsTab.js` | Every turn logs which agent handled it, sentiment, per-stage latency (STT/LLM/TTS/total), and whether the reply was AI-generated or a rule-based fallback — surfaced on an admin-only dashboard. |
| **Multi-Agent Orchestration** | `agents/orchestrator.py` + `agents/{tracking,complaints,schedule,support}_agent.py` + `tools/` | Real dispatch to specialists, each with its own system prompt and one-or-more DB-backed tools (see "Tools" below) — not prompt-stuffing. Capped at 2 model calls per specialist turn (`agents/base.py`). |

## Tools (`tools/`)

Every specialist action is backed by a real Python function that hits the
database — the model is never trusted to state a fact or take an action
without calling a tool for it:

| Tool | File | What it does |
|---|---|---|
| `get_vehicle_status` | `tools/tracking_tools.py` | Live `TrackingLog` + `DeliveryAgent` lookup for today's active vehicles that have reported recently (a vehicle that stopped sending GPS is no longer listed as live); optional `area` or `vehicleNo` filter — `vehicleNo` lets a follow-up like "when was **it** last updated?" re-verify via a narrow tool call instead of answering from memory. |
| `get_complaint_status` | `tools/complaint_tools.py` | The logged-in customer's own delivery issues from `DeliveryIssue` (the REST API and collection keep the legacy name "complaints"). |
| `create_complaint` | `tools/complaint_tools.py` | **Writes** a new `DeliveryIssue` row, optionally linked to a shipment by tracking number — shares `insert_complaint()` with `routes/complaints.py`'s REST endpoint, so the voice tool and the REST API never diverge on how a complaint gets written. |
| `list_complaints_admin` | `tools/complaint_tools.py` | Admin-only delivery-issue listing/counts across all customers, filterable by status/category/day-window — checks `current_user["role"]=="admin"` itself and returns an honest `{"note": ...}"}` if not, rather than the model refusing on its own assumption. |
| `get_my_shipments` | `tools/schedule_tools.py` | The logged-in customer's own recent shipments (tracking number, status, `isActive`, pickup time, estimated delivery) — real per-user data, scoped to the caller (the tool takes no customer id). Offered by both `schedule_agent` and `tracking_agent`: "Where is my parcel?" without a tracking number is answered from it directly when exactly one shipment is active, and the customer is asked which one when several are. |
| `get_shipment_status` | `tools/shipment_tools.py` | Public status + timeline for a tracking number (no personal data). Offered by `tracking_agent` together with `get_vehicle_status` and `get_my_shipments`. By design it is a public lookup — the tracking number is the credential, exactly as on the public tracking page — so any caller who has a number can read its status. |
| `get_support_info` | `tools/support_tools.py` | Current `SupportConfig` contact details. |
| `search_knowledge_base` | `tools/knowledge_base_tools.py` | Wraps the same KB-matching logic `rule_based_reply()` uses (`agents/general_agent.py`'s `_best_kb_match()`), so even the zero-key fallback and the tool-calling tier agree on one scoring implementation. |
| `get_operations_summary` | `tools/analytics.py` | Cross-cutting operations stats: shipment counts by status, delivery-issue stats (by status/category, avg resolution time) + today's vehicle/delivery activity — plain-Python aggregation over `Shipment`/`DeliveryIssue`/`TrackingLog`, same demo-scale style `routes/analytics.py` already uses. Bound into `general_agent` since it spans multiple domains rather than one specialist. |

**`create_complaint` requires a confirmation turn.** `agents/complaints_agent.py`'s
system prompt instructs the model to summarize the complaint (subject,
category, description) and explicitly ask "Should I file this?" before ever
calling `create_complaint`, and to only call it after the user confirms in a
later turn. **This is a prompt-level guarantee, not a code-enforced state
machine** — there's no server-side flag that blocks the tool call; it relies
on conversation memory (below) plus instruction-following. Worth knowing if
you're evaluating how hard this guarantee actually is.

## Ollama owns classification, tool-calling, and summarization

Every LLM surface goes through the local Ollama model (`services/ollama_client.py`, model set by `OLLAMA_MODEL`, default
`qwen2.5:3b` — fully resident on a 6 GB GPU):

- The **text** LLM path (`services/llm.py`, used by `general_agent`'s fallback tier) calls `ollama_client.reply`.
- The **tool-calling / multi-agent** path (`agents/base.py`, `agents/orchestrator.py`) uses Ollama's native tool calling and
  structured (JSON-schema) output, so the classifier can only return a valid agent name.

`OPENAI_API_KEY` still exists in `config.py`, but only for the OpenAI STT/TTS providers (`services/stt.py`/`services/tts.py`,
Whisper and `tts-1`), and only while those providers are selected — a completely separate code path with no bearing on
reasoning/classification/tool-calling. The local providers (`faster_whisper`/`onnx_local`, `piper`) need no API key at all.

Tool schemas in `tools/*.py` keep the `{"name", "description", "input_schema"}` shape; `ollama_client.chat()` maps `input_schema`
to Ollama's `parameters` at the call boundary.

`agents/base.py:run_tool_agent()` accepts a *list* of tools and an `executors` dict keyed by tool name — `complaints_agent` offers
`get_complaint_status`, `draft_complaint` and `list_complaints_admin` in a single call and lets the model pick. The loop is capped
at two model calls per turn (one to decide+invoke a tool or answer directly, one to phrase the grounded answer) and two tool calls.
A tool the role was never offered, malformed arguments, a tool that exceeds `TOOL_TIMEOUT_SECONDS` (30 s) or a reply that is raw
tool-call JSON never reaches the user: the turn falls back to the database / rule-based answer.

The classifier (`agents/orchestrator.py:classify` -> `ollama_client.classify`) asks for `{agent, sentiment}` against a JSON schema.
`_keyword_classify` remains the fallback when Ollama is unreachable or returns something out of schema.

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
call. The Ollama client is async and runs on the application's event loop, so `on_stage` is called
directly from the request's own task; `voice/pipeline.py` schedules the Socket.IO emit with `asyncio.run_coroutine_threadsafe`,
which is legal from either a task or a worker thread.

**One nuance:** when Ollama is unreachable, no
`tool_execution`/`generating_response` events fire at all (the tool-calling
attempt returns `None` before any tool runs). The frontend
handles this by treating the HTTP response itself as stronger ground truth
than any socket event: when `/api/voice/chat` resolves, `ChatBot.js` force-
transitions straight to `GENERATING_RESPONSE` (bypassing the normal
transition table via a `FORCE` action) regardless of which stage events did
or didn't arrive — because having the reply text in hand is definitive
proof generation is complete.

## Degradation matrix

The three stages degrade independently:

| Stage | Works when | When it can't run |
|---|---|---|
| Reasoning (Ollama) | `ollama serve` is reachable and `OLLAMA_MODEL` is pulled | Keyword-routed reply; tracking questions with a tracking number are still answered from the database, everything else from the rule-based KB (`source: "builtin"`). No tool-calling, so no other live lookups. See below |
| STT | `openai`: `OPENAI_API_KEY` set. `faster_whisper` / `onnx_local`: package + model present and loadable (no key) | `/api/voice/chat` returns `422` — "voice isn't available right now". The same `422` is returned for a silent/empty recording |
| TTS | `openai`: `OPENAI_API_KEY` set. `piper`: package + voice file present (no key) | The reply is returned as text with no audio (`audioBase64: null`); the conversation continues |

So, for example: with no API keys and no Ollama, `STT_PROVIDER=onnx_local` + `TTS_PROVIDER=piper` still gives a working voice
loop with rule-based replies; running Ollama upgrades the reasoning to full multi-agent routing with tool-calling
and live stage events. With the default `openai` providers and no `OPENAI_API_KEY`, text chat works but voice returns `422`.
Setup for the local providers: `docs/LOCAL_VOICE.md`.

**Ollama outages.** Every Ollama call has a hard time budget (`OLLAMA_TIMEOUT_SECONDS`, default 30 s; voice turns use
`OLLAMA_VOICE_TIMEOUT_SECONDS`, default 8 s). After an outage-type failure (server down, timeout, 5xx) all Ollama calls are skipped
for `OLLAMA_COOLDOWN_SECONDS` (default 30 s) and the turn uses the built-in fallbacks straight away — so a dead server costs one
failed call, once, not one per call. A successful call clears the cooldown; request-level errors (a 4xx such as a model that is not
installed, a slow *database* tool) do not trip it. There is no second LLM to switch to: the fallbacks are keywords, the database
and the rule-based knowledge base. Details: `services/ollama_client.py`.

**Dates.** Tools that return dates (`get_shipment_status`, `get_my_shipments`) also return ready-made customer-facing text
(`estimatedDeliveryText`, `pickupScheduledText`, `deliveredOnText`, e.g. "Monday, 12 October 2026") and the agent prompts
forbid "today"/"tomorrow"/"in N days": the model does not know today's date, and once said "by today" for a delivery 5 days away.

Every LLM call site (`agents/orchestrator.py:classify()`, `agents/base.py:run_tool_agent()`, `services/llm.py:get_llm_reply()`)
checks `ollama_client.is_unavailable()` before calling, so an outage never adds latency to the rest of the turn. `OPENAI_API_KEY`
only gates the OpenAI STT/TTS providers, not any reasoning path.

## Verification and resilience (added)

* `backend-fastapi/scripts/verify_sandwich.py` exercises each stage with the real providers and the full
  `/api/voice/chat` round trip; `tests/test_voice_sandwich.py` covers the same flow in CI with STT/TTS stubbed.
* Voice turns use a tighter LLM budget (`OLLAMA_VOICE_TIMEOUT_SECONDS`, default 8 s) than chat.
* If the LLM is unavailable, a tracking question containing a tracking number is still answered from the database
  (`agents/tracking_agent.py: fallback`), reported with `source: "builtin"`.
* Spelled tracking numbers are extracted tolerantly, and a mis-heard one is repaired only against the signed-in
  customer's own shipments (`tools/shipment_tools.py`).
