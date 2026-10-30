import React, { useEffect, useState } from "react";
import { Loader2, Plus, Trash2, Printer, Send, Save, CheckCircle2, Lock } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

const EMPTY_MED = { name: "", dosage: "", frequency: "", duration: "", instructions: "" };
const VITALS = [["bp", "BP"], ["pulse", "Pulse"], ["temp", "Temp"], ["spo2", "SpO₂"], ["weight", "Weight"]];
const inp = "w-full px-2.5 py-1.5 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none";
const L = ({ t, children, hint }) => <label className="block text-xs font-semibold text-[#42526E]">{t}{hint && <span className="font-normal text-[#97A0AF]"> · {hint}</span>}<div className="mt-1">{children}</div></label>;

const fromEhr = (e, a) => ({
  chief_complaint: e?.chief_complaint || a?.reason || "", diagnosis: (e?.diagnosis || []).join(", "), vitals: e?.vitals || {},
  notes: e?.notes || "", treatment_plan: e?.treatment_plan || "", prescriptions: e?.prescriptions?.length ? e.prescriptions : [{ ...EMPTY_MED }],
  investigations: (e?.investigations || []).join(", "), follow_up_date: e?.follow_up_date ? e.follow_up_date.slice(0, 10) : "", follow_up_notes: e?.follow_up_notes || "",
});

