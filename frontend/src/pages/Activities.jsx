import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../lib/api";
import { ACTIVITY_CATEGORIES, statusColor, relativeTime, fmtCurrency } from "../lib/constants";
import { Search } from "lucide-react";

export default function Activities() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") || "";
  const status = params.get("status") || "";
  const q = params.get("q") || "";
  const [list, setList] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetch = async () => {
    setLoading(true);
    const { data } = await api.get("/activities", {
      params: { category: category || undefined, status: status || undefined, q: q || undefined, limit: 100 },
    });
    setList(data.items); setTotal(data.total); setLoading(false);
  };
  useEffect(() => { fetch(); /* eslint-disable-next-line */ }, [category, status, q]);

  const setParam = (k, v) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    setParams(p);
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6" data-testid="activities-page">
      <div>
        <div className="overline">Live Operations</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
          Activities <span className="text-[#5E6C84] font-medium">/ {total.toLocaleString()}</span>
        </h1>
        <p className="text-sm text-[#5E6C84] mt-1">Emergency cases, appointments, bookings and KYC events.</p>
      </div>

      <div className="flex flex-nowrap overflow-x-auto scrollbar-thin gap-1.5 border-b border-[#DFE1E6] pb-3 -mx-4 px-4 sm:mx-0 sm:px-0" data-testid="category-tabs">
        <CategoryChip label="All" active={!category} onClick={() => setParam("category", "")} testid="cat-all" />
        {ACTIVITY_CATEGORIES.map((c) => (
          <CategoryChip
            key={c.value}
            label={c.label}
            color={c.color}
            active={category === c.value}
            onClick={() => setParam("category", c.value)}
            testid={`cat-${c.value}`}
          />
        ))}
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
        <input
          data-testid="activities-search-input"
          placeholder="Search activities…"
          defaultValue={q}
          onChange={(e) => setParam("q", e.target.value)}
          className="pl-9 pr-3 py-2 text-sm bg-white border border-[#DFE1E6] rounded-md w-full focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
        />
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm" data-testid="activities-table">
            <thead className="bg-[#F8F9FA] border-b border-[#DFE1E6]">
              <tr className="text-left">
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Category</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Title</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Contact</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">Status</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">City</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84] text-right">Amount</th>
                <th className="px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84]">When</th>
              </tr>
            </thead>
            <tbody>
              {loading && (<tr><td colSpan={7} className="py-10 text-center text-sm text-[#5E6C84]">Loading…</td></tr>)}
              {!loading && list.length === 0 && (<tr><td colSpan={7} className="py-10 text-center text-sm text-[#5E6C84]">No activities.</td></tr>)}
              {list.map((a) => {
                const cat = ACTIVITY_CATEGORIES.find((x) => x.value === a.category);
                return (
                  <tr
                    key={a.id}
                    onClick={() => a.contact_id && navigate(`/contacts/${a.contact_id}`)}
                    className="border-b border-[#F1F2F4] last:border-0 hover:bg-[#F8F9FA] cursor-pointer"
                    data-testid={`activity-row-${a.id}`}
                  >
                    <td className="px-3 py-2.5">
                      <span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded" style={{ background: `${cat?.color}15`, color: cat?.color }}>
                        {cat?.label || a.category}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-medium text-[#091E42]">{a.title}</td>
                    <td className="px-3 py-2.5 text-[#42526E]">{a.contact_name}</td>
                    <td className="px-3 py-2.5">
                      <span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded" style={{ background: `${statusColor(a.status)}15`, color: statusColor(a.status) }}>
                        {a.status}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-[#42526E]">{a.city || "—"}</td>
                    <td className="px-3 py-2.5 text-right font-mono">{a.amount > 0 ? fmtCurrency(a.amount) : "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-[#5E6C84]">{relativeTime(a.created_at)}</td>
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

function CategoryChip({ label, color, active, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-1.5 whitespace-nowrap shrink-0 ${
        active ? "bg-[#091E42] text-white" : "text-[#42526E] hover:bg-[#F1F2F4]"
      }`}
    >
      {color && <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />}
      {label}
    </button>
  );
}
