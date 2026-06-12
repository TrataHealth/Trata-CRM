import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Loader2, Crown, ChevronRight, MapPin, CheckCircle2, XCircle, User } from "lucide-react";
import { relativeTime } from "../lib/constants";
import SlaChip from "../components/SlaChip";

export default function KycAdminQueue() {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.get("/admin/kyc-queue").then((r) => setItems(r.data.items));
  }, []);

  if (items === null) {
    return <div className="p-8 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 inline animate-spin mr-2" /> Loading queue…</div>;
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 max-w-5xl" data-testid="kyc-queue-page">
      <div>
        <div className="overline flex items-center gap-1.5"><Crown className="h-3 w-3 text-[#FFAB00]" /> Master Admin · Final Approvals</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
          KYC Final Approval Queue <span className="text-[#5E6C84] font-medium">/ {items.length}</span>
        </h1>
        <p className="text-sm text-[#5E6C84] mt-1">Providers whose KYC has been reviewed by a sales rep and are awaiting your final verification. SLA target: 24h.</p>
        {items.length > 0 && (() => {
          const now = Date.now();
          const hours = items.map((c) => (now - new Date(c.kyc_agent_completed_at).getTime()) / 3600000);
          const avg = hours.reduce((a, b) => a + b, 0) / hours.length;
          const overdue = hours.filter((h) => h >= 24).length;
          const fmt = (h) => h >= 24 ? `${Math.floor(h / 24)}d ${Math.floor(h % 24)}h` : `${h.toFixed(1)}h`;
          return (
            <div className="mt-3 inline-flex flex-wrap items-center gap-3 px-3 py-2 bg-white border border-[#DFE1E6] rounded-md text-xs" data-testid="kyc-queue-ops">
              <span><b className="text-[#091E42]">Avg time-pending:</b> <span className="text-[#42526E]">{fmt(avg)}</span></span>
              {overdue > 0 && <span className="text-[#BF2600] font-semibold">⚠ {overdue} overdue (&gt;24h)</span>}
            </div>
          );
        })()}
      </div>

      {items.length === 0 ? (
        <div className="bg-white border border-[#DFE1E6] rounded-md p-12 text-center" data-testid="kyc-queue-empty">
          <CheckCircle2 className="h-10 w-10 text-[#36B37E] mx-auto mb-2" />
          <div className="font-semibold text-[#091E42]">Inbox zero</div>
          <p className="text-sm text-[#5E6C84] mt-1">No providers are waiting for your final approval right now.</p>
        </div>
      ) : (
        <div className="space-y-2" data-testid="kyc-queue-list">
          {items.map((c) => (
            <button
              key={c.id}
              onClick={() => navigate(`/contacts/${c.id}`)}
              data-testid={`kyc-queue-row-${c.id}`}
              className="w-full text-left bg-white border border-[#DFE1E6] rounded-md p-4 flex items-center gap-4 hover:border-[#4C9AFF] hover:shadow-sm transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-[#091E42] truncate flex items-center gap-2 flex-wrap">
                  {c.name}
                  <span className="text-xs px-1.5 py-0.5 bg-[#FFFAE6] text-[#974F0C] rounded font-semibold uppercase tracking-wider">Awaiting Final</span>
                  <SlaChip since={c.kyc_agent_completed_at} threshold={24} prefix="Pending" testid={`kyc-sla-${c.id}`} />
                </div>
                <div className="text-xs text-[#5E6C84] truncate mt-0.5">
                  +91 {c.phone}
                  {c.city && <> · <MapPin className="h-3 w-3 inline" /> {c.city}</>}
                  · submitted {relativeTime(c.kyc_agent_completed_at)}
                </div>
                <div className="mt-2 flex items-center gap-3 text-xs">
                  {c.assigned_agent_name && (
                    <span className="inline-flex items-center gap-1 text-[#42526E]">
                      <User className="h-3 w-3" /> Sales rep: <b className="text-[#091E42]">{c.assigned_agent_name}</b>
                    </span>
                  )}
                  <span className="inline-flex items-center gap-1 text-[#006644]">
                    <CheckCircle2 className="h-3 w-3" /> {c.kyc_agent_summary?.approved || 0} approved
                  </span>
                  {(c.kyc_agent_summary?.rejected || 0) > 0 && (
                    <span className="inline-flex items-center gap-1 text-[#BF2600]">
                      <XCircle className="h-3 w-3" /> {c.kyc_agent_summary.rejected} rejected
                    </span>
                  )}
                </div>
              </div>
              <ChevronRight className="h-5 w-5 text-[#5E6C84]" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
