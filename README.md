# 📦 Shipora — Parcel Delivery & Fleet Management Platform

A full-stack platform for sending parcels and running the fleet that delivers them: **shipment lifecycle management**, **live delivery-vehicle tracking over WebSockets**, delivery-issue handling, role-based workflows for customers, delivery agents and operations, and an AI assistant (ShipBot) that answers from real shipment data.

---

## Features

### Customer
- Create shipments: pickup address (saved or picked on the map), receiver, delivery address, parcel type/weight/value — **same-day delivery, Bengaluru only** (pickup and drop must both be inside the city)
- **Upfront fare estimate** (public, no sign-in): pickup area + drop area + weight → fare, distance and ETA, then book with the same details prefilled. Fare = base fare covering the first km + a per-km rate (`FARE_*` env vars); parcels up to 20 kg (`MAX_PARCEL_KG`); pay the rider in cash or UPI on delivery
- Track by tracking number: status, timeline, route, assigned agent, **live vehicle position**
- Cancel before pickup, report delivery issues (optionally anonymous) and read operations' replies
- Public tracking page (`/track/SHP…`) — works signed out and exposes no personal data

### Delivery agent
- Assigned shipments with one-tap status updates (picked up → in transit → out for delivery → delivered) and exception reporting (receiver unavailable, address issue, delivery failed, damaged)
- Live GPS sharing, vehicle status/ETA, areas covered, daily route logs and delivery history

### Operations
- Live delivery network map and fleet feed
- Shipments table with filters (active · delayed · failed · unassigned …) and agent assignment
- Delivery performance (on-time %, first-attempt success), shipment statistics, delivery issue management, support-contact settings, AI chat analytics

### Shipment lifecycle
`CREATED → PICKUP_SCHEDULED → PICKED_UP → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED`
plus `DELIVERY_FAILED`, `CUSTOMER_UNAVAILABLE`, `ADDRESS_ISSUE`, `DAMAGED`, `CANCELLED`, `RETURN_TO_ORIGIN`. Transitions are validated server-side (`backend-fastapi/models/shipment.py`), gated by role, and capped at 3 delivery attempts. Every response carries `allowedNextStatuses` for the caller, so the UI never duplicates the rules.

### ShipBot — AI assistant
Router agent → specialist agents (tracking, delivery issues, shipment schedule, support, general), each with database-backed tools (`get_shipment_status`, `get_my_shipments`, `get_vehicle_status`, `create_complaint`, `get_operations_summary`, …). The reasoning provider is selected with `LLM_PROVIDER`: **Gemini** (default; classification + tool-calling) or a local **Ollama** model (`LLM_PROVIDER=ollama`, runs on the GPU, no cloud dependency). If the chosen provider is unavailable the system does not switch to the other one: it falls back to keyword routing, a database answer for tracking questions, and a rule-based knowledge base. Voice is optional and provider-selectable: speech-to-text is OpenAI Whisper, local faster-whisper (GPU when CUDA works, otherwise CPU) or local ONNX Whisper; text-to-speech is OpenAI TTS or local Piper — see [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md).

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, React Router 6, React-Leaflet, Socket.IO client, Axios, Recharts, lucide-react |
| Backend | Python, FastAPI, Uvicorn, python-socketio |
| Database | MongoDB (Atlas) via Motor + Beanie; falls back to in-memory mongomock if unreachable |
| Auth | PyJWT + bcrypt |
| Maps | OpenStreetMap tiles, Nominatim geocoding, OSRM road routing |
| AI | Google Gemini or local Ollama (classification + tool-calling); voice: OpenAI, faster-whisper / ONNX Whisper, Piper |

## Repository layout

```
backend-fastapi/        the backend (FastAPI + MongoDB)
├── models/             Customer, DeliveryAgent, TrackingLog, DeliveryIssue, Shipment, Admin, …
├── routes/             auth, shipments, vehicles, admin, complaints, support, chat, voice, analytics
├── services/           shipments.py (lifecycle + realtime), llm / stt / tts
├── agents/ tools/      ShipBot router, specialists, DB-backed tools
├── scripts/            bootstrap_real_data.py, verify_sandwich.py, stress_voice_ids.py
├── sockets.py          vehicle feed, shipment rooms, voice stage events
└── tests/              pytest suite (REST, lifecycle, WebSocket, AI tools)
frontend/src/
├── lib/shipora.js      domain constants + wire-name → UI-name mapping (+ tests)
├── hooks/useLive.js    vehicle feed + shipment room hooks
├── components/         ShipmentUI, VehicleMap, LocationPicker, ChatBot, …
└── pages/              UserDashboard, CreateShipment, ShipmentDetail, TrackShipment, DriverDashboard, AdminDashboard, …
docs/                   voice architecture, local voice setup
```

