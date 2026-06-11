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

  const sendOtp = async (phone) => {
    const { data } = await api.post("/auth/send-otp", { phone });
    return data;
  };

  const verifyOtp = async (phone, otp) => {
    const { data } = await api.post("/auth/verify-otp", { phone, otp });
    // returns { needs_password_setup, temp_token, user }
    return data;
  };

  const setPassword = async (tempToken, password) => {
    const { data } = await api.post(
      "/auth/set-password",
      { password },
      { headers: { Authorization: `Bearer ${tempToken}` } }
    );
    _persist(data.user, data.token);
    return data.user;
  };

  const loginPassword = async (tempToken, password) => {
    const { data } = await api.post(
      "/auth/login-password",
      { password },
      { headers: { Authorization: `Bearer ${tempToken}` } }
    );
    _persist(data.user, data.token);
    return data.user;
  };

  const _persist = (u, t) => {
    localStorage.setItem("trata_token", t);
    localStorage.setItem("trata_user", JSON.stringify(u));
    setUser(u);
  };

  const logout = () => {
    localStorage.removeItem("trata_token");
    localStorage.removeItem("trata_user");
    setUser(null);
  };

  const isInternal = !!user && (
    user.is_master_admin ||
    ["admin", "manager", "sales_rep", "ops_rep"].includes(user.role)
  );
  const isProvider = user?.role === "provider_owner";
  const isSalesRep = !!user && user.role === "sales_rep" && !user.is_master_admin;
  const isAdmin = !!user && (user.is_master_admin || ["admin", "manager"].includes(user.role));

  return (
    <AuthContext.Provider value={{
      user, loading, sendOtp, verifyOtp, setPassword, loginPassword, logout,
      isInternal, isProvider, isSalesRep, isAdmin,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
