import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Loader2, FilePlus2, BellRing } from "lucide-react";
import { toast } from "sonner";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from "recharts";
import api from "../lib/api";
import { T, money, toastErr } from "../components/ledger/ui";
import { InvoiceList } from "../components/ledger/InvoiceList";

const Kpi = ({ label, value, tone = "text-[#091E42]", testid }) => (
  <div className={`${T.card} p-4`} data-testid={testid}>
    <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
    <div className={`font-heading text-2xl font-black mt-1 ${tone}`}>{value}</div>
  </div>
);

const inr = (v) => (v < 1000 ? `₹${v}` : v < 100000 ? `₹${(v / 1000).toFixed(1)}k` : `₹${(v / 100000).toFixed(1)}L`);

export default function AdminRevenue() {
  const [data, setData] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [busy, setBusy] = useState("");
  const load = useCallback(async () => {
    try {
      const [r, d] = await Promise.all([api.get("/ledger/revenue"), api.get("/ledger/invoices", { params: { status: "draft" } })]);
      setData(r.data); setDrafts(d.data.items);
    } catch (e) { toastErr(e, "Could not load revenue"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (path, label) => {
    setBusy(path);
    try {
      const { data: res } = await api.post(`/ledger/run/${path}`);
      toast.success(path === "monthly-drafts" ? `${res.created} draft invoice(s) raised for ${res.month}${res.error ? ` · ${res.error}` : ""}` : `${res.reminded} overdue reminder(s) sent`);
      load();
    } catch (e) { toastErr(e, `${label} failed`); } finally { setBusy(""); }
  };

  if (!data) return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading revenue…</div>;
  const t = data.totals;
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="admin-revenue">
      <Link to="/admin/ledger" className="text-xs text-[#0052CC] inline-flex items-center gap-1"><ArrowLeft className="h-3 w-3" /> Provider ledger</Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42]">Revenue</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Trata fees, GST and collections from issued provider invoices (drafts and void excluded). Drafts auto-raise on the 1st; overdue reminders go out every 3 days.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button className={T.btnGhost} disabled={!!busy} onClick={() => run("monthly-drafts", "Raise drafts")} data-testid="revenue-run-drafts">
            {busy === "monthly-drafts" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FilePlus2 className="h-3.5 w-3.5" />} Raise last month's drafts now
          </button>
          <button className={T.btnGhost} disabled={!!busy} onClick={() => run("reminders", "Reminders")} data-testid="revenue-run-reminders">
            {busy === "reminders" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BellRing className="h-3.5 w-3.5" />} Send due reminders now
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Kpi label="Trata fees (taxable)" value={money(t.taxable)} testid="revenue-kpi-fees" />
        <Kpi label="GST collected" value={money(t.gst)} testid="revenue-kpi-gst" />
        <Kpi label="Collected" value={money(t.paid)} tone="text-[#006644]" testid="revenue-kpi-paid" />
        <Kpi label="Unpaid" value={money(t.unpaid)} tone="text-[#974F0C]" testid="revenue-kpi-unpaid" />
        <Kpi label="Overdue" value={money(t.overdue)} tone="text-[#BF2600]" testid="revenue-kpi-overdue" />
      </div>

      <section className={`${T.card} p-4`} data-testid="revenue-chart">
        <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold mb-2">Month by month</div>
        {data.months.length === 0 ? <div className="p-6 text-center text-sm text-[#5E6C84]">No issued invoices yet.</div> : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.months} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#EBECF0" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={inr} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => money(v)} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="service_fee" stackId="f" name="Service fees" fill="#0B3D91" />
                <Bar dataKey="promotion_fee" stackId="f" name="Promotion fees" fill="#00B8A9" />
                <Bar dataKey="gst" stackId="f" name="GST" fill="#4C9AFF" />
                <Bar dataKey="unpaid" name="Unpaid" fill="#FF991F" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      <div className="grid lg:grid-cols-5 gap-4">
        <section className={`${T.card} lg:col-span-3 overflow-x-auto`}>
          <div className={T.head}>Monthly breakdown</div>
          <table className="min-w-full text-xs" data-testid="revenue-table">
            <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]"><tr>
              {["Month", "Invoices", "Fees", "CGST", "SGST", "IGST", "Invoiced", "Paid", "Unpaid"].map((h, i) => <th key={h} className={`px-3 py-2 ${i ? "text-right" : "text-left"}`}>{h}</th>)}
            </tr></thead>
            <tbody>{data.months.length === 0 && <tr><td colSpan={9} className="px-3 py-6 text-center text-[#5E6C84]" data-testid="revenue-table-empty">No issued invoices yet.</td></tr>}
              {[...data.months].reverse().map((m) => (
              <tr key={m.month} className="border-t border-[#DFE1E6]" data-testid={`revenue-row-${m.month}`}>
                <td className="px-3 py-2 font-semibold">{m.month}</td><td className="px-3 py-2 text-right">{m.invoices}</td>
                {["taxable", "cgst", "sgst", "igst", "invoiced", "paid", "unpaid"].map((k) => <td key={k} className={`px-3 py-2 text-right font-mono ${k === "unpaid" && m.unpaid ? "text-[#974F0C] font-bold" : ""}`}>{money(m[k])}</td>)}
              </tr>
            ))}</tbody>
          </table>
        </section>
        <section className={`${T.card} lg:col-span-2`} data-testid="revenue-outstanding">
          <div className={T.head}>Outstanding by provider</div>
          {data.outstanding.length === 0 ? <div className="p-6 text-center text-sm text-[#5E6C84]">Nothing outstanding.</div> : data.outstanding.map((o) => (
            <Link key={o.provider_user_id} to={`/admin/ledger/${o.provider_user_id}`} className="px-4 py-2 border-t border-[#F4F5F7] flex items-center justify-between gap-3 hover:bg-[#F8F9FA]" data-testid={`outstanding-${o.provider_user_id}`}>
              <div className="min-w-0"><div className="text-xs font-semibold truncate">{o.provider_name}</div>
                <div className="text-[10px] text-[#5E6C84]">{o.invoices} invoice{o.invoices === 1 ? "" : "s"} · oldest due {o.oldest_due || "—"}</div></div>
              <div className="text-right"><div className="font-mono text-xs font-bold">{money(o.unpaid)}</div>
                {o.overdue > 0 && <div className="text-[10px] text-[#BF2600] font-semibold">{money(o.overdue)} overdue</div>}</div>
            </Link>
          ))}
        </section>
      </div>

      <section className={T.card} data-testid="revenue-drafts">
        <div className={T.head}>Draft invoices awaiting review ({drafts.length})</div>
        <InvoiceList invoices={drafts} admin onChanged={load} />
      </section>
    </div>
  );
}
