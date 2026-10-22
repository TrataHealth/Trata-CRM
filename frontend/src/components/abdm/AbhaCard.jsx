import React from "react";
import { BadgeCheck, Download, ImageDown } from "lucide-react";
import { T, downloadPdf } from "../ledger/ui";

export function AbhaCard({ record, cardReady = true }) {
  if (!record) return null;
  const file = (f) => downloadPdf(`/abdm/records/${record.id}/card`, `ABHA-${record.abha_number}.${f}`, { format: f });
  return (
    <div className="rounded-lg border border-[#B3D4FF] bg-gradient-to-br from-[#F4F8FF] to-white p-4" data-testid="abha-result-card">
      <div className="flex items-start gap-3">
        {record.photo ? <img alt="" src={`data:image/jpeg;base64,${record.photo}`} className="h-16 w-14 object-cover rounded border border-[#DFE1E6]" />
          : <div className="h-16 w-14 rounded bg-[#DEEBFF] grid place-items-center text-[#0747A6] font-bold">{(record.name || "?")[0]}</div>}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 font-heading font-bold text-[#091E42]" data-testid="abha-result-name">
            {record.name || "—"} {record.kyc_verified && <BadgeCheck className="h-4 w-4 text-[#00875A]" />}
          </div>
          <div className="font-mono text-sm font-semibold text-[#0747A6] mt-0.5" data-testid="abha-result-number">{record.abha_number}</div>
          <div className="text-xs text-[#42526E]" data-testid="abha-result-address">{record.abha_address || "No ABHA address yet"}</div>
          <div className="text-[11px] text-[#5E6C84] mt-1">
            {[record.gender, record.dob, record.mobile_masked, [record.district, record.state].filter(Boolean).join(", ")].filter(Boolean).join(" · ")}
          </div>
        </div>
      </div>
      {cardReady && <div className="flex gap-2 mt-3">
        <button className={T.btnGhost} onClick={() => file("png")} data-testid="abha-card-png"><ImageDown className="h-3.5 w-3.5" /> ABHA card (image)</button>
        <button className={T.btnGhost} onClick={() => file("pdf")} data-testid="abha-card-pdf"><Download className="h-3.5 w-3.5" /> ABHA card (PDF)</button>
      </div>}
    </div>
  );
}
