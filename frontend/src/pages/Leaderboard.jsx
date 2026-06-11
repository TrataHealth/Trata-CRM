import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Trophy, Loader2 } from "lucide-react";
import { Avatar } from "./Contacts";

export default function Leaderboard() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/agent/leaderboard").then((r) => setRows(r.data.items)); }, []);
  if (!rows) return <div className="p-8 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin inline mr-2" /> Loading…</div>;
  const max = Math.max(1, ...rows.map((r) => r.onboarded));
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="leaderboard-page">
      <div>
        <div className="overline">Sales Performance</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1 flex items-center gap-2">
          <Trophy className="h-7 w-7 text-[#FFAB00]" /> Leaderboard
        </h1>
        <p className="text-sm text-[#5E6C84] mt-1">Month-to-date · ranked by providers onboarded onto the Trata Provider App.</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm" data-testid="leaderboard-table">
            <thead className="bg-[#F8F9FA] border-b border-[#DFE1E6] text-left text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">
              <tr>
                <th className="px-3 py-2.5">#</th>
                <th className="px-3 py-2.5">Agent</th>
                <th className="px-3 py-2.5">Role</th>
                <th className="px-3 py-2.5 text-right">Calls</th>
                <th className="px-3 py-2.5 text-right">Meetings</th>
                <th className="px-3 py-2.5 text-right">Onboarded ⭐</th>
                <th className="px-3 py-2.5">Progress</th>
                <th className="px-3 py-2.5 text-right">Total Leads</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const medal = ["🥇", "🥈", "🥉"][i] || "";
                return (
                  <tr key={r.agent_id} className="border-b border-[#F1F2F4]" data-testid={`lb-row-${r.agent_id}`}>
                    <td className="px-3 py-3 font-heading text-lg font-bold text-[#091E42]">{i + 1} {medal}</td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar name={r.name} size={32} />
                        <div className="font-semibold text-[#091E42]">{r.name}</div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-xs uppercase font-semibold text-[#5E6C84]">{r.role}</td>
                    <td className="px-3 py-3 text-right font-mono">{r.calls}</td>
                    <td className="px-3 py-3 text-right font-mono">{r.meetings}</td>
                    <td className="px-3 py-3 text-right font-mono text-lg font-bold text-[#36B37E]">{r.onboarded}</td>
                    <td className="px-3 py-3" style={{ minWidth: 160 }}>
                      <div className="h-2 rounded-full bg-[#F1F2F4] overflow-hidden">
                        <div className="h-full bg-[#36B37E]" style={{ width: `${(r.onboarded / max) * 100}%` }} />
                      </div>
                    </td>
                    <td className="px-3 py-3 text-right text-[#5E6C84]">{r.leads}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
