# 📦 Shipora — Parcel Delivery & Fleet Management Platform

Shipora lets customers book same-day parcel deliveries and watch the rider on a live map, gives delivery agents their assignments and GPS sharing, and gives operations a view of the whole network. **ShipBot**, a text and voice assistant, answers from real shipment data.

## Features
- **Customer** — book a same-day shipment (Bengaluru), get an upfront fare estimate without signing in, track by number with a live vehicle position, report delivery issues.
- **Delivery agent** — assigned shipments, one-tap status updates, exception reporting, live GPS, route logs.
- **Operations** — live fleet map, shipment filters and assignment, delivery performance, issue management, AI-chat analytics.

Lifecycle: `CREATED → PICKUP_SCHEDULED → PICKED_UP → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED` (plus failed / cancelled / returned states). Transitions are validated and role-gated on the server, with a 3-attempt cap.

## Architecture

```
┌────────────────────────────── CLIENT: React 18 SPA ──────────────────────────────┐
│  Customer UI      Delivery-Agent UI      Operations UI      ShipBot (chat + voice)│
│  Leaflet live map · Axios (REST + JWT) · Socket.IO client · voice state machine   │
└──────────────────────┬──────────────────────────────────────┬────────────────────┘
                REST   │                                      │  WebSocket
                       ▼                                      ▼
┌────────────────────── SERVER: FastAPI + python-socketio (Uvicorn) ───────────────┐
│  API layer      routes/ auth · shipments · vehicles · admin · chat · voice        │
│                 JWT auth · role checks · rate limit · idempotency                 │
│  Domain layer   services/shipments.py  lifecycle rules + persist + broadcast      │
│                 pricing · geo · dispatch (auto-assign) · simulator                │
│  Realtime       sockets.py   fleet feed · shipment rooms · voice stage events     │
│  AI layer       voice/pipeline.py  STT → agents → TTS                             │
│                 agents/   router → tracking · complaints · schedule · support     │
│                 tools/    DB-backed functions (the only source of facts)          │
│                 memory/   per-session conversation history                        │
└────────┬───────────────────────┬───────────────────────────┬──────────────────────┘
         ▼                       ▼                           ▼
   MongoDB (Motor+Beanie)   OpenStreetMap / Nominatim    Ollama (local LLM)
   or in-memory mongomock   / OSRM (maps, routing)       Whisper STT · Piper TTS
```

- **Server owns the rules** — status transitions and permissions live in the backend; the UI renders `allowedNextStatuses`.
- **One write path** — REST routes, AI tools and the simulator all change shipments through `services/shipments.py`, which validates, saves, logs and broadcasts.
- **Grounded AI, graceful fallbacks** — ShipBot states only what a tool fetched; LLM, STT, TTS and MongoDB each have a fallback.

## Workflow

### 1. Shipment workflow
```
Customer                    Server                         Delivery agent        Operations
   │ estimate (public)        │                                  │                    │
   ├─ pickup+drop+weight ───▶ │ pricing + OSRM distance/ETA      │                    │
   │ book shipment ─────────▶ │ validate (Bengaluru, ≤20 kg)     │                    │
   │                          │ status = CREATED, tracking SHP…  │                    │
   │                          │ auto-dispatch or admin assigns ◀─┼────────────────────┤
   │                          │ status = PICKUP_SCHEDULED ──────▶│ sees assignment    │
   │                          │ ◀── PICKED_UP → IN_TRANSIT ──────┤ one-tap updates    │
   │ ◀── live updates ────────┤ ◀── DELIVERED / exception ───────┤                    │
```

Each update is checked against the transition table and the caller's role, saved with a timeline entry, then broadcast. Exceptions can be retried up to 3 delivery attempts; return-to-origin is an operations decision.