function Meds({ meds, set }) {
  const upd = (i, k, v) => set(meds.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  return (
    <div className="space-y-2" data-testid="consult-meds">
      {meds.map((m, i) => (
        <div key={i} className="grid grid-cols-12 gap-1.5 items-center" data-testid={`consult-med-${i}`}>
          <input value={m.name} onChange={(e) => upd(i, "name", e.target.value)} placeholder="Medicine" className={`${inp} col-span-12 sm:col-span-3`} data-testid={`consult-med-name-${i}`} />
          <input value={m.dosage} onChange={(e) => upd(i, "dosage", e.target.value)} placeholder="Dose (1 tab)" className={`${inp} col-span-4 sm:col-span-2`} />
          <input value={m.frequency} onChange={(e) => upd(i, "frequency", e.target.value)} placeholder="1-0-1" className={`${inp} col-span-4 sm:col-span-2`} />
          <input value={m.duration} onChange={(e) => upd(i, "duration", e.target.value)} placeholder="5 days" className={`${inp} col-span-4 sm:col-span-2`} />
          <input value={m.instructions} onChange={(e) => upd(i, "instructions", e.target.value)} placeholder="After food" className={`${inp} col-span-10 sm:col-span-2`} />
          <button type="button" onClick={() => set(meds.length > 1 ? meds.filter((_, j) => j !== i) : [{ ...EMPTY_MED }])} className="col-span-2 sm:col-span-1 justify-self-center text-[#97A0AF] hover:text-[#BF2600]" aria-label="Remove medicine" data-testid={`consult-med-remove-${i}`}><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      <button type="button" onClick={() => set([...meds, { ...EMPTY_MED }])} className="inline-flex items-center gap-1 text-xs font-semibold text-[#0052CC]" data-testid="consult-med-add"><Plus className="h-3.5 w-3.5" /> Add medicine</button>
    </div>
  );
}

/** Notes + prescription for one appointment, stored in the shared consultation_ehr row (same record as the Provider app). */
export function ConsultEditor({ appt, onClose, onChanged }) {
  const [s, setS] = useState({ loading: true });
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState("");
  const base = appt ? `/provider/doctor/appointments/${appt.source}/${appt.id}/consult` : "";
  useEffect(() => {
    if (!appt) return;
    setS({ loading: true }); setF(null);
    api.get(base).then(({ data }) => { setS({ loading: false, ...data }); setF(fromEhr(data.ehr, data.appointment)); })
      .catch((e) => setS({ loading: false, err: e?.response?.data?.detail || "Could not load" }));
  }, [appt, base]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const final = ["completed", "cancelled", "canceled", "no_show"].includes(String(s.appointment?.status || "").toLowerCase());

  const save = async (complete = false) => {
    setBusy(complete ? "complete" : "save");
    try {
      const { data } = await api.put(base, { ...f, investigations: f.investigations.split(",").map((x) => x.trim()).filter(Boolean), follow_up_date: f.follow_up_date || null, complete });
      setS((p) => ({ ...p, ehr: data.ehr, appointment: complete ? { ...p.appointment, status: "completed" } : p.appointment }));
      toast.success(complete ? "Saved and marked completed" : "Saved — visible in your Provider app too");
      onChanged?.();
      return true;
    } catch (e) { toast.error(e?.response?.data?.detail || "Save failed"); return false; }
    finally { setBusy(""); }
  };
  const share = async () => {
    if (!(await save())) return;
    setBusy("share");
    try {
      const { data } = await api.post(`${base}/share`);
      setS((p) => ({ ...p, ehr: data.ehr }));
      toast.success(data.patient_notified ? "Prescription shared — the patient has been notified" : "Prescription shared (patient has no app account to notify)");
    } catch (e) { toast.error(e?.response?.data?.detail || "Share failed"); }
    setBusy("");
  };
  const stale = s.ehr?.shared && s.ehr?.updated_at && s.ehr?.signed_at && new Date(s.ehr.updated_at) - new Date(s.ehr.signed_at) > 2000;

  return (
    <Dialog open={!!appt} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[92vh] overflow-y-auto" data-testid="consult-editor">
        <DialogHeader><DialogTitle className="font-heading text-xl">Consultation · {appt?.patient_name || "Patient"}</DialogTitle></DialogHeader>
        {s.loading || !f ? <div className="py-10 text-sm text-[#5E6C84] flex items-center gap-2">{s.err || <><Loader2 className="h-4 w-4 animate-spin" /> Loading…</>}</div> : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="consult-share-state">
              {s.ehr?.shared
                ? <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-[#E3FCEF] text-[#006644] font-semibold"><CheckCircle2 className="h-3.5 w-3.5" /> Shared with patient {new Date(s.ehr.signed_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                : <span className="px-2 py-1 rounded bg-[#F4F5F7] text-[#42526E] font-semibold">Not shared with patient yet</span>}
              {stale && <span className="px-2 py-1 rounded bg-[#FFFAE6] text-[#974F0C]" data-testid="consult-stale">Edited after sharing — share again to update the patient</span>}
              <span className="text-[#97A0AF]">Synced with your Provider app</span>
            </div>
            <L t="Chief complaint"><textarea rows={2} value={f.chief_complaint} onChange={set("chief_complaint")} className={inp} data-testid="consult-complaint" /></L>
            <div className="grid grid-cols-5 gap-2">{VITALS.map(([k, l]) => (
              <L key={k} t={l}><input value={f.vitals[k] || ""} onChange={(e) => setF({ ...f, vitals: { ...f.vitals, [k]: e.target.value } })} className={inp} data-testid={`consult-vital-${k}`} /></L>))}</div>
            <L t="Diagnosis" hint="separate with commas"><input value={f.diagnosis} onChange={set("diagnosis")} className={inp} data-testid="consult-diagnosis" /></L>
            <div><div className="text-xs font-semibold text-[#42526E] mb-1">Prescription</div><Meds meds={f.prescriptions} set={(m) => setF({ ...f, prescriptions: m })} /></div>
            <L t="Advice for the patient"><textarea rows={2} value={f.treatment_plan} onChange={set("treatment_plan")} className={inp} data-testid="consult-advice" /></L>
            <div className="grid sm:grid-cols-3 gap-3">
              <L t="Tests advised" hint="commas"><input value={f.investigations} onChange={set("investigations")} className={inp} data-testid="consult-tests" /></L>
              <L t="Follow-up date"><input type="date" value={f.follow_up_date} onChange={set("follow_up_date")} className={inp} data-testid="consult-followup-date" /></L>
              <L t="Follow-up note"><input value={f.follow_up_notes} onChange={set("follow_up_notes")} className={inp} data-testid="consult-followup-note" /></L>
            </div>
            <L t={<span className="inline-flex items-center gap-1"><Lock className="h-3 w-3" /> Private notes</span>} hint="never shown to the patient">
              <textarea rows={3} value={f.notes} onChange={set("notes")} className={`${inp} bg-[#FFFAE6]/40`} data-testid="consult-private-notes" /></L>
            <div className="flex flex-wrap gap-2 pt-2 border-t border-[#DFE1E6]">
              <button onClick={() => save(false)} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-md border border-[#DFE1E6] text-[#091E42] hover:bg-[#F4F5F7] disabled:opacity-50" data-testid="consult-save-btn">
                {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save</button>
              {!final && <button onClick={() => save(true)} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-md bg-[#36B37E] text-white hover:bg-[#00875A] disabled:opacity-50" data-testid="consult-complete-btn">
                {busy === "complete" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Save &amp; mark completed</button>}
              <button onClick={share} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-50" data-testid="consult-share-btn">
                {busy === "share" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} {s.ehr?.shared ? "Share again" : "Share with patient"}</button>
              <button onClick={async () => { if (await save()) window.open(`/provider/rx/${appt.source}/${appt.id}`, "_blank"); }} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] ml-auto" data-testid="consult-print-btn">
                <Printer className="h-4 w-4" /> Print / PDF</button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
