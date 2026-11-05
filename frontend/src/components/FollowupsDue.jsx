import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarClock } from "lucide-react";
import api from "../lib/api";
import { stageLabel, typeLabel } from "../lib/constants";

/** Phase E follow-up queue — open crm_sales_leads whose next follow-up date has passed. */
export function FollowupsDue() {
  const nav = useNavigate();
  const [items, setItems] = useState(null);
  useEffect(() => { api.get("/sales/followups-due").then(({ data }) => setItems(data.items)).catch(() => setItems([])); }, []);
  if (!items) return null;
  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md p-4" data-testid="followups-due-card">
      <div className="flex items-center gap-2 mb-3">
        <CalendarClock className="h-4 w-4 text-[#FF8B00]" />
        <h3 className="text-sm font-semibold text-[#091E42]">Follow-ups due</h3>
        <span className="ml-auto text-xs font-bold text-[#FF8B00]" data-testid="followups-due-count">{items.length}</span>
      </div>
      {!items.length ? <div className="text-sm text-[#97A0AF]">No follow-ups overdue.</div> : (
        <ul className="divide-y divide-[#F4F5F7]">
          {items.slice(0, 8).map((l) => (
            <li key={l.id} onClick={() => nav(`/contacts/${l.id}`)} className="py-2 flex items-center gap-3 cursor-pointer hover:bg-[#F8F9FA] -mx-2 px-2 rounded" data-testid={`followup-${l.id}`}>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[#091E42] truncate">{l.name}</div>
                <div className="text-xs text-[#5E6C84] truncate">{typeLabel(l.type)} · {stageLabel(l.pipeline_stage)}{l.assigned_agent_name ? ` · ${l.assigned_agent_name}` : ""}</div>
              </div>
              <span className={`text-[11px] font-bold ${l.overdue_days > 2 ? "text-[#DE350B]" : "text-[#FF8B00]"}`}>{l.overdue_days ? `${l.overdue_days}d overdue` : "Due today"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
