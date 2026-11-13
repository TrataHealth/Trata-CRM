import React, { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

const PERSON = ["doctor", "paramedic", "nutritionist", "wellness", "ambulance_driver"];
const input = "mt-1 w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none font-normal";

/** Master admin: edit a provider profile's names and phone. */
export function EditProviderDialog({ row, onClose, onDone }) {
  const [f, setF] = useState({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (row) setF({ provider_name: row.org_name || "", admin_name: row.admin_name || "", phone: row.phone || "" }); }, [row]);
  if (!row) return null;
  const person = PERSON.includes(row.role);
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));
  const save = async () => {
    const body = {};
    if (!person && f.provider_name.trim() !== (row.org_name || "")) body.provider_name = f.provider_name.trim();
    if (f.admin_name.trim() !== (row.admin_name || "")) body.admin_name = f.admin_name.trim();
    if (f.phone.trim() !== (row.phone || "")) body.phone = f.phone.trim();
    if (!Object.keys(body).length) return onClose();
    setBusy(true);
    try {
      const { data } = await api.put(`/admin/directory/profiles/${row.profile_table}/${row.profile_id}`, body);
      if (data.notes?.includes("sign_in_unchanged_patient_app"))
        toast.warning("Listed phone updated. Sign-in number kept, because this login is also used for the Patient App.");
      else toast.success(data.updated.some((u) => u === "users.phone") ? "Saved — they now sign in with the new number" : "Saved");
      onDone();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="edit-provider-dialog">
        <DialogHeader><DialogTitle className="font-heading">Edit provider details</DialogTitle></DialogHeader>
        {!person && <label className="text-xs font-semibold text-[#42526E] block">Provider name
          <input value={f.provider_name} onChange={set("provider_name")} className={input} data-testid="edit-provider-name" /></label>}
        <label className="text-xs font-semibold text-[#42526E] block">{person ? "Name" : "Admin name"}
          <input value={f.admin_name} onChange={set("admin_name")} className={input} data-testid="edit-admin-name" /></label>
        <label className="text-xs font-semibold text-[#42526E] block">Phone
          <input value={f.phone} onChange={set("phone")} inputMode="tel" className={input} data-testid="edit-phone" />
          <span className="block mt-1 font-normal text-[#5E6C84]">{row.id ? "Also changes the number they sign in to the Provider App with. Their Patient App account isn't changed." : "This provider has no app login yet — only the listed number changes."}</span></label>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-[#DFE1E6]" data-testid="edit-cancel">Cancel</button>
          <button onClick={save} disabled={busy} className="px-4 py-2 text-sm font-semibold rounded-md bg-[#0052CC] text-white disabled:opacity-60 inline-flex items-center gap-1.5" data-testid="edit-save">
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
