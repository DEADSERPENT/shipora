# ♻️ EcoTrack — Waste Disposal Management System

A full-stack web application for managing daily waste collection with **live GPS vehicle tracking**, complaint management, AI chat assistant, and role-based dashboards for residents, drivers, and admins.

---

## 🚀 Features

### 🏠 Resident
- Live GPS tracking of waste collection vehicles on an interactive map
- Proximity alert + road route line when a truck is within 3 km of home
- Side-panel dashboard: stats, active vehicles, areas covered
- Pickup schedule management (daily / alternate days / weekly)
- Waste type selection (mixed, household, recyclable, organic)
- Residence type: independent house or flat/apartment
- 30-day collection log
- Complaint box with **anonymous submission** option
- View admin replies and complaint status updates

### 🚛 Driver
- Real-time GPS location broadcasting via WebSocket
- Update current area and ETA (visible to all residents live)
- Mark areas as completed
- 30-day collection history with summary stats

### 🏢 Admin
- Live driver feed with vehicle status cards
- Date-filtered collection logs table
- Complaint management — read, reply, and update status
- Editable customer support contact details (phone, email, WhatsApp, office)
- Stats overview: active drivers, areas covered, registered users

### 🤖 EcoBot AI Assistant — multi-agent voice AI
- Floating chat widget available on every page, with a **continuous voice conversation mode**: press Start, talk freely (automatic end-of-speech detection, no re-tapping the mic), press End when done
- **Multi-agent orchestration**: a router agent classifies each message and dispatches to a specialist — Tracking, Complaints, Schedule, or Support — each with a scoped prompt and real tool call(s) against the database (live vehicle status, filing/checking complaints, a resident's own pickup schedule, current support contact info). Anything else falls through to a general assistant (KB-search tool → provider-agnostic LLM → rule-based knowledge base, three independent fallback tiers).
- **Conversation memory** — MongoDB-backed, keyed per session, so follow-up questions ("which truck?" → "KA01AB1234") resolve correctly
- A **formal conversation state machine** (10 states: IDLE/LISTENING/TRANSCRIBING/THINKING/TOOL_EXECUTION/GENERATING_RESPONSE/SPEAKING/WAITING_FOR_NEXT_INPUT/ERROR/END) drives every UI indicator — no boolean-flag soup. Backend stages are reported live over Socket.IO, not guessed client-side timing.
- Built-in rule-based responses work **without any API key**; the specialist agents activate once `ANTHROPIC_API_KEY` is set (independent of `LLM_PROVIDER`, see [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md))
- 🎙️ **Voice input** — audio is recorded in the browser (`MediaRecorder`) and transcribed server-side via OpenAI Whisper (the only STT provider implemented today)
- 🔊 **Voice output** — EcoBot's answer is synthesized server-side (OpenAI TTS, the only TTS provider implemented today) and played back
- **Speech analytics** — every conversation (text or voice) is logged with intent, sentiment, and per-stage latency, surfaced on an admin-only Chat Analytics dashboard
- Full pipeline diagrams, state machine spec, and design tradeoffs: [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md)

### 🔐 Auth & Profiles
- JWT authentication (7-day expiry) for residents, drivers, and admins
- Per-role profile pages with editable/locked fields
- Forgot password and change password flows
- Indian format validation: phone (10-digit), vehicle plate, driving licence

---

## 🛠 Tech Stack

| Layer     | Technology |
|-----------|-----------|
| Frontend  | React 18, React Router 6, React-Leaflet 4, Socket.io-client, Axios |
| Backend   | Python, FastAPI, Uvicorn, python-socketio |
| Database  | MongoDB / Motor + Beanie ODM (auto-falls back to in-memory MongoDB via mongomock-motor) |
| Auth      | PyJWT + bcrypt |
| Maps      | OpenStreetMap tiles, Nominatim geocoding, OSRM road routing |
| AI Chat   | Anthropic Claude Haiku, OpenAI, or Google Gemini (pick via `LLM_PROVIDER`, optional) |
| Multi-Agent | Anthropic tool-calling — router + Tracking/Complaints/Support specialist agents (`agents/`) |
| STT / TTS | OpenAI Whisper (`whisper-1`) + OpenAI TTS (`tts-1`), server-side, browser `MediaRecorder` for capture |
| Analytics | Speech/chat analytics logged per turn (intent, sentiment, latency) to MongoDB, admin dashboard via Recharts |

---

## 📁 Project Structure

```
waste-disposal-system/
├── backend/
│   ├── models/
│   │   ├── user.py             # Resident schema (Beanie Document)
│   │   ├── driver.py           # Driver schema
│   │   ├── admin.py            # Admin schema
│   │   ├── vehicle_log.py      # Daily vehicle activity log
│   │   ├── complaint.py        # Complaints with anonymous flag
│   │   ├── support_config.py   # Editable support contact details
│   │   ├── chat_analytics.py   # Per-turn chat/voice analytics (intent, sentiment, latency)
│   │   └── conversation_turn.py # One turn of MongoDB-backed conversation memory
│   ├── routes/
│   │   ├── auth.py             # Register / Login / Profile / Password
│   │   ├── vehicles.py         # Vehicle status, logs & history
│   │   ├── admin.py            # Admin stats & driver overview
│   │   ├── complaints.py       # Complaint CRUD (shares tools/complaint_tools.insert_complaint)
│   │   ├── support.py          # Support config (public read, admin write)
│   │   ├── chat.py             # EcoBot text chat endpoint — thin wrapper over voice/pipeline.py
│   │   ├── voice.py            # Voice round-trip endpoint — thin wrapper over voice/pipeline.py
│   │   └── analytics.py        # Admin-only chat/voice analytics aggregation
│   ├── agents/                 # Prompts + which tool(s) to bind + dispatch — no DB calls here
│   │   ├── orchestrator.py     # Router: classifies intent + sentiment, dispatches to a specialist
│   │   ├── base.py             # Shared Anthropic tool-calling loop (N tools, on_stage callback)
│   │   ├── tracking_agent.py   # Binds tools/tracking_tools.py
│   │   ├── complaints_agent.py # Binds tools/complaint_tools.py (status check + confirmed filing)
│   │   ├── schedule_agent.py   # Binds tools/schedule_tools.py
│   │   ├── support_agent.py    # Binds tools/support_tools.py
│   │   └── general_agent.py    # 3-tier fallback: KB-search tool -> provider-agnostic LLM -> rule-based KB
│   ├── tools/                  # Tool schemas + DB-backed executors — no prompts, no dispatch logic
│   │   ├── tracking_tools.py
│   │   ├── complaint_tools.py  # incl. insert_complaint(), shared with routes/complaints.py
│   │   ├── schedule_tools.py
│   │   ├── support_tools.py
│   │   └── knowledge_base_tools.py
│   ├── memory/
│   │   └── conversation_memory.py # MongoDB-backed get_history()/append_turn(), keyed by sessionId
│   ├── voice/
│   │   └── pipeline.py         # run_text_turn()/run_voice_turn() — the actual business logic
│   ├── services/
│   │   ├── llm.py              # Provider-agnostic LLM abstraction (Claude/OpenAI/Gemini)
│   │   ├── stt.py               # STTProvider ABC — only OpenAI Whisper implemented today
│   │   └── tts.py               # TTSProvider ABC — only OpenAI TTS implemented today
│   ├── utils/
│   │   └── dates.py            # JS-compatible date formatting
│   ├── auth_utils.py           # JWT sign/verify, password hashing, FastAPI auth dependencies
│   ├── config.py                # Env var loading
│   ├── database.py              # Mongo connection (real or in-memory fallback)
│   ├── serializers.py           # Response JSON shaping
│   ├── sockets.py                # python-socketio server + live vehicle location + voice:stage events
│   ├── main.py                   # FastAPI app, CORS, routers, Socket.IO mount
│   └── Dockerfile
└── frontend/
    └── src/
        ├── context/
        │   └── AuthContext.js
        ├── components/
        │   ├── Navbar.js
        │   ├── VehicleMap.js         # Leaflet map with 3 km radius + routing
        │   ├── LocationPicker.js     # Map picker with address search & pincode
        │   ├── BackButton.js
        │   ├── ChatBot.js            # EcoBot floating chat widget — continuous voice conversation via MediaRecorder + VAD + Socket.IO
        │   ├── voiceConversationMachine.js # The conversation FSM (states, transitions, UI labels) — see docs/VOICE_ARCHITECTURE.md
        │   ├── ChatAnalyticsTab.js   # Admin dashboard tab: intent/sentiment/latency charts
        │   └── ScrollToTopButton.js  # Animated scroll-to-top button
        └── pages/
            ├── Login.js
            ├── Register.js
            ├── ForgotPassword.js
            ├── Profile.js
            ├── UserDashboard.js
            ├── DriverDashboard.js
            ├── AdminDashboard.js
            ├── DriverHistory.js
            ├── CollectionLog.js
            ├── ComplaintBox.js
            └── Support.js
```

---

## ⚙️ Setup & Installation

### Prerequisites
- Python 3.11+
- Node.js 18+ (frontend)
- MongoDB (optional — falls back to in-memory if not running)

### 1. Clone the repository
```bash
git clone https://github.com/VaibhavKaranth/ecotrack-waste-disposal.git
cd ecotrack-waste-disposal
```

### 2. Backend setup
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows — use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

Create `backend/.env` (copy from `.env.example`):
```env
PORT=5000
CLIENT_URL=http://localhost:3000
JWT_SECRET=your_jwt_secret_here
MONGO_URI=mongodb://localhost:27017/waste-disposal

# AI provider — set LLM_PROVIDER to anthropic | openai | gemini
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_api_key_here   # optional — enables AI chat
OPENAI_API_KEY=your_api_key_here
GEMINI_API_KEY=your_api_key_here
```

```bash
uvicorn main:app --reload --port 5000
```

### 3. Frontend setup
```bash
cd ../frontend
npm install
npm start
```

App opens at **http://localhost:3000**

---

## 🔐 Roles & Access

| Role     | Capabilities |
|----------|-------------|
| Resident | Track vehicles, file complaints, view collection logs, update profile |
| Driver   | Share GPS location, mark areas done, view 30-day history |
| Admin    | Monitor all activity, manage complaints, edit support contacts |

---

## 🗺️ Key Routes

| Route | Page |
|-------|------|
| `/dashboard` | Resident dashboard — side panel + live map |
| `/driver` | Driver dashboard — GPS sharing + status |
| `/admin` | Admin panel — Overview / Logs / Complaints / Settings |
| `/profile` | Editable profile for all roles |
| `/complaints` | Resident complaint box |
| `/collection-log` | Resident 30-day log |
| `/driver-history` | Driver 30-day history |
| `/support` | Customer support page |

---

## 🌐 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register/user` | — | Register resident |
| POST | `/api/auth/register/driver` | — | Register driver |
| POST | `/api/auth/register/admin` | — | Register admin |
| POST | `/api/auth/login` | — | Login (all roles) |
| GET  | `/api/auth/profile` | JWT | Get full profile |
| PUT  | `/api/auth/profile` | JWT | Update profile |
| POST | `/api/auth/forgot-password` | — | Verify email for reset |
| POST | `/api/auth/reset-password` | — | Reset password |
| POST | `/api/auth/change-password` | JWT | Change password |
| GET  | `/api/vehicles/history` | JWT | 30-day log |
| POST | `/api/vehicles/status` | JWT | Driver: update area + ETA |
| GET  | `/api/admin/stats` | JWT (admin) | Stats overview |
| GET  | `/api/complaints` | JWT | Get complaints |
| POST | `/api/complaints` | JWT (user) | Submit complaint |
| PUT  | `/api/complaints/:id` | JWT (admin) | Reply & update status |
| GET  | `/api/support/config` | — | Get support contacts |
| PUT  | `/api/support/config` | JWT (admin) | Update support contacts |
| POST | `/api/chat` | — | EcoBot text chat (routes through the multi-agent orchestrator; conversation context comes from MongoDB via `sessionId`) |
| POST | `/api/voice/chat` | — | EcoBot voice round-trip (audio upload → STT → orchestrator → TTS → audio reply); `speak=false` skips TTS synthesis |
| GET  | `/api/analytics/overview` | JWT (admin) | Chat/voice analytics summary (agent/sentiment distribution, latency, recent conversations) |
| GET  | `/api/analytics/timeseries` | JWT (admin) | Daily conversation counts |

---

## ⚡ Socket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `vehicles:initial` | Server → Client | Current vehicle state on connect |
| `vehicles:update` | Server → All | Broadcast after any driver update |
| `driver:location` | Client → Server | Driver emits GPS coordinates |
| `driver:offline` | Client → Server | Driver stops sharing |
| `voice:join` | Client → Server | ChatBot joins its `voice:{sessionId}` room when a conversation starts |
| `voice:leave` | Client → Server | ChatBot leaves the room when the conversation ends |
| `voice:stage` | Server → Room | Real-time conversation stage (`transcribing`/`thinking`/`tool_execution`/`generating_response`), scoped to one session — drives the frontend's conversation state machine, see [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md) |

---

## 🤖 EcoBot Setup (Optional)

EcoBot works out of the box with built-in rule-based answers.
To enable AI-powered responses, pick a provider in `backend/.env` via `LLM_PROVIDER` and set the matching key:

```env
LLM_PROVIDER=anthropic   # anthropic | openai | gemini
ANTHROPIC_API_KEY=sk-ant-...
```

| Provider | Env var | Get a key |
|----------|---------|-----------|
| Anthropic (Claude Haiku) | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI (GPT-4o mini) | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| Google Gemini | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |

If the selected provider's key is missing or still the placeholder value, EcoBot automatically falls back to the built-in rule-based knowledge base — no crash, no empty replies.

### Multi-agent specialists (Anthropic-only)

The Tracking, Complaints, and Support specialist agents (`backend/agents/`) use Anthropic's tool-calling API directly, gated on `ANTHROPIC_API_KEY` specifically — set it even if `LLM_PROVIDER` is `openai` or `gemini` to enable them. Without it, EcoBot still works, just without database-backed specialist answers (falls back to the general rule-based/LLM assistant). See [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md) for why this path isn't provider-agnostic like the rest of the app.

### Voice (STT/TTS)

```env
STT_PROVIDER=openai   # only openai implemented currently
TTS_PROVIDER=openai
TTS_VOICE=alloy
```

Voice reuses `OPENAI_API_KEY` above — no separate key needed. Click the mic icon in the chat widget to record a question (browser `MediaRecorder`), and toggle "speak replies" to have EcoBot's answer synthesized and played back. If `OPENAI_API_KEY` is missing, the mic button still records but the widget shows a clean "voice isn't available" message and text chat keeps working normally.

### Speech analytics dashboard

Every chat/voice turn is logged (intent, sentiment, source, per-stage latency) to MongoDB. Admins can view aggregated charts and a recent-conversations table under **Admin Dashboard → 🎙️ Chat Analytics**.

---

## 🐳 Docker Setup

Bring up MongoDB and the FastAPI backend together with Docker Compose:

```bash
docker compose up --build
```

This starts:
- `mongo` — MongoDB 7 with a persistent named volume
- `backend` — the FastAPI app on **http://localhost:5000**, reading env vars from `backend/.env`

The frontend is not containerized — run it separately as in step 3 above (`cd frontend && npm start`).

---

## 📖 API Docs

FastAPI generates interactive API documentation automatically:

- Swagger UI — http://localhost:5000/docs
- ReDoc — http://localhost:5000/redoc
- Raw OpenAPI schema — http://localhost:5000/openapi.json

---

## 📄 License

MIT — free to use and modify.
