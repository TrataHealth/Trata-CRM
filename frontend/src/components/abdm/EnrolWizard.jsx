import React, { useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { T, toastErr } from "../ledger/ui";
import { AbhaCard } from "./AbhaCard";

const digits = (v, n) => v.replace(/\D/g, "").slice(0, n);

function Step({ n, title, active, done, children }) {
  return (
    <div className={`border-l-2 pl-4 pb-5 ${active ? "border-[#0052CC]" : done ? "border-[#00875A]" : "border-[#DFE1E6]"}`}>
      <div className={`text-[11px] font-bold uppercase tracking-wider ${active ? "text-[#0052CC]" : done ? "text-[#00875A]" : "text-[#97A0AF]"}`}>Step {n} · {title}</div>
      {active && <div className="mt-2 space-y-2">{children}</div>}
    </div>
  );
}

export function EnrolWizard({ consentText, onSaved }) {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ aadhaar: "", consent: false, patient_phone: "", otp: "", mobile: "", mobile_otp: "", address: "" });
  const [txn, setTxn] = useState(null);
  const [rec, setRec] = useState(null);
  const [mobileSent, setMobileSent] = useState(false);
  const [sugg, setSugg] = useState([]);
  const set = (k, n) => (e) => setF({ ...f, [k]: n ? digits(e.target.value, n) : e.target.value });

  const run = async (fn) => { setBusy(true); try { await fn(); } catch (e) { toastErr(e, "ABDM request failed"); } finally { setBusy(false); } };
  const toAddress = async (t) => { setStep(4); const { data } = await api.get(`/abdm/enrol/${t}/suggestions`).catch(() => ({ data: {} })); setSugg(data.suggestions || []); };

  const sendOtp = () => run(async () => {
    const { data } = await api.post("/abdm/enrol/otp", { aadhaar: f.aadhaar, consent: f.consent, patient_phone: f.patient_phone || null });
    setTxn(data.txn_id); setStep(2); toast.success(data.message || "OTP sent to Aadhaar-linked mobile");
  });
  const verify = () => run(async () => {
    const { data } = await api.post("/abdm/enrol/verify", { txn_id: txn, otp: f.otp, mobile: f.mobile });
    setRec(data.record); onSaved?.();
    toast.success(data.is_new ? "ABHA created" : "Patient already had an ABHA — linked");
    if (data.needs_mobile_verify) setStep(3);
    else if (!data.has_address) await toAddress(txn);
    else setStep(5);
  });
  const mobileOtp = () => run(async () => { await api.post("/abdm/enrol/mobile-otp", { txn_id: txn, mobile: f.mobile }); setMobileSent(true); toast.success("OTP sent to the communication mobile"); });
  const mobileVerify = () => run(async () => {
    await api.post("/abdm/enrol/mobile-verify", { txn_id: txn, otp: f.mobile_otp }); toast.success("Mobile verified");
    rec?.abha_address ? setStep(5) : await toAddress(txn);
  });
  const address = () => run(async () => {
    const { data } = await api.post("/abdm/enrol/address", { txn_id: txn, address: f.address }); setRec(data.record); setStep(5); onSaved?.();
    toast.success(`ABHA address ${data.abha_address} created`);
  });
  const reset = () => { setStep(1); setTxn(null); setRec(null); setMobileSent(false); setSugg([]); setF({ aadhaar: "", consent: false, patient_phone: "", otp: "", mobile: "", mobile_otp: "", address: "" }); };
  const Btn = ({ onClick, disabled, children, testid }) => (
    <button className={T.btn} onClick={onClick} disabled={busy || disabled} data-testid={testid}>{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{children}</button>
  );

  return (
    <div className="grid lg:grid-cols-[1fr_360px] gap-6" data-testid="enrol-wizard">
      <div>
        <Step n={1} title="Patient consent & Aadhaar" active={step === 1} done={step > 1}>
          <label className={T.label}>Patient's Aadhaar number<input className={`${T.input} font-mono tracking-widest`} inputMode="numeric" value={f.aadhaar} onChange={set("aadhaar", 12)} placeholder="12 digits" autoComplete="off" data-testid="enrol-aadhaar" /></label>
          <label className={T.label}>Patient's Trata app phone (optional, to link records)<input className={T.input} inputMode="numeric" value={f.patient_phone} onChange={set("patient_phone", 10)} data-testid="enrol-patient-phone" /></label>
          <label className="flex gap-2 items-start text-[11px] text-[#42526E] bg-[#FFFAE6] border border-[#FFE380] rounded p-2.5 leading-relaxed">
            <input type="checkbox" className="mt-0.5" checked={f.consent} onChange={(e) => setF({ ...f, consent: e.target.checked })} data-testid="enrol-consent" />
            <span>{consentText} <b>Read this to the patient and tick only after they agree.</b></span>
          </label>
          <Btn onClick={sendOtp} disabled={f.aadhaar.length !== 12 || !f.consent} testid="enrol-send-otp">Send Aadhaar OTP</Btn>
        </Step>
        <Step n={2} title="Aadhaar OTP & mobile" active={step === 2} done={step > 2}>
          <label className={T.label}>OTP sent to the Aadhaar-linked mobile<input className={`${T.input} font-mono tracking-widest`} inputMode="numeric" value={f.otp} onChange={set("otp", 6)} data-testid="enrol-otp" /></label>
          <label className={T.label}>Patient's mobile for ABHA communication<input className={T.input} inputMode="numeric" value={f.mobile} onChange={set("mobile", 10)} data-testid="enrol-mobile" /></label>
          <Btn onClick={verify} disabled={f.otp.length !== 6 || f.mobile.length !== 10} testid="enrol-verify">Verify & create ABHA</Btn>
        </Step>
        <Step n={3} title="Verify communication mobile" active={step === 3} done={step > 3}>
          <p className="text-[11px] text-[#5E6C84]">This mobile differs from the Aadhaar-linked one, so ABDM needs it verified.</p>
          {!mobileSent ? <Btn onClick={mobileOtp} testid="enrol-mobile-send">Send OTP to {f.mobile}</Btn> : <>
            <label className={T.label}>Mobile OTP<input className={`${T.input} font-mono tracking-widest`} inputMode="numeric" value={f.mobile_otp} onChange={set("mobile_otp", 6)} data-testid="enrol-mobile-otp" /></label>
            <Btn onClick={mobileVerify} disabled={f.mobile_otp.length !== 6} testid="enrol-mobile-verify">Verify mobile</Btn>
          </>}
          <button className="text-[11px] text-[#0052CC] underline" onClick={() => (rec?.abha_address ? setStep(5) : toAddress(txn))} data-testid="enrol-mobile-skip">Skip for now</button>
        </Step>
        <Step n={4} title="Choose ABHA address" active={step === 4} done={step > 4}>
          {sugg.length > 0 && <div className="flex flex-wrap gap-1.5">{sugg.map((s) => (
            <button key={s} onClick={() => setF({ ...f, address: s })} className={`${T.chip} border ${f.address === s ? "bg-[#0052CC] text-white border-[#0052CC]" : "bg-white text-[#42526E] border-[#DFE1E6]"}`} data-testid={`enrol-suggestion-${s}`}>{s}</button>
          ))}</div>}
          <label className={T.label}>ABHA address (8–18 letters, numbers, . or _)
            <div className="flex items-center gap-1"><input className={T.input} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value.replace(/[^a-zA-Z0-9._]/g, "").slice(0, 18) })} data-testid="enrol-address" /><span className="text-xs text-[#5E6C84] mt-1">@sbx</span></div>
          </label>
          <Btn onClick={address} disabled={f.address.length < 8} testid="enrol-address-submit">Create ABHA address</Btn>
        </Step>
        <Step n={5} title="Done" active={step === 5} done={false}>
          <p className="text-xs text-[#006644] flex items-center gap-1.5"><ShieldCheck className="h-4 w-4" /> ABHA is ready and saved to your ABHA patients list.</p>
          <button className={T.btnGhost} onClick={reset} data-testid="enrol-new">Create another ABHA</button>
        </Step>
      </div>
      <aside>{rec ? <AbhaCard record={rec} /> : <div className="text-xs text-[#5E6C84] border border-dashed border-[#DFE1E6] rounded-lg p-6 text-center">The patient's ABHA will appear here.</div>}</aside>
    </div>
  );
}
