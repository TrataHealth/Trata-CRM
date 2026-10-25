import React, { useCallback, useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { relativeTime } from "../lib/constants";
import { toast } from "sonner";
import {
  Users, UserPlus, Loader2, Trash2, AlertTriangle, CheckCircle2, XCircle, Clock,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  sectionHead: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  btnPrimary: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnGhost:   "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
  btnDanger:  "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#BF2600] hover:bg-[#FFEBE6] disabled:opacity-40",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
};

const ROLES = ["Doctor", "Nurse", "Ward boy", "Receptionist", "Lab technician", "Radiographer", "Pharmacist", "Administrator", "Housekeeping", "Security", "Other"];
const DEPARTMENTS = ["Emergency", "ICU", "OT", "OPD", "Cardiology", "Neurology", "Orthopedics", "Pediatrics", "Radiology", "Pathology", "Pharmacy", "Administration", "Other"];

const Tile = ({ label, value, sub, icon: Icon, tone = "#0052CC" }) => (
  <div className={T.card + " p-4"} data-testid={`staff-tile-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
    <div className="flex items-center justify-between">
      <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
      <Icon className="h-4 w-4" style={{ color: tone }} />
    </div>
    <div className="font-heading text-3xl font-black text-[#091E42] mt-1">{value ?? 0}</div>
    {sub && <div className="text-[11px] text-[#5E6C84] mt-1">{sub}</div>}
  </div>
);

export default function HospitalStaff() {
  const { user } = useAuth();
  const [state, setState] = useState({ loading: true, staff: [], err: "" });
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", role: "Doctor", department: "", specialization: "", phone: "", email: "", shift_start: "", shift_end: "", salary: "" });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/hospital/staff");
      setState({ loading: false, staff: data.staff || [], err: "" });
    } catch (e) { setState({ loading: false, staff: [], err: e?.response?.data?.detail || "Could not load staff" }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submitAdd = async () => {
    if (!form.name.trim()) return toast.error("Name is required");
    setBusy(true);
    try {
      await api.post("/hospital/staff", { ...form, salary: form.salary ? Number(form.salary) : null });
      toast.success("Staff member added");
      setForm({ name: "", role: "Doctor", department: "", specialization: "", phone: "", email: "", shift_start: "", shift_end: "", salary: "" });
      setShowAdd(false);
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Create failed"); } finally { setBusy(false); }
  };

  const toggleDuty = async (s) => {
    try { await api.post(`/hospital/staff/${s.id}/duty`, { is_on_duty: !s.is_on_duty }); await load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Toggle failed"); }
  };

  const removeStaff = async (s) => {
    if (!window.confirm(`Remove ${s.name}?`)) return;
    try { await api.delete(`/hospital/staff/${s.id}`); toast("Removed"); await load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Delete failed"); }
  };

  const staff = state.staff;
  const roleCounts = staff.reduce((a, s) => (a[s.role] = (a[s.role] || 0) + 1, a), {});
  const totalCount = staff.length;
  const onDuty = staff.filter((s) => s.is_on_duty).length;
  const active = staff.filter((s) => s.is_active).length;
  const availableRoles = Array.from(new Set(staff.map((s) => s.role).filter(Boolean))).sort();
  const filtered = staff.filter((s) => {
    if (roleFilter !== "all" && s.role !== roleFilter) return false;
    if (q) {
      const hay = `${s.name} ${s.role} ${s.department} ${s.specialization} ${s.phone} ${s.email}`.toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    }
    return true;
  });

  if (state.loading) return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="staff-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading staff…</div>;
  if (state.err) return (
    <div className="p-6 max-w-xl mx-auto mt-10" data-testid="staff-error">
      <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <div><div className="font-semibold">Staff unavailable</div><div className="text-xs mt-1">{state.err}</div></div>
      </div>
    </div>
  );

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="hospital-staff-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><Users className="h-3 w-3" /> Staff Roster</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{user?.business_name ? `${user.business_name} · Staff` : "Staff"}</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Same roster the mobile Provider App shows. Toggle on-duty status, add or remove staff — changes reflect on the app instantly.</p>
        </div>
        <button className={T.btnPrimary} onClick={() => setShowAdd((v) => !v)} data-testid="staff-add-toggle"><UserPlus className="h-3.5 w-3.5" /> Add staff</button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Tile label="Total staff" value={totalCount} sub={`${availableRoles.length} role${availableRoles.length === 1 ? "" : "s"}`} icon={Users} tone="#0052CC" />
        <Tile label="On duty now" value={onDuty} sub={totalCount ? `${Math.round(onDuty / totalCount * 100)}% of roster` : "—"} icon={CheckCircle2} tone="#006644" />
        <Tile label="Active" value={active} sub={`${totalCount - active} inactive`} icon={CheckCircle2} tone="#5243AA" />
        <Tile label="Top role" value={Object.entries(roleCounts).sort((a,b)=>b[1]-a[1])[0]?.[0] || "—"} sub={Object.entries(roleCounts).sort((a,b)=>b[1]-a[1])[0]?.[1] ? `${Object.entries(roleCounts).sort((a,b)=>b[1]-a[1])[0][1]} people` : ""} icon={Users} tone="#DE350B" />
      </div>

      {showAdd && (
        <section className={T.card} data-testid="staff-add-form">
          <div className={T.sectionHead}>Add staff member</div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-2">
            <label className="text-[11px] text-[#42526E]">Name*<input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="staff-form-name" /></label>
            <label className="text-[11px] text-[#42526E]">Role<select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} data-testid="staff-form-role">{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select></label>
            <label className="text-[11px] text-[#42526E]">Department<select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} data-testid="staff-form-dept"><option value="">—</option>{DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
            <label className="text-[11px] text-[#42526E]">Specialization<input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })} placeholder="e.g. Cardiology" /></label>
            <label className="text-[11px] text-[#42526E]">Phone<input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/[^0-9]/g, "") })} maxLength={10} placeholder="10-digit" /></label>
            <label className="text-[11px] text-[#42526E]">Email<input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} type="email" /></label>
            <label className="text-[11px] text-[#42526E]">Shift start<input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.shift_start} onChange={(e) => setForm({ ...form, shift_start: e.target.value })} placeholder="09:00" /></label>
            <label className="text-[11px] text-[#42526E]">Shift end<input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.shift_end} onChange={(e) => setForm({ ...form, shift_end: e.target.value })} placeholder="18:00" /></label>
            <label className="text-[11px] text-[#42526E]">Salary (₹/month)<input type="number" className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.salary} onChange={(e) => setForm({ ...form, salary: e.target.value })} placeholder="Optional" /></label>
          </div>
          <div className="px-4 pb-4 flex justify-end gap-2">
            <button className={T.btnGhost} onClick={() => setShowAdd(false)}>Cancel</button>
            <button className={T.btnPrimary} disabled={busy || !form.name.trim()} onClick={submitAdd} data-testid="staff-form-submit">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />} Add staff</button>
          </div>
        </section>
      )}

      <section className={T.card}>
        <div className={T.sectionHead + " flex-wrap gap-2"} data-testid="staff-filters">
          <div className="flex items-center gap-2 flex-1 min-w-[180px]">
            <input className="text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded w-full max-w-[280px]" placeholder="Search name, role, department…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="staff-search" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-[#5E6C84]">Role</span>
            <select className="text-xs px-2 py-1 bg-white border border-[#DFE1E6] rounded" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} data-testid="staff-role-filter">
              <option value="all">All ({staff.length})</option>
              {availableRoles.map((r) => <option key={r} value={r}>{r} ({roleCounts[r]})</option>)}
            </select>
          </div>
        </div>
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="staff-empty">
            {staff.length === 0 ? "No staff registered yet. Click Add staff to onboard your first team member." : "No staff match this filter."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
                <tr>
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Role</th>
                  <th className="px-3 py-2 text-left">Department</th>
                  <th className="px-3 py-2 text-left">Contact</th>
                  <th className="px-3 py-2 text-left">Shift</th>
                  <th className="px-3 py-2 text-center">On duty</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((s) => (
                  <tr key={s.id} className="border-t border-[#DFE1E6]" data-testid={`staff-row-${s.id}`}>
                    <td className="px-3 py-2">
                      <div className="text-[#091E42] font-semibold">{s.name}</div>
                      {s.specialization && <div className="text-[10px] text-[#5E6C84]">{s.specialization}</div>}
                      {s.hpr_id && <div className="text-[10px] text-[#5E6C84] font-mono">HPR {s.hpr_id}{s.hpr_verified_at && " · verified"}</div>}
                    </td>
                    <td className="px-3 py-2">{s.role}</td>
                    <td className="px-3 py-2">{s.department || "—"}</td>
                    <td className="px-3 py-2">
                      {s.phone && <div className="font-mono">+91 {s.phone}</div>}
                      {s.email && <div className="text-[10px] text-[#5E6C84] truncate max-w-[180px]">{s.email}</div>}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{s.shift_start && s.shift_end ? <><Clock className="h-3 w-3 inline mr-1" />{s.shift_start}–{s.shift_end}</> : "—"}</td>
                    <td className="px-3 py-2 text-center">
                      <button onClick={() => toggleDuty(s)} className={`${T.chip} ${s.is_on_duty ? "bg-[#E3FCEF] text-[#006644] hover:bg-[#ABF5D1]" : "bg-[#F4F5F7] text-[#42526E] hover:bg-[#DFE1E6]"}`} data-testid={`staff-duty-${s.id}`}>
                        {s.is_on_duty ? <><CheckCircle2 className="h-3 w-3 mr-1" /> ON</> : <><XCircle className="h-3 w-3 mr-1" /> OFF</>}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button className={T.btnDanger} onClick={() => removeStaff(s)} data-testid={`staff-delete-${s.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
