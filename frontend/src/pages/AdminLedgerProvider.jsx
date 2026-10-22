import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Loader2, Plus, Megaphone, FileText, Percent, Users, Trash2 } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { T, money, thisMonth, pretty, toastErr, INDIAN_STATES } from "../components/ledger/ui";
import { PatientServices } from "../components/ledger/PatientServices";
import { ServiceForm } from "../components/ledger/ServiceForm";
import { InvoiceList } from "../components/ledger/InvoiceList";
import { Statement } from "../components/ledger/Statement";

const FEE_KEYS = ["consultation", "teleconsultation", "admission", "ambulance_ride", "lab_test", "diagnostic_scan", "surgery", "procedure", "icu_stay", "room_charges", "implant", "diagnostics", "pharmacy", "other"];

function Promotions({ uid, promos, onChanged }) {
  const [f, setF] = useState({ title: "", description: "", amount: "", charge_date: new Date().toISOString().slice(0, 10), channel: "in_app" });
  const save = async () => {
    if (!f.title || !f.amount) return toast.error("Title and amount required");
    try { await api.post(`/ledger/providers/${uid}/promotions`, { ...f, amount: parseFloat(f.amount) }); toast.success("Promotion fee added"); setF({ ...f, title: "", description: "", amount: "" }); onChanged(); }
    catch (e) { toastErr(e); }
  };
  const del = async (p) => { try { await api.delete(`/ledger/promotions/${p.id}`); onChanged(); } catch (e) { toastErr(e); } };
  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <section className={`${T.card} p-4 space-y-2`} data-testid="promo-form">
        <div className="text-sm font-semibold flex items-center gap-1.5"><Megaphone className="h-4 w-4 text-[#FF991F]" /> Add flat marketing fee</div>
        <label className={T.label}>Campaign *<input className={T.input} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. Featured listing – June" data-testid="promo-title" /></label>
        <label className={T.label}>Channel<select className={T.input} value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })} data-testid="promo-channel">
          <option value="in_app">Inside Patient App</option><option value="outside_app">Outside app (social, print, events)</option></select></label>
        <div className="grid grid-cols-2 gap-2">
          <label className={T.label}>Flat fee (₹) *<input className={T.input} inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} data-testid="promo-amount" /></label>
          <label className={T.label}>Date *<input type="date" className={T.input} value={f.charge_date} onChange={(e) => setF({ ...f, charge_date: e.target.value })} data-testid="promo-date" /></label>
        </div>
        <label className={T.label}>Description<textarea rows={2} className={T.input} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <button className={T.btn} onClick={save} data-testid="promo-save"><Plus className="h-3.5 w-3.5" /> Add fee</button>
      </section>
      <section className={`${T.card} lg:col-span-2`}>
        <div className={T.head}>Marketing & promotion charges</div>
        {promos.length === 0 ? <div className="p-6 text-center text-sm text-[#5E6C84]">No promotion fees yet.</div> : promos.map((p) => (
          <div key={p.id} className="px-4 py-2 border-t border-[#F4F5F7] flex items-center justify-between gap-3" data-testid={`promo-row-${p.id}`}>
            <div className="min-w-0"><div className="text-xs font-semibold">{p.title}</div><div className="text-[10px] text-[#5E6C84]">{p.charge_date} · {pretty(p.channel)}{p.invoice_id ? " · invoiced" : ""}</div></div>
            <div className="flex items-center gap-2"><span className="font-mono text-xs font-bold">{money(p.amount)}</span>
              {!p.invoice_id && <button onClick={() => del(p)} className="text-[#5E6C84] hover:text-[#BF2600]" data-testid={`promo-delete-${p.id}`}><Trash2 className="h-3.5 w-3.5" /></button>}</div>
          </div>
        ))}
      </section>
    </div>
  );
}

