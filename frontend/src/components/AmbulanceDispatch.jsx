import React, { useState } from "react";
import { Truck, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";

const CLOSED = ["COMPLETED", "CANCELLED", "AUTO_CLOSED", "CLOSED", "REJECTED"];
const NEXT = { assigned: "dispatched", dispatched: "arrived", arrived: "completed" };
const err = (e) => String(e?.response?.data?.detail || "Action failed").replace(/_/g, " ");

export const AssignVehicle = ({ caseRow, fleet, onDone }) => {
  const [vid, setVid] = useState("");
  const [busy, setBusy] = useState(false);
  if (CLOSED.includes(String(caseRow.status || "").toUpperCase())) return null;
  const choices = (fleet || []).filter((v) => String(v.status || "").toLowerCase() === "available" || v.id === caseRow.ambulance_id);
  const assign = async () => {
    setBusy(true);
    try {
      await api.post(`/provider/ambulance/cases/${caseRow.id}/assign`, { ambulance_id: vid });
      toast.success("Vehicle assigned");
      setVid("");
      onDone();
    } catch (e) { toast.error(err(e)); } finally { setBusy(false); }
  };
  return (
    <div className="flex items-center gap-1 mt-1.5" data-testid={`assign-vehicle-${caseRow.id}`}>
      <select value={vid} onChange={(e) => setVid(e.target.value)} className="text-[11px] px-1.5 py-1 border border-[#DFE1E6] rounded bg-white max-w-[150px]" data-testid={`assign-vehicle-select-${caseRow.id}`}>
        <option value="">{choices.length ? "Pick vehicle…" : "No vehicle free"}</option>
        {choices.map((v) => <option key={v.id} value={v.id}>{v.vehicle_number || v.id.slice(0, 6)}</option>)}
      </select>
      <button onClick={assign} disabled={!vid || busy} className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded bg-[#0052CC] text-white disabled:bg-[#A5ADBA]" data-testid={`assign-vehicle-btn-${caseRow.id}`}>
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Truck className="h-3 w-3" />} {caseRow.ambulance_id ? "Reassign" : "Assign vehicle"}
      </button>
    </div>
  );
};

export const AllocationsPanel = ({ allocations, onDone }) => {
  const [busy, setBusy] = useState(null);
  const advance = async (a) => {
    setBusy(a.id);
    try {
      await api.post(`/provider/ambulance/allocations/${a.id}/status`, { status: NEXT[a.status] });
      toast.success(`Marked ${NEXT[a.status]}`);
      onDone();
    } catch (e) { toast.error(err(e)); } finally { setBusy(null); }
  };
  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden lg:col-span-2" data-testid="provider-allocations">
      <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]">Dispatches · shared with patient tracking</div>
      {(!allocations || allocations.length === 0) ? (
        <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="provider-allocations-empty">No vehicles dispatched yet. Assign one from a case above.</div>
      ) : allocations.map((a) => (
        <div key={a.id} className="px-4 py-3 border-b border-[#DFE1E6] last:border-0 flex items-center justify-between gap-3" data-testid={`allocation-${a.id}`}>
          <div className="min-w-0">
            <div className="text-sm font-semibold font-mono text-[#091E42]">{a.vehicle_number || "—"}</div>
            <div className="text-[11px] text-[#5E6C84]">Case {String(a.case_id || "").slice(0, 8)} · {a.allocated_at ? relativeTime(a.allocated_at) : ""}{a.response_time_minutes != null ? ` · reached in ${a.response_time_minutes} min` : ""}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-[#DEEBFF] text-[#0747A6]" data-testid={`allocation-status-${a.id}`}>{a.status}</span>
            {NEXT[a.status] && (
              <button onClick={() => advance(a)} disabled={busy === a.id} className="text-[11px] font-semibold px-2 py-1 rounded border border-[#0052CC] text-[#0052CC] hover:bg-[#DEEBFF]" data-testid={`allocation-advance-${a.id}`}>
                Mark {NEXT[a.status]}
              </button>
            )}
          </div>
        </div>
      ))}
    </section>
  );
};
