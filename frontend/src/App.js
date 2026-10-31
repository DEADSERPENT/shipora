import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Navbar from './components/Navbar';
import ScrollToTopButton from './components/ScrollToTopButton';
import ChatBot from './components/ChatBot';
import Home from './pages/Home';
import Login from './pages/Login';
import Register from './pages/Register';
import UserDashboard from './pages/UserDashboard';
import DriverDashboard from './pages/DriverDashboard';
import AdminDashboard from './pages/AdminDashboard';
import ForgotPassword from './pages/ForgotPassword';
import Profile from './pages/Profile';
import AgentHistory from './pages/AgentHistory';
import ShipmentHistory from './pages/ShipmentHistory';
import DeliveryIssues from './pages/DeliveryIssues';
import CreateShipment from './pages/CreateShipment';
import ShipmentDetail from './pages/ShipmentDetail';
import TrackShipment from './pages/TrackShipment';
import Support from './pages/Support';
import { roleHome } from './lib/shipora';
import 'leaflet/dist/leaflet.css';

// Role names in the router are the backend's wire-level roles (user / driver / admin);
// the UI shows them as Customer / Delivery Agent / Operations (see lib/shipora.js).
const ProtectedRoute = ({ children, allowedRole }) => {
  const { user, loading } = useAuth();
  if (loading) return (
    <div className="loading-screen">
      <div className="spinner" />
      <p style={{ color: 'var(--muted)', fontWeight: 600 }}>Loading Shipora…</p>
    </div>
  );
  if (!user) return <Navigate to="/login" replace />;
  if (allowedRole && user.role !== allowedRole) return <Navigate to="/" replace />;
  return children;
};

const HomeRedirect = () => {
  const { user } = useAuth();
  if (!user) return <Navigate to="/" replace />;
  return <Navigate to={roleHome(user.role)} replace />;
};

// /shipments/:id is open to every signed-in role; the backend decides what each may see.
const ShipmentRoute = () => {
  const { trackingNumber } = useParams();
  return <ShipmentDetail key={trackingNumber} />;
};

function AppRoutes() {
  const { user } = useAuth();
  return (
    <>
      <Navbar />
      <ScrollToTopButton />
      <ChatBot />
      <Routes>
        <Route path="/"                element={user ? <HomeRedirect /> : <Home />} />
        <Route path="/login"           element={user ? <HomeRedirect /> : <Login />} />
        <Route path="/register"        element={user ? <HomeRedirect /> : <Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />

        {/* Public tracking — no sign-in needed */}
        <Route path="/track"               element={<TrackShipment />} />
        <Route path="/track/:trackingNumber" element={<TrackShipment />} />

        <Route path="/dashboard" element={<ProtectedRoute allowedRole="user"><UserDashboard /></ProtectedRoute>} />
        <Route path="/driver"    element={<ProtectedRoute allowedRole="driver"><DriverDashboard /></ProtectedRoute>} />
        <Route path="/admin"     element={<ProtectedRoute allowedRole="admin"><AdminDashboard /></ProtectedRoute>} />
        <Route path="/profile"   element={<ProtectedRoute><Profile /></ProtectedRoute>} />

        {/* Customer */}
        <Route path="/shipments"         element={<ProtectedRoute allowedRole="user"><ShipmentHistory initialFilter="all" /></ProtectedRoute>} />
        <Route path="/shipments/history" element={<ProtectedRoute allowedRole="user"><ShipmentHistory initialFilter="history" /></ProtectedRoute>} />
        <Route path="/shipments/new"     element={<ProtectedRoute allowedRole="user"><CreateShipment /></ProtectedRoute>} />
        <Route path="/issues"            element={<ProtectedRoute allowedRole="user"><DeliveryIssues /></ProtectedRoute>} />

        {/* Any signed-in role */}
        <Route path="/shipments/:trackingNumber" element={<ProtectedRoute><ShipmentRoute /></ProtectedRoute>} />

        {/* Delivery agent */}
        <Route path="/agent/history" element={<ProtectedRoute allowedRole="driver"><AgentHistory /></ProtectedRoute>} />

        <Route path="/support" element={<Support />} />

        <Route path="*" element={<HomeRedirect />} />
      </Routes>
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}
