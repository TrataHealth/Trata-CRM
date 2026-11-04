import React, { useEffect, useState } from "react";
import { FlaskConical, ScanLine, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";

const SERVICES = [
  { key: "pathology", label: "Pathology", hint: "Blood & sample tests patients can book", Icon: FlaskConical },
  { key: "imaging", label: "Imaging", hint: "X-ray, ultrasound, CT / MRI bookings", Icon: ScanLine },
];

/** Diagnostic-centre service switches — writes service_types on diagnostic_centre_profiles. */
export function ServiceTypesToggle({ userId, onChange }) {
  const [types, setTypes] = useState(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.get(`/admin/directory/providers/${userId}/service-types`)
      .then(({ data }) => setTypes(data.applicable ? data.service_types : null)).catch(() => setTypes(null));
  }, [userId]);

  if (!types) return null;

  const flip = async (key) => {
    const next = types.includes(key) ? types.filter((t) => t !== key) : [...types, key];
    if (!next.length) { toast.error("A diagnostic centre must offer at least one service"); return; }
    setBusy(key);
    try {
      const { data } = await api.put(`/admin/directory/providers/${userId}/service-types`, { service_types: next });
      setTypes(data.service_types);
      onChange?.();
      toast.success(`${SERVICES.find((s) => s.key === key).label} ${data.service_types.includes(key) ? "switched on" : "switched off"}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not update services");
    } finally { setBusy(""); }
  };

  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md p-4" data-testid="service-types-card">
      <div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] mb-3">Services offered</div>
      <div className="grid sm:grid-cols-2 gap-3">
        {SERVICES.map(({ key, label, hint, Icon }) => {
          const on = types.includes(key);
          return (
            <button key={key} type="button" onClick={() => flip(key)} disabled={!!busy} data-testid={`service-toggle-${key}`}
                    aria-pressed={on}
                    className={`flex items-center gap-3 p-3 rounded-md border text-left transition-colors ${on ? "border-[#0052CC] bg-[#DEEBFF]/50" : "border-[#DFE1E6] bg-[#FAFBFC]"}`}>
              <Icon className={`h-5 w-5 ${on ? "text-[#0052CC]" : "text-[#97A0AF]"}`} />
              <span className="flex-1">
                <span className="block text-sm font-semibold text-[#091E42]">{label}</span>
                <span className="block text-xs text-[#5E6C84]">{hint}</span>
              </span>
              {busy === key ? <Loader2 className="h-4 w-4 animate-spin text-[#5E6C84]" /> : (
                <span className={`relative inline-block h-5 w-9 rounded-full transition-colors ${on ? "bg-[#0052CC]" : "bg-[#C1C7D0]"}`} data-testid={`service-state-${key}`} data-on={on}>
                  <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${on ? "translate-x-4" : "translate-x-0.5"}`} />
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
