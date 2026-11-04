import React, { useEffect, useState } from "react";
import { X, Loader2, UserPlus, CheckCircle2, Search } from "lucide-react";
import api from "../lib/api";

// Mirrors the Provider app role picker (mobile/app/index.tsx) and each role's sign-up form (unified-signup.tsx).
const GROUPS = [
  ["Hospitals and its Care Facilities", [["hospital", "Multi & Super Speciality Hospital"], ["path_lab", "Path Lab"], ["diagnostic_centre", "Diagnostic Centre"], ["pharmacy", "Pharmacy"]]],
  ["Speciality centres", [["cancer_care", "Cancer Care"], ["diabetes", "Diabetes"], ["women_baby", "Women & Baby Care"], ["nursing_home", "Nursing Homes"], ["elderly_care", "Elderly Care"]]],
  ["Doctor and Other Healthcare Professionals", [["doctor", "Doctor"], ["nurse", "Nurse"], ["mental_wellness", "Mental Wellness"], ["nutritionist", "Nutritionist"]]],
  ["Emergency and Medical Support", [["ambulance_provider", "Ambulance Service"], ["ambulance_driver", "Ambulance Driver"], ["paramedic", "Paramedic"], ["blood_bank", "Blood Banks"]]],
  ["Wellness and Lifestyle", [["wellness_event", "Health Camps & Retreats"], ["veterinarian", "Veterinarian"], ["dental", "Dental Clinic"], ["skin_hair", "Skin and Hair Clinic"]]],
];
const F = (k, label, o = {}) => ({ k, label, ...o });
const ADDR = [F("address", "Full address", { req: true, wide: true }), F("city", "City", { req: true }), F("state", "State", { req: true }), F("pincode", "Pincode", { req: true, re: /^\d{6}$/ })];
const HOSPITAL = [F("fullName", "Your full name (admin)", { req: true }), F("name", "Hospital / centre name", { req: true }), F("licenseNumber", "Registration / licence number", { req: true }),
  F("hfrId", "HFR ID (optional)"), F("capacity", "Bed capacity", { num: true }), F("specialization", "Primary specialisation"), ...ADDR];
const CLINICIAN = [F("fullName", "Full name", { req: true }), F("email", "Email"), F("licenseNumber", "Medical council registration no.", { req: true }), F("hprId", "HPR ID (optional)"),
  F("specialization", "Specialisation", { req: true }), F("qualification", "Qualification", { req: true }), F("experience", "Years of experience", { num: true }),
  F("hospitalId", "Associated hospital", { req: true, pick: "hospital", wide: true })];
const LAB = [F("fullName", "Full name", { req: true }), F("email", "Email"), F("labName", "Lab name", { req: true }), F("labAddress", "Lab address", { wide: true }),
  F("licenseNumber", "Licence number", { req: true }), F("qualification", "Qualification"), F("homeCollection", "Home sample collection", { bool: true }), ...ADDR.slice(1)];
const WELLNESS = [F("fullName", "Full name", { req: true }), F("email", "Email"), F("qualifications", "Qualifications"), F("councilRegistration", "Council registration"),
  F("yearsExperience", "Years of experience", { num: true }), F("businessName", "Clinic name"), ...ADDR.slice(1)];
