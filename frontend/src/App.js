import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Navbar from './components/Navbar';
import ScrollToTopButton from './components/ScrollToTopButton';
import ChatBot from './components/ChatBot';
import Login from './pages/Login';
import Register from './pages/Register';
import UserDashboard from './pages/UserDashboard';
import DriverDashboard from './pages/DriverDashboard';
import AdminDashboard from './pages/AdminDashboard';
import ForgotPassword from './pages/ForgotPassword';
import Profile from './pages/Profile';
import DriverHistory from './pages/DriverHistory';
import CollectionLog from './pages/CollectionLog';
import ComplaintBox from './pages/ComplaintBox';
import Support from './pages/Support';
import 'leaflet/dist/leaflet.css';

const ProtectedRoute = ({ children, allowedRole }) => {
  const { user, loading } = useAuth();
  if (loading) return (
    <div className="loading-screen">
      <div className="spinner" />
      <p style={{ color: '#6b8f6b', fontWeight: 600 }}>Loading EcoTrack…</p>
    </div>
  );
  if (!user) return <Navigate to="/login" replace />;
  if (allowedRole && user.role !== allowedRole) return <Navigate to="/" replace />;
  return children;
};

const HomeRedirect = () => {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === 'driver') return <Navigate to="/driver" replace />;
  if (user.role === 'admin')  return <Navigate to="/admin"  replace />;
  return <Navigate to="/dashboard" replace />;
};

function AppRoutes() {
  const { user } = useAuth();
  return (
    <>
      <Navbar />
      <ScrollToTopButton />
      <ChatBot />
      <Routes>
        <Route path="/login"           element={user ? <HomeRedirect /> : <Login />} />
        <Route path="/register"        element={user ? <HomeRedirect /> : <Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/dashboard" element={
          <ProtectedRoute allowedRole="user"><UserDashboard /></ProtectedRoute>
        } />
        <Route path="/driver" element={
          <ProtectedRoute allowedRole="driver"><DriverDashboard /></ProtectedRoute>
        } />
        <Route path="/admin" element={
          <ProtectedRoute allowedRole="admin"><AdminDashboard /></ProtectedRoute>
        } />
        <Route path="/profile" element={
          <ProtectedRoute><Profile /></ProtectedRoute>
        } />
        <Route path="/driver-history" element={
          <ProtectedRoute allowedRole="driver"><DriverHistory /></ProtectedRoute>
        } />
        <Route path="/collection-log" element={
          <ProtectedRoute allowedRole="user"><CollectionLog /></ProtectedRoute>
        } />
        <Route path="/complaints" element={
          <ProtectedRoute allowedRole="user"><ComplaintBox /></ProtectedRoute>
        } />
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
