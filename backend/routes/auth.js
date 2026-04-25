const express = require('express');
const jwt = require('jsonwebtoken');
const User = require('../models/User');
const Driver = require('../models/Driver');
const Admin = require('../models/Admin');
const authMiddleware = require('../middleware/auth');

const router = express.Router();
const sign = (payload) =>
  jwt.sign(payload, process.env.JWT_SECRET || 'ecotrack_secret', { expiresIn: '7d' });

// ─── Register User ────────────────────────────────────────────────────────────
router.post('/register/user', async (req, res) => {
  try {
    const { name, email, password, phone, address, location, wasteType, pickupSchedule } = req.body;

    if (await User.findOne({ email }))
      return res.status(400).json({ message: 'Email already registered' });

    const { residentType } = req.body;
    const user = await new User({
      name, email, password, phone, address, location, wasteType, pickupSchedule, residentType
    }).save();

    const token = sign({ id: user._id, role: 'user', name: user.name, email: user.email });
    res.status(201).json({
      token,
      user: { id: user._id, name: user.name, email: user.email, role: 'user',
              location: user.location, address: user.address,
              wasteType: user.wasteType, pickupSchedule: user.pickupSchedule,
              residentType: user.residentType }
    });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Register Driver ──────────────────────────────────────────────────────────
router.post('/register/driver', async (req, res) => {
  try {
    const { name, email, password, phone, vehicleNo, licenseNo, assignedArea } = req.body;

    if (await Driver.findOne({ email }))
      return res.status(400).json({ message: 'Email already registered' });

    const driver = await new Driver({
      name, email, password, phone, vehicleNo, licenseNo, assignedArea
    }).save();

    const token = sign({ id: driver._id, role: 'driver', name: driver.name,
                         email: driver.email, vehicleNo: driver.vehicleNo,
                         assignedArea: driver.assignedArea });
    res.status(201).json({
      token,
      user: { id: driver._id, name: driver.name, email: driver.email, role: 'driver',
              vehicleNo: driver.vehicleNo, assignedArea: driver.assignedArea }
    });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Register Admin ───────────────────────────────────────────────────────────
router.post('/register/admin', async (req, res) => {
  try {
    const { name, email, password, organization } = req.body;
    if (await Admin.findOne({ email }))
      return res.status(400).json({ message: 'Email already registered' });
    const admin = await new Admin({ name, email, password, organization }).save();
    const token = sign({ id: admin._id, role: 'admin', name: admin.name,
                         email: admin.email, organization: admin.organization });
    res.status(201).json({
      token,
      user: { id: admin._id, name: admin.name, email: admin.email,
              role: 'admin', organization: admin.organization }
    });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Login (shared for user, driver & admin) ─────────────────────────────────
router.post('/login', async (req, res) => {
  try {
    const { email, password, role } = req.body;

    const Model = role === 'driver' ? Driver : role === 'admin' ? Admin : User;
    const account = await Model.findOne({ email });
    if (!account) return res.status(400).json({ message: 'Invalid credentials' });

    const ok = await account.comparePassword(password);
    if (!ok) return res.status(400).json({ message: 'Invalid credentials' });

    const base = { id: account._id, role: account.role, name: account.name, email: account.email };
    let extra = {};
    if (role === 'driver')
      extra = { vehicleNo: account.vehicleNo, assignedArea: account.assignedArea };
    else if (role === 'admin')
      extra = { organization: account.organization };
    else
      extra = { location: account.location, address: account.address,
                wasteType: account.wasteType, pickupSchedule: account.pickupSchedule,
                residentType: account.residentType };

    const payload = { ...base, ...extra };
    res.json({ token: sign(payload), user: payload });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Get Profile ──────────────────────────────────────────────────────────────
router.get('/profile', authMiddleware, async (req, res) => {
  try {
    const Model = req.user.role === 'driver' ? Driver : req.user.role === 'admin' ? Admin : User;
    const doc = await Model.findById(req.user.id).select('-password');
    if (!doc) return res.status(404).json({ message: 'Account not found' });
    res.json(doc);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Forgot Password: verify email exists ─────────────────────────────────────
router.post('/forgot-password', async (req, res) => {
  try {
    const { email, role } = req.body;
    const Model = role === 'driver' ? Driver : role === 'admin' ? Admin : User;
    const account = await Model.findOne({ email });
    if (!account)
      return res.status(404).json({ message: 'No account found with this email for the selected role.' });
    res.json({ message: 'Account verified. You can now set a new password.' });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Reset Password ────────────────────────────────────────────────────────────
router.post('/reset-password', async (req, res) => {
  try {
    const { email, role, newPassword } = req.body;
    if (!newPassword || newPassword.length < 6)
      return res.status(400).json({ message: 'Password must be at least 6 characters.' });
    const Model = role === 'driver' ? Driver : role === 'admin' ? Admin : User;
    const account = await Model.findOne({ email });
    if (!account)
      return res.status(404).json({ message: 'Account not found.' });
    account.password = newPassword;
    await account.save();
    res.json({ message: 'Password reset successfully. You can now log in.' });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Update Profile ───────────────────────────────────────────────────────────
router.put('/profile', authMiddleware, async (req, res) => {
  try {
    const allowedUser   = ['name', 'phone', 'address', 'location', 'wasteType', 'pickupSchedule', 'residentType'];
    const allowedDriver = ['name', 'phone', 'assignedArea'];
    const allowedAdmin  = ['name', 'organization'];
    const allowed = req.user.role === 'driver' ? allowedDriver
                  : req.user.role === 'admin'  ? allowedAdmin
                  : allowedUser;

    const updates = {};
    allowed.forEach(f => { if (req.body[f] !== undefined) updates[f] = req.body[f]; });

    const Model = req.user.role === 'driver' ? Driver : req.user.role === 'admin' ? Admin : User;
    const doc = await Model.findByIdAndUpdate(req.user.id, updates, { new: true }).select('-password');
    res.json(doc);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Change Password (requires current password) ──────────────────────────────
router.post('/change-password', authMiddleware, async (req, res) => {
  try {
    const { currentPassword, newPassword } = req.body;
    if (!newPassword || newPassword.length < 6)
      return res.status(400).json({ message: 'New password must be at least 6 characters.' });

    const Model = req.user.role === 'driver' ? Driver : req.user.role === 'admin' ? Admin : User;
    const account = await Model.findById(req.user.id);
    if (!account) return res.status(404).json({ message: 'Account not found.' });

    const ok = await account.comparePassword(currentPassword);
    if (!ok) return res.status(400).json({ message: 'Current password is incorrect.' });

    account.password = newPassword;
    await account.save();
    res.json({ message: 'Password changed successfully.' });
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

module.exports = router;
