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

### 🤖 EcoBot AI Assistant
- Floating chat widget available on every page
- Answers questions about EcoTrack features, waste disposal, schedules, complaints
- Built-in rule-based responses work **without any API key**
- Upgrades to Claude AI (Haiku) when `ANTHROPIC_API_KEY` is set

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
| Backend   | Node.js, Express.js, Socket.io |
| Database  | MongoDB / Mongoose (auto-falls back to in-memory MongoDB) |
| Auth      | JWT + bcryptjs |
| Maps      | OpenStreetMap tiles, Nominatim geocoding, OSRM road routing |
| AI Chat   | Anthropic Claude Haiku (optional) |

---

## 📁 Project Structure

```
waste-disposal-system/
├── backend/
│   ├── models/
│   │   ├── User.js           # Resident schema
│   │   ├── Driver.js         # Driver schema
│   │   ├── Admin.js          # Admin schema
│   │   ├── VehicleLog.js     # Daily vehicle activity log
│   │   ├── Complaint.js      # Complaints with anonymous flag
│   │   └── SupportConfig.js  # Editable support contact details
│   ├── routes/
│   │   ├── auth.js           # Register / Login / Profile / Password
│   │   ├── vehicles.js       # Vehicle status, logs & history
│   │   ├── admin.js          # Admin stats & driver overview
│   │   ├── complaints.js     # Complaint CRUD
│   │   ├── support.js        # Support config (public read, admin write)
│   │   └── chat.js           # EcoBot AI chat endpoint
│   ├── middleware/
│   │   └── auth.js           # JWT verification middleware
│   └── server.js             # Express + Socket.io server
└── frontend/
    └── src/
        ├── context/
        │   └── AuthContext.js
        ├── components/
        │   ├── Navbar.js
        │   ├── VehicleMap.js         # Leaflet map with 3 km radius + routing
        │   ├── LocationPicker.js     # Map picker with address search & pincode
        │   ├── BackButton.js
        │   ├── ChatBot.js            # EcoBot floating chat widget
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
- Node.js 18+
- MongoDB (optional — falls back to in-memory if not running)

### 1. Clone the repository
```bash
git clone https://github.com/VaibhavKaranth/ecotrack-waste-disposal.git
cd ecotrack-waste-disposal
```

### 2. Backend setup
```bash
cd backend
npm install
```

Create `backend/.env`:
```env
PORT=5000
CLIENT_URL=http://localhost:3000
JWT_SECRET=your_jwt_secret_here
MONGO_URI=mongodb://localhost:27017/waste-disposal
ANTHROPIC_API_KEY=your_api_key_here   # optional — enables AI chat
```

```bash
node server.js
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
| POST | `/api/chat` | — | EcoBot chat |

---

## ⚡ Socket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `vehicles:initial` | Server → Client | Current vehicle state on connect |
| `vehicles:update` | Server → All | Broadcast after any driver update |
| `driver:location` | Client → Server | Driver emits GPS coordinates |
| `driver:offline` | Client → Server | Driver stops sharing |

---

## 🤖 EcoBot Setup (Optional)

EcoBot works out of the box with built-in rule-based answers.  
To enable full Claude AI responses, add to `backend/.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

Get a free key at [console.anthropic.com](https://console.anthropic.com)

---

## 📄 License

MIT — free to use and modify.
