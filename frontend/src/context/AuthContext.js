import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import axios from 'axios';

const AuthContext = createContext(null);

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};

const API = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

export const AuthProvider = ({ children }) => {
  const [user,    setUser]    = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('eco_token');
    const saved = localStorage.getItem('eco_user');
    if (token && saved) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      setUser(JSON.parse(saved));
    }
    setLoading(false);
  }, []);

  const persist = (token, userData) => {
    localStorage.setItem('eco_token', token);
    localStorage.setItem('eco_user', JSON.stringify(userData));
    axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    setUser(userData);
  };

  const login = useCallback(async (email, password, role) => {
    const { data } = await axios.post(`${API}/auth/login`, { email, password, role });
    persist(data.token, data.user);
    return data.user;
  }, []);

  const register = useCallback(async (formData, role) => {
    const { data } = await axios.post(`${API}/auth/register/${role}`, formData);
    persist(data.token, data.user);
    return data.user;
  }, []);

  const updateProfile = useCallback(async (updates) => {
    const { data } = await axios.put(`${API}/auth/profile`, updates);
    const current = JSON.parse(localStorage.getItem('eco_user') || '{}');
    const merged = { ...current, ...updates };
    localStorage.setItem('eco_user', JSON.stringify(merged));
    setUser(merged);
    return data;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('eco_token');
    localStorage.removeItem('eco_user');
    delete axios.defaults.headers.common['Authorization'];
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, register, updateProfile, logout, loading, API }}>
      {children}
    </AuthContext.Provider>
  );
};
