const express = require('express');
const authMiddleware = require('../middleware/auth');
const VehicleLog = require('../models/VehicleLog');
const Driver = require('../models/Driver');
const User = require('../models/User');

const router = express.Router();

const adminOnly = (req, res, next) => {
  if (req.user.role !== 'admin')
    return res.status(403).json({ message: 'Admin access required' });
  next();
};

// ─── Overall stats + today's logs ─────────────────────────────────────────────
router.get('/stats', authMiddleware, adminOnly, async (_req, res) => {
  try {
    const today = new Date().toDateString();
    const [totalDrivers, totalResidents, todayLogs] = await Promise.all([
      Driver.countDocuments(),
      User.countDocuments(),
      VehicleLog.find({ date: today })
        .populate('driverId', 'name vehicleNo assignedArea phone')
    ]);
    const activeToday = todayLogs.filter(l => l.isActive).length;
    const totalAreasCompleted = todayLogs.reduce(
      (sum, l) => sum + (l.areasCompleted?.length || 0), 0
    );
    res.json({ totalDrivers, totalResidents, activeToday, totalAreasCompleted, todayLogs });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Logs filtered by date ─────────────────────────────────────────────────────
router.get('/logs', authMiddleware, adminOnly, async (req, res) => {
  try {
    const date = req.query.date || new Date().toDateString();
    const logs = await VehicleLog.find({ date })
      .populate('driverId', 'name vehicleNo assignedArea phone email')
      .sort({ lastUpdated: -1 });
    res.json(logs);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── All drivers with today's log ─────────────────────────────────────────────
router.get('/drivers', authMiddleware, adminOnly, async (_req, res) => {
  try {
    const [drivers, logs] = await Promise.all([
      Driver.find().select('-password').sort({ createdAt: -1 }),
      VehicleLog.find({ date: new Date().toDateString() })
    ]);
    const logMap = {};
    logs.forEach(l => { logMap[l.driverId.toString()] = l; });
    res.json(drivers.map(d => ({
      ...d.toObject(),
      todayLog: logMap[d._id.toString()] || null
    })));
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

module.exports = router;
