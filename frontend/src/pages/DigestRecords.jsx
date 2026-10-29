import React, { useEffect, useState } from "react";
import { Link, useParams, useSearchParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import api from "../lib/api";
import { HL } from "../components/MorningDigest";

const shift = (iso, n) => { const d = new Date(`${iso}T00:00:00`); d.setDate(d.getDate() + n); return d.toLocaleDateString("en-CA"); };
const fmt = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short", year: "numeric" });

/** The rows behind one morning-summary number for one day (master admin). */
export default function DigestRecords() {
  const { metric } = useParams();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const date = sp.get("date") || shift(new Date().toLocaleDateString("en-CA"), -1);
  const [s, setS] = useState({ loading: true, items: [], err: "" });
  const label = (HL.find(([k]) => k === metric) || [metric, metric])[1];

  useEffect(() => {
    setS((p) => ({ ...p, loading: true }));
    api.get("/admin/digest/records", { params: { metric, date } })
      .then(({ data }) => setS({ loading: false, items: data.items, err: "" }))
      .catch((e) => setS({ loading: false, items: [], err: e?.response?.data?.detail || "Could not load" }));
  }, [metric, date]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="digest-records-page">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-[#5E6C84] hover:text-[#091E42]" data-testid="digest-records-back"><ArrowLeft className="h-4 w-4" /> Dashboard</Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline text-[#974F0C]">Morning summary</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="digest-records-title">{label} <span className="text-[#5E6C84] font-medium">/ {s.items.length}</span></h1>
          <p className="text-sm text-[#5E6C84] mt-1" data-testid="digest-records-date">{fmt(date)}</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setSp({ date: shift(date, -1) })} className="p-2 rounded-md border border-[#DFE1E6] hover:bg-[#F4F5F7]" data-testid="digest-records-prev" aria-label="Previous day"><ChevronLeft className="h-4 w-4" /></button>
          <input type="date" value={date} onChange={(e) => e.target.value && setSp({ date: e.target.value })} className="border border-[#DFE1E6] rounded-md px-2 py-1.5 text-sm" data-testid="digest-records-date-input" />
          <button onClick={() => setSp({ date: shift(date, 1) })} className="p-2 rounded-md border border-[#DFE1E6] hover:bg-[#F4F5F7]" data-testid="digest-records-next" aria-label="Next day"><ChevronRight className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5" data-testid="digest-records-metrics">{HL.map(([k, l]) => (
        <Link key={k} to={`/admin/summary/${k}?date=${date}`} className={`text-xs px-3 py-1.5 rounded-full border ${k === metric ? "bg-[#0052CC] text-white border-[#0052CC]" : "border-[#DFE1E6] text-[#42526E] hover:bg-[#F4F5F7]"}`} data-testid={`digest-records-tab-${k}`}>{l}</Link>))}</div>
      <section className="bg-white border border-[#DFE1E6] rounded-md overflow-x-auto">
        {s.loading ? <div className="p-6 text-xs text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
          : s.err ? <div className="p-4 text-sm text-[#BF2600]" data-testid="digest-records-error">{s.err}</div>
          : s.items.length === 0 ? <div className="p-10 text-center text-sm text-[#5E6C84]" data-testid="digest-records-empty">Nothing on this day.</div>
          : <table className="w-full text-sm min-w-[640px]"><thead className="bg-[#F8F9FA] text-[10px] uppercase tracking-wider text-[#5E6C84]"><tr>
              <th className="text-left px-4 py-2">Time</th><th className="text-left px-4 py-2">Who</th><th className="text-left px-4 py-2">Type</th><th className="text-left px-4 py-2">Status</th></tr></thead>
            <tbody>{s.items.map((r) => (
              <tr key={`${r.table}-${r.id}`} onClick={() => r.patient_user_id && nav(`/admin/patients/${r.patient_user_id}`)}
                  className={`border-t border-[#F4F5F7] ${r.patient_user_id ? "cursor-pointer hover:bg-[#F8F9FA]" : ""}`} data-testid={`digest-record-${r.id}`}>
                <td className="px-4 py-2.5 text-xs text-[#5E6C84] whitespace-nowrap">{new Date(r.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</td>
                <td className="px-4 py-2.5"><div className="font-semibold text-[#091E42]">{r.who || "—"}</div>{r.phone && <div className="text-xs text-[#5E6C84]">{r.phone}</div>}</td>
                <td className="px-4 py-2.5 text-xs text-[#42526E] capitalize">{r.table.replace(/_/g, " ")}{r.what && <span className="text-[#5E6C84]"> · {String(r.what).replace(/_/g, " ")}</span>}</td>
                <td className="px-4 py-2.5"><span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-[#F4F5F7] text-[#42526E]">{r.status || "—"}</span></td>
              </tr>))}</tbody></table>}
      </section>
    </div>
  );
}
