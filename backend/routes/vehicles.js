const express = require('express');
const authMiddleware = require('../middleware/auth');
const VehicleLog = require('../models/VehicleLog');

const router = express.Router();

// ─── Get current live vehicle locations (in-memory) ───────────────────────────
router.get('/locations', (_req, res) => {
  res.json(res.app.get('vehicleLocations') || {});
});

// ─── Get today's logs ─────────────────────────────────────────────────────────
router.get('/today', authMiddleware, async (_req, res) => {
  try {
    const logs = await VehicleLog.find({ date: new Date().toDateString() })
      .populate('driverId', 'name vehicleNo assignedArea phone');
    res.json(logs);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── 30-day history (driver: own logs; resident/admin: all logs) ─────────────
router.get('/history', authMiddleware, async (req, res) => {
  try {
    const days = Math.min(parseInt(req.query.days) || 30, 30);
    const dates = Array.from({ length: days }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - i);
      return d.toDateString();
    });

    let logs;
    if (req.user.role === 'driver') {
      logs = await VehicleLog.find({ driverId: req.user.id, date: { $in: dates } })
        .sort({ createdAt: -1 });
    } else {
      logs = await VehicleLog.find({ date: { $in: dates } })
        .populate('driverId', 'name vehicleNo assignedArea')
        .sort({ createdAt: -1 });
    }
    res.json(logs);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Driver: update status (area + ETA) ──────────────────────────────────────
router.post('/status', authMiddleware, async (req, res) => {
  try {
    if (req.user.role !== 'driver')
      return res.status(403).json({ message: 'Drivers only' });

    const { currentArea, eta, areasCompleted } = req.body;
    const today = new Date().toDateString();

    const log = await VehicleLog.findOneAndUpdate(
      { driverId: req.user.id, date: today },
      {
        $set: { currentArea, eta, lastUpdated: new Date() },
        $addToSet: areasCompleted?.length
          ? { areasCompleted: { $each: areasCompleted } }
          : {}
      },
      { upsert: true, new: true }
    );

    // Sync to in-memory store & broadcast
    const vehicleLocations = req.app.get('vehicleLocations');
    if (vehicleLocations[req.user.id]) {
      vehicleLocations[req.user.id] = {
        ...vehicleLocations[req.user.id],
        currentArea,
        eta,
        areasCompleted: log.areasCompleted
      };
      req.app.get('io').emit('vehicles:update', vehicleLocations);
    }

    res.json(log);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Driver: add completed area ───────────────────────────────────────────────
router.post('/area-complete', authMiddleware, async (req, res) => {
  try {
    if (req.user.role !== 'driver')
      return res.status(403).json({ message: 'Drivers only' });

    const { area } = req.body;
    const today = new Date().toDateString();

    const log = await VehicleLog.findOneAndUpdate(
      { driverId: req.user.id, date: today },
      { $addToSet: { areasCompleted: area }, $set: { lastUpdated: new Date() } },
      { upsert: true, new: true }
    );

    const vehicleLocations = req.app.get('vehicleLocations');
    if (vehicleLocations[req.user.id]) {
      vehicleLocations[req.user.id].areasCompleted = log.areasCompleted;
      req.app.get('io').emit('vehicles:update', vehicleLocations);
    }

    res.json(log);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

module.exports = router;
