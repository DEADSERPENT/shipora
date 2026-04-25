const mongoose = require('mongoose');
const bcrypt = require('bcryptjs');

const userSchema = new mongoose.Schema({
  name:     { type: String, required: true, trim: true },
  email:    { type: String, required: true, unique: true, lowercase: true },
  password: { type: String, required: true, minlength: 6 },
  phone:    { type: String, required: true },
  address:  { type: String, required: true },
  location: {
    lat: { type: Number, required: true },
    lng: { type: Number, required: true }
  },
  wasteType: {
    type: String,
    enum: ['household', 'recyclable', 'organic', 'mixed'],
    default: 'mixed'
  },
  pickupSchedule: {
    type: String,
    enum: ['daily', 'alternate', 'weekly'],
    default: 'daily'
  },
  residentType: {
    type: String,
    enum: ['house', 'flat'],
    default: 'house'
  },
  role: { type: String, default: 'user' }
}, { timestamps: true });

userSchema.pre('save', async function (next) {
  if (!this.isModified('password')) return next();
  this.password = await bcrypt.hash(this.password, 12);
  next();
});

userSchema.methods.comparePassword = function (plain) {
  return bcrypt.compare(plain, this.password);
};

module.exports = mongoose.model('User', userSchema);
