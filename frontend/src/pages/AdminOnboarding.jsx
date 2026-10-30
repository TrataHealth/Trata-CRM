import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { toast } from "sonner";
import {
  UserPlus, Building2, Ambulance, Stethoscope, FlaskConical,
  ShieldCheck, ChevronRight, Loader2, AlertTriangle, RefreshCw, ArrowUpRight, MapPin, ScanLine,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  head: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  btn: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnGhost: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
  input: "w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
};

const VERTICALS = [
  { key: "hospital", label: "Hospital",   icon: Building2   },
  { key: "ambulance", label: "Ambulance", icon: Ambulance   },
  { key: "doctor", label: "Doctor",       icon: Stethoscope },
  { key: "path_lab", label: "Lab Partner", icon: FlaskConical },
  { key: "diagnostic_centre", label: "Imaging & Diagnostics", icon: ScanLine },
];

const STATUS_TONE = {
  approved: "bg-[#E3FCEF] text-[#006644]",
  verified: "bg-[#E3FCEF] text-[#006644]",
  pending:  "bg-[#FFFAE6] text-[#974F0C]",
  rejected: "bg-[#FFEBE6] text-[#BF2600]",
};
function StatusChip({ status }) {
  const v = String(status || "pending").toLowerCase();
  const tone = STATUS_TONE[v] || "bg-[#F4F5F7] text-[#5E6C84]";
  return <span className={`${T.chip} ${tone}`}>{v.toUpperCase()}</span>;
}

const emptyForm = {
  phone: "", name: "", vertical: "hospital",
  city: "", state: "", email: "", address: "", lat: "", lng: "",
};