---

## Setup

Prerequisites: Python 3.11+, Node 18+, and (optionally) a MongoDB URI — without one the backend uses an in-memory database that resets on restart.

```bash
# backend
cd backend-fastapi
python -m venv .venv && .venv\Scripts\activate      # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt                     # add requirements-dev.txt to run tests
cp .env.example .env                                # then fill it in
uvicorn main:app --reload --port 5000

# frontend (separate terminal)
cd frontend
npm install
npm start                                           # http://localhost:3000
```

`backend-fastapi/.env`:

```env
PORT=5000
CLIENT_URL=http://localhost:3000
JWT_SECRET=change-me
MONGO_URI=mongodb+srv://…/shipora      # or mongodb://localhost:27017/shipora
GEMINI_API_KEY=…                              # optional — enables ShipBot's AI path
OPENAI_API_KEY=…                              # optional — voice (STT/TTS)
```

The frontend defaults to `http://localhost:5000` for REST and Socket.IO (`REACT_APP_API_URL`, `REACT_APP_SOCKET_URL` to override).

### Tests

```bash
cd backend-fastapi && python -m pytest -q                   # 294 tests, in-memory DB — never touches Atlas
cd frontend && CI=true npm test -- --watchAll=false       # domain-module unit tests
```

### Docker
`docker compose up --build` starts MongoDB and the backend on port 5000. *(Compose file is unchanged from before the Shipora conversion and has not been re-verified.)*

---

## Roles

| UI name | Wire role | Home |
|---------|-----------|------|
| Customer | `user` | `/dashboard` |
| Delivery Agent | `driver` | `/driver` |
| Operations | `admin` | `/admin` |

## Key API endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register/{user,driver,admin}` · `/api/auth/login` | — | Register / login |
| GET·PUT | `/api/auth/profile` | JWT | Profile |
| POST | `/api/shipments` | customer | Create shipment |
| GET | `/api/shipments` | JWT | List (customer: own · agent: assigned · admin: all) |
| GET | `/api/shipments/{id or SHP…}` | JWT | Detail incl. `allowedNextStatuses` |
| GET | `/api/shipments/track/{SHP…}` | — | Public status + timeline |
| PUT | `/api/shipments/{id}/assign` | admin | Assign agent (schedules pickup) |
| POST | `/api/shipments/{id}/status` | JWT | Change status (role-gated, transition-validated) |
| GET | `/api/shipments/stats/summary` | admin | Counts by status |
| POST | `/api/vehicles/status` · `/api/vehicles/area-complete` | agent | Vehicle status / areas covered |
| GET | `/api/vehicles/history` · `/today` | JWT | Tracking logs |
| GET | `/api/admin/stats` · `/drivers` · `/logs` | admin | Operations data |
| GET·POST·PUT | `/api/complaints` | JWT | Delivery issues |
| POST | `/api/chat` · `/api/voice/chat` | optional | ShipBot |
| GET | `/api/health` · `/api/health/ready` | — | Liveness / readiness |

Interactive docs: http://localhost:5000/docs

## Socket events

| Event | Direction | Description |
|-------|-----------|-------------|
| `vehicles:initial` / `vehicles:update` | server → client | Live delivery-vehicle positions |
| `driver:location` / `driver:offline` | client → server | Agent GPS / stop sharing |
| `shipment:join` / `shipment:leave` | client → server | Join a shipment room by tracking number |
| `shipment:update` | server → room | Status changed |
| `voice:join` / `voice:leave` / `voice:stage` | both | Voice conversation progress |

## API notes

Wire-level role strings are `user` (customer), `driver` (delivery agent) and `admin` (operations). Some paths keep short names: `/api/vehicles` (live vehicle tracking), `/api/complaints` (delivery issues) and `/api/auth/register/{user,driver,admin}`. MongoDB collections: `customers`, `delivery_agents`, `delivery_issues`, `tracking_logs`, `shipments`, `admins`, `support_configs`, `chat_analytics`, `conversation_turns`.

Operations (admin) sign-up is closed whenever the app is connected to a real MongoDB: set `ADMIN_SIGNUP_CODE` to allow invite-code sign-ups, or create the first admin with the script below. Open sign-up exists only on the throw-away in-memory dev database. Every account collection has a unique index on `email`.

First-time setup of real data (first admin + support contact details): `backend-fastapi/scripts/bootstrap_real_data.py` (see its docstring). Demo data is only ever seeded into the throw-away in-memory database, never into a real MongoDB.

## License
MIT
