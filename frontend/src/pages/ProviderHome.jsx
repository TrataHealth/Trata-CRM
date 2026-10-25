import React from "react";
import { useAuth } from "../lib/auth";
import ProviderDashboard from "./ProviderDashboard";
import PharmacyDashboard from "./PharmacyDashboard";

export default function ProviderHome() {
  const { user } = useAuth();
  return user?.provider_type === "pharmacy" ? <PharmacyDashboard /> : <ProviderDashboard />;
}
