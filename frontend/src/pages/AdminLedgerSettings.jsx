import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { T, toastErr, INDIAN_STATES } from "../components/ledger/ui";

const GROUPS = [
  ["Company", [["legal_name", "Legal name *"], ["address", "Registered address *"], ["state", "State *"], ["gstin", "GSTIN"], ["pan", "PAN"], ["cin", "CIN"], ["email", "Billing email"], ["phone", "Phone"]]],
  ["Bank / payment", [["bank_name", "Bank name"], ["account_name", "Account name"], ["account_number", "Account number"], ["ifsc", "IFSC"], ["upi_id", "UPI ID"]]],
  ["Invoice defaults", [["invoice_prefix", "Invoice prefix *"], ["default_sac", "Default SAC code"], ["payment_terms_days", "Payment terms (days)"]]],
];

export default function AdminLedgerSettings() {
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/ledger/settings").then(({ data }) => setF(data)).catch((e) => toastErr(e)); }, []);
  const save = async () => {
    if (!f.legal_name || !f.address || !f.state) return toast.error("Legal name, address and state are required");
    setBusy(true);
    try { await api.put("/ledger/settings", { ...f, payment_terms_days: parseInt(f.payment_terms_days, 10) || 15 }); toast.success("Invoice settings saved"); }
    catch (e) { toastErr(e); } finally { setBusy(false); }
  };
  if (!f) return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 max-w-4xl" data-testid="ledger-settings">
      <Link to="/admin/ledger" className="text-xs text-[#0052CC] inline-flex items-center gap-1"><ArrowLeft className="h-3 w-3" /> Provider ledger</Link>
      <div>
        <h1 className="font-heading text-2xl font-black text-[#091E42]">Trata Health invoice settings</h1>
        <p className="text-sm text-[#5E6C84] mt-1">These details print on every provider invoice. Existing invoices keep the details they were raised with.</p>
      </div>
      {GROUPS.map(([title, fields]) => (
        <section key={title} className={`${T.card} p-4`}>
          <div className="text-sm font-semibold mb-2">{title}</div>
          <div className="grid sm:grid-cols-2 gap-3">
            {fields.map(([k, label]) => (
              <label key={k} className={`${T.label} ${k === "address" ? "sm:col-span-2" : ""}`}>{label}
                {k === "state" ? (
                  <select className={T.input} value={f.state || ""} onChange={(e) => setF({ ...f, state: e.target.value })} data-testid="settings-state">
                    <option value="">Select…</option>{INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                ) : <input className={T.input} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`settings-${k}`} />}
              </label>
            ))}
          </div>
        </section>
      ))}
      <section className={`${T.card} p-4`}>
        <label className={T.label}>Terms printed in the footer
          <textarea rows={3} className={T.input} value={f.terms || ""} onChange={(e) => setF({ ...f, terms: e.target.value })} data-testid="settings-terms" />
        </label>
      </section>
      <button className={T.btn} onClick={save} disabled={busy} data-testid="settings-save">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save settings</button>
    </div>
  );
}
