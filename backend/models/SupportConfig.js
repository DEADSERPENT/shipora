const mongoose = require('mongoose');

const supportConfigSchema = new mongoose.Schema({
  singleton:     { type: String, default: 'config', unique: true },
  phone:         { type: String, default: '1800-ECO-TRACK' },
  email:         { type: String, default: 'support@ecotrack.in' },
  whatsapp:      { type: String, default: '+91 98765 43210' },
  officeAddress: { type: String, default: 'City Municipal Office, Ground Floor, Civic Center' },
  officeHours:   { type: String, default: 'Mon – Fri · 9 AM – 5 PM' },
}, { timestamps: true });

module.exports = mongoose.model('SupportConfig', supportConfigSchema);
