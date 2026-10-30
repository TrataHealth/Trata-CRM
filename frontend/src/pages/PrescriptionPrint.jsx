import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Loader2, Printer } from "lucide-react";
import api from "../lib/api";

const fmt = (iso) => (iso ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" }) : "");

/** A4 printable prescription (patient-facing fields only — private notes are never printed). */
export default function PrescriptionPrint() {
  const { source, id } = useParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get(`/provider/doctor/appointments/${source}/${id}/consult`).then((r) => { setD(r.data); setTimeout(() => window.print(), 600); })
      .catch((e) => setErr(e?.response?.data?.detail || "Could not load prescription"));
  }, [source, id]);
  if (err) return <div className="p-10 text-sm text-[#BF2600]" data-testid="rx-print-error">{err}</div>;
  if (!d) return <div className="p-10 text-sm text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Preparing prescription…</div>;
  const { doctor: doc, appointment: a, ehr: e } = d;
  const v = e?.vitals || {};
  return (
    <div className="bg-[#F4F5F7] min-h-screen print:bg-white py-8 print:py-0" data-testid="rx-print">
      <style>{"@page { size: A4; margin: 14mm; } @media print { .no-print { display: none !important; } }"}</style>
      <div className="no-print max-w-[210mm] mx-auto mb-4 flex justify-end"><button onClick={() => window.print()} className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-md bg-[#0052CC] text-white" data-testid="rx-print-btn"><Printer className="h-4 w-4" /> Print / Save as PDF</button></div>
      <div className="max-w-[210mm] mx-auto bg-white p-10 print:p-0 shadow print:shadow-none text-[#091E42]">
        <header className="flex justify-between items-start border-b-2 border-[#0052CC] pb-4">
          <div>
            <div className="font-heading text-2xl font-black">{doc?.full_name || "Doctor"}</div>
            <div className="text-sm text-[#42526E]">{[doc?.qualification, doc?.specialization].filter(Boolean).join(" · ")}</div>
            <div className="text-xs text-[#5E6C84] mt-1">{[doc?.clinic_name || doc?.hospital_name, doc?.address, doc?.city].filter(Boolean).join(", ")}{doc?.phone ? ` · ${doc.phone}` : ""}</div>
          </div>
          <div className="text-right text-xs text-[#5E6C84]"><img src="/brand/trata-full.png" alt="" className="h-8 ml-auto mb-1" onError={(x) => { x.currentTarget.style.display = "none"; }} />Trata Health<br />{fmt(a?.date)}</div>
        </header>
        <section className="grid grid-cols-3 gap-2 text-sm py-3 border-b border-[#DFE1E6]">
          <div><span className="text-[#5E6C84]">Patient: </span><b>{a?.patient_name || "—"}</b></div>
          <div><span className="text-[#5E6C84]">Age / Sex: </span>{[a?.age, a?.gender].filter(Boolean).join(" / ") || "—"}</div>
          <div><span className="text-[#5E6C84]">Phone: </span>{a?.patient_phone || "—"}</div>
        </section>
        {Object.values(v).some(Boolean) && <div className="text-xs text-[#42526E] py-2">{[["BP", v.bp], ["Pulse", v.pulse], ["Temp", v.temp], ["SpO₂", v.spo2], ["Wt", v.weight]].filter(([, x]) => x).map(([l, x]) => `${l}: ${x}`).join("   ·   ")}</div>}
        {e?.chief_complaint && <p className="text-sm mt-3"><b>Complaint:</b> {e.chief_complaint}</p>}
        {e?.diagnosis?.length > 0 && <p className="text-sm mt-1"><b>Diagnosis:</b> {e.diagnosis.join(", ")}</p>}
        <div className="font-heading text-3xl font-black mt-5">℞</div>
        <table className="w-full text-sm mt-2" data-testid="rx-print-meds"><thead><tr className="text-left text-[11px] uppercase tracking-wider text-[#5E6C84] border-b border-[#DFE1E6]">
          <th className="py-1.5 w-6">#</th><th>Medicine</th><th>Dose</th><th>Frequency</th><th>Duration</th><th>Instructions</th></tr></thead>
          <tbody>{(e?.prescriptions || []).map((m, i) => (
            <tr key={i} className="border-b border-[#F4F5F7] align-top"><td className="py-2">{i + 1}</td><td className="font-semibold">{m.name}</td><td>{m.dosage}</td><td>{m.frequency}</td><td>{m.duration}</td><td>{m.instructions}</td></tr>))}</tbody></table>
        {e?.treatment_plan && <p className="text-sm mt-5"><b>Advice:</b> {e.treatment_plan}</p>}
        {e?.investigations?.length > 0 && <p className="text-sm mt-1"><b>Tests advised:</b> {e.investigations.join(", ")}</p>}
        {(e?.follow_up_date || e?.follow_up_notes) && <p className="text-sm mt-1"><b>Follow-up:</b> {fmt(e.follow_up_date)} {e.follow_up_notes}</p>}
        <footer className="mt-16 flex justify-between items-end text-xs text-[#5E6C84]">
          <span>Generated from Trata Health · Consultation ref {e?.id?.slice(0, 8) || "—"}</span>
          <span className="text-center"><span className="block w-48 border-t border-[#091E42] mb-1" />{doc?.full_name || "Doctor"}'s signature</span>
        </footer>
      </div>
    </div>
  );
}
