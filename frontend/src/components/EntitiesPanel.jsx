import React, { useEffect, useState } from "react";
import { Building2, Plus, Loader2, X, Upload } from "lucide-react";
import api from "../lib/api";

import { KIND_LABEL, ALLOWED, FIELDS } from "../lib/entityFields";
import BulkImportDialog from "./entities/BulkImportDialog";
import PendingRows from "./entities/PendingRows";

const inp = "w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none";

function AddForm({ kinds, onSave, onCancel }) {
  const [f, setF] = useState({ entity_kind: kinds[0] }); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const bad = FIELDS.some(([k, , req]) => req && !String(f[k] || "").trim()) || !/^[6-9]\d{9}$/.test(f.dedicated_phone || "") || (f.pincode && !/^\d{6}$/.test(f.pincode));
  const save = async () => {
    setBusy(true); setErr("");
    const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "" && v != null));
    if (body.dispatch_radius_km) body.dispatch_radius_km = Number(body.dispatch_radius_km);
    try { await onSave(body); } catch (e) { setErr(e?.response?.data?.detail || "Could not add entity"); } finally { setBusy(false); }
  };
  return (
    <div className="border border-[#B3D4FF] bg-[#DEEBFF]/30 rounded-md p-4 space-y-3" data-testid="entity-add-form">
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84]">Entity type *
          <select className={`${inp} mt-1 font-normal normal-case tracking-normal bg-white`} value={f.entity_kind} onChange={(e) => set("entity_kind", e.target.value)} data-testid="entity-kind-select">
            {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></label>
        {f.entity_kind === "ambulance" && <label className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84]">Dispatch radius (km)
          <input className={`${inp} mt-1 font-normal bg-white`} inputMode="numeric" value={f.dispatch_radius_km || ""} onChange={(e) => set("dispatch_radius_km", e.target.value)} data-testid="entity-f-dispatch_radius_km" /></label>}
        {FIELDS.map(([k, label, req, wide]) => <label key={k} className={`text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] ${wide ? "sm:col-span-2" : ""}`}>{label}{req && " *"}
          <input className={`${inp} mt-1 font-normal normal-case tracking-normal bg-white`} value={f[k] || ""} data-testid={`entity-f-${k}`}
            onChange={(e) => set(k, k === "dedicated_phone" ? e.target.value.replace(/\D/g, "").slice(0, 10) : e.target.value)} /></label>)}
      </div>
      <p className="text-xs text-[#5E6C84]">The dedicated phone becomes this entity's own login for the Provider app and CRM.</p>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="entity-add-error">{err}</div>}
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white" data-testid="entity-add-cancel">Cancel</button>
        <button onClick={save} disabled={busy || bad} className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md disabled:opacity-50" data-testid="entity-add-submit">
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}Add entity</button>
      </div>
    </div>
  );
}

function EntityRow({ e, onRemove, busy }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3 border-b border-[#F4F5F7] last:border-0" data-testid={`entity-row-${e.id}`}>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-[#091E42] truncate">{e.name} <span className="ml-1 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#F4F5F7] text-[#42526E]">{KIND_LABEL[e.entity_kind] || e.entity_kind}</span></div>
        <div className="text-xs text-[#5E6C84] truncate">{e.contact_person} · {e.dedicated_phone} · {e.city}</div>
      </div>
      {e.is_active === false ? <span className="text-xs text-[#97A0AF]">Removed</span>
        : <button onClick={() => onRemove(e)} disabled={busy} className="p-1.5 rounded hover:bg-[#FFEBE6] text-[#BF2600] disabled:opacity-60" title="Remove entity" data-testid={`entity-remove-${e.id}`}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}</button>}
    </div>
  );
}

export default function EntitiesPanel({ base, params }) {
  const [state, setState] = useState(null); const [err, setErr] = useState(""); const [adding, setAdding] = useState(false);
  const [bulk, setBulk] = useState(false); const [pending, setPending] = useState([]);
  const load = () => Promise.all([api.get(base, { params }), api.get(`${base}/pending`, { params })])
    .then(([r, p]) => { setState(r.data); setPending(p.data.items); setErr(""); }).catch((e) => setErr(e?.response?.data?.detail || "Could not load entities"));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [base, JSON.stringify(params)]);
  const add = async (body) => { await api.post(base, body, { params }); setAdding(false); load(); };
  const [removing, setRemoving] = useState(null);
  const remove = async (e) => {
    if (!window.confirm(`Remove ${e.name}?`)) return;
    setRemoving(e.id); setErr("");
    try { await api.delete(`${base}/${e.id}`, { params }); await load(); }
    catch (x) { setErr(x?.response?.data?.detail || "Could not remove entity"); } finally { setRemoving(null); }
  };
  const kinds = ALLOWED[state?.root_kind] || [];
  const active = (state?.entities || []).filter((e) => e.is_active !== false);
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-lg p-5" data-testid="entities-panel">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div><div className="font-heading font-bold text-[#091E42] flex items-center gap-2"><Building2 className="h-4 w-4 text-[#0052CC]" /> Internal entities <span className="text-[#5E6C84] font-medium" data-testid="entities-count">/ {active.length}</span></div>
          <p className="text-xs text-[#5E6C84] mt-0.5">{state?.org?.org_name ? `${state.org.org_name} — ` : ""}branches and units, each with its own login.</p></div>
        {state && !adding && <div className="flex gap-2">
          <button onClick={() => setBulk(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold rounded-md border border-[#DFE1E6] text-[#091E42] hover:bg-[#F8F9FA]" data-testid="entity-bulk-btn"><Upload className="h-4 w-4" /> Bulk import</button>
          <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold rounded-md text-white bg-[#0052CC] hover:bg-[#0747A6]" data-testid="entity-add-btn"><Plus className="h-4 w-4" /> Add entity</button></div>}
      </div>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="entities-error">{err}</div>}
      {!state && !err && <div className="text-sm text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>}
      {adding && <AddForm kinds={kinds} onSave={add} onCancel={() => setAdding(false)} />}
      {state && (state.entities.length ? <div className="mt-2">{state.entities.map((e) => <EntityRow key={e.id} e={e} onRemove={remove} busy={removing === e.id} />)}</div>
        : !adding && <div className="text-sm text-[#5E6C84] py-4 flex items-center gap-2" data-testid="entities-empty">No entities yet.</div>)}
      {state && <PendingRows items={pending} kinds={kinds} base={base} params={params} onChanged={load} />}
      {bulk && <BulkImportDialog base={base} params={params} kinds={kinds} existingPhones={new Set(active.map((e) => e.dedicated_phone))}
        onClose={() => setBulk(false)} onFinished={load} />}
    </div>
  );
}
