import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw, Link2, KeyRound, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { T, toastErr } from "../ledger/ui";

const TONE = { linked: "bg-[#E3FCEF] text-[#006644]", link_requested: "bg-[#DEEBFF] text-[#0747A6]", new: "bg-[#F4F5F7] text-[#42526E]", failed: "bg-[#FFEBE6] text-[#BF2600]" };
const LABEL = { linked: "Linked to ABHA", link_requested: "Linking…", new: "Queued", failed: "Failed" };
const HI = { DischargeSummary: "Discharge summary", DiagnosticReport: "Lab / diagnostic report", OPConsultation: "OPD consultation", Prescription: "Prescription", Invoice: "Bill" };

export function HealthRecordsPanel({ patientUserId, refreshKey, showConsents = true }) {
  const [d, setD] = useState(null);
  const [lr, setLr] = useState([]);
  const [consents, setConsents] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api.get("/abdm/care-contexts", { params: patientUserId ? { patient_user_id: patientUserId } : {} }).then((r) => setD(r.data)).catch((e) => toastErr(e, "Could not load shared records"));
    if (!patientUserId) {
      api.get("/abdm/link-requests").then((r) => setLr(r.data.link_requests)).catch(() => {});
      if (showConsents) api.get("/abdm/consents").then((r) => setConsents(r.data.consents)).catch(() => {});
    }
  }, [patientUserId, showConsents]);
  useEffect(() => { load(); }, [load, refreshKey]);
  const sync = async () => {
    setBusy(true);
    try { const { data } = await api.post("/abdm/care-contexts/sync", { patient_user_id: patientUserId || null }); toast.success(`Checked records · ${data.new_records ?? data.new ?? 0} new`); load(); }
    catch (e) { toastErr(e, "Sync failed"); } finally { setBusy(false); }
  };
  const rows = d?.care_contexts || [];

  return (
    <section className={T.card} data-testid="abdm-health-records">
      <div className={T.head}>
        <span className="flex items-center gap-1.5"><Link2 className="h-3.5 w-3.5" /> Records shared to ABHA ({rows.length})</span>
        <div className="flex items-center gap-2 normal-case tracking-normal font-normal">
          {d && Object.entries(d.counts).map(([k, v]) => <span key={k} className={`${T.chip} ${TONE[k] || ""}`} data-testid={`abdm-count-${k}`}>{LABEL[k] || k} {v}</span>)}
          <button className={T.btnGhost} onClick={sync} disabled={busy} data-testid="abdm-sync-now"><RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} /> Sync now</button>
        </div>
      </div>
      {lr.length > 0 && <div className="px-4 py-3 bg-[#FFFAE6] border-b border-[#FFE380]" data-testid="abdm-link-requests">
        <div className="text-[11px] font-bold text-[#974F0C] flex items-center gap-1"><KeyRound className="h-3.5 w-3.5" /> Patients linking from their ABHA app — read the code to the patient (SMS delivery not set up)</div>
        {lr.map((x) => <div key={x.id} className="text-xs mt-1" data-testid={`abdm-link-request-${x.id}`}>{x.patient_name || x.abha_address} · {x.references.length} record(s) · code <b className="font-mono tracking-widest">{x.otp_display}</b> · expires {x.expires_at.slice(11, 16)} UTC</div>)}
      </div>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]"><tr>
            {["Record", "Type", !patientUserId && "Patient", "Provider", "Date", "Status"].filter(Boolean).map((h) => <th key={h} className="px-3 py-2 text-left">{h}</th>)}
          </tr></thead>
          <tbody>
            {d && rows.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-[#5E6C84]" data-testid="abdm-records-empty">No shareable records yet. Discharge summaries, lab reports, OPD notes, prescriptions and bills appear here once the patient has an ABHA.</td></tr>}
            {rows.map((c) => (
              <tr key={c.reference} className="border-t border-[#DFE1E6]" data-testid={`abdm-cc-${c.reference}`}>
                <td className="px-3 py-2"><div className="font-semibold">{c.display}</div><div className="font-mono text-[10px] text-[#97A0AF]">{c.reference}</div></td>
                <td className="px-3 py-2">{HI[c.hi_type] || c.hi_type}</td>
                {!patientUserId && <td className="px-3 py-2">{c.patient_name}<div className="text-[10px] text-[#5E6C84]">{c.abha_address}</div></td>}
                <td className="px-3 py-2">{c.provider_name || "—"}</td>
                <td className="px-3 py-2 whitespace-nowrap">{(c.record_date || "").slice(0, 10)}</td>
                <td className="px-3 py-2"><span className={`${T.chip} ${TONE[c.status] || ""}`}>{LABEL[c.status] || c.status}</span>
                  {c.status_note && <div className="text-[10px] text-[#5E6C84] max-w-[220px] truncate" title={c.status_note}>{c.status_note}</div>}
                  {c.share_count > 0 && <div className="text-[10px] text-[#006644]">Shared {c.share_count}× with consent</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!patientUserId && showConsents && consents.length > 0 && <div className="border-t border-[#DFE1E6] px-4 py-3" data-testid="abdm-consents">
        <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold mb-1.5 flex items-center gap-1"><ShieldCheck className="h-3.5 w-3.5" /> Patient consents received</div>
        {consents.map((c) => <div key={c.consent_id} className="text-xs py-1 flex flex-wrap gap-2" data-testid={`abdm-consent-${c.consent_id}`}>
          <span className={`${T.chip} ${c.status === "GRANTED" ? TONE.linked : TONE.failed}`}>{c.status}</span>
          <span>{c.patient}</span><span className="text-[#5E6C84]">{c.purpose} · {c.requester || c.hiu} · {(c.care_contexts || []).length} record(s)</span>
        </div>)}
      </div>}
    </section>
  );
}
