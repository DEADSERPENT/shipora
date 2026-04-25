const mongoose = require('mongoose');

const complaintSchema = new mongoose.Schema({
  residentId:    { type: mongoose.Schema.Types.ObjectId, ref: 'User' },
  residentName:  { type: String },
  residentEmail: { type: String },
  isAnonymous:   { type: Boolean, default: false },
  subject:       { type: String, required: true },
  category:      { type: String, required: true,
                   enum: ['missed_pickup', 'vehicle_issue', 'timing', 'cleanliness', 'driver_behaviour', 'other'] },
  description:   { type: String, required: true },
  status:        { type: String, default: 'open',
                   enum: ['open', 'in_progress', 'resolved', 'closed'] },
  adminReply:    { type: String, default: '' },
  resolvedAt:    { type: Date },
}, { timestamps: true });

module.exports = mongoose.model('Complaint', complaintSchema);
