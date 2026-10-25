import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "../../lib/api";
import { RX_STATUS, Chip, inr, when, itemLine, errMsg, inp, primary, ghost, danger } from "./ui";

const OPEN = ["submitted", "issued", "pending"];
const FILTERS = [["all", "All"], ["new", "New"], ["accepted", "Accepted"], ["ready_for_pickup", "Ready"], ["fulfilled", "Fulfilled"], ["rejected", "Rejected"]];

function RxActions({ rx, onDone }) {
  const [mode, setMode] = useState(null); const [amount, setAmount] = useState(rx.total_amount ?? ""); const [reason, setReason] = useState(""); const [busy, setBusy] = useState(false);
  const run = async (status) => {
    setBusy(true);
    try {
      await api.put(`/pharmacy-console/prescriptions/${rx.id}/status`, { status, store: rx.store_id, ...(amount !== "" && status !== "rejected" ? { total_amount: Number(amount) } : {}), ...(status === "rejected" ? { rejection_reason: reason } : {}), ...(status === "fulfilled" ? { is_paid: true } : {}) });
      toast.success(`Prescription marked ${status.replace(/_/g, " ")}`); setMode(null); onDone();
    } catch (e) { errMsg(e); } finally { setBusy(false); }
  };
  if (mode) return (
    <div className="mt-3 p-3 bg-[#F8F9FA] rounded-md space-y-2" data-testid={`rx-form-${rx.id}`}>
      {mode === "rejected" ? <input className={inp} placeholder="Reason (shown to the patient) *" value={reason} onChange={(e) => setReason(e.target.value)} data-testid={`rx-reason-${rx.id}`} />
        : <input className={inp} inputMode="decimal" placeholder="Bill amount ₹" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} data-testid={`rx-amount-${rx.id}`} />}
      <div className="flex gap-2 justify-end"><button className={ghost} onClick={() => setMode(null)}>Cancel</button>
        <button className={mode === "rejected" ? danger : primary} disabled={busy || (mode === "rejected" ? !reason.trim() : amount === "")} onClick={() => run(mode)} data-testid={`rx-confirm-${rx.id}`}>Confirm</button></div>
    </div>
  );
  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {OPEN.includes(rx.status) && <button className={primary} disabled={busy} onClick={() => run("accepted")} data-testid={`rx-accept-${rx.id}`}>Accept</button>}
      {rx.status === "accepted" && <button className={primary} onClick={() => setMode("ready_for_pickup")} data-testid={`rx-ready-${rx.id}`}>Ready for pickup</button>}
      {["accepted", "ready_for_pickup"].includes(rx.status) && <button className={ghost} onClick={() => setMode("fulfilled")} data-testid={`rx-fulfil-${rx.id}`}>Mark fulfilled</button>}
      {[...OPEN, "accepted"].includes(rx.status) && <button className={danger} onClick={() => setMode("rejected")} data-testid={`rx-reject-${rx.id}`}>Reject</button>}
    </div>
  );
}

export default function PrescriptionsTab({ store, showStore }) {
  const [data, setData] = useState(null); const [f, setF] = useState("all");
  const load = () => api.get("/pharmacy-console/prescriptions", { params: { store } }).then((r) => setData(r.data)).catch((e) => { errMsg(e); setData({ prescriptions: [] }); });
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [store]);
  const rows = (data?.prescriptions || []).filter((x) => f === "all" || (f === "new" ? OPEN.includes(x.status) : x.status === f));
  return (
    <div className="space-y-3" data-testid="rx-tab">
      <div className="flex flex-wrap gap-1.5">{FILTERS.map(([v, l]) => <button key={v} onClick={() => setF(v)} className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${f === v ? "bg-[#0052CC] text-white border-[#0052CC]" : "border-[#DFE1E6] text-[#42526E] hover:bg-[#F4F5F7]"}`} data-testid={`rx-filter-${v}`}>{l}</button>)}</div>
      {data?.unreachable_stores > 0 && <div className="text-xs text-[#974F0C]">Some stores could not be reached on the Provider app; showing the rest.</div>}
      {!data ? <div className="text-sm text-[#5E6C84]">Loading prescriptions…</div> : rows.length === 0 ? <div className="text-sm text-[#5E6C84] py-8 text-center" data-testid="rx-empty">No prescriptions here. Prescriptions sent by doctors and patients land here.</div>
        : <div className="grid lg:grid-cols-2 gap-3">{rows.map((rx) => (
          <div key={rx.id} className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid={`rx-${rx.id}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div><div className="flex items-center gap-2"><span className="font-semibold text-[#091E42]">{rx.patient_name || "Patient"}</span><Chip map={RX_STATUS} s={rx.status} testid={`rx-status-${rx.id}`} /></div>
                <div className="text-xs text-[#5E6C84] mt-0.5">{rx.doctor_name ? `By ${rx.doctor_name} · ` : ""}{when(rx.submitted_at)}{showStore && ` · ${rx.store_name}`}</div></div>
              <div className="font-heading font-black text-[#091E42]">{inr(rx.total_amount)}</div>
            </div>
            <ul className="mt-2 text-sm text-[#172B4D] list-disc pl-5">{(rx.items || []).map((it, i) => <li key={i}>{itemLine(it)}</li>)}</ul>
            {rx.notes && <p className="text-xs text-[#42526E] mt-1">{rx.notes}</p>}
            {rx.rejection_reason && <p className="text-xs text-[#BF2600] mt-1">Rejected: {rx.rejection_reason}</p>}
            <div className="text-xs text-[#5E6C84] mt-1">{rx.patient_phone}{rx.delivery_mode ? ` · ${rx.delivery_mode}` : ""}</div>
            <RxActions rx={rx} onDone={load} />
          </div>))}</div>}
    </div>
  );
}
