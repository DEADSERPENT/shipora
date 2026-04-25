const express = require('express');
const authMiddleware = require('../middleware/auth');
const Complaint = require('../models/Complaint');

const router = express.Router();

// ─── Resident: submit complaint ───────────────────────────────────────────────
router.post('/', authMiddleware, async (req, res) => {
  try {
    if (req.user.role !== 'user')
      return res.status(403).json({ message: 'Only residents can submit complaints.' });
    const { subject, category, description, isAnonymous } = req.body;
    if (!subject || !category || !description)
      return res.status(400).json({ message: 'Subject, category and description are required.' });

    const doc = {
      subject, category, description,
      isAnonymous: !!isAnonymous,
    };
    if (!isAnonymous) {
      doc.residentId    = req.user.id;
      doc.residentName  = req.user.name;
      doc.residentEmail = req.user.email;
    }

    const complaint = await new Complaint(doc).save();
    res.status(201).json(complaint);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Get complaints ───────────────────────────────────────────────────────────
// Admin: all; resident: own (non-anonymous only, since anonymous have no residentId)
router.get('/', authMiddleware, async (req, res) => {
  try {
    let complaints;
    if (req.user.role === 'admin') {
      complaints = await Complaint.find({}).sort({ createdAt: -1 });
    } else {
      complaints = await Complaint.find({ residentId: req.user.id }).sort({ createdAt: -1 });
    }

    // Mask identity of anonymous complaints for admin view
    if (req.user.role === 'admin') {
      complaints = complaints.map(c => {
        const obj = c.toObject();
        if (obj.isAnonymous) {
          obj.residentName  = 'Anonymous';
          obj.residentEmail = '—';
        }
        return obj;
      });
    }

    res.json(complaints);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

// ─── Admin: update status and reply ──────────────────────────────────────────
router.put('/:id', authMiddleware, async (req, res) => {
  try {
    if (req.user.role !== 'admin')
      return res.status(403).json({ message: 'Admin only.' });
    const { status, adminReply } = req.body;
    const updates = {};
    if (status)                    updates.status     = status;
    if (adminReply !== undefined)  updates.adminReply = adminReply;
    if (status === 'resolved' || status === 'closed') updates.resolvedAt = new Date();
    const c = await Complaint.findByIdAndUpdate(req.params.id, updates, { new: true });
    if (!c) return res.status(404).json({ message: 'Complaint not found.' });
    res.json(c);
  } catch (err) {
    res.status(500).json({ message: err.message });
  }
});

module.exports = router;
