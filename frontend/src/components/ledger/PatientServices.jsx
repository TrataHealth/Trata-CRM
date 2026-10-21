import React, { useState } from "react";
import { ChevronDown, ChevronRight, FileText, Plus, Sparkles, Smartphone, Trash2 } from "lucide-react";
import api from "../../lib/api";
import { relativeTime } from "../../lib/constants";
import { T, money, KIND_LABEL, STATUS_TONE, pretty, openFile, toastErr } from "./ui";

function Details({ s }) {
  const entries = Object.entries(s.details || {});
  return (
    <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1 text-[11px]" data-testid={`service-details-${s.key}`}>
      {entries.map(([k, v]) => (
        <div key={k} className="min-w-0"><span className="text-[#5E6C84]">{k}: </span><span className="text-[#091E42] break-words">{String(v)}</span></div>
      ))}
      {s.notes && <div className="sm:col-span-3"><span className="text-[#5E6C84]">Notes: </span>{s.notes}</div>}
      {(s.line_items || []).length > 0 && (
        <div className="sm:col-span-3 mt-1 border border-[#DFE1E6] rounded">
          {s.line_items.map((l, i) => (
            <div key={i} className="flex justify-between px-2 py-1 border-b border-[#F4F5F7] last:border-0"><span>{l.description}</span><span className="font-mono">{money(l.amount)}</span></div>
          ))}
        </div>
      )}
      {(s.proofs || []).length > 0 && (
        <div className="sm:col-span-3 flex flex-wrap gap-1.5 mt-1">
          {s.proofs.map((f) => (
            <button key={f.id} onClick={() => openFile(f.id)} className="inline-flex items-center gap-1 text-[11px] text-[#0052CC] hover:underline" data-testid={`proof-open-${f.id}`}>
              <FileText className="h-3 w-3" /> {f.filename}
            </button>
          ))}
        </div>
      )}
      {s.review_reason && <div className="sm:col-span-3 text-[#BF2600]">Review note: {s.review_reason}</div>}
      {s.created_by && <div className="sm:col-span-3 text-[#5E6C84]">Added by {s.created_by.name} ({pretty(s.created_by.role)}){s.reviewed_by ? ` · reviewed by ${s.reviewed_by.name}` : ""}</div>}
    </div>
  );
}

function ServiceRow({ s, canDelete, onChanged }) {
  const [open, setOpen] = useState(false);
  const del = async () => {
    if (!window.confirm("Remove this service entry?")) return;
    try { await api.delete(`/ledger/services/${s.ref_id}`); onChanged(); } catch (e) { toastErr(e); }
  };
  const isManual = s.kind === "manual";
  return (
    <div className="px-3 py-2 border-t border-[#F4F5F7]" data-testid={`service-row-${s.key}`}>
      <div className="flex items-start justify-between gap-3">
        <button className="flex items-start gap-2 text-left min-w-0" onClick={() => setOpen(!open)} data-testid={`service-toggle-${s.key}`}>
          {open ? <ChevronDown className="h-3.5 w-3.5 mt-0.5 text-[#5E6C84]" /> : <ChevronRight className="h-3.5 w-3.5 mt-0.5 text-[#5E6C84]" />}
          <div className="min-w-0">
            <div className="text-xs font-semibold text-[#091E42] truncate">{s.title}</div>
            <div className="text-[10px] text-[#5E6C84] flex items-center gap-1.5 flex-wrap">
              <span className="font-semibold">{KIND_LABEL[s.kind] || s.kind}{isManual && s.category ? ` · ${pretty(s.category)}` : ""}</span>
              <span>· {(s.date || "").slice(0, 10)}</span>
              {isManual ? (s.source === "ai" && <span className="inline-flex items-center gap-0.5 text-[#5243AA]"><Sparkles className="h-2.5 w-2.5" />AI-filled</span>)
                : <span className="inline-flex items-center gap-0.5 text-[#00875A]"><Smartphone className="h-2.5 w-2.5" />Patient app</span>}
              {s.invoice_id && <span className="text-[#0747A6]">· invoiced</span>}
            </div>
          </div>
        </button>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`${T.chip} ${STATUS_TONE[s.status] || "bg-[#F4F5F7] text-[#42526E]"}`}>{pretty(s.status)}</span>
          <span className="text-xs font-bold font-mono text-[#091E42] w-24 text-right">{s.amount ? money(s.amount) : "—"}</span>
          {isManual && canDelete && !s.invoice_id && <button onClick={del} className="text-[#5E6C84] hover:text-[#BF2600]" data-testid={`service-delete-${s.key}`}><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
      </div>
      {open && <Details s={s} />}
    </div>
  );
}

export function PatientServices({ patients, onAdd, onChanged, canDelete }) {
  const [open, setOpen] = useState({});
  if (!patients.length) {
    return <div className={`${T.card} p-8 text-center text-sm text-[#5E6C84]`} data-testid="ledger-patients-empty">No patients have reached this provider through the Trata Health app yet.</div>;
  }
  return (
    <div className="space-y-2" data-testid="ledger-patients">
      {patients.map((p) => {
        const isOpen = open[p.key] ?? patients.length <= 3;
        return (
          <section key={p.key} className={T.card} data-testid={`ledger-patient-${p.key}`}>
            <div className="px-4 py-3 flex items-center justify-between gap-3">
              <button className="flex items-center gap-2 min-w-0 text-left" onClick={() => setOpen({ ...open, [p.key]: !isOpen })} data-testid={`ledger-patient-toggle-${p.key}`}>
                {isOpen ? <ChevronDown className="h-4 w-4 text-[#5E6C84]" /> : <ChevronRight className="h-4 w-4 text-[#5E6C84]" />}
                <div className="h-8 w-8 rounded-full bg-[#DEEBFF] text-[#0747A6] text-xs font-bold flex items-center justify-center shrink-0">{(p.name || "?").slice(0, 1).toUpperCase()}</div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-[#091E42] truncate">{p.name || "Unnamed patient"}</div>
                  <div className="text-[11px] text-[#5E6C84]">{p.phone || "—"} · {p.services.length} service{p.services.length === 1 ? "" : "s"} · first visit {p.first_seen ? relativeTime(p.first_seen) : "—"}</div>
                </div>
              </button>
              <div className="flex items-center gap-3 shrink-0">
                {p.pending_review > 0 && <span className={`${T.chip} ${STATUS_TONE.pending_review}`}>{p.pending_review} to review</span>}
                <div className="text-right"><div className="text-[10px] text-[#5E6C84] uppercase">Billable</div><div className="text-sm font-black font-mono">{money(p.total_amount)}</div></div>
                <button className={T.btnGhost} onClick={() => onAdd(p.key)} data-testid={`ledger-add-service-${p.key}`}><Plus className="h-3.5 w-3.5" /> Add service</button>
              </div>
            </div>
            {isOpen && p.services.map((s) => <ServiceRow key={s.key} s={s} canDelete={canDelete(s)} onChanged={onChanged} />)}
          </section>
        );
      })}
    </div>
  );
}
