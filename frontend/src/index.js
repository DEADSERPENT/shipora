import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import './public.css';
import './trackpage.css';
import App from './App';

// Fix Leaflet default marker icons with webpack
import L from 'leaflet';
import iconUrl from 'leaflet/dist/images/marker-icon.png';
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png';
import iconShadowUrl from 'leaflet/dist/images/marker-shadow.png';

delete L.Icon.Default.prototype._getIconUrl;
// Set all three explicitly: Leaflet otherwise derives iconRetinaUrl relative to the current route (404 on nested routes).
L.Icon.Default.mergeOptions({ iconUrl, iconRetinaUrl, shadowUrl: iconShadowUrl });

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
