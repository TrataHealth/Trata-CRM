import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Receipt } from "lucide-react";
import api from "../lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { T, toastErr } from "../components/ledger/ui";
import { PatientServices } from "../components/ledger/PatientServices";
import { ServiceForm } from "../components/ledger/ServiceForm";
import { InvoiceList } from "../components/ledger/InvoiceList";

export default function ProviderLedger() {
  const [state, setState] = useState({ loading: true, data: null });
  const [form, setForm] = useState({ open: false, patient: "" });
  const load = useCallback(async () => {
    try { const { data } = await api.get("/provider/ledger"); setState({ loading: false, data }); }
    catch (e) { toastErr(e, "Could not load services"); setState({ loading: false, data: null }); }
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("trata:live", load);
    return () => window.removeEventListener("trata:live", load);
  }, [load]);

  if (state.loading) return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  if (!state.data) return <div className="p-8 text-sm text-[#BF2600]">Could not load your services.</div>;
  const { patients, invoices, categories } = state.data;
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="provider-ledger">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><Receipt className="h-3 w-3" /> Trata patients & billing</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Services to Trata patients</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Patients who reached you through the Trata Health app. Add in-facility services (surgery, ICU, procedures) with the bill as proof — Trata reviews each entry.</p>
        </div>
        <button className={T.btn} onClick={() => setForm({ open: true, patient: "" })} disabled={!patients.length} data-testid="provider-ledger-add"><Plus className="h-3.5 w-3.5" /> Add extended service</button>
      </div>
      <Tabs defaultValue="patients">
        <TabsList>
          <TabsTrigger value="patients" data-testid="provider-tab-patients">Patients ({patients.length})</TabsTrigger>
          <TabsTrigger value="invoices" data-testid="provider-tab-invoices">Invoices from Trata ({invoices.length})</TabsTrigger>
        </TabsList>
        <TabsContent value="patients" className="mt-4">
          <PatientServices patients={patients} onAdd={(k) => setForm({ open: true, patient: k })} onChanged={load}
            canDelete={(s) => s.status !== "approved"} />
        </TabsContent>
        <TabsContent value="invoices" className="mt-4"><section className={T.card}><InvoiceList invoices={invoices} admin={false} onChanged={load} /></section></TabsContent>
      </Tabs>
      <ServiceForm open={form.open} onClose={() => setForm({ open: false, patient: "" })} mode="provider"
        patients={patients} defaultPatient={form.patient} categories={categories} onSaved={load} />
    </div>
  );
}
