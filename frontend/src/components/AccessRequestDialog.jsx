import React, { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Search, X } from "lucide-react";
import api from "../lib/api";

const ROLES = [["provider_admin", "Provider admin / owner"], ["provider_staff", "Provider staff"]];
const input = "mt-1 w-full px-3 py-2 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none";

function ProviderPicker({ value, onChange }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (value || q.trim().length < 2) { setItems([]); return undefined; }
    const t = setTimeout(() => api.get("/public/providers/search", { params: { q } }).then((r) => setItems(r.data.items)).catch(() => setItems([])), 250);
    return () => clearTimeout(t);
  }, [q, value]);
  if (value) return (
    <div className="mt-1 flex items-center justify-between px-3 py-2 text-sm border border-[#4C9AFF] bg-[#DEEBFF]/50 rounded-md" data-testid="access-provider-selected">
      <span><b>{value.name}</b> <span className="text-[#5E6C84] capitalize">· {value.type?.replace(/_/g, " ")}{value.city ? ` · ${value.city}` : ""}</span></span>
      <button type="button" onClick={() => onChange(null)} aria-label="Change provider" data-testid="access-provider-clear"><X className="h-4 w-4 text-[#5E6C84]" /></button>
    </div>
  );
  return (
    <div className="relative">
      <Search className="absolute left-3 top-[1.15rem] h-4 w-4 text-[#97A0AF]" />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search hospital, lab, pharmacy…" className={`${input} pl-9`} data-testid="access-provider-search" />
      {items.length > 0 && <ul className="absolute z-10 mt-1 w-full bg-white border border-[#DFE1E6] rounded-md shadow-lg max-h-56 overflow-auto">{items.map((p) => (
        <li key={p.id}><button type="button" onClick={() => onChange(p)} className="w-full text-left px-3 py-2 text-sm hover:bg-[#F4F5F7]" data-testid={`access-provider-option-${p.id}`}>
          <b className="text-[#091E42]">{p.name}</b> <span className="text-xs text-[#5E6C84] capitalize">· {p.type?.replace(/_/g, " ")}{p.city ? ` · ${p.city}` : ""}</span></button></li>))}</ul>}
      {q.trim().length >= 2 && items.length === 0 && <div className="text-[11px] text-[#5E6C84] mt-1">No onboarded provider matches. Ask your organisation to sign up on the Trata Provider app first.</div>}
    </div>
  );
}

/** Login-screen form: an unregistered provider user asks Trata Health Admin for access. */
export function AccessRequestDialog({ phone, onClose }) {
  const [f, setF] = useState({ name: "", phone: phone || "", role_wanted: "provider_staff", note: "" });
  const [provider, setProvider] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  const set = (k) => (e) => { setErr(""); setF({ ...f, [k]: k === "phone" ? e.target.value.replace(/\D/g, "").slice(0, 10) : e.target.value }); };
  const pick = (p) => { setErr(""); setProvider(p); };

  const submit = async (e) => {
    e.preventDefault(); setErr("");
    if (f.name.trim().length < 2) return setErr("Enter your name");
    if (f.phone.length !== 10) return setErr("Enter a valid 10-digit phone");
    if (!provider) return setErr("Choose your provider from the list");
    setBusy(true);
    try { await api.post("/public/access-requests", { ...f, provider_contact_id: provider.id }); setDone(true); }
    catch (x) { setErr(x?.response?.data?.detail || "Could not send request"); }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#091E42]/50 flex items-center justify-center p-4" data-testid="access-request-dialog">
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl relative">
        <button onClick={onClose} className="absolute right-4 top-4 text-[#5E6C84]" aria-label="Close" data-testid="access-request-close"><X className="h-5 w-5" /></button>
        {done ? (
          <div className="text-center py-6" data-testid="access-request-success">
            <CheckCircle2 className="h-10 w-10 text-[#36B37E] mx-auto" />
            <h3 className="font-heading text-xl font-bold text-[#091E42] mt-3">Request sent</h3>
            <p className="text-sm text-[#5E6C84] mt-1">Trata Health Admin will review it and contact you on +91 {f.phone}.</p>
            <button onClick={onClose} className="mt-5 px-4 py-2 text-sm font-semibold rounded-md bg-[#0052CC] text-white" data-testid="access-request-done">Done</button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div>
              <h3 className="font-heading text-xl font-bold text-[#091E42]">Request access</h3>
              <p className="text-xs text-[#5E6C84] mt-1">For people working at a provider already on Trata Health. Trata Health Admin reviews every request.</p>
            </div>
            <label className="block text-xs font-semibold text-[#42526E]">Your name<input value={f.name} onChange={set("name")} maxLength={80} className={input} data-testid="access-name-input" /></label>
            <label className="block text-xs font-semibold text-[#42526E]">Phone
              <div className="flex mt-1"><span className="px-3 inline-flex items-center bg-[#F1F2F4] border border-r-0 border-[#DFE1E6] rounded-l-md text-sm">+91</span>
                <input value={f.phone} onChange={set("phone")} className={`${input} mt-0 rounded-l-none`} data-testid="access-phone-input" /></div></label>
            <div className="text-xs font-semibold text-[#42526E]">Access needed
              <div className="grid grid-cols-2 gap-2 mt-1">{ROLES.map(([k, l]) => (
                <button key={k} type="button" onClick={() => setF({ ...f, role_wanted: k })} data-testid={`access-role-${k}`}
                        className={`px-3 py-2 text-sm rounded-md border ${f.role_wanted === k ? "border-[#0052CC] bg-[#DEEBFF] text-[#091E42]" : "border-[#DFE1E6] text-[#42526E]"}`}>{l}</button>))}</div></div>
            <div className="text-xs font-semibold text-[#42526E]">Your provider (onboarded with Trata Health)<ProviderPicker value={provider} onChange={pick} /></div>
            <label className="block text-xs font-semibold text-[#42526E]">Note <span className="font-normal text-[#97A0AF]">(optional)</span>
              <textarea value={f.note} onChange={set("note")} maxLength={500} rows={2} placeholder="e.g. I'm the front-desk manager" className={input} data-testid="access-note-input" /></label>
            {err && <div className="text-sm text-[#FF5630]" data-testid="access-request-error">{err}</div>}
            <button type="submit" disabled={busy} className="w-full inline-flex justify-center items-center gap-2 py-2.5 text-sm font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-60" data-testid="access-request-submit">
              {busy && <Loader2 className="h-4 w-4 animate-spin" />} Send request
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
