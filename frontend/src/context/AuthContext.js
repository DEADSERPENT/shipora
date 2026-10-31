import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API_URL, TOKEN_KEY } from '../lib/shipora';

const AuthContext = createContext(null);

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};

const API = API_URL;
const USER_KEY  = 'shipora_user';

export const AuthProvider = ({ children }) => {
  const [user,    setUser]    = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    const saved = localStorage.getItem(USER_KEY);
    if (token && saved) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      setUser(JSON.parse(saved));
    }
    setLoading(false);
  }, []);

  // A 401 anywhere (expired/invalid JWT) logs the user out instead of leaving a dead session.
  useEffect(() => {
    const id = axios.interceptors.response.use(r => r, (err) => {
      const url = err.config?.url || '';
      if (err.response?.status === 401 && !url.includes('/auth/login') && localStorage.getItem(TOKEN_KEY)) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        delete axios.defaults.headers.common['Authorization'];
        setUser(null);
      }
      return Promise.reject(err);
    });
    return () => axios.interceptors.response.eject(id);
  }, []);

  const persist = (token, userData) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(userData));
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
    const current = JSON.parse(localStorage.getItem(USER_KEY) || '{}');
    const merged = { ...current, ...updates };
    localStorage.setItem(USER_KEY, JSON.stringify(merged));
    setUser(merged);
    return data;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    delete axios.defaults.headers.common['Authorization'];
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, register, updateProfile, logout, loading, API }}>
      {children}
    </AuthContext.Provider>
  );
};
