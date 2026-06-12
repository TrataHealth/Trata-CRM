import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Avatar } from "./Contacts";
import { PIPELINE_STAGES, CONTACT_TYPES, relativeTime, fmtCurrency, typeLabel } from "../lib/constants";
import { Search, Phone, UserPlus } from "lucide-react";
import OnboardProviderModal from "../components/OnboardProviderModal";

const STAGE_COLOR = Object.fromEntries(PIPELINE_STAGES.map((s) => [s.value, s.color]));
const STAGE_LABEL = Object.fromEntries(PIPELINE_STAGES.map((s) => [s.value, s.label]));

export default function AgentLeads() {
  const [params, setParams] = useSearchParams();
  const [list, setList] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [onboardOpen, setOnboardOpen] = useState(false);
  const [bump, setBump] = useState(0);
  const stage = params.get("stage") || "";
  const ptype = params.get("type") || "";
  const touched = params.get("touched") || "";
  const q = params.get("q") || "";
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      setLoading(true);
      const { data } = await api.get("/agent/leads", {
        params: { stage: stage || undefined, provider_type: ptype || undefined, last_touched: touched || undefined, q: q || undefined, limit: 200 },
      });
      setList(data.items); setTotal(data.total); setLoading(false);
    })();
  }, [stage, ptype, touched, q, bump]);

  const set = (k, v) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p); };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="agent-leads-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline">Onboarding pipeline</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
            My Leads <span className="text-[#5E6C84] font-medium">/ {total}</span>
          </h1>
          <p className="text-sm text-[#5E6C84] mt-1">All leads currently assigned to you, ready to work.</p>
        </div>
        <button
          data-testid="agent-leads-onboard-btn"
          onClick={() => setOnboardOpen(true)}
          className="flex items-center gap-2 px-3.5 py-2 text-sm font-semibold rounded-md text-white bg-[#0052CC] hover:bg-[#0747A6] shadow-sm"
        >
          <UserPlus className="h-4 w-4" /> Onboard provider
        </button>
      </div>

      {onboardOpen && (
        <OnboardProviderModal
          onClose={() => setOnboardOpen(false)}
          onCreated={(created) => {
            setOnboardOpen(false);
            setBump((b) => b + 1);
            if (created?.contact?.id) navigate(`/contacts/${created.contact.id}`);
          }}
        />
      )}

      <div className="flex flex-wrap gap-2">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
          <input data-testid="agent-leads-search" defaultValue={q} onChange={(e) => set("q", e.target.value)}
            placeholder="Search name, phone, specialization…"
            className="pl-9 w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none" />
        </div>
        <select data-testid="filter-stage" value={stage} onChange={(e) => set("stage", e.target.value)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white">
          <option value="">All stages</option>
          {PIPELINE_STAGES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select data-testid="filter-type" value={ptype} onChange={(e) => set("type", e.target.value)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white">
          <option value="">All types</option>
          {CONTACT_TYPES.filter(c => c.value !== "patient").map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <select data-testid="filter-touched" value={touched} onChange={(e) => set("touched", e.target.value)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white">
          <option value="">Any time</option>
          <option value="today">Touched today</option>
          <option value="7d">Touched in 7 days</option>
          <option value="30d">Touched in 30 days</option>
          <option value="stale">Stale (7+ days)</option>
        </select>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm" data-testid="agent-leads-table">
            <thead className="bg-[#F8F9FA] border-b border-[#DFE1E6]">
              <tr className="text-left">
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Lead</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Type</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Phone</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">City</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Stage</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Last touched</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84] text-right">Deal</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={7} className="py-10 text-center text-sm text-[#5E6C84]">Loading…</td></tr>}
              {!loading && list.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-sm text-[#5E6C84]">No leads match these filters.</td></tr>}
              {list.map((c) => (
                <tr key={c.id} onClick={() => navigate(`/contacts/${c.id}`)} className="border-b border-[#F1F2F4] hover:bg-[#F8F9FA] cursor-pointer" data-testid={`al-row-${c.id}`}>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Avatar name={c.name} src={c.avatar} size={32} />
                      <div className="min-w-0">
                        <div className="font-semibold text-[#091E42] truncate">{c.name}</div>
                        <div className="text-[11px] text-[#5E6C84] truncate">{c.specialization || c.email || "—"}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5"><span className="text-xs uppercase font-semibold text-[#42526E]">{typeLabel(c.type)}</span></td>
                  <td className="px-3 py-2.5 font-mono text-xs">{c.phone}</td>
                  <td className="px-3 py-2.5 text-[#42526E]">{c.city || "—"}</td>
                  <td className="px-3 py-2.5">
                    <span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded"
                          style={{ background: `${STAGE_COLOR[c.pipeline_stage]}15`, color: STAGE_COLOR[c.pipeline_stage] }}>
                      {STAGE_LABEL[c.pipeline_stage]}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-[#5E6C84]">{relativeTime(c.updated_at || c.created_at)}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{c.deal_value ? fmtCurrency(c.deal_value) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
