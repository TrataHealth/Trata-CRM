import React, { useEffect, useMemo, useState } from "react";
import { Loader2, MapPin, UserPlus } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";

const input = "w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded";
const btn = "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40";
const ghost = "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40";
const LOC_REQUIRED = ["hospital", "path_lab", "diagnostic_centre", "pharmacy", "ambulance_provider", "cancer_care", "diabetes", "women_baby", "elderly_care", "nursing_home", "skin_hair"];

function useLookup(kind, on) {
  const [items, setItems] = useState([]);
  useEffect(() => { if (on) api.get(`/admin/onboarding/lookup/${kind}`).then(({ data }) => setItems(data.items || [])).catch(() => {}); }, [kind, on]);
  return items;
}

function Field({ f, value, onChange, hospitals, ambulances }) {
  const id = `admin-onb-${f.k}`;
  const lbl = <>{f.label}{f.req && " *"}</>;
  if (f.type === "bool") return (
    <label className="text-[11px] text-[#42526E] flex items-center gap-2 mt-5">
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} data-testid={id} /> {f.label}</label>);
  const opts = f.type === "hospital" ? hospitals.map((h) => [h.id, `${h.name}${h.city ? ` · ${h.city}` : ""}`])
    : f.type === "ambulance_provider" ? ambulances.map((h) => [h.id, `${h.name}${h.city ? ` · ${h.city}` : ""}`]) : f.opts;
  return (
    <label className="text-[11px] text-[#42526E]">{lbl}
      {opts ? <select className={input} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={id}>
        <option value="">Select…</option>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        : <input className={input} type={f.type === "number" ? "number" : f.type === "email" ? "email" : "text"} value={value ?? ""}
            placeholder={f.ph} onChange={(e) => onChange(f.k === "pincode" ? e.target.value.replace(/\D/g, "").slice(0, 6) : e.target.value)} data-testid={id} />}
    </label>);
}

/** Same fields as the Provider App's sign-up form for each provider type. */
export function SignupForm({ onCancel, onDone }) {
  const [types, setTypes] = useState([]);
  const [type, setType] = useState("hospital");
  const [phone, setPhone] = useState("");
  const [vals, setVals] = useState({});
  const [loc, setLoc] = useState({ lat: "", lng: "", busy: false, results: [] });
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/admin/onboarding/provider-types").then(({ data }) => setTypes(data.types || [])).catch(() => toast.error("Could not load provider types")); }, []);
  const spec = types.find((t) => t.id === type);
  const groups = useMemo(() => [...new Set(types.map((t) => t.category))], [types]);
  const hospitals = useLookup("hospital", !!spec?.fields.some((f) => f.type === "hospital"));
  const ambulances = useLookup("ambulance_provider", !!spec?.fields.some((f) => f.type === "ambulance_provider"));
  const locReq = LOC_REQUIRED.includes(type);

  const lookup = async () => {
    const q = [vals.address || vals.labAddress, vals.city, vals.state, vals.pincode].filter(Boolean).join(", ");
    if (q.length < 3) return toast.error("Enter address / city first");
    setLoc((l) => ({ ...l, busy: true }));
    try {
      const { data } = await api.get("/admin/geocode", { params: { q } });
      const r = data.results || [];
      if (!r.length) toast.error("No match — enter lat/lng manually");
      setLoc({ busy: false, results: r, lat: r[0] ? String(r[0].lat) : loc.lat, lng: r[0] ? String(r[0].lng) : loc.lng });
    } catch (e) { toast.error(e?.response?.data?.detail || "Lookup failed"); setLoc((l) => ({ ...l, busy: false })); }
  };
  const submit = async () => {
    if (!/^\d{10}$/.test(phone)) return toast.error("Enter a valid 10-digit phone");
    const lat = parseFloat(loc.lat), lng = parseFloat(loc.lng), has = Number.isFinite(lat) && Number.isFinite(lng);
    if (locReq && !has) return toast.error("Latitude & longitude are required for patient-app discovery");
    setBusy(true);
    try {
      const { data } = await api.post("/admin/onboarding/signup", { type, phone, values: vals, lat: has ? lat : null, lng: has ? lng : null });
      toast.success(data.existing_login ? `${spec.label} profile added to their existing Trata login` : `${spec.label} onboarded — now upload the KYC docs`);
      onDone(data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Onboarding failed"); } finally { setBusy(false); }
  };

  return (
    <div className="p-4 space-y-4" data-testid="admin-onboarding-signup-form">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-[11px] text-[#42526E]">Provider type *
          <select className={input} value={type} onChange={(e) => { setType(e.target.value); setVals({}); }} data-testid="admin-onb-type">
            {groups.map((g) => <optgroup key={g} label={g}>{types.filter((t) => t.category === g).map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</optgroup>)}
          </select></label>
        <label className="text-[11px] text-[#42526E]">Phone (+91) *
          <input className={input} value={phone} maxLength={10} placeholder="10-digit mobile" data-testid="admin-onb-phone"
            onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))} /></label>
        {spec?.fields.filter((f) => !f.show_if || vals[f.show_if[0]] === f.show_if[1]).map((f) => (
          <Field key={f.k} f={f} value={vals[f.k]} onChange={(v) => setVals((p) => ({ ...p, [f.k]: v }))} hospitals={hospitals} ambulances={ambulances} />))}
      </div>
      {spec?.loc && <div className="border border-dashed border-[#DFE1E6] rounded-md p-3 space-y-2" data-testid="admin-onb-location">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold flex items-center gap-1"><MapPin className="h-3 w-3" /> Location {locReq ? "*" : "(optional)"}</div>
          <button type="button" className={ghost} onClick={lookup} disabled={loc.busy} data-testid="admin-onb-geocode">
            {loc.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <MapPin className="h-3.5 w-3.5" />} Look up from address</button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[11px] text-[#42526E]">Latitude<input className={input} value={loc.lat} inputMode="decimal" placeholder="26.8467" onChange={(e) => setLoc({ ...loc, lat: e.target.value })} data-testid="admin-onb-lat" /></label>
          <label className="text-[11px] text-[#42526E]">Longitude<input className={input} value={loc.lng} inputMode="decimal" placeholder="80.9462" onChange={(e) => setLoc({ ...loc, lng: e.target.value })} data-testid="admin-onb-lng" /></label>
        </div>
        {loc.results.length > 1 && <select className={input} data-testid="admin-onb-geocode-results"
          onChange={(e) => { const r = loc.results[+e.target.value]; setLoc((l) => ({ ...l, lat: String(r.lat), lng: String(r.lng) })); }}>
          {loc.results.map((r, i) => <option key={i} value={i}>{r.label}</option>)}</select>}
        <p className="text-[10px] text-[#5E6C84]">Patients discover providers by distance — without coordinates the provider won&apos;t appear in the Patient App.</p>
      </div>}
      <div className="flex justify-end gap-2 pt-1">
        <button className={ghost} onClick={onCancel} data-testid="admin-onb-cancel">Cancel</button>
        <button className={btn} disabled={busy || !spec} onClick={submit} data-testid="admin-onb-submit">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />} Onboard &amp; continue to KYC</button>
      </div>
      <p className="text-[10px] text-[#5E6C84]">Same fields and the same database tables as the Provider App&apos;s sign-up. The provider sets their password on first login; if the number already has a Trata login (e.g. Patient App), the new profile is added to it and their patient account is untouched.</p>
    </div>
  );
}