export default function AdminOnboarding() {
  const nav = useNavigate();
  const [state, setState] = useState({ loading: true, providers: [], err: "" });
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [geo, setGeo] = useState({ busy: false, results: [] });

  const lookup = async () => {
    const q = [form.address, form.city, form.state].filter(Boolean).join(", ");
    if (q.length < 3) return toast.error("Enter address / city first");
    setGeo({ busy: true, results: [] });
    try {
      const { data } = await api.get("/admin/geocode", { params: { q } });
      if (!data.results?.length) toast.error("No match — enter lat/lng manually");
      else setForm(f => ({ ...f, lat: String(data.results[0].lat), lng: String(data.results[0].lng) }));
      setGeo({ busy: false, results: data.results || [] });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Lookup failed");
      setGeo({ busy: false, results: [] });
    }
  };

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/onboarding/providers");
      setState({ loading: false, providers: data.providers || [], err: "" });
    } catch (e) {
      setState({ loading: false, providers: [], err: e?.response?.data?.detail || "Could not load providers" });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    if (!form.name.trim()) return toast.error("Provider name is required");
    if (!/^\d{10}$/.test(form.phone)) return toast.error("Enter a valid 10-digit phone");
    const lat = parseFloat(form.lat), lng = parseFloat(form.lng);
    const hasLoc = Number.isFinite(lat) && Number.isFinite(lng);
    if (form.vertical !== "doctor" && !hasLoc) return toast.error("Latitude & longitude are required for patient-app discovery");
    setBusy(true);
    try {
      const { data } = await api.post("/admin/onboarding/providers", {
        ...form, lat: hasLoc ? lat : null, lng: hasLoc ? lng : null,
        ...(["path_lab", "diagnostic_centre"].includes(form.vertical) ? { vertical: "pathology", lab_kind: form.vertical } : {}),
      });
      toast.success(data.already_existed
        ? "Provider already existed on Trata — jumping to KYC"
        : `${form.name} onboarded — now upload the KYC docs`);
      setForm(emptyForm);
      setShowForm(false);
      nav(`/admin/onboarding/${data.user_id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Onboarding failed");
    } finally { setBusy(false); }
  };

  if (state.loading) return (
    <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="admin-onboarding-loading">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading provider roster…
    </div>
  );

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="admin-onboarding-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><ShieldCheck className="h-3 w-3" /> Trata Health Admin · Onboarding</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
            Onboard providers &amp; approve KYC
          </h1>
          <p className="text-sm text-[#5E6C84] mt-1 max-w-2xl">
            Create a new hospital, ambulance, doctor, Lab Partner or Imaging & Diagnostics Partner account here — it will appear in the mobile Provider App
            and the Trata Admin App instantly. Then upload the checklist docs and one-click approve.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className={T.btnGhost} onClick={load} data-testid="admin-onboarding-refresh"><RefreshCw className="h-3.5 w-3.5" /> Refresh</button>
          <button className={T.btn} onClick={() => setShowForm(v => !v)} data-testid="admin-onboarding-toggle-form">
            <UserPlus className="h-3.5 w-3.5" /> {showForm ? "Close" : "Onboard provider"}
          </button>
        </div>
      </div>

      {showForm && (
        <section className={T.card} data-testid="admin-onboarding-form">
          <div className={T.head}>New provider</div>
          <div className="p-4 space-y-4">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">Vertical</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
                {VERTICALS.map(v => {
                  const Icon = v.icon;
                  const active = form.vertical === v.key;
                  return (
                    <button key={v.key} type="button"
                      onClick={() => setForm({ ...form, vertical: v.key })}
                      className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs font-semibold transition ${
                        active ? "border-[#0052CC] bg-[#DEEBFF] text-[#0747A6]" : "border-[#DFE1E6] text-[#42526E] hover:bg-[#F4F5F7]"
                      }`}
                      data-testid={`admin-onb-vertical-${v.key}`}>
                      <Icon className="h-4 w-4" /> {v.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="text-[11px] text-[#42526E]">Provider name *
                <input className={T.input} value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. Sunrise Care Hospital"
                  data-testid="admin-onb-name" />
              </label>
              <label className="text-[11px] text-[#42526E]">Phone (+91) *
                <input className={T.input} value={form.phone}
                  onChange={e => setForm({ ...form, phone: e.target.value.replace(/\D/g, "").slice(0, 10) })}
                  maxLength={10} placeholder="10-digit mobile"
                  data-testid="admin-onb-phone" />
              </label>
              <label className="text-[11px] text-[#42526E]">City
                <input className={T.input} value={form.city}
                  onChange={e => setForm({ ...form, city: e.target.value })}
                  data-testid="admin-onb-city" />
              </label>
              <label className="text-[11px] text-[#42526E]">State
                <input className={T.input} value={form.state}
                  onChange={e => setForm({ ...form, state: e.target.value })}
                  data-testid="admin-onb-state" />
              </label>
              <label className="text-[11px] text-[#42526E]">Email
                <input type="email" className={T.input} value={form.email}
                  onChange={e => setForm({ ...form, email: e.target.value })}
                  data-testid="admin-onb-email" />
              </label>
              <label className="text-[11px] text-[#42526E]">Address
                <input className={T.input} value={form.address}
                  onChange={e => setForm({ ...form, address: e.target.value })}
                  data-testid="admin-onb-address" />
              </label>
            </div>
            <div className="border border-dashed border-[#DFE1E6] rounded-md p-3 space-y-2" data-testid="admin-onb-location">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold flex items-center gap-1">
                  <MapPin className="h-3 w-3" /> Location {form.vertical !== "doctor" ? "*" : "(optional)"}
                </div>
                <button type="button" className={T.btnGhost} onClick={lookup} disabled={geo.busy} data-testid="admin-onb-geocode">
                  {geo.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <MapPin className="h-3.5 w-3.5" />} Look up from address
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-[11px] text-[#42526E]">Latitude
                  <input className={T.input} value={form.lat} inputMode="decimal" placeholder="19.2352"
                    onChange={e => setForm({ ...form, lat: e.target.value })} data-testid="admin-onb-lat" />
                </label>
                <label className="text-[11px] text-[#42526E]">Longitude
                  <input className={T.input} value={form.lng} inputMode="decimal" placeholder="72.8408"
                    onChange={e => setForm({ ...form, lng: e.target.value })} data-testid="admin-onb-lng" />
                </label>
              </div>
              {geo.results.length > 1 && (
                <select className={T.input} data-testid="admin-onb-geocode-results"
                  onChange={e => { const r = geo.results[+e.target.value]; setForm(f => ({ ...f, lat: String(r.lat), lng: String(r.lng) })); }}>
                  {geo.results.map((r, i) => <option key={i} value={i}>{r.label}</option>)}
                </select>
              )}
              <p className="text-[10px] text-[#5E6C84]">Patients discover providers by distance — without coordinates the provider won&apos;t appear in the Patient App.</p>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button className={T.btnGhost} onClick={() => { setForm(emptyForm); setShowForm(false); }}>Cancel</button>
              <button className={T.btn} disabled={busy} onClick={submit} data-testid="admin-onb-submit">
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
                Onboard &amp; continue to KYC
              </button>
            </div>
            <p className="text-[10px] text-[#5E6C84]">
              Password is left blank — the provider will set it themselves on first login (mobile app or PC console).
              Onboarding writes directly to Supabase, so both apps see the new account immediately.
            </p>
          </div>
        </section>
      )}

      <section className={T.card} data-testid="admin-onboarding-list">
        <div className={T.head}>
          <span>Provider roster · {state.providers.length}</span>
          <span className="normal-case text-[10px] text-[#5E6C84] font-normal">Live from shared Supabase</span>
        </div>
        {state.err ? (
          <div className="p-6 text-sm text-[#BF2600] flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 mt-0.5" /> {state.err}
          </div>
        ) : state.providers.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="admin-onboarding-empty">
            No providers onboarded yet. Click <b>Onboard provider</b> to create the first one.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
                <tr>
                  <th className="px-3 py-2 text-left">Provider</th>
                  <th className="px-3 py-2 text-left">Vertical</th>
                  <th className="px-3 py-2 text-left">Phone</th>
                  <th className="px-3 py-2 text-center">KYC status</th>
                  <th className="px-3 py-2 text-center">Docs</th>
                  <th className="px-3 py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {state.providers.map(p => (
                  <tr key={p.id} className="border-t border-[#DFE1E6] hover:bg-[#F8F9FA]" data-testid={`admin-onb-row-${p.id}`}>
                    <td className="px-3 py-2">
                      <div className="font-semibold text-[#091E42]">{p.name || "—"}</div>
                      <div className="text-[10px] text-[#5E6C84] font-mono">{p.id.slice(0, 8)}…</div>
                    </td>
                    <td className="px-3 py-2 capitalize">{p.vertical || p.role}</td>
                    <td className="px-3 py-2 font-mono">+91 {p.phone}</td>
                    <td className="px-3 py-2 text-center"><StatusChip status={p.verification_status || "pending"} /></td>
                    <td className="px-3 py-2 text-center">
                      <span className="text-[#091E42] font-semibold">{p.docs_approved}</span>
                      <span className="text-[#5E6C84]"> / {p.docs_total}</span>
                      {p.docs_pending > 0 && <span className="ml-1 text-[10px] text-[#974F0C]">({p.docs_pending} pending)</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button className={T.btnGhost}
                        onClick={() => nav(`/admin/onboarding/${p.id}`)}
                        data-testid={`admin-onb-open-${p.id}`}>
                        Manage KYC <ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