const SCHEMA = {
  hospital: HOSPITAL, cancer_care: HOSPITAL, diabetes: HOSPITAL, women_baby: HOSPITAL, nursing_home: HOSPITAL, elderly_care: HOSPITAL, skin_hair: HOSPITAL,
  path_lab: LAB, diagnostic_centre: LAB,
  pharmacy: [F("ownerName", "Owner name", { req: true }), F("businessName", "Pharmacy name", { req: true }), F("email", "Email"), F("drugLicenseNumber", "Drug licence number", { req: true }),
    F("gstNumber", "GST number"), F("pharmacistCouncilReg", "Pharmacist council reg."), F("is24x7", "Open 24x7", { bool: true }), F("homeDelivery", "Home delivery", { bool: true }),
    F("deliveryRadiusKm", "Delivery radius (km)", { num: true }), ...ADDR],
  doctor: [...CLINICIAN.slice(0, -1), F("hospitalId", "Associated hospital", { req: true, pick: "hospital", wide: true })],
  nurse: CLINICIAN,
  paramedic: [F("fullName", "Full name", { req: true }), F("email", "Email"), F("specialization", "Specialisation", { req: true }), F("qualification", "Qualification", { req: true }),
    F("experienceYears", "Years of experience", { num: true }), F("hospitalId", "Associated hospital", { req: true, pick: "hospital", wide: true })],
  mental_wellness: [...WELLNESS, F("subRole", "Practice type", { opts: ["therapist", "psychiatrist", "counsellor", "coach", "career", "relationship", "child"] }), F("sessionFee", "Session fee (₹)", { num: true })],
  nutritionist: [...WELLNESS, F("feePerConsult", "Fee per consult (₹)", { num: true }), F("monthlyPackagePrice", "Monthly package (₹)", { num: true })],
  ambulance_provider: [F("businessName", "Business name", { req: true }), F("ownerName", "Owner name", { req: true }), F("email", "Email"), F("registrationNumber", "Registration number", { req: true }),
    F("licenseNumber", "Licence number", { req: true }), F("totalAmbulances", "Total ambulances", { num: true }), ...ADDR],
  ambulance_driver: [F("fullName", "Full name", { req: true }), F("ambulanceProviderId", "Ambulance service", { req: true, pick: "ambulance_provider", wide: true }),
    F("licenseNumber", "Driving licence number", { req: true }), F("licenseCategory", "Licence category", { opts: ["LMV-TR", "HMV", "TRANS", "LMV"] }), F("experienceYears", "Years of experience", { num: true }), ...ADDR],
  blood_bank: [F("inchargeName", "In-charge name", { req: true }), F("bankName", "Blood bank name", { req: true }), F("email", "Email"), F("licenseNumber", "Licence number", { req: true }),
    F("nacoRegistration", "NACO registration"), F("operates24x7", "Operates 24x7", { bool: true }), F("organizesDrives", "Organises donation drives", { bool: true }), ...ADDR],
  wellness_event: [F("organiserName", "Organiser name", { req: true }), F("displayName", "Display name", { req: true }), F("organiserType", "Organiser type", { opts: ["individual", "organisation", "hospital"] }),
    F("registrationNumber", "Registration number"), F("email", "Email"), ...ADDR],
  veterinarian: [F("ownerName", "Owner name", { req: true }), F("businessName", "Clinic name", { req: true }), F("primaryVetName", "Primary vet name"), F("email", "Email"), F("vciRegistration", "VCI registration"), ...ADDR],
  dental: [F("ownerName", "Owner name", { req: true }), F("clinicName", "Clinic name", { req: true }), F("primaryDentistName", "Primary dentist"), F("email", "Email"), F("licenseNumber", "Licence number", { req: true }),
    F("gstNumber", "GST number"), F("dentalCouncilReg", "Dental council reg."), F("chairCount", "Chairs", { num: true }), ...ADDR],
};
// Payload key tweaks so each form posts exactly what the app's handleSubmit sends.
const SHAPE = {
  veterinarian: (d) => ({ ...d, clinicName: d.businessName }), doctor: (d) => ({ ...d, doctorType: "hospital_doctor" }), nurse: (d) => ({ ...d, doctorType: "hospital_doctor" }),
  hospital: (d) => ({ ...d, hospitalType: "multi_specialty", specializations: d.specialization ? [d.specialization] : [] }),
};
const inp = "w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none";

function Picker({ kind, value, onPick }) {
  const [q, setQ] = useState(""); const [items, setItems] = useState([]);
  useEffect(() => { const t = setTimeout(() => api.get("/admin/provider-app/entities", { params: { kind, q } }).then((r) => setItems(r.data.items)).catch(() => {}), 250); return () => clearTimeout(t); }, [q, kind]);
  if (value) return <div className="flex items-center justify-between px-3 py-2 text-sm border border-[#B3D4FF] bg-[#DEEBFF]/40 rounded-md">{value.name}<button onClick={() => onPick(null)} className="text-xs text-[#0052CC]">Change</button></div>;
  return <div><div className="relative"><Search className="h-3.5 w-3.5 absolute left-2.5 top-2.5 text-[#97A0AF]" /><input className={`${inp} pl-8`} placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} data-testid={`pick-${kind}`} /></div>
    <div className="max-h-32 overflow-auto mt-1">{items.map((i) => <button key={i.id} onClick={() => onPick(i)} className="block w-full text-left px-2 py-1.5 text-xs hover:bg-[#F4F5F7] rounded" data-testid={`pick-item-${i.id}`}>{i.name} <span className="text-[#5E6C84]">{i.city}</span></button>)}</div></div>;
}

