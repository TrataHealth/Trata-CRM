import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Contacts from "./pages/Contacts";
import ContactDetail from "./pages/ContactDetail";
import Pipeline from "./pages/Pipeline";
import Activities from "./pages/Activities";
import Tasks from "./pages/Tasks";
import Analytics from "./pages/Analytics";
import Team from "./pages/Team";
import { Toaster } from "sonner";

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-10 text-sm text-[#5E6C84]">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster position="top-right" />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
          <Route path="/contacts" element={<RequireAuth><Contacts /></RequireAuth>} />
          <Route path="/contacts/:id" element={<RequireAuth><ContactDetail /></RequireAuth>} />
          <Route path="/pipeline" element={<RequireAuth><Pipeline /></RequireAuth>} />
          <Route path="/activities" element={<RequireAuth><Activities /></RequireAuth>} />
          <Route path="/tasks" element={<RequireAuth><Tasks /></RequireAuth>} />
          <Route path="/analytics" element={<RequireAuth><Analytics /></RequireAuth>} />
          <Route path="/team" element={<RequireAuth><Team /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
