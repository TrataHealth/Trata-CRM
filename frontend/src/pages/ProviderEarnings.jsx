import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { fmtCurrency, relativeTime, ACTIVITY_CATEGORIES } from "../lib/constants";
import {
  Wallet, Banknote, Percent, Receipt, Download, CalendarClock, Loader2, CheckCircle2,
} from "lucide-react";

const PERIODS = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "all", label: "All time" },
];

export default function ProviderEarnings() {
  const { user } = useAuth();
  const [period, setPeriod] = useState("30d");
  const [data, setData] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async (silent) => {
      if (!silent) setLoading(true);
      const [e, p] = await Promise.all([
        api.get("/provider/earnings", { params: { period } }),
        api.get("/provider/payouts"),
      ]);
      setData(e.data);
      setPayouts(p.data.items);
      setLoading(false);
    };
    load();
    const onLive = (ev) => { if (ev.detail?.type === "payout") load(true); };
    window.addEventListener("trata:live", onLive);
    return () => window.removeEventListener("trata:live", onLive);
  }, [period]);

  const downloadInvoice = (id) => {
    const token = localStorage.getItem("trata_token");
    // Open invoice in a new tab — backend returns printable HTML
    const url = `${api.defaults.baseURL}/provider/invoice/${id}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.text())
      .then((html) => {
        const w = window.open("", "_blank", "noopener");
        if (w) { w.document.write(html); w.document.close(); }
      });
  };

  if (loading || !data) {
    return <div className="p-8 text-sm text-[#5E6C84]" data-testid="earnings-loading">Loading earnings…</div>;
  }

  const s = data.summary;
  const np = data.next_payout;
  const npDate = new Date(np.scheduled_for);
  const npDateStr = npDate.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });

  const byCat = Object.entries(data.by_category).map(([cat, amt]) => {
    const c = ACTIVITY_CATEGORIES.find((x) => x.value === cat);
    return { cat, label: c?.label || cat, color: c?.color || "#5E6C84", amount: amt };
  }).sort((a, b) => b.amount - a.amount);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="provider-earnings-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline">Money</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Earnings & Payouts</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Every rupee TrataHealth has settled to you — and what's coming next Monday.</p>
        </div>
        <div className="flex bg-[#F1F2F4] rounded-md p-1" data-testid="period-tabs">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              data-testid={`period-${p.value}`}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-xs font-semibold rounded transition-colors ${
                period === p.value ? "bg-white text-[#091E42] shadow-sm" : "text-[#5E6C84] hover:text-[#091E42]"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Hero: Next Payout */}
      <div
        className="rounded-md p-5 lg:p-7 text-white relative overflow-hidden"
        style={{ background: "linear-gradient(135deg, #006644, #091E42)" }}
        data-testid="next-payout-card"
      >
        <div className="absolute inset-0 bg-grid opacity-10" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-white/70">
              <CalendarClock className="h-3.5 w-3.5 text-[#79F2C0]" /> Next Payout
            </div>
            <div className="mt-2 font-heading text-5xl font-black tracking-tight" data-testid="next-payout-amount">
              {fmtCurrency(np.net)}
            </div>
            <div className="text-sm text-white/70 mt-2">
              Lands in your bank on <span className="font-semibold text-white">{npDateStr}</span>
              {" · "}gross {fmtCurrency(np.gross)} − fee {fmtCurrency(np.fee)} ({data.fee_pct}%)
            </div>
          </div>
          <div className="text-right">
            <div className="overline text-white/60">Lifetime net</div>
            <div className="font-heading text-2xl font-bold text-[#79F2C0] mt-1">{fmtCurrency(data.lifetime.net)}</div>
            <div className="text-[11px] text-white/60 mt-1">gross {fmtCurrency(data.lifetime.gross)}</div>
          </div>
        </div>
      </div>

      {/* KPI strip — period window */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4" data-testid="earnings-kpis">
        <Stat icon={Wallet}   label={`Gross · ${period}`} value={fmtCurrency(s.gross)} sub={`${s.transactions} transactions`} accent="#0052CC" testid="kpi-gross" />
        <Stat icon={Percent}  label="Platform fee" value={fmtCurrency(s.fee)} sub={`${data.fee_pct}% commission`} accent="#FF5630" testid="kpi-fee" />
        <Stat icon={Banknote} label="Net earnings" value={fmtCurrency(s.net)} sub="After fees" accent="#36B37E" testid="kpi-net" />
        <Stat icon={Receipt}  label="Past payouts" value={payouts.length} sub="settled to your account" accent="#FFAB00" testid="kpi-payouts" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Daily revenue chart */}
        <div className="lg:col-span-2 bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="revenue-chart">
          <div className="overline">Daily Gross</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1 mb-3">Revenue trend</div>
          <ResponsiveContainer width="100%" height={230}>
            <AreaChart data={data.daily}>
              <defs>
                <linearGradient id="earnGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#36B37E" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#36B37E" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#5E6C84" }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: "#5E6C84" }} tickFormatter={(v) => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} formatter={(v) => fmtCurrency(v)} />
              <Area type="monotone" dataKey="amount" stroke="#36B37E" strokeWidth={2} fill="url(#earnGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Earnings by category */}
        <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="earnings-by-category">
          <div className="overline">Revenue Mix</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1 mb-3">By Category</div>
          {byCat.length === 0 ? (
            <div className="py-6 text-center text-sm text-[#5E6C84]">No revenue in this period yet.</div>
          ) : (
            <ul className="space-y-3">
              {byCat.map((b) => {
                const pct = s.gross > 0 ? Math.round((b.amount / s.gross) * 100) : 0;
                return (
                  <li key={b.cat}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-[#091E42] font-medium truncate flex items-center gap-2">
                        <span className="h-2 w-2 rounded-sm shrink-0" style={{ background: b.color }} />
                        {b.label}
                      </span>
                      <span className="font-mono text-[#091E42]">{fmtCurrency(b.amount)}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-[#F1F2F4] overflow-hidden">
                      <div className="h-full" style={{ width: `${pct}%`, background: b.color }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* Payout history table */}
      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="payouts-table-wrap">
        <div className="p-4 lg:p-5 border-b border-[#DFE1E6]">
          <div className="overline">Settled to your account</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Payout history</div>
        </div>
        {payouts.length === 0 ? (
          <div className="p-10 text-center text-sm text-[#5E6C84]">No payouts yet. Once your completed activities accumulate, weekly payouts will appear here.</div>
        ) : (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-sm" data-testid="payouts-table">
              <thead className="bg-[#F8F9FA] border-b border-[#DFE1E6]">
                <tr className="text-left">
                  <Th>Period</Th>
                  <Th align="right">Gross</Th>
                  <Th align="right">Fee</Th>
                  <Th align="right">Net</Th>
                  <Th>Status</Th>
                  <Th>Reference</Th>
                  <Th>Paid on</Th>
                  <Th align="right">Invoice</Th>
                </tr>
              </thead>
              <tbody>
                {payouts.map((p) => (
                  <tr key={p.id} className="border-b border-[#F1F2F4] last:border-0 hover:bg-[#F8F9FA]" data-testid={`payout-row-${p.id}`}>
                    <Td className="font-medium text-[#091E42]">
                      <div>{p.period_start.slice(0, 10)} → {p.period_end.slice(0, 10)}</div>
                      <div className="text-[11px] text-[#5E6C84]">{p.activity_count} transactions</div>
                    </Td>
                    <Td align="right" className="font-mono text-[#091E42]">{fmtCurrency(p.gross)}</Td>
                    <Td align="right" className="font-mono text-[#FF5630]">−{fmtCurrency(p.fee)}</Td>
                    <Td align="right" className="font-mono font-semibold text-[#091E42]">{fmtCurrency(p.net)}</Td>
                    <Td>
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded bg-[#E3FCEF] text-[#006644]">
                        <CheckCircle2 className="h-3 w-3" /> {p.status}
                      </span>
                    </Td>
                    <Td className="font-mono text-xs text-[#5E6C84]">{p.utr}</Td>
                    <Td className="text-xs text-[#5E6C84]">{relativeTime(p.paid_at)}</Td>
                    <Td align="right">
                      <button
                        data-testid={`invoice-${p.id}`}
                        onClick={() => downloadInvoice(p.id)}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold text-[#0052CC] hover:bg-[#DEEBFF] rounded"
                      >
                        <Download className="h-3.5 w-3.5" /> {p.invoice_number}
                      </button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="text-[11px] text-[#5E6C84]">
        Payouts are settled to your registered bank account every Monday, covering the previous week's completed activities. Platform fee is {data.fee_pct}% of gross.
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value, sub, accent, testid }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-3 lg:p-5" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="overline truncate">{label}</div>
        <Icon className="h-4 w-4 shrink-0" style={{ color: accent }} strokeWidth={1.75} />
      </div>
      <div className="font-heading text-2xl lg:text-3xl font-bold text-[#091E42] mt-1 tracking-tight truncate">{value}</div>
      <div className="text-[11px] lg:text-xs text-[#5E6C84] mt-1 truncate">{sub}</div>
    </div>
  );
}

function Th({ children, align = "left" }) {
  return <th className={`px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84] text-${align}`}>{children}</th>;
}
function Td({ children, align = "left", className = "" }) {
  return <td className={`px-3 py-2.5 text-${align} ${className}`}>{children}</td>;
}
