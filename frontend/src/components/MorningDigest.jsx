import React, { useEffect, useState } from "react";
import { Sunrise, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";

const HL = [["signups", "Patient app sign-ups"], ["doctor_appointments", "Doctor appointments"], ["pathlab_bookings", "Path lab bookings"],
  ["diagnostics_bookings", "Diagnostics bookings"], ["pharmacy_orders", "Pharmacy orders"], ["sos", "SOS cases"]];

function TopList({ title, total, rows }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider font-bold text-[#5E6C84]">{title} · {total} changes</div>
      <ul className="mt-1 space-y-0.5">{rows.length ? rows.map((r) => (
        <li key={r.table} className="text-xs text-[#42526E] flex justify-between gap-2"><span className="capitalize truncate">{r.table}</span><b className="text-[#091E42]">{r.n}</b></li>
      )) : <li className="text-xs text-[#97A0AF]">No activity</li>}</ul>
    </div>
  );
}

/** Master admin morning summary of yesterday's Patient + Provider app activity (written at 8 AM IST). */
export function MorningDigest() {
  const [d, setD] = useState(undefined);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/admin/digest/latest").then((r) => setD(r.data.digest)).catch(() => setD(null)); }, []);
  const gen = async (day) => {
    setBusy(true);
    try { const { data } = await api.post("/admin/digest/generate", { day }); setD(data.digest); } catch (e) { toast.error(e?.response?.data?.detail || "Could not build summary"); }
    setBusy(false);
  };
  if (d === undefined) return null;
  const s = d?.stats;
  return (
    <section className="bg-gradient-to-br from-[#FFFAE6] to-white border border-[#FFE380] rounded-md p-5" data-testid="morning-digest">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1.5 text-[#974F0C]"><Sunrise className="h-3.5 w-3.5" /> Morning summary</div>
          <div className="font-heading font-bold text-[#091E42] mt-1" data-testid="digest-date">
            {s ? `${new Date(`${s.date}T00:00:00`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" })}${d.day === "today" ? " (so far)" : ""}` : "No summary yet"}
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => gen("yesterday")} disabled={busy} className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-md border border-[#DFE1E6] bg-white text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-50" data-testid="digest-yesterday-btn">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} Yesterday
          </button>
          <button onClick={() => gen("today")} disabled={busy} className="px-3 py-1.5 text-xs font-semibold rounded-md border border-[#DFE1E6] bg-white text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-50" data-testid="digest-today-btn">Today so far</button>
        </div>
      </div>
      {!s ? <p className="text-sm text-[#5E6C84] mt-2" data-testid="digest-empty">Your first summary arrives at 8 AM India time. Tap a button to build one now.</p> : <>
        <p className="text-sm text-[#091E42] mt-3 leading-relaxed max-w-3xl" data-testid="digest-text">{d.text || (s.changes || HL.some(([k]) => s.highlights[k]) ? `${s.changes} changes recorded across both apps.` : "No activity was recorded on this day.")}</p>
        <div className="flex flex-wrap gap-2 mt-3">{HL.map(([k, l]) => (
          <span key={k} className="text-xs px-2.5 py-1 rounded-full bg-white border border-[#DFE1E6] text-[#42526E]" data-testid={`digest-hl-${k}`}><b className="text-[#091E42]">{s.highlights[k] ?? 0}</b> {l}</span>))}</div>
        <div className="grid sm:grid-cols-2 gap-5 mt-4">
          <TopList title="Patient app" total={s.patient_total} rows={s.patient_top} />
          <TopList title="Provider app" total={s.provider_total} rows={s.provider_top} />
        </div>
      </>}
    </section>
  );
}