### 2. Live tracking workflow
```
Agent app ── driver:location (GPS) ──▶ sockets.py ──▶ update vehicle + TrackingLog
                                           │
                                           ├─▶ fleet room      → vehicles:update   → Operations map
                                           └─▶ shipment room   → shipment:update   → Customer tracking page
Sweeper (background): no GPS for a while → vehicle marked stale → watchers notified
```

### 3. ShipBot request workflow
```
message (text/voice) → load history (MongoDB) → router {agent, sentiment} → specialist agent
   → tool call → DB query scoped to caller's role → grounded reply → save turn + analytics
```

## ShipBot and the voice sandwich

The voice pipeline is a **sandwich**: speech-to-text → reasoning → text-to-speech. Plain text is the only interface between the three layers, so each can be inspected, tested and swapped on its own. An end-to-end speech model would hide all of that in one opaque call and make database-grounded answers hard to enforce.

```
 Mic ──▶ ① STT        audio → transcript        (Whisper: OpenAI | faster-whisper | ONNX)
         │             + repair of spelled tracking numbers ("S H P one alpha…" → SHP1A…)
         ▼
         ② Reasoning  router picks {agent, sentiment}, then a specialist
         │             (tracking · complaints · schedule · support · general)
         │             calls tools/ → real DB queries → grounded reply
         ▼
         ③ TTS        reply → audio             (Piper local WAV | OpenAI MP3)
         ▼
       Speaker, then listening resumes automatically
```

- **Real progress events** — the backend emits `voice:stage` (transcribing, thinking, tool_execution, generating_response) over Socket.IO; the frontend runs a ten-state machine on them.
- **Independent fallbacks** — no LLM: keyword routing plus database answers. No STT: user is asked to type. No TTS: text reply only. With `onnx_local` + `piper`, voice works with no API keys.
- **Verify it** — `python scripts/verify_sandwich.py`. More: [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md), [`docs/LOCAL_VOICE.md`](docs/LOCAL_VOICE.md).

## Tech stack

| Layer | Technology |
|-------|-----------|
| App | React 18, React-Leaflet, Socket.IO · Python 3.11+, FastAPI, Uvicorn, python-socketio |
| Database | MongoDB via Motor + Beanie (in-memory mongomock fallback) |
| Auth / Maps | PyJWT + bcrypt · OpenStreetMap, Nominatim, OSRM |
| AI | Ollama (`qwen2.5:3b`); STT: Whisper / faster-whisper / ONNX; TTS: OpenAI / Piper |

## Getting started

Prerequisites: Python 3.11+, Node 18+. MongoDB and Ollama are optional (no MongoDB = in-memory database, reset on restart).

**Backend**
```bat
:: first time only
cd backend-fastapi
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env

:: every later session (from the repo root)
backend-fastapi\.venv\Scripts\activate.bat
cd backend-fastapi
uvicorn main:app --reload --port 5000
```

PowerShell: `.venv\Scripts\Activate.ps1`. macOS/Linux: `source .venv/bin/activate`. API docs at http://localhost:5000/docs.

**Frontend** (separate terminal)
```bash
cd frontend
npm install
npm start        # http://localhost:3000
```

**Minimal `backend-fastapi/.env`**

```env
PORT=5000
CLIENT_URL=http://localhost:3000
JWT_SECRET=<32+ random chars>     # python -c "import secrets; print(secrets.token_urlsafe(48))"
MONGO_URI=mongodb://localhost:27017/shipora
OLLAMA_MODEL=qwen2.5:3b           # optional: ollama pull qwen2.5:3b
STT_PROVIDER=openai               # openai | faster_whisper | onnx_local
TTS_PROVIDER=openai               # openai | piper
OPENAI_API_KEY=…                  # only for OpenAI STT/TTS
```

The app refuses to start without a strong `JWT_SECRET`. First admin on a real database: `scripts/bootstrap_real_data.py`.

**Tests:** `python -m pytest -q` in `backend-fastapi` (in-memory DB); `CI=true npm test -- --watchAll=false` in `frontend`.

## License

MIT
