import React, { useEffect, useState } from "react";
import { BadgeCheck, Fingerprint } from "lucide-react";
import api from "../../lib/api";

/** Batch-loads ABHA info for Supabase patient ids. */
export function useAbhaLookup(ids) {
  const key = (ids || []).filter(Boolean).sort().join(",");
  const [map, setMap] = useState({});
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!key) return;
    api.post("/abdm/patients/lookup", { user_ids: key.split(",") })
      .then((r) => setMap(r.data.abha)).catch(() => {});
  }, [key, tick]);
  return [map, () => setTick((t) => t + 1)];
}

export function AbhaBadge({ abha, compact, testid }) {
  if (!abha) return null;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${abha.kyc_verified ? "bg-[#E3FCEF] border-[#ABF5D1] text-[#006644]" : "bg-[#DEEBFF] border-[#B3D4FF] text-[#0747A6]"}`}
      title={abha.kyc_verified ? "ABHA verified with OTP" : "ABHA captured from QR — not OTP-verified"} data-testid={testid || "abha-badge"}>
      {abha.kyc_verified ? <BadgeCheck className="h-3 w-3" /> : <Fingerprint className="h-3 w-3" />}
      ABHA{!compact && <span className="font-mono">{abha.abha_number}</span>}
    </span>
  );
}
