import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Phone, MapPin, ShieldCheck, LogIn } from "lucide-react";
import api from "../lib/api";
import { KIND_LABEL } from "../lib/entityFields";

const KYC = { approved: ["Approved", "bg-[#E3FCEF] text-[#006644]"], agent_reviewed: ["Under final review", "bg-[#DEEBFF] text-[#0747A6]"], rejected: ["Rejected", "bg-[#FFEBE6] text-[#BF2600]"] };
const fmt = (m) => (m.label.includes("₹") ? `₹${Number(m.value).toLocaleString("en-IN")}` : m.value);

export default function EntityDashboard() {
  const { entityId } = useParams();
  const [d, setD] = useState(null); const [err, setErr] = useState("");
  useEffect(() => { api.get(`/provider/entities/${entityId}/summary`).then((r) => setD(r.data)).catch((e) => setErr(e?.response?.data?.detail || "Could not load this entity")); }, [entityId]);
  const e = d?.entity; const [kl, kc] = KYC[d?.kyc_status] || ["KYC pending", "bg-[#FFF0B3] text-[#974F0C]"];
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 max-w-5xl" data-testid="entity-dashboard">
      <Link to="/provider/entities" className="inline-flex items-center gap-1 text-sm text-[#0052CC] font-semibold" data-testid="entity-back"><ArrowLeft className="h-4 w-4" /> My Entities</Link>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="entity-dashboard-error">{err}</div>}
      {!d && !err && <div className="text-sm text-[#5E6C84]">Loading…</div>}
      {e && <>
        <div>
          <div className="overline">{KIND_LABEL[e.entity_kind] || e.entity_kind}</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="entity-dashboard-name">{e.name}</h1>
          <div className="flex flex-wrap gap-3 text-sm text-[#42526E] mt-2">
            <span className="flex items-center gap-1"><Phone className="h-3.5 w-3.5" />{e.dedicated_phone}</span>
            <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{[e.address, e.city].filter(Boolean).join(", ")}</span>
            {e.contact_person && <span>Admin: {e.contact_person}</span>}
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            <span className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-1 rounded ${kc}`} data-testid="entity-kyc"><ShieldCheck className="h-3.5 w-3.5" />{kl}</span>
            <span className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-1 rounded ${d.crm_login === "active" ? "bg-[#E3FCEF] text-[#006644]" : "bg-[#F4F5F7] text-[#42526E]"}`} data-testid="entity-login">
              <LogIn className="h-3.5 w-3.5" />{d.crm_login === "active" ? "Has signed in" : "Not signed in yet"}</span>
            {e.is_active === false && <span className="text-xs font-bold px-2 py-1 rounded bg-[#FFEBE6] text-[#BF2600]">Removed</span>}
          </div>
        </div>
        {d.metrics.length > 0 && <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="entity-metrics">{d.metrics.map((m) => (
          <div key={m.label} className="bg-white border border-[#DFE1E6] rounded-lg p-4"><div className="text-[10px] font-bold uppercase tracking-wider text-[#5E6C84]">{m.label}</div>
            <div className="font-heading text-2xl font-black text-[#091E42] mt-1">{fmt(m)}</div></div>))}</div>}
        <div className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid="entity-activity">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] mb-2">Recent activity</div>
          {d.activities.length ? d.activities.map((a, i) => <div key={i} className="py-2 border-b border-[#F4F5F7] last:border-0"><div className="text-sm font-semibold text-[#091E42]">{a.title}</div>
            <div className="text-xs text-[#5E6C84]">{new Date(a.created_at).toLocaleString()}{a.description ? ` · ${a.description}` : ""}</div></div>) : <div className="text-sm text-[#5E6C84]">No activity yet.</div>}
        </div>
        <p className="text-xs text-[#5E6C84]">This unit manages its own day-to-day work by signing in with {e.dedicated_phone} on the Provider app or the CRM.</p>
      </>}
    </div>
  );
}
