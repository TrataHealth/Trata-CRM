import React, { useEffect, useState } from "react";
import { Loader2, Search, Trash2 } from "lucide-react";
import api from "../../lib/api";
import { relativeTime } from "../../lib/constants";
import { BulkBar, BulkActionDialog, RowCheck, useSelection } from "./BulkActions";

const ROLE_LABEL = { path_lab: "Path Lab", ambulance_provider: "Ambulance", hospital: "Hospital", doctor: "Doctor", paramedic: "Paramedic",
  pharmacy: "Pharmacy", diagnostic_centre: "Diagnostic centre", pharmacist: "Pharmacist", lab_tech: "Lab technician", nurse: "Nurse",
  receptionist: "Receptionist", patient: "Patient", customer: "Patient" };
const label = (r) => ROLE_LABEL[r] || String(r || "Patient").replace(/_/g, " ");
const th = "text-left px-4 py-2.5";

/** Deleted accounts — the same list as the Provider App admin's Deleted page (profiles marked deactivated). */
export function DeletedUsers({ app }) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [s, setS] = useState({ loading: true, items: [], roles: [] });
  const [action, setAction] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => {
      setS((p) => ({ ...p, loading: true }));
      api.get("/admin/directory/deleted", { params: { app, q: q || undefined } })
        .then(({ data }) => setS({ loading: false, ...data })).catch(() => setS((p) => ({ ...p, loading: false })));
    }, 250);
    return () => clearTimeout(t);
  }, [app, q, tick]);
  const items = s.items.filter((i) => !role || i.role === role);
  const restorable = (i) => (app === "provider" ? !!i.user_id : /^admin_deleted/.test(i.archived_reason || ""));
  const pick = useSelection(items.filter(restorable), (i) => i.row_key);
  const ids = [...new Set(items.filter((i) => pick.sel.has(i.row_key)).map((i) => i.user_id || i.id))];
  const provider = app === "provider";

  return (
    <div className="space-y-4" data-testid={`deleted-users-${app}`}>
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative w-full sm:w-80"><Search className="absolute left-3 top-2.5 h-4 w-4 text-[#97A0AF]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search deleted users…" className="w-full pl-9 pr-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="deleted-search" /></div>
        {provider && <select value={role} onChange={(e) => setRole(e.target.value)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white" data-testid="deleted-role-filter">
          <option value="">All types ({s.total || 0})</option>
          {s.roles.map((r) => <option key={r.role} value={r.role}>{label(r.role)} ({r.count})</option>)}
        </select>}
      </div>
      <BulkBar count={pick.selected.length} archivedView onAction={setAction} onClear={pick.clear} />
      <BulkActionDialog action={action} ids={ids} field="user_ids" onClose={() => setAction(null)}
                        onDone={() => { setAction(null); pick.clear(); setTick((t) => t + 1); }} />
      <section className="bg-white border border-[#DFE1E6] rounded-md overflow-x-auto">
        {s.loading && !items.length ? <div className="p-6 text-xs text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
          : !items.length ? <div className="p-10 text-center text-sm text-[#5E6C84]" data-testid="deleted-empty"><Trash2 className="h-5 w-5 mx-auto mb-2" />No deleted users.</div>
          : <table className="w-full text-sm min-w-[860px]">
            <thead className="bg-[#F8F9FA] text-[10px] uppercase tracking-wider text-[#5E6C84]"><tr>
              <th className="pl-4 py-2.5 w-8"><RowCheck checked={pick.all} onChange={pick.toggleAll} testId="deleted-select-all" /></th>
              <th className={th}>{provider ? "Provider name" : "Patient"}</th>{provider && <th className={th}>Admin name</th>}<th className={th}>Type</th>
              <th className={th}>Phone</th><th className={th}>Deleted</th><th className={th}>Reason</th><th className={th}>Erased in</th></tr></thead>
            <tbody>{items.map((i) => {
              const can = restorable(i);
              return (
                <tr key={i.row_key} className={`border-t border-[#F4F5F7] ${pick.sel.has(i.row_key) ? "bg-[#DEEBFF]/40" : ""}`} data-testid={`deleted-row-${i.row_key}`}>
                  <td className="pl-4 py-3">{can && <RowCheck checked={pick.sel.has(i.row_key)} onChange={() => pick.toggle(i.row_key)} testId={`deleted-select-${i.row_key}`} />}</td>
                  <td className="px-4 py-3 font-semibold text-[#091E42]">{(provider ? i.org_name : i.name) || <span className="text-[#97A0AF] font-normal">Not set</span>}</td>
                  {provider && <td className="px-4 py-3 text-[#091E42]">{i.admin_name || <span className="text-[#97A0AF]">Not set</span>}</td>}
                  <td className="px-4 py-3"><span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-[#F4F5F7] text-[#42526E]">{label(i.role)}</span></td>
                  <td className="px-4 py-3 font-mono text-xs">{/^\+?\d{10,13}$/.test(i.phone || "") ? i.phone : "—"}</td>
                  <td className="px-4 py-3 text-xs text-[#5E6C84]">{relativeTime(i.archived_at || i.updated_at || i.requested_at) || "—"}</td>
                  <td className="px-4 py-3 text-xs text-[#42526E] max-w-[220px] truncate" title={i.deleted_reason || i.archived_reason || ""}>
                    {i.deletion_status === "pending" ? "Deletion requested in the app" : (i.deleted_reason || i.archived_reason || "Deleted in the Provider App").replace(/^admin_deleted: /, "")}</td>
                  <td className="px-4 py-3 text-xs" data-testid={`deleted-days-${i.row_key}`}>{i.days_left != null ? `${i.days_left} days` : "—"}</td>
                </tr>);
            })}</tbody></table>}
      </section>
    </div>
  );
}
