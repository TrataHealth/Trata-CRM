import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Phone, Mail, MapPin, ShieldCheck, ShieldAlert, BadgeCheck, FileText, Star } from "lucide-react";
import { Avatar } from "./Contacts";
import { fmtCurrency, relativeTime, statusColor } from "../lib/constants";

export default function ProviderProfile() {
  const [data, setData] = useState(null);
  const [kyc, setKyc] = useState([]);

  useEffect(() => {
    (async () => {
      const [me, acts] = await Promise.all([
        api.get("/provider/me"),
        api.get("/provider/activities", { params: { category: "kyc", limit: 10 } }),
      ]);
      setData(me.data);
      setKyc(acts.data.items);
    })();
  }, []);

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]">Loading…</div>;
  const c = data.contact;
  const u = data.user;
  const meta = c.meta || {};

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-5xl" data-testid="provider-profile-page">
      <div>
        <div className="overline">Your Account</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Profile & KYC</h1>
        <p className="text-sm text-[#5E6C84] mt-1">This is what TrataHealth HQ sees about your business.</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md p-6">
        <div className="flex flex-wrap items-start gap-6">
          <Avatar name={c.name} src={c.avatar} size={72} />
          <div className="flex-1 min-w-0">
            <div className="overline">{(u.provider_type || "").toUpperCase()}</div>
            <h2 className="font-heading text-2xl font-black tracking-tight text-[#091E42] mt-1">{c.name}</h2>
            <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-[#5E6C84]">
              <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" /> +91 {c.phone}</span>
              {c.email && <span className="inline-flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" /> {c.email}</span>}
              {c.city && <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> {c.city}, {c.state}</span>}
              {c.rating && <span className="inline-flex items-center gap-1.5 text-[#FFAB00]"><Star className="h-3.5 w-3.5 fill-current" /> {c.rating}</span>}
            </div>
            {c.specialization && <div className="mt-1 text-sm text-[#42526E]">{c.specialization}</div>}
          </div>
          <div>
            {c.is_verified ? (
              <div className="inline-flex items-center gap-2 px-3 py-2 bg-[#E3FCEF] text-[#006644] rounded-md text-sm font-semibold" data-testid="kyc-status-verified">
                <ShieldCheck className="h-4 w-4" /> KYC Verified
              </div>
            ) : (
              <div className="inline-flex items-center gap-2 px-3 py-2 bg-[#FFFAE6] text-[#974F0C] rounded-md text-sm font-semibold" data-testid="kyc-status-pending">
                <ShieldAlert className="h-4 w-4" /> KYC Pending
              </div>
            )}
          </div>
        </div>

        {/* Metadata grid */}
        <div className="mt-6 pt-6 border-t border-[#F1F2F4] grid grid-cols-2 md:grid-cols-4 gap-4">
          {meta.license_number && <Meta label="License #" value={meta.license_number} />}
          {meta.experience_years && <Meta label="Experience" value={`${meta.experience_years} years`} />}
          {meta.total_beds && <Meta label="Total beds" value={meta.total_beds} />}
          {meta.available_beds != null && <Meta label="Available beds" value={meta.available_beds} />}
          {meta.ambulance_count && <Meta label="Fleet size" value={`${meta.ambulance_count} vehicles`} />}
          <Meta label="Pipeline stage" value={c.pipeline_stage} />
          <Meta label="Onboarded" value={relativeTime(c.created_at)} />
          <Meta label="Deal value" value={c.deal_value ? fmtCurrency(c.deal_value) : "—"} />
        </div>
      </div>

      {/* KYC timeline */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="overline">Verification Trail</div>
            <div className="font-heading text-lg font-bold text-[#091E42] mt-1">KYC History</div>
          </div>
          <BadgeCheck className="h-4 w-4 text-[#36B37E]" />
        </div>
        {kyc.length === 0 ? (
          <div className="py-8 text-center text-sm text-[#5E6C84]">No KYC events recorded yet.</div>
        ) : (
          <ul className="space-y-3">
            {kyc.map((k) => (
              <li key={k.id} className="flex items-start gap-3" data-testid={`kyc-event-${k.id}`}>
                <span className="h-2 w-2 rounded-full mt-2" style={{ background: statusColor(k.status) }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-[#091E42]">{k.title}</div>
                  <div className="text-xs text-[#5E6C84]">{k.description}</div>
                </div>
                <span className="text-[11px] uppercase tracking-wider font-semibold rounded px-1.5 py-0.5"
                      style={{ background: `${statusColor(k.status)}15`, color: statusColor(k.status) }}>{k.status}</span>
                <span className="text-[11px] text-[#5E6C84]">{relativeTime(k.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
        {!c.is_verified && (
          <div className="mt-4 pt-4 border-t border-[#F1F2F4] text-xs text-[#5E6C84]">
            <FileText className="h-3.5 w-3.5 inline mr-1" />
            Need to update your KYC documents? Open the Trata Provider App on your phone → Profile → KYC. Updates sync here within a minute.
          </div>
        )}
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
