import React, { useCallback, useEffect, useState } from "react";
import { Pencil, Trash2, Plus, Users } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { Button } from "./ui/button";
import { LabStaffForm, ROLE_LABEL } from "./LabStaffForm";

/** Staff of a Path Lab / Diagnostic Centre (shared lab_staff table). Hidden for other provider types. */
export function LabStaffCard({ userId }) {
  const [d, setD] = useState(null);
  const [editing, setEditing] = useState(null); // null | "new" | staff row
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const base = `/admin/labs/${userId}/staff`;

  useEffect(() => {
    api.get(base).then(({ data }) => setD(data))
      .catch((e) => { setD(null); if (e?.response?.status !== 404) setErr("Couldn't load this lab's staff right now."); });
  }, [base]);

  const run = useCallback(async (fn, ok, closeForm = false) => {
    setBusy(true);
    try { const { data } = await fn(); setD(data); if (closeForm) setEditing(null); if (ok) toast.success(ok); }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not update staff"); }
    finally { setBusy(false); }
  }, []);

  if (err) return <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded-md p-3" data-testid="lab-staff-error">{err}</div>;
  if (!d) return null;
  const save = (f) => run(() => (editing === "new" ? api.post(base, f) : api.put(`${base}/${editing.id}`, f)), editing === "new" ? "Staff added" : "Staff updated", true);

  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md p-4 space-y-3" data-testid="lab-staff-card">
      <div className="flex items-center gap-3 flex-wrap">
        <Users className="h-4 w-4 text-[#5E6C84]" />
        <div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84]">Staff · {d.lab.entity_type === "diagnostic_centre" ? "Diagnostic Centre" : "Path Lab"}</div>
        <span className="text-xs text-[#42526E]" data-testid="lab-staff-counts">{d.counts.active} active · <b className="text-[#006644]">{d.counts.on_duty} on duty</b></span>
        {editing !== "new" && <Button size="sm" variant="outline" className="ml-auto h-8" onClick={() => setEditing("new")} data-testid="lab-staff-add"><Plus className="h-3.5 w-3.5 mr-1" />Add staff</Button>}
      </div>
      {editing === "new" && <LabStaffForm roles={d.roles} busy={busy} onSave={save} onCancel={() => setEditing(null)} />}
      {!d.items.length && editing !== "new" ? <div className="text-sm text-[#97A0AF]" data-testid="lab-staff-empty">No staff added yet.</div> : (
        <ul className="divide-y divide-[#F4F5F7]">
          {d.items.map((s) => editing?.id === s.id ? (
            <li key={s.id} className="py-2"><LabStaffForm roles={d.roles} initial={s} busy={busy} onSave={save} onCancel={() => setEditing(null)} /></li>
          ) : (
            <li key={s.id} className={`py-2.5 flex items-center gap-3 ${s.is_active ? "" : "opacity-50"}`} data-testid={`lab-staff-row-${s.id}`}>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-[#091E42] truncate">{s.name} <span className="ml-1 text-[11px] font-medium text-[#5E6C84]">{ROLE_LABEL[s.role] || s.role}</span></div>
                <div className="text-xs text-[#5E6C84] truncate">{[s.phone, s.qualification, s.shift_start && `${s.shift_start}–${s.shift_end || "?"}`].filter(Boolean).join(" · ") || "—"}</div>
              </div>
              <button type="button" disabled={busy || !s.is_active} onClick={() => run(() => api.post(`${base}/toggle-duty/${s.id}`))} data-testid={`lab-staff-duty-${s.id}`}
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider transition-colors ${s.is_on_duty ? "bg-[#E3FCEF] text-[#006644]" : "bg-[#F4F5F7] text-[#5E6C84]"}`}>
                {s.is_on_duty ? "On duty" : "Off duty"}
              </button>
              <button type="button" onClick={() => setEditing(s)} className="p-1.5 text-[#5E6C84] hover:text-[#0052CC]" data-testid={`lab-staff-edit-${s.id}`}><Pencil className="h-3.5 w-3.5" /></button>
              <button type="button" disabled={busy} onClick={() => window.confirm(`Remove ${s.name} from this lab?`) && run(() => api.delete(`${base}/${s.id}`), "Staff removed")}
                      className="p-1.5 text-[#5E6C84] hover:text-[#DE350B]" data-testid={`lab-staff-delete-${s.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
