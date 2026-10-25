import React from "react";
import EntitiesPanel from "../components/EntitiesPanel";
import { useAuth } from "../lib/auth";

export default function ProviderEntities() {
  const { user } = useAuth();
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 max-w-5xl" data-testid="provider-entities-page">
      <div>
        <div className="overline">Organisation</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{user?.business_name || "Your organisation"}</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Add branches and units under your organisation, then open any of them for its summary. Same as the Provider app.</p>
      </div>
      <EntitiesPanel base="/provider/entities" linkBase="/provider/entities" />
    </div>
  );
}
