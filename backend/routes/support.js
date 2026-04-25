const express = require('express');
const authMiddleware = require('../middleware/auth');
const SupportConfig  = require('../models/SupportConfig');

const router = express.Router();

const DEFAULTS = {
  phone:         '1800-ECO-TRACK',
  email:         'support@ecotrack.in',
  whatsapp:      '+91 98765 43210',
  officeAddress: 'City Municipal Office, Ground Floor, Civic Center',
  officeHours:   'Mon – Fri · 9 AM – 5 PM',
};

// ─── Public: get support config ───────────────────────────────────────────────
router.get('/config', async (_req, res) => {
  try {
    const config = await SupportConfig.findOne({ singleton: 'config' });
    res.json(config || DEFAULTS);
  } catch {
    res.json(DEFAULTS);
  }
});

// ─── Admin: update support config ─────────────────────────────────────────────
router.put('/config', authMiddleware, async (req, res) => {
  try {
    if (req.user.role !== 'admin')
      return res.status(403).json({ message: 'Admin only.' });
    const allowed = ['phone', 'email', 'whatsapp', 'officeAddress', 'officeHours'];
    const updates = {};
    allowed.forEach(f => { if (req.body[f] !== undefined) updates[f] = req.body[f]; });
    const config = await SupportConfig.findOneAndUpdate(
      { singleton: 'config' },
      { $set: updates },
      { new: true, upsert: true }
    );
    res.json(config);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

module.exports = router;
