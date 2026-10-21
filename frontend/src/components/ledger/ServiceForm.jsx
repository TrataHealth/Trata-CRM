import React, { useState } from "react";
import { Sparkles, Upload, Loader2, FileText, X, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";
import { T, pretty, toastErr, openFile } from "./ui";

const EMPTY = { category: "surgery", title: "", service_date: new Date().toISOString().slice(0, 10), amount: "", notes: "", line_items: [] };

function FileChip({ f, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] bg-[#F4F5F7] border border-[#DFE1E6] rounded px-2 py-1" data-testid={`proof-chip-${f.id}`}>
      <FileText className="h-3 w-3 text-[#0052CC]" />
      <button type="button" className="hover:underline truncate max-w-[160px]" onClick={() => openFile(f.id)}>{f.filename}</button>
      <button type="button" onClick={onRemove} aria-label="Remove"><X className="h-3 w-3 text-[#5E6C84]" /></button>
    </span>
  );
}

function LineItems({ items, onChange }) {
  const set = (i, k, v) => onChange(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  return (
    <div className="space-y-1" data-testid="service-line-items">
      {items.map((it, i) => (
        <div key={i} className="flex gap-2">
          <input className={T.input} placeholder="Item" value={it.description} onChange={(e) => set(i, "description", e.target.value)} />
          <input className={`${T.input} w-28`} inputMode="decimal" placeholder="₹" value={it.amount} onChange={(e) => set(i, "amount", e.target.value)} />
          <button type="button" onClick={() => onChange(items.filter((_, j) => j !== i))} className="mt-1 text-[#5E6C84]"><Trash2 className="h-3.5 w-3.5" /></button>
        </div>
      ))}
      <button type="button" className="text-[11px] text-[#0052CC] inline-flex items-center gap-1" onClick={() => onChange([...items, { description: "", amount: "" }])} data-testid="service-add-line">
        <Plus className="h-3 w-3" /> Add bill line
      </button>
    </div>
  );
}

// mode: "admin" (uid required) | "provider"
export function ServiceForm({ open, onClose, mode, uid, patients, defaultPatient, categories, onSaved }) {
  const [patientId, setPatientId] = useState(defaultPatient || "");
  const [form, setForm] = useState(EMPTY);
  const [proofs, setProofs] = useState([]);
  const [busy, setBusy] = useState("");
  const [ai, setAi] = useState(null);
  const base = mode === "admin" ? `/ledger/providers/${uid}` : "/provider/ledger";
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  React.useEffect(() => {
    if (open) { setPatientId(defaultPatient || ""); setForm(EMPTY); setProofs([]); setAi(null); }
  }, [open, defaultPatient]);

  const upload = async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const { data } = await api.post(`${base}/files`, fd);
    setProofs((p) => [...p, data]);
    return data;
  };

  const onFiles = async (files, withAi) => {
    for (const f of files) {
      setBusy(withAi ? "ai" : "upload");
      try {
        const up = await upload(f);
        if (withAi) {
          const { data } = await api.post(`/ledger/ai-extract/${up.id}`);
          const x = data.extracted || {};
          setAi(x);
          setForm((cur) => ({
            ...cur, category: x.category || cur.category, title: x.title || cur.title,
            service_date: /^\d{4}-\d{2}-\d{2}$/.test(x.service_date || "") ? x.service_date : cur.service_date,
            amount: x.amount != null ? String(x.amount) : cur.amount,
            notes: [x.notes, x.bill_number && `Bill #${x.bill_number}`, x.doctor_name && `Dr. ${x.doctor_name}`].filter(Boolean).join(" · ") || cur.notes,
            line_items: (x.line_items || []).map((l) => ({ description: l.description, amount: String(l.amount ?? "") })),
          }));
          if (x.patient_name) {
            const hit = patients.find((p) => (p.name || "").toLowerCase().includes(x.patient_name.toLowerCase().split(" ")[0]));
            if (hit && !patientId) setPatientId(hit.key);
          }
          toast.success("AI filled the form — please review every field");
        }
      } catch (e) { toastErr(e, withAi ? "AI extraction failed — fill manually" : "Upload failed"); }
      finally { setBusy(""); }
    }
  };

  const submit = async () => {
    if (!patientId) return toast.error("Pick the patient");
    if (!form.title.trim() || form.amount === "") return toast.error("Service name and amount are required");
    if (!proofs.length) return toast.error("Upload at least one proof document");
    setBusy("save");
    try {
      const p = patients.find((x) => x.key === patientId);
      await api.post(`${base}/services`, {
        patient_id: patientId, patient_name: p?.name, ...form, amount: parseFloat(form.amount),
        line_items: form.line_items.filter((l) => l.description).map((l) => ({ description: l.description, amount: parseFloat(l.amount) || 0 })),
        proof_file_ids: proofs.map((f) => f.id), source: ai ? "ai" : "manual", ai_extracted: ai,
      });
      toast.success(mode === "admin" ? "Service added & approved" : "Submitted for Trata review");
      onSaved();
      onClose();
    } catch (e) { toastErr(e, "Could not save service"); }
    finally { setBusy(""); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="service-form-dialog">
        <DialogHeader><DialogTitle className="font-heading">Add extended service</DialogTitle></DialogHeader>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="relative border-2 border-dashed border-[#B3D4FF] bg-[#F4F8FF] rounded-md p-3 cursor-pointer hover:bg-[#DEEBFF] transition-colors" data-testid="service-ai-upload">
            <input type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => onFiles([...e.target.files], true)} />
            <div className="flex items-center gap-2 text-sm font-semibold text-[#0747A6]">
              {busy === "ai" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Auto-fill from bill (AI)
            </div>
            <div className="text-[11px] text-[#42526E] mt-1">Upload the hospital bill / OT note PDF. AI reads it and fills the form; the file is kept as proof.</div>
          </label>
          <label className="border-2 border-dashed border-[#DFE1E6] rounded-md p-3 cursor-pointer hover:bg-[#F4F5F7] transition-colors" data-testid="service-proof-upload">
            <input type="file" multiple accept="application/pdf,image/*" className="hidden" onChange={(e) => onFiles([...e.target.files], false)} />
            <div className="flex items-center gap-2 text-sm font-semibold text-[#42526E]">
              {busy === "upload" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload proof documents *
            </div>
            <div className="text-[11px] text-[#5E6C84] mt-1">PDF / JPG / PNG, up to 15 MB each. At least one is mandatory.</div>
          </label>
        </div>
        {proofs.length > 0 && <div className="flex flex-wrap gap-1.5" data-testid="service-proofs">{proofs.map((f) => <FileChip key={f.id} f={f} onRemove={() => setProofs(proofs.filter((x) => x.id !== f.id))} />)}</div>}
        {ai && <div className="text-[11px] bg-[#FFFAE6] border border-[#FFE380] rounded px-2 py-1.5 text-[#974F0C]" data-testid="service-ai-banner">AI-filled{ai.confidence != null ? ` · confidence ${Math.round(ai.confidence * 100)}%` : ""}{ai.patient_name ? ` · bill patient: ${ai.patient_name}` : ""}. Check every field before saving.</div>}
        <div className="grid sm:grid-cols-2 gap-3">
          <label className={T.label}>Patient (came via Trata app) *
            <select className={T.input} value={patientId} onChange={(e) => setPatientId(e.target.value)} data-testid="service-patient">
              <option value="">Select patient…</option>
              {patients.map((p) => <option key={p.key} value={p.key}>{p.name || p.phone || p.key.slice(0, 8)}</option>)}
            </select>
          </label>
          <label className={T.label}>Category *
            <select className={T.input} value={form.category} onChange={set("category")} data-testid="service-category">
              {categories.map((c) => <option key={c} value={c}>{pretty(c)}</option>)}
            </select>
          </label>
          <label className={`${T.label} sm:col-span-2`}>Service name *
            <input className={T.input} value={form.title} onChange={set("title")} placeholder="e.g. Laparoscopic appendectomy" data-testid="service-title" />
          </label>
          <label className={T.label}>Service date *
            <input type="date" className={T.input} value={form.service_date} onChange={set("service_date")} data-testid="service-date" />
          </label>
          <label className={T.label}>Bill amount (₹) *
            <input className={T.input} inputMode="decimal" value={form.amount} onChange={set("amount")} placeholder="0.00" data-testid="service-amount" />
          </label>
        </div>
        <LineItems items={form.line_items} onChange={(li) => setForm({ ...form, line_items: li })} />
        <label className={T.label}>Notes
          <textarea rows={2} className={T.input} value={form.notes} onChange={set("notes")} data-testid="service-notes" />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button className={T.btnGhost} onClick={onClose} data-testid="service-cancel">Cancel</button>
          <button className={T.btn} onClick={submit} disabled={!!busy} data-testid="service-submit">
            {busy === "save" && <Loader2 className="h-3.5 w-3.5 animate-spin" />} {mode === "admin" ? "Save & approve" : "Submit for review"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
