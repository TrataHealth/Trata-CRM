import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { T, toastErr } from "../ledger/ui";
import { AbhaCard } from "./AbhaCard";

const METHODS = [
  ["abha-number", "ABHA number", "14 digits, e.g. 91-1234-5678-9012"],
  ["abha-address", "ABHA address", "e.g. ravi.kumar@sbx"],
  ["mobile", "Mobile number", "10-digit mobile linked to ABHA"],
  ["aadhaar", "Aadhaar number", "12 digits — OTP goes to Aadhaar mobile"],
];

export function VerifyWizard({ onSaved }) {
  const [f, setF] = useState({ method: "abha-number", identifier: "", otp_via: "abdm", patient_phone: "", otp: "" });
  const [txn, setTxn] = useState(null);
  const [accounts, setAccounts] = useState(null);
  const [rec, setRec] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn) => { setBusy(true); try { await fn(); } catch (e) { toastErr(e, "ABDM request failed"); } finally { setBusy(false); } };
  const done = (r) => { setRec(r); setAccounts(null); onSaved?.(); toast.success("ABHA verified"); };
  const reset = () => { setTxn(null); setAccounts(null); setRec(null); setF({ ...f, identifier: "", otp: "", patient_phone: "" }); };
  const hint = METHODS.find((m) => m[0] === f.method)[2];
  const viaChoice = ["abha-number", "abha-address"].includes(f.method);

  const send = () => run(async () => {
    const { data } = await api.post("/abdm/verify/otp", { method: f.method, identifier: f.identifier, otp_via: f.otp_via, patient_phone: f.patient_phone || null });
    setTxn(data.txn_id); toast.success(data.message || "OTP sent");
  });
  const confirm = () => run(async () => {
    const { data } = await api.post("/abdm/verify/confirm", { txn_id: txn, otp: f.otp });
    data.select ? setAccounts(data.select) : done(data.record);
  });
  const pick = (n) => run(async () => { const { data } = await api.post("/abdm/verify/select", { txn_id: txn, abha_number: n }); done(data.record); });

  return (
    <div className="grid lg:grid-cols-[1fr_360px] gap-6" data-testid="verify-wizard">
      <div className="space-y-3 max-w-lg">
        {!txn && <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5" data-testid="verify-methods">
            {METHODS.map(([k, l]) => (
              <button key={k} onClick={() => setF({ ...f, method: k, identifier: "" })} data-testid={`verify-method-${k}`}
                className={`px-2 py-2 text-xs font-semibold rounded-md border transition-colors ${f.method === k ? "bg-[#0052CC] text-white border-[#0052CC]" : "bg-white text-[#42526E] border-[#DFE1E6] hover:bg-[#F4F5F7]"}`}>{l}</button>
            ))}
          </div>
          <label className={T.label}>{METHODS.find((m) => m[0] === f.method)[1]}
            <input className={`${T.input} font-mono`} value={f.identifier} placeholder={hint} autoComplete="off" onChange={(e) => setF({ ...f, identifier: e.target.value.trim() })} data-testid="verify-identifier" /></label>
          {viaChoice && <div className="flex gap-4 text-xs text-[#42526E]" data-testid="verify-otp-via">
            {[["abdm", "OTP to ABHA mobile"], ["aadhaar", "OTP to Aadhaar mobile"]].map(([k, l]) => (
              <label key={k} className="flex items-center gap-1.5"><input type="radio" checked={f.otp_via === k} onChange={() => setF({ ...f, otp_via: k })} data-testid={`verify-via-${k}`} />{l}</label>
            ))}
          </div>}
          <label className={T.label}>Patient's Trata app phone (optional, to link records)
            <input className={T.input} inputMode="numeric" value={f.patient_phone} onChange={(e) => setF({ ...f, patient_phone: e.target.value.replace(/\D/g, "").slice(0, 10) })} data-testid="verify-patient-phone" /></label>
          <button className={T.btn} onClick={send} disabled={busy || f.identifier.length < 3} data-testid="verify-send-otp">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Send OTP</button>
        </>}
        {txn && !rec && !accounts && <>
          <p className="text-xs text-[#42526E]">Ask the patient for the 6-digit OTP they just received.</p>
          <label className={T.label}>OTP<input className={`${T.input} font-mono tracking-widest`} inputMode="numeric" value={f.otp} onChange={(e) => setF({ ...f, otp: e.target.value.replace(/\D/g, "").slice(0, 6) })} data-testid="verify-otp" /></label>
          <div className="flex gap-2">
            <button className={T.btn} onClick={confirm} disabled={busy || f.otp.length !== 6} data-testid="verify-confirm">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Verify</button>
            <button className={T.btnGhost} onClick={reset} data-testid="verify-cancel">Start over</button>
          </div>
        </>}
        {accounts && <div className="space-y-2" data-testid="verify-accounts">
          <p className="text-xs text-[#42526E]">This mobile has several ABHAs. Pick the patient's:</p>
          {accounts.map((a) => (
            <button key={a.abha_number} onClick={() => pick(a.abha_number)} disabled={busy} className="w-full text-left p-3 border border-[#DFE1E6] rounded-md hover:border-[#0052CC] transition-colors" data-testid={`verify-account-${a.abha_number}`}>
              <div className="text-sm font-semibold">{a.name}</div><div className="text-xs font-mono text-[#0747A6]">{a.abha_number} · {a.abha_address}</div>
            </button>
          ))}
        </div>}
        {rec && <button className={T.btnGhost} onClick={reset} data-testid="verify-new">Verify another patient</button>}
      </div>
      <aside>{rec ? <AbhaCard record={rec} /> : <div className="text-xs text-[#5E6C84] border border-dashed border-[#DFE1E6] rounded-lg p-6 text-center">Verified ABHA details appear here.</div>}</aside>
    </div>
  );
}