function BillingTerms({ uid, bp, onChanged }) {
  const [f, setF] = useState({ fee_pct: 10, category_fee_pct: {}, ...bp });
  useEffect(() => setF({ fee_pct: 10, category_fee_pct: {}, ...bp }), [bp]);
  const save = async () => {
    const cat = Object.fromEntries(Object.entries(f.category_fee_pct || {}).filter(([, v]) => v !== "" && v != null).map(([k, v]) => [k, parseFloat(v)]));
    try { await api.put(`/ledger/providers/${uid}/billing`, { ...f, fee_pct: parseFloat(f.fee_pct), category_fee_pct: cat }); toast.success("Billing terms saved"); onChanged(); }
    catch (e) { toastErr(e); }
  };
  const inp = (k, label, ph) => <label className={T.label}>{label}<input className={T.input} value={f[k] || ""} placeholder={ph} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`billing-${k}`} /></label>;
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <section className={`${T.card} p-4 space-y-3`}>
        <div className="text-sm font-semibold flex items-center gap-1.5"><Percent className="h-4 w-4 text-[#0052CC]" /> Trata fee</div>
        <label className={T.label}>Default fee % on each service's bill amount *
          <input className={T.input} inputMode="decimal" value={f.fee_pct} onChange={(e) => setF({ ...f, fee_pct: e.target.value })} data-testid="billing-fee-pct" /></label>
        <div className="text-[11px] text-[#5E6C84]">Override per service type (leave blank to use default):</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {FEE_KEYS.map((k) => (
            <label key={k} className="text-[10px] text-[#42526E]">{pretty(k)}
              <input className={T.input} inputMode="decimal" placeholder={`${f.fee_pct}%`} value={f.category_fee_pct?.[k] ?? ""} onChange={(e) => setF({ ...f, category_fee_pct: { ...f.category_fee_pct, [k]: e.target.value } })} data-testid={`billing-cat-${k}`} />
            </label>
          ))}
        </div>
      </section>
      <section className={`${T.card} p-4 space-y-2`}>
        <div className="text-sm font-semibold">Invoice “Billed to” details</div>
        {inp("legal_name", "Legal name", "As per GST registration")}
        {inp("gstin", "GSTIN", "22AAAAA0000A1Z5")}
        {inp("pan", "PAN")}
        {inp("billing_address", "Billing address")}
        <div className="grid grid-cols-2 gap-2">
          <label className={T.label}>State (place of supply)
            <select className={T.input} value={f.state || ""} onChange={(e) => setF({ ...f, state: e.target.value })} data-testid="billing-state">
              <option value="">Select…</option>{INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>{inp("billing_email", "Billing email")}</div>
        <p className="text-[10px] text-[#5E6C84]">Same state as Trata → CGST 9% + SGST 9%; otherwise IGST 18%. GSTIN's state code takes priority when present.</p>
        <button className={T.btn} onClick={save} data-testid="billing-save">Save billing terms</button>
      </section>
    </div>
  );
}

function InvoiceTab({ uid, invoices, onChanged }) {
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get("/ledger/settings").then(({ data }) => setF({ month: thisMonth(), sac_code: data.default_sac || "", notes: "" }))
      .catch(() => setF({ month: thisMonth(), sac_code: "", notes: "" }));
  }, []);
  if (!f) return <div className="p-6 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  const gen = async () => {
    if (!f.sac_code.trim()) return toast.error("Enter the SAC code");
    setBusy(true);
    try { const { data } = await api.post(`/ledger/providers/${uid}/invoices`, f); toast.success(`Invoice ${data.number} raised · ${money(data.grand_total)}`); onChanged(); }
    catch (e) { toastErr(e, "Could not raise invoice"); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4">
      <section className={`${T.card} p-4`} data-testid="invoice-generate">
        <div className="text-sm font-semibold flex items-center gap-1.5 mb-2"><FileText className="h-4 w-4 text-[#0052CC]" /> Raise monthly invoice</div>
        <div className="grid sm:grid-cols-4 gap-3 items-end">
          <label className={T.label}>Billing month *<input type="month" className={T.input} value={f.month} onChange={(e) => setF({ ...f, month: e.target.value })} data-testid="invoice-month" /></label>
          <label className={T.label}>SAC code *<input className={T.input} value={f.sac_code} onChange={(e) => setF({ ...f, sac_code: e.target.value })} placeholder="e.g. 998599" data-testid="invoice-sac" /></label>
          <label className={T.label}>Notes on invoice<input className={T.input} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} data-testid="invoice-notes" /></label>
          <button className={T.btn} onClick={gen} disabled={busy} data-testid="invoice-generate-btn">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Raise invoice</button>
        </div>
        <p className="text-[11px] text-[#5E6C84] mt-2">Includes completed app services with a bill amount, approved extended services and promotion fees dated in that month that aren't already invoiced. Trata fee + 18% GST. Items lock once invoiced.</p>
      </section>
      <section className={T.card}><div className={T.head}>Invoices</div><InvoiceList invoices={invoices} admin onChanged={onChanged} /></section>
    </div>
  );
}

