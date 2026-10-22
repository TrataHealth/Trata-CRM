import React, { useEffect, useState } from "react";
import { Search, Download, BadgeCheck } from "lucide-react";
import api from "../../lib/api";
import { T, toastErr, downloadPdf } from "../ledger/ui";

export function AbhaRecords({ refreshKey }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  useEffect(() => {
    const id = setTimeout(() => api.get("/abdm/records", { params: q ? { q } : {} }).then((r) => setRows(r.data.records)).catch((e) => toastErr(e, "Could not load ABHA list")), 250);
    return () => clearTimeout(id);
  }, [q, refreshKey]);

  return (
    <section className={T.card} data-testid="abha-records">
      <div className={T.head}>
        <span>Patients with ABHA ({rows?.length ?? 0})</span>
        <label className="relative normal-case tracking-normal font-normal">
          <Search className="h-3.5 w-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-[#97A0AF]" />
          <input className={`${T.input} mt-0 pl-7 w-56`} placeholder="Name, ABHA number, address, phone" value={q} onChange={(e) => setQ(e.target.value)} data-testid="abha-records-search" />
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]"><tr>
            {["Patient", "ABHA number", "ABHA address", "Details", "Last verified", ""].map((h) => <th key={h} className="px-3 py-2 text-left">{h}</th>)}
          </tr></thead>
          <tbody>
            {rows && rows.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-[#5E6C84]" data-testid="abha-records-empty">No ABHAs yet — create or verify one above.</td></tr>}
            {(rows || []).map((r) => (
              <tr key={r.id} className="border-t border-[#DFE1E6]" data-testid={`abha-row-${r.id}`}>
                <td className="px-3 py-2"><div className="font-semibold flex items-center gap-1">{r.name || "—"}{r.kyc_verified && <BadgeCheck className="h-3.5 w-3.5 text-[#00875A]" />}</div>
                  {r.patient_phone && <div className="text-[10px] text-[#5E6C84]">Trata app: {r.patient_phone}</div>}</td>
                <td className="px-3 py-2 font-mono text-[#0747A6]">{r.abha_number}</td>
                <td className="px-3 py-2">{r.abha_address || "—"}</td>
                <td className="px-3 py-2 text-[#42526E]">{[r.gender, r.dob, r.mobile_masked].filter(Boolean).join(" · ")}</td>
                <td className="px-3 py-2 text-[#42526E] whitespace-nowrap">{(r.last_verified_at || "").slice(0, 10)}<div className="text-[10px] text-[#5E6C84]">{(r.last_verified_via || "").replace(/_/g, " ")}</div></td>
                <td className="px-3 py-2 text-right">{r.card_available
                  ? <button className={T.btnGhost} onClick={() => downloadPdf(`/abdm/records/${r.id}/card`, `ABHA-${r.abha_number}.pdf`, { format: "pdf" })} data-testid={`abha-row-card-${r.id}`}><Download className="h-3.5 w-3.5" /> Card</button>
                  : <span className="text-[10px] text-[#97A0AF]">Verify again for card</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
