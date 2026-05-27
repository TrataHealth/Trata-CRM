import React, { createContext, useContext, useEffect, useState } from "react";
import api from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem("trata_user");
    const token = localStorage.getItem("trata_token");
    if (stored && token) {
      try { setUser(JSON.parse(stored)); } catch {}
    }
    setLoading(false);
  }, []);

  const login = async (phone, otp) => {
    const { data } = await api.post("/auth/verify-otp", { phone, otp });
    localStorage.setItem("trata_token", data.token);
    localStorage.setItem("trata_user", JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  };

  const sendOtp = async (phone) => {
    const { data } = await api.post("/auth/send-otp", { phone });
    return data;
  };

  const logout = () => {
    localStorage.removeItem("trata_token");
    localStorage.removeItem("trata_user");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, sendOtp, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
