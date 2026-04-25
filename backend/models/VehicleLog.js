const mongoose = require('mongoose');

const vehicleLogSchema = new mongoose.Schema({
  driverId:       { type: mongoose.Schema.Types.ObjectId, ref: 'Driver', required: true },
  date:           { type: String, required: true },   // e.g. "Mon Apr 18 2024"
  lat:            Number,
  lng:            Number,
  currentArea:    String,
  eta:            String,
  areasCompleted: [String],
  lastUpdated:    Date,
  isActive:       { type: Boolean, default: true }
}, { timestamps: true });

vehicleLogSchema.index({ driverId: 1, date: 1 }, { unique: true });

module.exports = mongoose.model('VehicleLog', vehicleLogSchema);
