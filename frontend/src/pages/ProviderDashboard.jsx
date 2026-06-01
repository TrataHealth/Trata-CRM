import React, { useEffect, useRef, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { useNavigate } from "react-router-dom";
import {
  Activity as ActivityIcon, Briefcase, CheckCircle2, Clock, Ambulance,
  Sparkles, AlertTriangle, Timer, Truck,
} from "lucide-react";
import { fmtCurrency, relativeTime, statusColor, ACTIVITY_CATEGORIES } from "../lib/constants";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, CartesianGrid,
} from "recharts";

const TYPE_THEME = {
  ambulance: { color: "#FF5630", icon: Ambulance, label: "Ambulance Fleet" },
};

export default function ProviderDashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [feed, setFeed] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef(null);
  const navigate = useNavigate();

  const load = async () => {
    const [d, a] = await Promise.all([
      api.get("/provider/dashboard"),
      api.get("/provider/activities", { params: { limit: 12 } }),
    ]);
    setData(d.data);
    setFeed(a.data.items);
  };

  useEffect(() => {
    load();
    // 30-sec polling so providers see live SOS arrivals
    intervalRef.current = setInterval(async () => {
      setRefreshing(true);
      try { await load(); } finally { setRefreshing(false); }
    }, 30000);
    return () => clearInterval(intervalRef.current);
  }, []);

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]" data-testid="provider-loading">Loading your console…</div>;

  const theme = TYPE_THEME[data.provider_type] || TYPE_THEME.hospital;
  const Icon = theme.icon;
  const k = data.kpis;
  const contact = data.contact;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="provider-dashboard-page">
      {/* Header banner */}
      <div className="rounded-md p-5 lg:p-6 text-white relative overflow-hidden" style={{ background: `linear-gradient(135deg, ${theme.color}, #091E42)` }}>
        <div className="absolute inset-0 bg-grid opacity-10" />
        <div className="relative flex flex-wrap items-start gap-4 justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-white/70">
              <Icon className="h-3.5 w-3.5" /> {theme.label}
            </div>
            <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight mt-1">{contact.name}</h1>
            <div className="text-sm text-white/70 mt-1 truncate">
              {contact.city}{contact.state ? `, ${contact.state}` : ""} · {contact.specialization || "—"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`text-[11px] uppercase tracking-wider font-semibold px-2 py-1 rounded ${contact.is_verified ? "bg-[#79F2C0] text-[#006644]" : "bg-[#FFE380] text-[#974F0C]"}`}>
              {contact.is_verified ? "Verified" : "Pending KYC"}
            </div>
            <div data-testid="live-indicator" className={`flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-semibold px-2 py-1 rounded bg-white/15 ${refreshing ? "animate-pulse" : ""}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-[#79F2C0]" /> Live
            </div>
          </div>
        </div>
      </div>

      {/* KPI strip - common */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4" data-testid="provider-kpis">
        <KPI icon={ActivityIcon} label="Total Activities" value={k.total_activities} accent={theme.color} testid="kpi-total" />
        <KPI icon={Clock} label="Active / Open" value={k.active} accent="#FF5630" testid="kpi-active" />
        <KPI icon={CheckCircle2} label="Completed" value={k.completed} accent="#36B37E" testid="kpi-completed" />
        <KPI icon={Briefcase} label="Revenue" value={fmtCurrency(k.revenue)} accent="#FFAB00" testid="kpi-revenue" />
      </div>

      {/* Type-specific extras */}
      <TypeSpecificKpis ptype={data.provider_type} kpis={k} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white border border-[#DFE1E6] rounded-md p-5">
          <div className="overline mb-1">14-Day Activity</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mb-3">Your operations velocity</div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={data.trend_14d}>
              <defs>
                <linearGradient id="provGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={theme.color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={theme.color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#5E6C84" }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: "#5E6C84" }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
              <Area type="monotone" dataKey="activities" stroke={theme.color} strokeWidth={2} fill="url(#provGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Category mix */}
        <div className="bg-white border border-[#DFE1E6] rounded-md p-5">
          <div className="overline mb-1">Activity Mix</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mb-3">By Category</div>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={Object.entries(data.by_category).filter(([, v]) => v > 0).map(([n, v]) => ({ name: n, value: v }))} dataKey="value" nameKey="name" innerRadius={45} outerRadius={75} strokeWidth={0}>
                {Object.keys(data.by_category).map((cat, i) => {
                  const c = ACTIVITY_CATEGORIES.find((x) => x.value === cat)?.color || "#5E6C84";
                  return <Cell key={i} fill={c} />;
                })}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="space-y-1 mt-2 text-xs">
            {Object.entries(data.by_category).map(([cat, v]) => {
              const label = ACTIVITY_CATEGORIES.find((x) => x.value === cat)?.label || cat;
              const color = ACTIVITY_CATEGORIES.find((x) => x.value === cat)?.color || "#5E6C84";
              if (!v) return null;
              return (
                <div key={cat} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
                    <span className="text-[#42526E]">{label}</span>
                  </div>
                  <span className="font-mono text-[#091E42]">{v}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Recent activity feed */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="provider-activity-feed">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="overline">Live Stream</div>
            <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Latest activities (auto-refreshes every 30s)</div>
          </div>
          <button onClick={() => navigate("/provider/activities")} className="text-xs text-[#0052CC] font-semibold hover:underline">View all →</button>
        </div>
        {feed.length === 0 ? (
          <div className="py-8 text-center text-sm text-[#5E6C84]">No activity yet. New cases/bookings will appear here live.</div>
        ) : (
          <ul className="divide-y divide-[#F1F2F4]">
            {feed.map((a) => {
              const cat = ACTIVITY_CATEGORIES.find((c) => c.value === a.category);
              return (
                <li key={a.id} className="py-2.5 flex items-center gap-3" data-testid={`pa-feed-${a.id}`}>
                  <span className="h-2 w-2 rounded-full shrink-0" style={{ background: statusColor(a.status) }} />
                  <span className="text-[11px] uppercase font-semibold tracking-wider w-28 shrink-0" style={{ color: cat?.color || "#5E6C84" }}>
                    {(cat?.label || a.category).replace(" Bookings", "")}
                  </span>
                  <span className="text-sm text-[#091E42] flex-1 truncate">{a.title}</span>
                  <span className="hidden md:inline text-xs text-[#5E6C84] truncate max-w-[140px]">{a.contact_name}</span>
                  <span className="text-[11px] uppercase tracking-wider font-semibold rounded px-1.5 py-0.5"
                        style={{ background: `${statusColor(a.status)}15`, color: statusColor(a.status) }}>{a.status}</span>
                  <span className="text-[11px] text-[#5E6C84] w-16 text-right tabular-nums">{relativeTime(a.created_at)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {!contact.is_verified && (
        <div className="bg-[#FFFAE6] border border-[#FFC400]/40 rounded-md p-4 flex items-start gap-3" data-testid="kyc-warning">
          <AlertTriangle className="h-5 w-5 text-[#974F0C] shrink-0" />
          <div className="flex-1">
            <div className="font-heading font-bold text-[#974F0C]">Your KYC is pending</div>
            <div className="text-sm text-[#5E6C84] mt-0.5">Complete your KYC to start receiving live bookings and emergency cases. <button onClick={() => navigate("/provider/profile")} className="text-[#0052CC] font-semibold hover:underline ml-1">View profile →</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

function KPI({ icon: Icon, label, value, accent = "#0052CC", testid }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-3 lg:p-5" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="overline truncate">{label}</div>
        <Icon className="h-4 w-4 shrink-0" style={{ color: accent }} strokeWidth={1.75} />
      </div>
      <div className="font-heading text-2xl lg:text-3xl font-bold text-[#091E42] mt-1 tracking-tight truncate">{value ?? "—"}</div>
    </div>
  );
}

function TypeSpecificKpis({ ptype, kpis }) {
  if (ptype === "ambulance") {
    return (
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 lg:gap-4" data-testid="ambulance-kpis">
        <BigStat icon={Truck} label="Fleet size" value={kpis.fleet_size || 0} sub="vehicles" />
        <BigStat icon={Timer} label="Avg response" value={kpis.avg_response_min != null ? `${kpis.avg_response_min}m` : "—"} sub="last 30 days" />
        <BigStat icon={ActivityIcon} label="Live trips" value={kpis.live_trips || 0} sub="dispatched / on the way" accent="#FF5630" />
        <BigStat icon={CheckCircle2} label="Trips completed" value={kpis.trips_completed || 0} sub="all-time" accent="#36B37E" />
      </div>
    );
  }
  return null;
}

function BigStat({ icon: Icon, label, value, sub, accent = "#0052CC" }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-4">
      <div className="flex items-center justify-between">
        <div className="overline">{label}</div>
        <Icon className="h-4 w-4" style={{ color: accent }} />
      </div>
      <div className="font-heading text-3xl font-bold text-[#091E42] mt-2 tracking-tight">{value}</div>
      <div className="text-xs text-[#5E6C84] mt-1">{sub}</div>
    </div>
  );
}
