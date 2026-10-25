import React, { useEffect, useState } from "react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import api from "../../lib/api";
import { inr, errMsg } from "./ui";

const Kpi = ({ label, value, sub, testid }) => (
  <div className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid={testid}>
    <div className="text-[10px] font-bold uppercase tracking-wider text-[#5E6C84]">{label}</div>
    <div className="font-heading text-2xl font-black text-[#091E42] mt-1">{value}</div>{sub && <div className="text-xs text-[#5E6C84]">{sub}</div>}
  </div>
);

export default function SalesTab({ store, showStore }) {
  const [days, setDays] = useState(30); const [d, setD] = useState(null);
  useEffect(() => { setD(null); api.get("/pharmacy-console/sales", { params: { store, days } }).then((r) => setD(r.data)).catch((e) => errMsg(e)); }, [store, days]);
  return (
    <div className="space-y-4" data-testid="sales-tab">
      <div className="flex gap-1.5">{[7, 30, 90].map((n) => <button key={n} onClick={() => setDays(n)} className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${days === n ? "bg-[#0052CC] text-white border-[#0052CC]" : "border-[#DFE1E6] text-[#42526E]"}`} data-testid={`sales-days-${n}`}>{n} days</button>)}</div>
      {!d ? <div className="text-sm text-[#5E6C84]">Loading sales…</div> : <>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Kpi label="Sales" value={inr(d.revenue)} sub={`last ${d.days} days`} testid="sales-revenue" />
          <Kpi label="Fulfilled" value={d.fulfilled} sub={`of ${d.total_requests} requests`} testid="sales-fulfilled" />
          <Kpi label="Avg bill" value={inr(d.avg_order_value)} testid="sales-avg" />
          <Kpi label="Open now" value={d.open_orders} sub={`${d.rejection_rate}% rejected`} testid="sales-open" />
        </div>
        <div className="bg-white border border-[#DFE1E6] rounded-lg p-4"><div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] mb-2">Daily sales</div>
          <div className="h-56" data-testid="sales-chart"><ResponsiveContainer><AreaChart data={d.series}><CartesianGrid strokeDasharray="3 3" stroke="#F4F5F7" />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => v.slice(5)} /><YAxis tick={{ fontSize: 10 }} width={50} />
            <Tooltip formatter={(v, n) => (n === "revenue" ? inr(v) : v)} /><Area type="monotone" dataKey="revenue" stroke="#0052CC" fill="#DEEBFF" /></AreaChart></ResponsiveContainer></div></div>
        <div className="grid lg:grid-cols-2 gap-3">
          <div className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid="sales-top-medicines"><div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] mb-2">Top medicines</div>
            {d.top_medicines.length ? d.top_medicines.map((m) => <div key={m.name} className="flex justify-between text-sm py-1 border-b border-[#F4F5F7] last:border-0"><span>{m.name}</span><b>{m.count}</b></div>) : <div className="text-sm text-[#5E6C84]">No fulfilled orders yet.</div>}</div>
          {showStore && <div className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid="sales-by-store"><div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] mb-2">By store</div>
            {d.by_store.map((s) => <div key={s.store_id} className="flex justify-between text-sm py-1 border-b border-[#F4F5F7] last:border-0"><span>{s.store_name}</span><span><b>{inr(s.revenue)}</b> · {s.orders}</span></div>)}</div>}
        </div>
      </>}
    </div>
  );
}
