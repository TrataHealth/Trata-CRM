import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Check, X, FileText, Sparkles, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { T, money, pretty, openFile, toastErr } from "../components/ledger/ui";

function ReviewCard({ s, onDone }) {
  const [amount, setAmount] = useState(String(s.amount));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (action) => {
    if (action === "reject" && !reason.trim()) return toast.error("Add a reason to reject");
    setBusy(true);
    try {
      await api.post(`/ledger/services/${s.id}/review`, { action, reason: reason || null, amount: action === "approve" ? parseFloat(amount) : null });
      toast.success(action === "approve" ? "Approved — now billable" : "Rejected");
      onDone();
    } catch (e) { toastErr(e); } finally { setBusy(false); }
  };
  return (
    <section className={`${T.card} p-4 space-y-2`} data-testid={`review-card-${s.id}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{s.provider_name || "Provider"} · {pretty(s.category)}</div>
          <div className="text-sm font-semibold text-[#091E42]">{s.title}</div>
          <div className="text-[11px] text-[#5E6C84]">Patient {s.patient_name || s.patient_phone || "—"} · {s.service_date} · by {s.created_by?.name}
            {s.source === "ai" && <span className="ml-1 inline-flex items-center gap-0.5 text-[#5243AA]"><Sparkles className="h-2.5 w-2.5" /> AI-filled</span>}</div>
        </div>
        <div className="text-right"><div className="text-[10px] text-[#5E6C84]">Claimed</div><div className="font-mono font-black">{money(s.amount)}</div></div>
      </div>
      {s.notes && <div className="text-[11px] text-[#42526E]">{s.notes}</div>}
      {(s.line_items || []).length > 0 && (
        <div className="border border-[#DFE1E6] rounded text-[11px]">{s.line_items.map((l, i) => <div key={i} className="flex justify-between px-2 py-1 border-b border-[#F4F5F7] last:border-0"><span>{l.description}</span><span className="font-mono">{money(l.amount)}</span></div>)}</div>
      )}
      {s.ai_extracted && <div className="text-[10px] text-[#5E6C84]">AI read: {s.ai_extracted.title || "—"} · {s.ai_extracted.amount != null ? money(s.ai_extracted.amount) : "—"} · {s.ai_extracted.patient_name || "no patient name"}</div>}
      <div className="flex flex-wrap gap-2">{(s.proofs || []).map((f) => (
        <button key={f.id} onClick={() => openFile(f.id)} className="inline-flex items-center gap-1 text-[11px] text-[#0052CC] border border-[#B3D4FF] rounded px-2 py-1 hover:bg-[#DEEBFF]" data-testid={`review-proof-${f.id}`}><FileText className="h-3 w-3" /> {f.filename}</button>
      ))}</div>
      <div className="grid sm:grid-cols-4 gap-2 items-end pt-1">
        <label className={T.label}>Approved amount (₹)<input className={T.input} value={amount} onChange={(e) => setAmount(e.target.value)} data-testid={`review-amount-${s.id}`} /></label>
        <label className={`${T.label} sm:col-span-2`}>Note / rejection reason<input className={T.input} value={reason} onChange={(e) => setReason(e.target.value)} data-testid={`review-reason-${s.id}`} /></label>
        <div className="flex gap-2">
          <button className={T.btn} disabled={busy} onClick={() => act("approve")} data-testid={`review-approve-${s.id}`}><Check className="h-3.5 w-3.5" /> Approve</button>
          <button className={T.btnDanger} disabled={busy} onClick={() => act("reject")} data-testid={`review-reject-${s.id}`}><X className="h-3.5 w-3.5" /> Reject</button>
        </div>
      </div>
    </section>
  );
}

export default function AdminLedgerReview() {
  const [items, setItems] = useState(null);
  const load = useCallback(() => api.get("/ledger/review-queue").then(({ data }) => setItems(data.items)).catch((e) => toastErr(e)), []);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-4 max-w-5xl" data-testid="ledger-review">
      <Link to="/admin/ledger" className="text-xs text-[#0052CC] inline-flex items-center gap-1"><ArrowLeft className="h-3 w-3" /> Provider ledger</Link>
      <div>
        <h1 className="font-heading text-2xl font-black text-[#091E42]">Extended services · review queue</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Services submitted by providers (manual or AI-filled). Check the proof documents, adjust the amount if needed, then approve to make them billable.</p>
      </div>
      {items === null ? <div className="flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
        : items.length === 0 ? <div className={`${T.card} p-8 text-center text-sm text-[#5E6C84]`} data-testid="review-empty">Nothing waiting for review.</div>
        : items.map((s) => <ReviewCard key={s.id} s={s} onDone={load} />)}
    </div>
  );
}
