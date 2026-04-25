const mongoose = require('mongoose');
const bcrypt = require('bcryptjs');

const driverSchema = new mongoose.Schema({
  name:         { type: String, required: true, trim: true },
  email:        { type: String, required: true, unique: true, lowercase: true },
  password:     { type: String, required: true, minlength: 6 },
  phone:        { type: String, required: true },
  vehicleNo:    { type: String, required: true, uppercase: true },
  licenseNo:    { type: String, required: true, uppercase: true },
  assignedArea: { type: String, required: true },
  role:         { type: String, default: 'driver' }
}, { timestamps: true });

driverSchema.pre('save', async function (next) {
  if (!this.isModified('password')) return next();
  this.password = await bcrypt.hash(this.password, 12);
  next();
});

driverSchema.methods.comparePassword = function (plain) {
  return bcrypt.compare(plain, this.password);
};

module.exports = mongoose.model('Driver', driverSchema);
