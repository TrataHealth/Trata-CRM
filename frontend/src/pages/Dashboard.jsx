import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useNavigate } from "react-router-dom";
import {
  Users, Activity, Briefcase, AlertTriangle, TrendingUp,
  Stethoscope, Building2, Ambulance, FlaskConical, Cross, User as UserIcon,
} from "lucide-react";
import { fmtCurrency, relativeTime, ACTIVITY_CATEGORIES, statusColor, typeLabel } from "../lib/constants";
import WebhookBridgePanel from "../components/WebhookBridgePanel";
import AdminBridgePanel from "../components/AdminBridgePanel";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, CartesianGrid,
} from "recharts";

const TYPE_ICONS = {
  patient: UserIcon, doctor: Stethoscope, hospital: Building2,
  paramedic: Cross, ambulance_provider: Ambulance, pathologist: FlaskConical,
};

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [feed, setFeed] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      const [s, f] = await Promise.all([
        api.get("/dashboard/stats"),
        api.get("/dashboard/activity-feed", { params: { limit: 15 } }),
      ]);
      setStats(s.data);
      setFeed(f.data.items);
    })();
  }, []);

  if (!stats) return <div className="p-8 text-sm text-[#5E6C84]" data-testid="dashboard-loading">Loading…</div>;

  const userTypes = Object.entries(stats.users.by_type);
  const pipelineData = Object.entries(stats.pipeline).map(([k, v]) => ({ stage: k.replace(/_/g, " "), value: v }));
  const breakdown = Object.entries(stats.activity_breakdown).map(([k, v]) => ({
    name: ACTIVITY_CATEGORIES.find((c) => c.value === k)?.label || k,
    value: v,
    fill: ACTIVITY_CATEGORIES.find((c) => c.value === k)?.color || "#5E6C84",
  }));

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 lg:space-y-8" data-testid="dashboard-page">
      <div className="flex items-end justify-between">
        <div>
          <div className="overline">Operations Overview</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Master Dashboard</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Realtime view of everything happening across the TrataHealth platform.</p>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4" data-testid="kpi-strip">
        <Kpi icon={Users} label="Total Users" value={stats.users.total} sub={`${stats.users.verified} verified · ${stats.users.pending} pending`} />
        <Kpi icon={Activity} label="Active Cases" value={stats.cases.active} sub={`${stats.cases.completed} completed`} accent="#FF5630" />
        <Kpi icon={Briefcase} label="Revenue" value={fmtCurrency(stats.revenue.total)} sub="Lifetime, all activities" accent="#36B37E" />
        <Kpi icon={AlertTriangle} label="Open Tasks" value={stats.tasks.open} sub={`${stats.tasks.overdue} overdue`} accent="#FFC400" />
      </div>

      {/* User type breakdown */}
      <div>
        <div className="overline mb-3">Users by Role</div>
        <div className="grid grid-cols-3 sm:grid-cols-3 md:grid-cols-6 gap-2 lg:gap-3" data-testid="user-type-grid">
          {userTypes.map(([t, n]) => {
            const Icon = TYPE_ICONS[t] || UserIcon;
            return (
              <button
                key={t}
                onClick={() => navigate(`/contacts?type=${t}`)}
                data-testid={`usertype-card-${t}`}
                className="text-left bg-white border border-[#DFE1E6] rounded-md p-3 lg:p-4 hover:border-[#0052CC] hover:shadow-sm transition-all"
              >
                <Icon className="h-5 w-5 text-[#0052CC]" strokeWidth={1.75} />
                <div className="mt-2 lg:mt-3 font-heading text-xl lg:text-2xl font-bold text-[#091E42]">{n}</div>
                <div className="text-[10px] lg:text-xs text-[#5E6C84] uppercase tracking-wider font-semibold mt-0.5 truncate">{typeLabel(t)}s</div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Growth chart */}
        <div className="lg:col-span-2 bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="growth-chart">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="overline">14-Day Activity & Growth</div>
              <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Platform Velocity</div>
            </div>
            <TrendingUp className="h-4 w-4 text-[#36B37E]" />
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={stats.growth_14d}>
              <defs>
                <linearGradient id="grad1" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#0052CC" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#0052CC" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="grad2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#36B37E" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#36B37E" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#5E6C84" }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: "#5E6C84" }} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
              <Area type="monotone" dataKey="activities" stroke="#0052CC" strokeWidth={2} fill="url(#grad1)" />
              <Area type="monotone" dataKey="new_contacts" stroke="#36B37E" strokeWidth={2} fill="url(#grad2)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Activity Breakdown donut */}
        <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="activity-breakdown">
          <div className="overline">Activity Mix</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1 mb-3">By Category</div>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={breakdown} dataKey="value" nameKey="name" innerRadius={45} outerRadius={75} strokeWidth={0}>
                {breakdown.map((e, i) => <Cell key={i} fill={e.fill} />)}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="space-y-1.5 mt-2 text-xs">
            {breakdown.map((b) => (
              <div key={b.name} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-sm" style={{ background: b.fill }} />
                  <span className="text-[#42526E]">{b.name}</span>
                </div>
                <span className="font-mono text-[#091E42]">{b.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Pipeline */}
        <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="pipeline-snapshot">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="overline">Provider Pipeline</div>
              <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Acquisition Funnel</div>
            </div>
            <button onClick={() => navigate("/pipeline")} className="text-xs text-[#0052CC] font-semibold hover:underline">View →</button>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={pipelineData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis type="number" tick={{ fontSize: 11, fill: "#5E6C84" }} />
              <YAxis dataKey="stage" type="category" tick={{ fontSize: 11, fill: "#42526E" }} width={100} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
              <Bar dataKey="value" fill="#0052CC" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Activity feed */}
        <div className="lg:col-span-2 bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="activity-feed">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="overline">Live Activity</div>
              <div className="font-heading text-lg font-bold text-[#091E42] mt-1">What's happening now</div>
            </div>
            <button onClick={() => navigate("/activities")} className="text-xs text-[#0052CC] font-semibold hover:underline">All activities →</button>
          </div>
          <ul className="divide-y divide-[#F1F2F4]">
            {feed.map((a) => (
              <li
                key={a.id}
                onClick={() => navigate(`/contacts/${a.contact_id}`)}
                className="py-2.5 px-1 flex items-center gap-3 hover:bg-[#F8F9FA] rounded-sm cursor-pointer"
                data-testid={`activity-feed-item-${a.id}`}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: statusColor(a.status) }} />
                <span className="text-xs uppercase font-semibold tracking-wider text-[#5E6C84] w-32 shrink-0">
                  {(ACTIVITY_CATEGORIES.find((c) => c.value === a.category)?.label || a.category).replace(" ", "·")}
                </span>
                <span className="text-sm text-[#091E42] flex-1 truncate">{a.title}</span>
                <span className="text-xs text-[#5E6C84] hidden md:inline truncate max-w-[140px]">{a.contact_name}</span>
                <span className="text-[11px] text-[#5E6C84] w-16 text-right tabular-nums">{relativeTime(a.created_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Phase 5: Provider App webhook bridge */}
      <WebhookBridgePanel />

      {/* Phase 5b: Admin App two-way bridge */}
      <AdminBridgePanel />
    </div>
  );
}

function Kpi({ icon: Icon, label, value, sub, accent = "#0052CC" }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-3 lg:p-5 hover:shadow-sm transition-shadow" data-testid={`kpi-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <div className="flex items-start justify-between">
        <div className="overline truncate">{label}</div>
        <Icon className="h-4 w-4 shrink-0" style={{ color: accent }} strokeWidth={1.75} />
      </div>
      <div className="font-heading text-2xl lg:text-3xl font-bold text-[#091E42] mt-1 lg:mt-2 tracking-tight truncate">{value}</div>
      <div className="text-[11px] lg:text-xs text-[#5E6C84] mt-1 truncate">{sub}</div>
    </div>
  );
}
