import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search, Loader2, Building2, UserPlus } from "lucide-react";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";
import { BulkBar, BulkActionDialog, SuspendedTag, RowCheck, useSelection } from "../components/users/BulkActions";

const ROLE_LABEL = { pathologist: "Pathology / Diagnostics", ambulance_provider: "Ambulance", hospital: "Hospital", doctor: "Doctor", paramedic: "Paramedic",
  pharmacy: "Pharmacy", diagnostic_centre: "Diagnostic centre", pharmacist: "Pharmacist", lab_tech: "Lab technician", nurse: "Nurse", receptionist: "Receptionist" };
const roleLabel = (r) => ROLE_LABEL[r] || String(r || "").replace(/_/g, " ");
const ORG_ROLES = ["hospital", "pathologist", "ambulance_provider", "pharmacy"];
const orgHeader = (r) => (ORG_ROLES.includes(r) ? `${roleLabel(r).split(" /")[0]} name` : "Provider name");
const KYC_TONE = { verified: "bg-[#E3FCEF] text-[#006644]", approved: "bg-[#E3FCEF] text-[#006644]", rejected: "bg-[#FFEBE6] text-[#BF2600]", pending: "bg-[#FFFAE6] text-[#974F0C]" };

/** Trata Health Admin: one row per Provider-app account (from the shared users table). */
export default function ProviderDirectory() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const role = sp.get("role") || "";
  const kyc = sp.get("kyc") || "";
  const [q, setQ] = useState("");
  const [s, setS] = useState({ loading: true, items: [], roles: [] });
  const [status, setStatus] = useState("");
  const [action, setAction] = useState(null);
  const [tick, setTick] = useState(0);
  const total = s.roles.reduce((n, r) => n + r.count, 0);
  const items = s.items.filter((p) => !status || (status === "suspended") === !!p.is_suspended);
  const pick = useSelection(items);
  const targetIds = items.filter((p) => pick.sel.has(p.id)).flatMap((p) => [p.id, ...(p.linked_accounts || [])]);

  useEffect(() => {
    const t = setTimeout(() => {
      setS((p) => ({ ...p, loading: true }));
      api.get("/admin/directory/providers", { params: { role: role || undefined, kyc: kyc || undefined, q: q || undefined } })
        .then(({ data }) => setS({ loading: false, ...data })).catch(() => setS((p) => ({ ...p, loading: false })));
    }, 250);
    return () => clearTimeout(t);
  }, [role, kyc, q, tick]);
  const setParam = (k, v) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n); };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="provider-directory">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5" /> Provider app</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="provider-directory-title">Trata Providers <span className="text-[#5E6C84] font-medium">/ {total}</span></h1>
          <p className="text-sm text-[#5E6C84] mt-1">Every account on the Trata Provider app — one row per account. Click one for the full profile and complete KYC.</p>
        </div>
        <button onClick={() => nav("/admin/onboarding")} className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6]" data-testid="provider-directory-onboard"><UserPlus className="h-4 w-4" /> Onboard provider</button>
      </div>
      <div className="flex flex-nowrap overflow-x-auto gap-1.5 border-b border-[#DFE1E6] pb-3" data-testid="provider-directory-roles">
        {[{ role: "", count: total }, ...s.roles].map((r) => (
          <button key={r.role || "all"} onClick={() => setParam("role", r.role)} data-testid={`provider-role-${r.role || "all"}`}
                  className={`shrink-0 px-3 py-1.5 text-sm rounded-md ${role === r.role ? "bg-[#091E42] text-white" : "text-[#42526E] hover:bg-[#F4F5F7]"}`}>
            {r.role ? roleLabel(r.role) : "All"} <span className="opacity-60">{r.count}</span></button>))}
      </div>
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative w-full sm:w-80"><Search className="absolute left-3 top-2.5 h-4 w-4 text-[#97A0AF]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search provider, admin, phone, email…" className="w-full pl-9 pr-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="provider-directory-search" /></div>
        <select value={kyc} onChange={(e) => setParam("kyc", e.target.value)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white" data-testid="provider-directory-kyc-filter">
          <option value="">Any KYC status</option><option value="pending">Pending</option><option value="verified">Verified</option><option value="rejected">Rejected</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white" data-testid="provider-directory-status-filter">
          <option value="">Any access</option><option value="active">Active</option><option value="suspended">Suspended</option>
        </select>
      </div>
      <BulkBar count={pick.selected.length} onAction={setAction} onClear={pick.clear} />
      <BulkActionDialog action={action} ids={targetIds} field="user_ids" onClose={() => setAction(null)}
                        onDone={() => { setAction(null); pick.clear(); setTick((t) => t + 1); }} />
      <section className="bg-white border border-[#DFE1E6] rounded-md overflow-x-auto">
        {s.loading && !items.length ? <div className="p-6 text-xs text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
          : !items.length ? <div className="p-10 text-center text-sm text-[#5E6C84]" data-testid="provider-directory-empty">No providers match.</div>
          : <table className="w-full text-sm min-w-[920px]">
            <thead className="bg-[#F8F9FA] text-[10px] uppercase tracking-wider text-[#5E6C84]"><tr>
              <th className="pl-4 py-2.5 w-8"><RowCheck checked={pick.all} onChange={pick.toggleAll} testId="provider-select-all" /></th>
              <th className="text-left px-4 py-2.5" data-testid="provider-col-org">{orgHeader(role)}</th><th className="text-left px-4 py-2.5" data-testid="provider-col-admin">Admin name</th><th className="text-left px-4 py-2.5">Type</th><th className="text-left px-4 py-2.5">Phone</th>
              <th className="text-left px-4 py-2.5">KYC</th><th className="text-left px-4 py-2.5">Documents</th><th className="text-left px-4 py-2.5">Joined</th><th className="text-left px-4 py-2.5">Last login</th></tr></thead>
            <tbody>{items.map((p) => (
              <tr key={p.id} onClick={() => nav(`/admin/onboarding/${p.id}`)} className={`border-t border-[#F4F5F7] hover:bg-[#F8F9FA] cursor-pointer ${pick.sel.has(p.id) ? "bg-[#DEEBFF]/40" : ""}`} data-testid={`provider-row-${p.id}`}>
                <td className="pl-4 py-3"><RowCheck checked={pick.sel.has(p.id)} onChange={() => pick.toggle(p.id)} testId={`provider-select-${p.id}`} /></td>
                <td className="px-4 py-3"><div className={p.org_name ? "font-semibold text-[#091E42]" : "text-[#97A0AF]"} data-testid={`provider-org-${p.id}`}>{p.org_name || "Not linked"}{p.is_suspended && <SuspendedTag reason={p.suspended_reason} testId={`provider-suspended-${p.id}`} />}</div>
                  {p.linked_accounts?.length > 0 && <div className="text-[11px] text-[#97A0AF]" data-testid={`provider-linked-${p.id}`}>+{p.linked_accounts.length} linked account{p.linked_accounts.length > 1 ? "s" : ""} with the same name</div>}</td>
                <td className="px-4 py-3"><div className={p.admin_name ? "text-[#091E42]" : "text-[#97A0AF]"} data-testid={`provider-admin-${p.id}`}>{p.admin_name || "Not set"}</div>{p.email && <div className="text-xs text-[#5E6C84]">{p.email}</div>}</td>
                <td className="px-4 py-3"><span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-[#F4F5F7] text-[#42526E]">{roleLabel(p.role)}</span></td>
                <td className="px-4 py-3 font-mono text-xs">{p.phone || "—"}</td>
                <td className="px-4 py-3"><span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${KYC_TONE[String(p.kyc_status).toLowerCase()] || KYC_TONE.pending}`}>{p.kyc_status}</span></td>
                <td className="px-4 py-3 text-xs text-[#42526E]">{p.docs_total ? `${p.docs_approved}/${p.docs_total} approved${p.docs_rejected ? ` · ${p.docs_rejected} rejected` : ""}` : "None"}</td>
                <td className="px-4 py-3 text-xs text-[#5E6C84]">{p.created_at ? relativeTime(p.created_at) : "—"}</td>
                <td className="px-4 py-3 text-xs text-[#5E6C84]">{p.last_login_at ? relativeTime(p.last_login_at) : "Never"}</td>
              </tr>))}</tbody></table>}
      </section>
    </div>
  );
}
