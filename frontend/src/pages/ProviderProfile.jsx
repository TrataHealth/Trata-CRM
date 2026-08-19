import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Phone, Mail, MapPin, ShieldCheck, ShieldAlert, Star, Building2 } from "lucide-react";
import { Avatar } from "./Contacts";
import { fmtCurrency, relativeTime } from "../lib/constants";

// Profile-only page. KYC checklist + upload history now lives on /provider/kyc.
export default function ProviderProfile() {
  const [data, setData] = useState(null);

  useEffect(() => {
    (async () => {
      const me = await api.get("/provider/me");
      setData(me.data);
    })();
  }, []);

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]" data-testid="provider-profile-loading">Loading…</div>;
  const c = data.contact || {};
  const u = data.user || {};
  const meta = c.meta || {};

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-5xl" data-testid="provider-profile-page">
      <div>
        <div className="overline flex items-center gap-1"><Building2 className="h-3 w-3" /> Your Account</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Profile</h1>
        <p className="text-sm text-[#5E6C84] mt-1">This is what TrataHealth HQ sees about your business. To manage KYC documents, open the <a href="/provider/kyc" className="text-[#0052CC] font-semibold hover:underline">KYC tab</a>.</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md p-6">
        <div className="flex flex-wrap items-start gap-6">
          <Avatar name={c.name} src={c.avatar} size={72} />
          <div className="flex-1 min-w-0">
            <div className="overline">{(u.provider_type || "").toUpperCase()}</div>
            <h2 className="font-heading text-2xl font-black tracking-tight text-[#091E42] mt-1">{c.name}</h2>
            <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-[#5E6C84]">
              {c.phone && <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" /> +91 {c.phone}</span>}
              {c.email && <span className="inline-flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" /> {c.email}</span>}
              {c.city && <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> {c.city}{c.state ? `, ${c.state}` : ""}</span>}
              {c.rating && <span className="inline-flex items-center gap-1.5 text-[#FFAB00]"><Star className="h-3.5 w-3.5 fill-current" /> {c.rating}</span>}
            </div>
            {c.specialization && <div className="mt-1 text-sm text-[#42526E]">{c.specialization}</div>}
          </div>
          <div>
            {c.is_verified ? (
              <a href="/provider/kyc" className="inline-flex items-center gap-2 px-3 py-2 bg-[#E3FCEF] text-[#006644] rounded-md text-sm font-semibold hover:bg-[#ABF5D1]" data-testid="kyc-status-verified">
                <ShieldCheck className="h-4 w-4" /> KYC Verified
              </a>
            ) : (
              <a href="/provider/kyc" className="inline-flex items-center gap-2 px-3 py-2 bg-[#FFFAE6] text-[#974F0C] rounded-md text-sm font-semibold hover:bg-[#FFF0B3]" data-testid="kyc-status-pending">
                <ShieldAlert className="h-4 w-4" /> Complete KYC →
              </a>
            )}
          </div>
        </div>

        <div className="mt-6 pt-6 border-t border-[#F1F2F4] grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="provider-profile-meta">
          {meta.license_number && <Meta label="License #" value={meta.license_number} />}
          {meta.experience_years && <Meta label="Experience" value={`${meta.experience_years} years`} />}
          {meta.total_beds && <Meta label="Total beds" value={meta.total_beds} />}
          {meta.available_beds != null && <Meta label="Available beds" value={meta.available_beds} />}
          {meta.ambulance_count && <Meta label="Fleet size" value={`${meta.ambulance_count} vehicles`} />}
          {c.pipeline_stage && <Meta label="Pipeline stage" value={c.pipeline_stage} />}
          {c.created_at && <Meta label="Onboarded" value={relativeTime(c.created_at)} />}
          <Meta label="Deal value" value={c.deal_value ? fmtCurrency(c.deal_value) : "—"} />
        </div>
      </div>
    </div>
  );
}

function Meta({ label, value }) {
  return (
    <div>
      <div className="overline">{label}</div>
      <div className="text-sm font-semibold text-[#091E42] mt-1">{value}</div>
    </div>
  );
}
