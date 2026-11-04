import React, { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export const ROLE_LABEL = {
  lab_technician: "Lab technician", pathologist: "Pathologist", phlebotomist: "Phlebotomist",
  front_desk: "Front desk", admin: "Admin", radiologist: "Radiologist",
};
const EMPTY = { name: "", role: "", phone: "", email: "", qualification: "", specialization: "", shift_start: "", shift_end: "", is_active: true };

/** Add / edit form for one lab staff member. */
export function LabStaffForm({ roles, initial, busy, onSave, onCancel }) {
  const [f, setF] = useState({ ...EMPTY, role: roles[0], ...(initial || {}) });
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));
  const field = (k, ph, type = "text") => (
    <Input value={f[k] || ""} onChange={set(k)} placeholder={ph} type={type} data-testid={`lab-staff-${k}`} className="h-9 text-sm" />
  );
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave(f); }} className="grid sm:grid-cols-4 gap-2 p-3 bg-[#F8F9FA] border border-[#DFE1E6] rounded-md" data-testid="lab-staff-form">
      {field("name", "Full name *")}
      <select value={f.role} onChange={set("role")} data-testid="lab-staff-role" className="h-9 px-2 text-sm border border-[#DFE1E6] rounded-md bg-white">
        {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] || r}</option>)}
      </select>
      {field("phone", "Phone")}
      {field("email", "Email", "email")}
      {field("qualification", "Qualification")}
      {field("specialization", "Specialization")}
      {field("shift_start", "Shift start (e.g. 09:00)")}
      {field("shift_end", "Shift end (e.g. 17:00)")}
      <label className="flex items-center gap-2 text-sm text-[#42526E]">
        <input type="checkbox" checked={f.is_active} onChange={(e) => setF((p) => ({ ...p, is_active: e.target.checked }))} data-testid="lab-staff-active" /> Active
      </label>
      <div className="sm:col-span-3 flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel} data-testid="lab-staff-cancel">Cancel</Button>
        <Button type="submit" size="sm" disabled={busy || !f.name.trim()} data-testid="lab-staff-save">{initial ? "Save changes" : "Add staff"}</Button>
      </div>
    </form>
  );
}
