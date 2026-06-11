import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import InstallPrompt from "./components/InstallPrompt";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Contacts from "./pages/Contacts";
import ContactDetail from "./pages/ContactDetail";
import Pipeline from "./pages/Pipeline";
import Activities from "./pages/Activities";
import Tasks from "./pages/Tasks";
import Analytics from "./pages/Analytics";
import Team from "./pages/Team";
import ProviderDashboard from "./pages/ProviderDashboard";
import ProviderActivities from "./pages/ProviderActivities";
import ProviderProfile from "./pages/ProviderProfile";
import ProviderEarnings from "./pages/ProviderEarnings";
import AgentDashboard from "./pages/AgentDashboard";
import AgentLeads from "./pages/AgentLeads";
import Leaderboard from "./pages/Leaderboard";
import ForgotPassword from "./pages/ForgotPassword";
import SecuritySetup from "./pages/SecuritySetup";
import Settings from "./pages/Settings";
import { Toaster } from "sonner";
import { registerSW } from "./lib/registerSW";

registerSW();

function RequireAuth({ children, internalOnly = false, providerOnly = false, adminOnly = false, allowSetupGate = false }) {
  const { user, loading, isInternal, isProvider, isAdmin, isSalesRep } = useAuth();
  if (loading) return <div className="p-10 text-sm text-[#5E6C84]">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!allowSetupGate && user.security_setup_required) return <Navigate to="/security-setup" replace />;
  if (adminOnly && !isAdmin) return <Navigate to={isSalesRep ? "/agent" : "/provider"} replace />;
  if (internalOnly && !isInternal) return <Navigate to="/provider" replace />;
  if (providerOnly && !isProvider) return <Navigate to={isSalesRep ? "/agent" : "/"} replace />;
  return <Layout>{children}</Layout>;
}

function RoleRoot() {
  const { user, loading, isProvider, isSalesRep } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (user.security_setup_required) return <Navigate to="/security-setup" replace />;
  if (isProvider) return <Navigate to="/provider" replace />;
  if (isSalesRep) return <Navigate to="/agent" replace />;
  return <Dashboard />;
}

function SecuritySetupRoute() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.security_setup_required) {
    // Already set up — bounce to home
    return <Navigate to="/" replace />;
  }
  return <SecuritySetup />;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster position="top-right" />
        <InstallPrompt />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/forgot" element={<ForgotPassword />} />
          <Route path="/security-setup" element={<SecuritySetupRoute />} />
          <Route path="/settings" element={<RequireAuth><Settings /></RequireAuth>} />

          {/* Admin / internal routes */}
          <Route path="/" element={<RequireAuth><RoleRoot /></RequireAuth>} />
          <Route path="/contacts" element={<RequireAuth internalOnly><Contacts /></RequireAuth>} />
          <Route path="/contacts/:id" element={<RequireAuth internalOnly><ContactDetail /></RequireAuth>} />
          <Route path="/pipeline" element={<RequireAuth internalOnly><Pipeline /></RequireAuth>} />
          <Route path="/activities" element={<RequireAuth internalOnly><Activities /></RequireAuth>} />
          <Route path="/analytics" element={<RequireAuth adminOnly><Analytics /></RequireAuth>} />
          <Route path="/team" element={<RequireAuth adminOnly><Team /></RequireAuth>} />

          {/* Shared (admins + providers + sales reps) */}
          <Route path="/tasks" element={<RequireAuth><Tasks /></RequireAuth>} />

          {/* Sales Agent routes */}
          <Route path="/agent" element={<RequireAuth internalOnly><AgentDashboard /></RequireAuth>} />
          <Route path="/agent/leads" element={<RequireAuth internalOnly><AgentLeads /></RequireAuth>} />
          <Route path="/agent/leaderboard" element={<RequireAuth adminOnly><Leaderboard /></RequireAuth>} />

          {/* Provider routes */}
          <Route path="/provider" element={<RequireAuth providerOnly><ProviderDashboard /></RequireAuth>} />
          <Route path="/provider/activities" element={<RequireAuth providerOnly><ProviderActivities /></RequireAuth>} />
          <Route path="/provider/earnings" element={<RequireAuth providerOnly><ProviderEarnings /></RequireAuth>} />
          <Route path="/provider/profile" element={<RequireAuth providerOnly><ProviderProfile /></RequireAuth>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
