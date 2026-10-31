// "Areas we serve" — neighbourhood centres across Bengaluru. Used by the home page estimate form (pick pickup / drop
// by area name, like Porter's "Areas We Serve") and to pre-pin the booking form. Coordinates are approximate area
// centres; the exact pin is still chosen on the map when booking.
export const BENGALURU_AREAS = [
  { name: 'Banashankari',          lat: 12.9255, lng: 77.5468 },
  { name: 'Banaswadi',             lat: 13.0140, lng: 77.6510 },
  { name: 'Bannerghatta Road',     lat: 12.8930, lng: 77.5970 },
  { name: 'Basavanagudi',          lat: 12.9423, lng: 77.5736 },
  { name: 'Begur',                 lat: 12.8786, lng: 77.6212 },
  { name: 'Bellandur',             lat: 12.9304, lng: 77.6784 },
  { name: 'Bommanahalli',          lat: 12.9081, lng: 77.6238 },
  { name: 'BTM Layout',            lat: 12.9166, lng: 77.6101 },
  { name: 'Domlur',                lat: 12.9610, lng: 77.6387 },
  { name: 'Electronic City',       lat: 12.8452, lng: 77.6602 },
  { name: 'Frazer Town',           lat: 12.9990, lng: 77.6150 },
  { name: 'Halasuru',              lat: 12.9810, lng: 77.6270 },
  { name: 'Hebbal',                lat: 13.0358, lng: 77.5970 },
  { name: 'Hennur',                lat: 13.0360, lng: 77.6380 },
  { name: 'HSR Layout',            lat: 12.9116, lng: 77.6474 },
  { name: 'Indiranagar',           lat: 12.9719, lng: 77.6412 },
  { name: 'Jayanagar',             lat: 12.9308, lng: 77.5838 },
  { name: 'JP Nagar',              lat: 12.9063, lng: 77.5857 },
  { name: 'Kalyan Nagar',          lat: 13.0250, lng: 77.6420 },
  { name: 'Kempegowda Airport',    lat: 13.1989, lng: 77.7068 },
  { name: 'Kengeri',               lat: 12.9140, lng: 77.4830 },
  { name: 'Koramangala',           lat: 12.9352, lng: 77.6245 },
  { name: 'Kumaraswamy Layout',    lat: 12.9086, lng: 77.5656 },
  { name: 'Mahadevapura',          lat: 12.9910, lng: 77.6960 },
  { name: 'Majestic',              lat: 12.9767, lng: 77.5713 },
  { name: 'Malleshwaram',          lat: 13.0035, lng: 77.5647 },
  { name: 'Marathahalli',          lat: 12.9569, lng: 77.7011 },
  { name: 'MG Road',               lat: 12.9758, lng: 77.6064 },
  { name: 'Nagarbhavi',            lat: 12.9606, lng: 77.5100 },
  { name: 'Nagawara',              lat: 13.0450, lng: 77.6200 },
  { name: 'Peenya',                lat: 13.0285, lng: 77.5197 },
  { name: 'Rajajinagar',           lat: 12.9911, lng: 77.5524 },
  { name: 'RT Nagar',              lat: 13.0210, lng: 77.5960 },
  { name: 'Sanjay Nagar',          lat: 13.0378, lng: 77.5760 },
  { name: 'Sarjapur Road',         lat: 12.9100, lng: 77.6870 },
  { name: 'Shivajinagar',          lat: 12.9857, lng: 77.6057 },
  { name: 'Varthur',               lat: 12.9390, lng: 77.7410 },
  { name: 'Vijayanagar',           lat: 12.9719, lng: 77.5300 },
  { name: 'Whitefield',            lat: 12.9698, lng: 77.7500 },
  { name: 'Yelahanka',             lat: 13.1007, lng: 77.5963 },
  { name: 'Yeshwanthpur',          lat: 13.0285, lng: 77.5409 },
];

export const findArea = (name) => {
  const q = (name || '').trim().toLowerCase();
  return q ? BENGALURU_AREAS.find(a => a.name.toLowerCase() === q) || null : null;
};