export default function ProviderAppOnboardModal({ onClose, onCreated, onOpen }) {
  const [role, setRole] = useState(""); const [phone, setPhone] = useState(""); const [d, setD] = useState({}); const [picks, setPicks] = useState({});
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [done, setDone] = useState(null);
  const fields = SCHEMA[role] || [];
  const set = (k, v) => setD((p) => ({ ...p, [k]: v }));
  const missing = fields.filter((f) => f.req && !(f.pick ? picks[f.k] : String(d[f.k] ?? "").trim()) || (f.re && d[f.k] && !f.re.test(d[f.k])));
  const submit = async () => {
    setBusy(true); setErr("");
    const data = { ...d }; fields.forEach((f) => { if (f.num && data[f.k] !== undefined) data[f.k] = Number(data[f.k]) || 0; if (f.pick && picks[f.k]) data[f.k] = picks[f.k].id; });
    try {
      const { data: job } = await api.post("/admin/provider-app/onboard", { role_id: role, phone, data: (SHAPE[role] || ((x) => x))(data) });
      for (let i = 0; i < 90; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        const { data: j } = await api.get(`/admin/provider-app/onboard/${job.job_id}`);
        if (j.status === "done") { setDone(j.result); onCreated?.(j.result); return; }
        if (j.status === "failed") { setErr(j.error || "Onboarding failed"); return; }
      }
      setErr("Still working on the Provider app. Check Contacts in a few minutes.");
    } catch (e) { setErr(e?.response?.data?.detail || "Onboarding failed"); } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 bg-[#091E42]/50 grid place-items-center p-4" data-testid="pa-onboard-modal">
      <div className="bg-white rounded-lg w-full max-w-2xl max-h-[90vh] flex flex-col shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#DFE1E6]"><div className="font-heading font-bold flex items-center gap-2"><UserPlus className="h-4 w-4 text-[#0052CC]" /> Onboard new provider</div>
          <button onClick={onClose} data-testid="pa-onboard-close"><X className="h-4 w-4" /></button></div>
        {done ? <div className="p-6 space-y-2" data-testid="pa-onboard-done"><div className="flex items-center gap-2 text-[#006644] font-semibold"><CheckCircle2 className="h-5 w-5" /> {done.message}</div>
          <p className="text-sm text-[#42526E]">{done.login_hint}. Account status: <b data-testid="pa-onboard-status">Pending KYC approval</b>, exactly like a self sign-up.</p>
          <p className="text-sm text-[#42526E]" data-testid="pa-onboard-email">{{ sent: "Welcome email sent.", failed: "Welcome email could not be sent.", no_email: "No email entered, so no welcome email was sent." }[done.welcome_email]}</p>
          <div className="flex gap-2 mt-3">{onOpen && done.contact_id && <button onClick={() => onOpen(done.contact_id)} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="pa-onboard-open">Open contact</button>}
          <button onClick={onClose} className="px-3 py-2 text-sm bg-[#0052CC] text-white rounded-md" data-testid="pa-onboard-finish">Done</button></div></div> : <>
        <div className="p-5 overflow-auto space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <label className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84]">Provider type *
              <select className={`${inp} mt-1 font-normal normal-case tracking-normal`} value={role} onChange={(e) => { setRole(e.target.value); setD({}); setPicks({}); setErr(""); }} data-testid="pa-role-select">
                <option value="">Select provider type…</option>
                {GROUPS.map(([g, rs]) => <optgroup key={g} label={g}>{rs.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>)}
              </select></label>
            <label className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84]">Mobile (login number) *
              <input className={`${inp} mt-1 font-normal`} inputMode="numeric" placeholder="9XXXXXXXXX" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))} data-testid="pa-phone" /></label>
          </div>
          {role && <div className="grid sm:grid-cols-2 gap-3 border-t border-[#DFE1E6] pt-4" data-testid={`pa-form-${role}`}>
            {fields.map((f) => <label key={f.k} className={`text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] ${f.wide ? "sm:col-span-2" : ""}`}>{f.label}{f.req && " *"}
              <div className="mt-1 font-normal normal-case tracking-normal">
                {f.pick ? <Picker kind={f.pick} value={picks[f.k]} onPick={(v) => setPicks((p) => ({ ...p, [f.k]: v }))} />
                  : f.bool ? <input type="checkbox" checked={!!d[f.k]} onChange={(e) => set(f.k, e.target.checked)} data-testid={`pa-f-${f.k}`} />
                  : f.opts ? <select className={inp} value={d[f.k] || f.opts[0]} onChange={(e) => set(f.k, e.target.value)} data-testid={`pa-f-${f.k}`}>{f.opts.map((o) => <option key={o}>{o}</option>)}</select>
                  : <input className={inp} inputMode={f.num ? "numeric" : undefined} value={d[f.k] ?? ""} onChange={(e) => set(f.k, e.target.value)} data-testid={`pa-f-${f.k}`} />}
              </div></label>)}
          </div>}
          {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="pa-onboard-error">{err}</div>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-[#DFE1E6]">
          <button onClick={onClose} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="pa-onboard-cancel">Cancel</button>
          <button onClick={submit} disabled={busy || !role || phone.length !== 10 || missing.length > 0} className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md disabled:opacity-50" data-testid="pa-onboard-submit">
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}{busy ? "Creating account… (up to a minute)" : "Onboard provider"}</button>
        </div></>}
      </div>
    </div>
  );
}
