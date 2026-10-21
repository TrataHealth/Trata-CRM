import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Receipt, Search, Loader2, ClipboardCheck, Settings2, RefreshCw, Building2, Ambulance, FlaskConical, Stethoscope, ScanLine } from "lucide-react";
import api from "../lib/api";
import { T, money, thisMonth, STATUS_TONE, pretty, toastErr } from "../components/ledger/ui";

const V_ICON = { hospital: Building2, ambulance: Ambulance, pathology: FlaskConical, path_lab: FlaskConical, diagnostic_centre: ScanLine, doctor: Stethoscope };
const V_LABEL = { pathology: "Lab (legacy)", path_lab: "Lab Partner", diagnostic_centre: "Imaging & Diagnostics Partner" };

const Kpi = ({ label, value, sub, testid }) => (
  <div className={`${T.card} p-4`} data-testid={testid}>
    <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
    <div className="font-heading text-2xl font-black text-[#091E42] mt-1">{value}</div>
    {sub && <div className="text-[11px] text-[#5E6C84] mt-0.5">{sub}</div>}
  </div>
);

export default function AdminLedger() {
  const [month, setMonth] = useState(thisMonth());
  const [state, setState] = useState({ loading: true, data: null });
  const [q, setQ] = useState("");
  const [vertical, setVertical] = useState("all");
  const [onlyActive, setOnlyActive] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(async (fresh = false) => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const { data } = await api.get("/ledger/providers", { params: { month, fresh } });
      setState({ loading: false, data });
    } catch (e) { toastErr(e, "Could not load ledger"); setState({ loading: false, data: null }); }
  }, [month]);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => (state.data?.providers || []).filter((p) =>
    (vertical === "all" || p.vertical === vertical) &&
    (!onlyActive || p.patients > 0 || p.manual_services > 0 || p.month_promotions > 0) &&
    (!q || `${p.display_name} ${p.phone} ${p.city}`.toLowerCase().includes(q.toLowerCase()))), [state.data, vertical, q, onlyActive]);
  const t = state.data?.totals || {};

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="admin-ledger">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><Receipt className="h-3 w-3" /> Provider Ledger & Invoicing</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Services catered to Trata patients</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Every Patient-App booking, SOS and admission per provider, plus in-facility extended services — the basis for monthly invoicing.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="text-xs px-2 py-1.5 border border-[#DFE1E6] rounded bg-white" data-testid="ledger-month" />
          <button className={T.btnGhost} onClick={() => load(true)} data-testid="ledger-refresh"><RefreshCw className={`h-3.5 w-3.5 ${state.loading ? "animate-spin" : ""}`} /> Refresh</button>
          <Link to="/admin/ledger/review" className={T.btnGhost} data-testid="ledger-review-link"><ClipboardCheck className="h-3.5 w-3.5" /> Review queue{t.pending_review ? ` (${t.pending_review})` : ""}</Link>
          <Link to="/admin/ledger/revenue" className={T.btn} data-testid="ledger-revenue-link"><Receipt className="h-3.5 w-3.5" /> Revenue</Link>
          <Link to="/admin/ledger/settings" className={T.btnGhost} data-testid="ledger-settings-link"><Settings2 className="h-3.5 w-3.5" /> Invoice settings</Link>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Providers" value={t.providers ?? "—"} sub="on the network" testid="ledger-kpi-providers" />
        <Kpi label="Trata patients served" value={t.patients ?? "—"} sub="via app booking or SOS" testid="ledger-kpi-patients" />
        <Kpi label={`Billable value · ${month}`} value={money(t.month_billable)} sub="app + approved extended services" testid="ledger-kpi-billable" />
        <Kpi label="Awaiting review" value={t.pending_review ?? 0} sub="provider-submitted services" testid="ledger-kpi-pending" />
      </div>

      <section className={T.card}>
        <div className={T.head}>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-[#5E6C84]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search provider…" className="pl-7 pr-2 py-1 text-xs normal-case tracking-normal font-normal border border-[#DFE1E6] rounded bg-white" data-testid="ledger-search" />
            </div>
            <select value={vertical} onChange={(e) => setVertical(e.target.value)} className="text-xs normal-case tracking-normal font-normal border border-[#DFE1E6] rounded bg-white px-2 py-1" data-testid="ledger-vertical">
              <option value="all">All types</option><option value="hospital">Hospitals</option><option value="ambulance">Ambulance</option>
              <option value="pathology">Labs (legacy)</option><option value="path_lab">Lab Partners</option>
              <option value="diagnostic_centre">Imaging & Diagnostics Partners</option><option value="doctor">Doctors</option>
            </select>
            <label className="flex items-center gap-1 normal-case tracking-normal font-normal text-xs text-[#42526E]">
              <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} data-testid="ledger-only-active" /> With Trata patients only
            </label>
          </div>
          <span>{rows.length} shown</span>
        </div>
        {state.loading && !state.data ? (
          <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Aggregating services from the shared database…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="ledger-empty">No providers match. Untick “With Trata patients only” to see everyone.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs" data-testid="ledger-table">
              <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
                <tr><th className="px-3 py-2 text-left">Provider</th><th className="px-3 py-2 text-right">Patients</th><th className="px-3 py-2 text-right">App services</th>
                  <th className="px-3 py-2 text-right">Extended</th><th className="px-3 py-2 text-right">Billable ({month})</th><th className="px-3 py-2 text-right">Promotions</th><th className="px-3 py-2 text-left">Invoice</th></tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const Icon = V_ICON[p.vertical] || Building2;
                  return (
                    <tr key={p.id} onClick={() => navigate(`/admin/ledger/${p.id}`)} className="border-t border-[#DFE1E6] hover:bg-[#F8F9FA] transition-colors cursor-pointer" data-testid={`ledger-row-${p.id}`}>
                      <td className="px-3 py-2">
                        <Link to={`/admin/ledger/${p.id}`} className="flex items-center gap-2 group" data-testid={`ledger-open-${p.id}`}>
                          <Icon className="h-4 w-4 text-[#0052CC] shrink-0" />
                          <div className="min-w-0"><div className="font-semibold text-[#091E42] group-hover:underline truncate">{p.display_name}</div>
                            <div className="text-[10px] text-[#5E6C84]">{V_LABEL[p.vertical] || pretty(p.vertical)} · {p.city || "—"}</div></div>
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right font-bold">{p.patients}</td>
                      <td className="px-3 py-2 text-right">{p.auto_services}</td>
                      <td className="px-3 py-2 text-right">{p.manual_services}{p.pending_review ? <span className={`${T.chip} ${STATUS_TONE.pending_review} ml-1`}>{p.pending_review}</span> : null}</td>
                      <td className="px-3 py-2 text-right font-mono font-bold">{money(p.month_billable)}</td>
                      <td className="px-3 py-2 text-right font-mono">{p.month_promotions ? money(p.month_promotions) : "—"}</td>
                      <td className="px-3 py-2">{p.month_invoice ? <span className={`${T.chip} ${STATUS_TONE[p.month_invoice.status]}`}>{p.month_invoice.number}</span> : <span className="text-[#A5ADBA]">Not raised</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
