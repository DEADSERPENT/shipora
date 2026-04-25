const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const http = require('http');
const { Server } = require('socket.io');
require('dotenv').config();

// ── MongoDB connection (real or in-memory fallback) ───────────────────────────
async function connectDB() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017/waste-disposal';
  try {
    await mongoose.connect(uri, { serverSelectionTimeoutMS: 3000 });
    console.log('✅ MongoDB Connected:', uri);
  } catch {
    console.log('⚠️  Local MongoDB not found — starting in-memory MongoDB...');
    const { MongoMemoryServer } = require('mongodb-memory-server');
    const memServer = await MongoMemoryServer.create();
    await mongoose.connect(memServer.getUri() + 'waste-disposal');
    console.log('✅ In-memory MongoDB started (data resets on restart)');
  }
}
connectDB();

const app = express();
const server = http.createServer(app);

const io = new Server(server, {
  cors: {
    origin: process.env.CLIENT_URL || 'http://localhost:3000',
    methods: ['GET', 'POST'],
    credentials: true
  }
});

// Middleware
app.use(cors({
  origin: process.env.CLIENT_URL || 'http://localhost:3000',
  credentials: true
}));
app.use(express.json());


// In-memory store for active vehicle locations
const vehicleLocations = {};

// ── Socket.IO ────────────────────────────────────────────────────────────────
io.on('connection', (socket) => {
  console.log(`📡 Client connected: ${socket.id}`);

  // Send current locations to newly connected client
  socket.emit('vehicles:initial', vehicleLocations);

  // Driver broadcasts their GPS location
  socket.on('driver:location', async (data) => {
    const { driverId, lat, lng, driverName, vehicleNo, currentArea, eta, areasCompleted } = data;

    vehicleLocations[driverId] = {
      driverId,
      lat,
      lng,
      driverName,
      vehicleNo,
      currentArea: currentArea || 'N/A',
      eta: eta || 'N/A',
      areasCompleted: areasCompleted || [],
      lastUpdated: new Date().toISOString(),
      isActive: true
    };

    // Broadcast to ALL clients
    io.emit('vehicles:update', vehicleLocations);

    // Persist to MongoDB
    try {
      const VehicleLog = require('./models/VehicleLog');
      await VehicleLog.findOneAndUpdate(
        { driverId, date: new Date().toDateString() },
        {
          $set: { lat, lng, currentArea, eta, lastUpdated: new Date(), isActive: true },
          $addToSet: areasCompleted && areasCompleted.length
            ? { areasCompleted: { $each: areasCompleted } }
            : { areasCompleted: { $each: [] } }
        },
        { upsert: true, new: true }
      );
    } catch (err) {
      console.error('VehicleLog save error:', err.message);
    }
  });

  // Driver marks themselves offline
  socket.on('driver:offline', (driverId) => {
    if (vehicleLocations[driverId]) {
      vehicleLocations[driverId].isActive = false;
      vehicleLocations[driverId].lastUpdated = new Date().toISOString();
      io.emit('vehicles:update', vehicleLocations);
    }
  });

  socket.on('disconnect', () => {
    console.log(`📡 Client disconnected: ${socket.id}`);
  });
});

// Make io & vehicleLocations accessible in route handlers
app.set('io', io);
app.set('vehicleLocations', vehicleLocations);

// ── API Routes ────────────────────────────────────────────────────────────────
app.use('/api/auth', require('./routes/auth'));
app.use('/api/vehicles', require('./routes/vehicles'));
app.use('/api/admin', require('./routes/admin'));
app.use('/api/complaints', require('./routes/complaints'));
app.use('/api/support', require('./routes/support'));
app.use('/api/chat',   require('./routes/chat'));

app.get('/api/health', (_req, res) =>
  res.json({ status: 'OK', timestamp: new Date().toISOString() })
);

// ── Start Server ──────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 5000;
server.listen(PORT, () =>
  console.log(`🚀 Server running on http://localhost:${PORT}`)
);
