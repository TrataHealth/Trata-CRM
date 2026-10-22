import React, { useEffect, useState } from "react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import api from "../../lib/api";
import { T, money, toastErr } from "./ui";

const VIEWS = [["weekly", "Weekly"], ["daily", "Day by day"], ["total", "Total"]];
const short = (v) => (v < 1000 ? `₹${v}` : v < 100000 ? `₹${(v / 1000).toFixed(1)}k` : `₹${(v / 100000).toFixed(1)}L`);

const Bucket = ({ label, sub, amount, count, tone = "text-[#091E42]", testid }) => (
  <div className="p-4 border border-[#DFE1E6] rounded-md" data-testid={testid}>
    <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
    <div className={`font-heading text-xl font-black mt-1 ${tone}`}>{money(amount)}</div>
    <div className="text-[10px] text-[#5E6C84] mt-0.5">{count} invoice{count === 1 ? "" : "s"}{sub ? ` · ${sub}` : ""}</div>
  </div>
);

export function CollectionsForecast({ refreshKey }) {
  const [view, setView] = useState("weekly");
  const [f, setF] = useState(null);
  useEffect(() => { api.get("/ledger/forecast", { params: { days: 30 } }).then((r) => setF(r.data)).catch((e) => toastErr(e, "Could not load forecast")); }, [refreshKey]);

  return (
    <section className={`${T.card} p-4`} data-testid="collections-forecast">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">Collections forecast · next 30 days</div>
          {f && <div className="text-[11px] text-[#5E6C84] mt-0.5">From unpaid invoices by due date ({f.from} → {f.to})</div>}
        </div>
        <div className="inline-flex rounded-md border border-[#DFE1E6] overflow-hidden" data-testid="forecast-view-toggle">
          {VIEWS.map(([k, l]) => (
            <button key={k} onClick={() => setView(k)} data-testid={`forecast-view-${k}`}
              className={`px-3 py-1.5 text-xs font-semibold transition-colors ${view === k ? "bg-[#0052CC] text-white" : "bg-white text-[#42526E] hover:bg-[#F4F5F7]"}`}>{l}</button>
          ))}
        </div>
      </div>
      {!f ? <div className="p-6 text-sm text-[#5E6C84]">Loading…</div> : view === "total" ? (
        <div className="grid sm:grid-cols-3 gap-3" data-testid="forecast-total">
          <Bucket label="Expected in 30 days" amount={f.expected_total} count={f.upcoming.count + f.overdue.count} sub="incl. overdue" tone="text-[#0B3D91]" testid="forecast-expected-total" />
          <Bucket label="Due in next 30 days" amount={f.upcoming.amount} count={f.upcoming.count} testid="forecast-upcoming" />
          <Bucket label="Already overdue" amount={f.overdue.amount} count={f.overdue.count} tone="text-[#BF2600]" testid="forecast-overdue-total" />
        </div>
      ) : view === "weekly" ? (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-3" data-testid="forecast-weekly">
          <Bucket label="Overdue now" amount={f.overdue.amount} count={f.overdue.count} tone="text-[#BF2600]" testid="forecast-week-overdue" />
          {f.weekly.map((w, i) => <Bucket key={w.from} label={w.label} sub={`${w.from.slice(5)} – ${w.to.slice(5)}`} amount={w.amount} count={w.count} testid={`forecast-week-${i}`} />)}
        </div>
      ) : (
        <div data-testid="forecast-daily">
          {f.overdue.amount > 0 && <div className="text-[11px] text-[#BF2600] font-semibold mb-1" data-testid="forecast-daily-overdue">+ {money(f.overdue.amount)} already overdue ({f.overdue.count})</div>}
          <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={f.daily} margin={{ left: 8, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#EBECF0" />
              <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} tick={{ fontSize: 10 }} interval={2} />
              <YAxis tickFormatter={short} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => money(v)} labelFormatter={(d) => `Due ${d}`} />
              <Bar dataKey="amount" name="Expected" fill="#0B3D91" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          </div>
        </div>
      )}
    </section>
  );
}