export default function AdminLedgerProvider() {
  const { uid } = useParams();
  const [state, setState] = useState({ loading: true, data: null });
  const [form, setForm] = useState({ open: false, patient: "" });
  const load = useCallback(async () => {
    try { const { data } = await api.get(`/ledger/providers/${uid}`); setState({ loading: false, data }); }
    catch (e) { toastErr(e, "Could not load provider"); setState({ loading: false, data: null }); }
  }, [uid]);
  useEffect(() => { load(); }, [load]);

  if (state.loading) return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading provider ledger…</div>;
  if (!state.data) return <div className="p-8 text-sm text-[#BF2600]" data-testid="ledger-provider-error">Provider not found.</div>;
  const { provider, patients, billing_profile, promotions, invoices, categories } = state.data;
  const services = patients.flatMap((p) => p.services);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="admin-ledger-provider">
      <Link to="/admin/ledger" className="text-xs text-[#0052CC] inline-flex items-center gap-1" data-testid="ledger-back"><ArrowLeft className="h-3 w-3" /> All providers</Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline">{pretty(provider.vertical)} · {provider.city || "—"}</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{provider.display_name || provider.name}</h1>
          <p className="text-sm text-[#5E6C84] mt-1">{provider.phone} · fee {billing_profile.fee_pct}% · {patients.length} Trata patient{patients.length === 1 ? "" : "s"} · {services.length} services</p>
        </div>
        <button className={T.btn} onClick={() => setForm({ open: true, patient: "" })} disabled={!patients.length} data-testid="ledger-add-service-top"><Plus className="h-3.5 w-3.5" /> Add extended service</button>
      </div>
      <Tabs defaultValue="patients">
        <TabsList data-testid="ledger-tabs">
          <TabsTrigger value="patients" data-testid="tab-patients"><Users className="h-3.5 w-3.5 mr-1" /> Patients & services</TabsTrigger>
          <TabsTrigger value="invoices" data-testid="tab-invoices">Invoices ({invoices.length})</TabsTrigger>
          <TabsTrigger value="statement" data-testid="tab-statement">Statement</TabsTrigger>
          <TabsTrigger value="promotions" data-testid="tab-promotions">Promotions</TabsTrigger>
          <TabsTrigger value="billing" data-testid="tab-billing">Billing terms</TabsTrigger>
        </TabsList>
        <TabsContent value="patients" className="mt-4">
          <PatientServices patients={patients} onAdd={(k) => setForm({ open: true, patient: k })} onChanged={load} canDelete={() => true} />
        </TabsContent>
        <TabsContent value="invoices" className="mt-4"><InvoiceTab uid={uid} invoices={invoices} onChanged={load} /></TabsContent>
        <TabsContent value="statement" className="mt-4"><Statement uid={uid} refreshKey={invoices.map((i) => i.status).join()} /></TabsContent>
        <TabsContent value="promotions" className="mt-4"><Promotions uid={uid} promos={promotions} onChanged={load} /></TabsContent>
        <TabsContent value="billing" className="mt-4"><BillingTerms uid={uid} bp={billing_profile} onChanged={load} /></TabsContent>
      </Tabs>
      <ServiceForm open={form.open} onClose={() => setForm({ open: false, patient: "" })} mode="admin" uid={uid}
        patients={patients} defaultPatient={form.patient} categories={categories} onSaved={load} />
    </div>
  );
}
