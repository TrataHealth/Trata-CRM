import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useSearchParams } from "react-router-dom";
import { ACTIVITY_CATEGORIES, VERTICAL_ACTIVITY_CATEGORIES, statusColor, relativeTime, fmtCurrency } from "../lib/constants";
import { useAuth } from "../lib/auth";

export default function ProviderActivities() {
  const { user } = useAuth();
  const allowed = VERTICAL_ACTIVITY_CATEGORIES[user?.provider_type];
  const cats = allowed ? ACTIVITY_CATEGORIES.filter((c) => allowed.includes(c.value)) : ACTIVITY_CATEGORIES;
  const [params, setParams] = useSearchParams();
  const category = params.get("category") || "";
  const status = params.get("status") || "";
  const [list, setList] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const { data } = await api.get("/provider/activities", {
        params: { category: category || undefined, status: status || undefined, limit: 100 },
      });
      setList(data.items); setTotal(data.total); setLoading(false);
    })();
  }, [category, status]);

  const setParam = (k, v) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    setParams(p);
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="provider-activities-page">
      <div>
        <div className="overline">My Operations</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
          My Activities <span className="text-[#5E6C84] font-medium">/ {total.toLocaleString()}</span>
        </h1>
        <p className="text-sm text-[#5E6C84] mt-1">Every case, booking and event assigned to your business.</p>
      </div>

      <div className="flex flex-nowrap overflow-x-auto scrollbar-thin gap-1.5 border-b border-[#DFE1E6] pb-3 -mx-4 px-4 sm:mx-0 sm:px-0">
        <Chip label="All" active={!category} onClick={() => setParam("category", "")} testid="pa-cat-all" />
        {cats.map((c) => (
          <Chip key={c.value} label={c.label} color={c.color} active={category === c.value} onClick={() => setParam("category", c.value)} testid={`pa-cat-${c.value}`} />
        ))}
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm" data-testid="provider-activities-table">
            <thead className="bg-[#F8F9FA] border-b border-[#DFE1E6]">
              <tr className="text-left">
                <Th>Category</Th><Th>Title</Th><Th>Contact</Th><Th>Status</Th><Th>City</Th><Th align="right">Amount</Th><Th>When</Th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={7} className="py-10 text-center text-sm text-[#5E6C84]">Loading…</td></tr>}
              {!loading && list.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-sm text-[#5E6C84]">No activities yet. They'll show up here the moment a case/booking is assigned to you.</td></tr>}
              {list.map((a) => {
                const cat = ACTIVITY_CATEGORIES.find((c) => c.value === a.category);
                return (
                  <tr key={a.id} className="border-b border-[#F1F2F4] hover:bg-[#F8F9FA]" data-testid={`pa-row-${a.id}`}>
                    <Td><span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded" style={{ background: `${cat?.color}15`, color: cat?.color }}>{cat?.label || a.category}</span></Td>
                    <Td className="font-medium text-[#091E42]">{a.title}</Td>
                    <Td className="text-[#42526E]">{a.contact_name}</Td>
                    <Td><span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded" style={{ background: `${statusColor(a.status)}15`, color: statusColor(a.status) }}>{a.status}</span></Td>
                    <Td className="text-[#42526E]">{a.city || "—"}</Td>
                    <Td align="right" className="font-mono">{a.amount > 0 ? fmtCurrency(a.amount) : "—"}</Td>
                    <Td className="text-xs text-[#5E6C84]">{relativeTime(a.created_at)}</Td>
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

function Th({ children, align = "left" }) {
  return <th className={`px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84] text-${align}`}>{children}</th>;
}
function Td({ children, align = "left", className = "" }) {
  return <td className={`px-3 py-2.5 text-${align} ${className}`}>{children}</td>;
}
function Chip({ label, color, active, onClick, testid }) {
  return (
    <button onClick={onClick} data-testid={testid}
      className={`px-3 py-1.5 text-sm font-medium rounded-md flex items-center gap-1.5 whitespace-nowrap shrink-0 ${active ? "bg-[#091E42] text-white" : "text-[#42526E] hover:bg-[#F1F2F4]"}`}>
      {color && <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />}
      {label}
    </button>
  );
}
