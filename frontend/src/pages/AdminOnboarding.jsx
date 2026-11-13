import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { SignupForm } from "../components/onboarding/SignupForm";
import {
  UserPlus, ShieldCheck, ChevronRight, Loader2, AlertTriangle, RefreshCw,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  head: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  btn: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnGhost: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
  input: "w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
};

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

export default function AdminOnboarding() {
  const nav = useNavigate();
  const [state, setState] = useState({ loading: true, providers: [], err: "" });
  const [showForm, setShowForm] = useState(false);
  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/onboarding/providers");
      setState({ loading: false, providers: data.providers || [], err: "" });
    } catch (e) {
      setState({ loading: false, providers: [], err: e?.response?.data?.detail || "Could not load providers" });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

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
            Create any provider the Provider App's sign-up offers — pick the type, fill the same form — it will appear in the mobile Provider App
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
          <SignupForm onCancel={() => setShowForm(false)} onDone={(d) => { setShowForm(false); nav(`/admin/onboarding/${d.user_id}`); }} />
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
                    <td className="px-3 py-2 capitalize">{{ path_lab: "Path Lab", diagnostic_centre: "Diagnostic Centre" }[p.role] || p.vertical || p.role}</td>
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
