import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Avatar } from "./Contacts";
import { Plus, Trash2, Loader2, ShieldCheck } from "lucide-react";
import { relativeTime } from "../lib/constants";

const ROLE_LABELS = {
  admin: "Admin",
  manager: "Manager",
  sales_rep: "Sales Rep",
  ops_rep: "Ops Rep",
};

export default function Team() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ name: "", phone: "", email: "", role: "sales_rep" });
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    const { data } = await api.get("/team");
    setList(data.items);
  };
  useEffect(() => { load(); }, []);

  const add = async () => {
    setErr("");
    if (!form.name || !form.phone) return setErr("Name and phone are required");
    setAdding(true);
    try {
      await api.post("/team", form);
      setForm({ name: "", phone: "", email: "", role: "sales_rep" });
      load();
    } catch (e) { setErr(e?.response?.data?.detail || "Failed"); }
    setAdding(false);
  };
  const del = async (id) => {
    if (!window.confirm("Remove this team member?")) return;
    await api.delete(`/team/${id}`);
    load();
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6" data-testid="team-page">
      <div>
        <div className="overline">Access Control</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Team & Roles</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Manage internal users with role-based access.</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="team-add-form">
        <div className="overline mb-3">Add team member</div>
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2">
          <input data-testid="team-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Full name" className="md:col-span-3 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" />
          <input data-testid="team-phone-input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/[^0-9]/g, "") })} placeholder="Phone (10 digit)" maxLength={10} className="md:col-span-3 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" />
          <input data-testid="team-email-input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="Email" className="md:col-span-3 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" />
          <select data-testid="team-role-select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="md:col-span-2 px-2 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white">
            {Object.entries(ROLE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button data-testid="team-add-btn" onClick={add} disabled={adding} className="md:col-span-1 flex items-center justify-center gap-1 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md hover:bg-[#0747A6] disabled:opacity-60">
            {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Plus className="h-4 w-4" /></>}
          </button>
        </div>
        {err && <div className="text-xs text-[#FF5630] mt-2" data-testid="team-error">{err}</div>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="team-grid">
        {list.map((m) => (
          <div key={m.id} className="bg-white border border-[#DFE1E6] rounded-md p-4 flex items-start gap-3" data-testid={`team-card-${m.id}`}>
            <Avatar name={m.name} size={44} />
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-[#091E42] flex items-center gap-1.5">
                {m.name}
                {m.is_master_admin && <ShieldCheck className="h-3.5 w-3.5 text-[#0052CC]" title="Master admin" />}
              </div>
              <div className="text-xs text-[#5E6C84] truncate">+91 {m.phone} {m.email ? `· ${m.email}` : ""}</div>
              <div className="mt-2 flex items-center gap-2">
                <span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded bg-[#F1F2F4] text-[#42526E]">
                  {ROLE_LABELS[m.role] || m.role}
                </span>
                <span className="text-[11px] text-[#5E6C84]">joined {relativeTime(m.created_at)}</span>
              </div>
            </div>
            {!m.is_master_admin && (
              <button onClick={() => del(m.id)} data-testid={`team-delete-${m.id}`} className="p-1.5 hover:bg-[#FFEBE6] text-[#5E6C84] hover:text-[#FF5630] rounded">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
