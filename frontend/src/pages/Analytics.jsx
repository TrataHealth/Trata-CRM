import React, { useEffect, useState } from "react";
import api from "../lib/api";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  AreaChart, Area, PieChart, Pie, Cell,
} from "recharts";
import { fmtCurrency } from "../lib/constants";

export default function Analytics() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/analytics/overview").then((r) => setData(r.data)); }, []);

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]">Loading…</div>;

  const cases = Object.entries(data.cases_by_status).map(([k, v]) => ({ status: k, value: v }));
  const buckets = Object.entries(data.response_time_buckets).map(([k, v]) => ({ range: k, count: v }));
  const totalRev30 = data.revenue_30d.reduce((s, d) => s + d.revenue, 0);
  const palette = ["#0052CC", "#36B37E", "#FFC400", "#FF5630", "#00B8D9", "#6554C0", "#5E6C84"];

  return (
    <div className="p-6 lg:p-8 space-y-6" data-testid="analytics-page">
      <div>
        <div className="overline">Insights & Reports</div>
        <h1 className="font-heading text-3xl font-black tracking-tight text-[#091E42] mt-1">Analytics</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Operational performance across cases, response times, geographies and revenue.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Stat label="Revenue · 30d" value={fmtCurrency(Math.round(totalRev30))} />
        <Stat label="Total Emergency Cases" value={cases.reduce((s, c) => s + c.value, 0)} />
        <Stat label="Top Response Bucket" value={buckets.sort((a, b) => b.count - a.count)[0]?.range + " min"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Cases by status" testid="cases-by-status">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={cases}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis dataKey="status" tick={{ fontSize: 10, fill: "#5E6C84" }} angle={-25} textAnchor="end" height={70} />
              <YAxis tick={{ fontSize: 11, fill: "#5E6C84" }} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
              <Bar dataKey="value" fill="#0052CC" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Response time distribution (mins)" testid="response-time-chart">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={buckets}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis dataKey="range" tick={{ fontSize: 11, fill: "#5E6C84" }} />
              <YAxis tick={{ fontSize: 11, fill: "#5E6C84" }} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} />
              <Bar dataKey="count" fill="#36B37E" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Revenue trend · 30d" testid="revenue-trend">
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.revenue_30d}>
              <defs>
                <linearGradient id="gradRev" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#36B37E" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#36B37E" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F2F4" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#5E6C84" }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: "#5E6C84" }} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #DFE1E6", borderRadius: 6 }} formatter={(v) => fmtCurrency(v)} />
              <Area type="monotone" dataKey="revenue" stroke="#36B37E" strokeWidth={2} fill="url(#gradRev)" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Top cities (by contacts)" testid="top-cities">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 p-2">
            {data.top_cities.map((c, i) => (
              <div key={c.city} className="flex items-center justify-between border-b border-[#F1F2F4] py-2">
                <div className="flex items-center gap-2">
                  <span className="overline w-5 text-right">{i + 1}</span>
                  <span className="text-sm text-[#091E42] font-medium">{c.city}</span>
                </div>
                <span className="font-mono text-sm text-[#091E42]">{c.count}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Card({ title, children, testid }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid={testid}>
      <div className="overline mb-3">{title}</div>
      {children}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-5">
      <div className="overline">{label}</div>
      <div className="mt-2 font-heading text-2xl font-bold text-[#091E42] tracking-tight">{value}</div>
    </div>
  );
}
