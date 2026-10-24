import React from "react";
import EntitiesPanel from "../components/EntitiesPanel";

export default function ProviderEntities() {
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 max-w-5xl" data-testid="provider-entities-page">
      <div>
        <div className="overline">Organisation</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">My Entities</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Add branches, labs, pharmacies and ambulance units under your organisation. Same as the Provider app.</p>
      </div>
      <EntitiesPanel base="/provider/entities" />
    </div>
  );
}
