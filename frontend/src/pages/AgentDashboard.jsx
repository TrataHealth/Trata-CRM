import React, { useEffect, useState } from "react";
import { FollowupsDue } from "../components/FollowupsDue";
import api from "../lib/api";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { PIPELINE_STAGES, relativeTime } from "../lib/constants";
import { Avatar } from "./Contacts";
import {
  Activity, Clock, AlertTriangle, CheckCircle2, Phone, Plus, Briefcase, MapPin,
  ListChecks, Loader2, Sparkles, X,
} from "lucide-react";
import QuickLogModal from "../components/QuickLogModal";
import { renderInsightsMarkdown, RANGE_OPTIONS } from "../lib/insights";

const STAGE_COLOR = Object.fromEntries(PIPELINE_STAGES.map((s) => [s.value, s.color]));
const STAGE_LABEL = Object.fromEntries(PIPELINE_STAGES.map((s) => [s.value, s.label]));

const PIN = (color) =>
  L.divIcon({
    className: "",
    html: `<div style="background:${color};width:18px;height:18px;border-radius:50%;border:3px solid white;box-shadow:0 2px 6px rgba(9,30,66,.3)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return;
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 12 });
  }, [points, map]);
  return null;
}

export default function AgentDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [dash, setDash] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [quickLogLead, setQuickLogLead] = useState(null);
  const [quickLogOpen, setQuickLogOpen] = useState(false);
  const [range, setRange] = useState("7d");
  const [statsLoading, setStatsLoading] = useState(false);
  const [ai, setAi] = useState({ open: false, loading: false, markdown: "", error: "" });

  const load = async (r = range) => {
    setStatsLoading(true);
    try {
      const [d, m] = await Promise.all([
        api.get("/agent/dashboard", { params: { range: r } }),
        api.get("/agent/leads/map"),
      ]);
      setDash(d.data);
      setMapData(m.data);
    } finally {
      setStatsLoading(false);
    }
  };
  useEffect(() => { load(range); /* eslint-disable-next-line */ }, [range]);

  const generateInsights = async () => {
    setAi({ open: true, loading: true, markdown: "", error: "" });
    try {
      const { data } = await api.post("/agent/ai-insights", { range });
      setAi({ open: true, loading: false, markdown: data.markdown || "", error: "" });
    } catch (e) {
      setAi({ open: true, loading: false, markdown: "", error: e?.response?.data?.detail || "Could not generate insights" });
    }
  };

  if (!dash) return <div className="p-8 text-sm text-[#5E6C84]" data-testid="agent-dashboard-loading">Loading your day…</div>;

  const k = dash.kpis;
  const openQuickLog = (lead = null) => { setQuickLogLead(lead); setQuickLogOpen(true); };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 pb-24" data-testid="agent-dashboard-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline">Sales Agent · {user?.name?.split(" ")[0]}</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">My Day</h1>
          <p className="text-sm text-[#5E6C84] mt-1">{dash.range?.label || "Onboarding healthcare providers onto the Trata app. Plan your route, log every touch."}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Range filter pill */}
          <div className="inline-flex items-center bg-white border border-[#DFE1E6] rounded-full p-0.5 shadow-sm" data-testid="agent-range-filter">
            {RANGE_OPTIONS.map((opt) => {
              const selected = range === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => setRange(opt.value)}
                  disabled={statsLoading}
                  data-testid={`agent-range-${opt.value}`}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-full transition-colors ${
                    selected ? "bg-[#0052CC] text-white" : "text-[#42526E] hover:text-[#091E42] hover:bg-[#F4F5F7]"
                  } disabled:opacity-60`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
          {/* AI insights button */}
          <button
            onClick={generateInsights}
            disabled={ai.loading}
            data-testid="agent-ai-insights-btn"
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-full text-white bg-gradient-to-r from-[#6554C0] to-[#403294] hover:opacity-95 disabled:opacity-60 shadow-sm"
          >
            {ai.loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {ai.loading ? "Thinking…" : "AI insight"}
          </button>
          <button
            onClick={() => openQuickLog()}
            data-testid="quick-log-fab-desktop"
            className="hidden sm:flex items-center gap-2 px-4 py-2 bg-[#0052CC] hover:bg-[#0747A6] text-white rounded-md text-sm font-semibold shadow-sm">
            <Plus className="h-4 w-4" /> Log Activity
          </button>
        </div>
      </div>

      {/* AI insights drawer */}
      {ai.open && (
        <div className="bg-white border border-[#6554C0]/30 rounded-md shadow-sm overflow-hidden" data-testid="agent-ai-insights-panel">
          <div className="px-5 py-3 border-b border-[#DFE1E6] flex items-center justify-between bg-[#EAE6FF]">
            <div className="flex items-center gap-2 text-[#403294] font-heading font-bold text-sm">
              <Sparkles className="h-4 w-4" /> AI coach — {dash.range?.label || range}
            </div>
            <button onClick={() => setAi({ open: false, loading: false, markdown: "", error: "" })} className="text-[#5E6C84] hover:text-[#091E42]" data-testid="agent-ai-insights-close" aria-label="Close insight panel">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="px-5 py-4 text-sm text-[#091E42] leading-relaxed">
            {ai.loading && (
              <div className="flex items-center gap-2 text-[#5E6C84]" data-testid="agent-ai-insights-loading">
                <Loader2 className="h-4 w-4 animate-spin text-[#6554C0]" /> Coaching insights for {dash.range?.label || range}…
              </div>
            )}
            {ai.error && <div className="text-[#BF2600]" data-testid="agent-ai-insights-error">{ai.error}</div>}
            {!ai.loading && !ai.error && ai.markdown && (
              <div data-testid="agent-ai-insights-content">{renderInsightsMarkdown(ai.markdown)}</div>
            )}
          </div>
        </div>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 lg:gap-4" data-testid="agent-kpis">
        <KPI icon={Briefcase} label="My Leads" value={k.total_leads} sub="assigned to you" accent="#0052CC" testid="kpi-leads" />
        <KPI icon={Activity} label="Today's Touches" value={k.today_activities} sub="activities logged today" accent="#36B37E" testid="kpi-today" />
        <KPI icon={CheckCircle2} label={`Onboarded · ${dash.range?.label?.replace("Last ", "") || "7 days"}`} value={k.onboarded_in_window ?? k.onboarded_this_week} sub="signed up on app" accent="#FFAB00" testid="kpi-onboarded" />
        <KPI icon={AlertTriangle} label="Stale Leads" value={k.stale_leads} sub="no touch in 7+ days" accent="#FF5630" testid="kpi-stale" />
        <KPI icon={ListChecks} label="Pending Tasks" value={dash.today_tasks.length} sub="due today / overdue" accent="#6554C0" testid="kpi-tasks" />
      </div>

      <FollowupsDue />

      {/* Funnel by stage */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="agent-funnel">
        <div className="overline mb-2">My Pipeline</div>
        <div className="font-heading text-lg font-bold text-[#091E42] mb-3">Sales funnel</div>
        <div className="grid grid-cols-4 lg:grid-cols-8 gap-2">
          {PIPELINE_STAGES.map((s) => (
            <button
              key={s.value}
              onClick={() => navigate(`/contacts?stage=${s.value}`)}
              data-testid={`funnel-stage-${s.value}`}
              className="text-left rounded-md p-3 hover:shadow-sm transition-all border"
              style={{ borderColor: `${s.color}30`, background: `${s.color}08` }}
            >
              <div className="overline" style={{ color: s.color }}>{s.label}</div>
              <div className="font-heading text-2xl font-bold mt-1 text-[#091E42]">{dash.by_stage[s.value] || 0}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Map + Today tasks side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="agent-map">
          <div className="p-4 border-b border-[#DFE1E6]">
            <div className="overline flex items-center gap-1.5"><MapPin className="h-3 w-3" /> Today's Field Plan</div>
            <div className="font-heading text-lg font-bold text-[#091E42] mt-1">My leads on the map</div>
          </div>
          <div style={{ height: 380 }}>
            {!mapData ? (
              <div className="h-full flex items-center justify-center text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading map…</div>
            ) : !mapData.center ? (
              <div className="h-full flex items-center justify-center text-sm text-[#5E6C84]">No leads with location yet.</div>
            ) : (
              <MapContainer center={[mapData.center.lat, mapData.center.lng]} zoom={5} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {mapData.leads.map((l) => (
                  <Marker key={l.id} position={[l.lat, l.lng]} icon={PIN(STAGE_COLOR[l.pipeline_stage] || "#5E6C84")}>
                    <Popup>
                      <b>{l.name}</b><br />
                      {l.type} · {l.city}<br />
                      Stage: <b style={{ color: STAGE_COLOR[l.pipeline_stage] }}>{STAGE_LABEL[l.pipeline_stage]}</b><br />
                      <a href={`/contacts/${l.id}`} style={{ color: "#0052CC", fontWeight: 600 }}>Open lead →</a>
                    </Popup>
                  </Marker>
                ))}
                <FitBounds points={mapData.leads.map((l) => [l.lat, l.lng])} />
              </MapContainer>
            )}
          </div>
          <div className="px-4 py-2 border-t border-[#DFE1E6] flex flex-wrap items-center gap-3 text-[11px]">
            {PIPELINE_STAGES.map((s) => (
              <div key={s.value} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                <span className="text-[#42526E]">{s.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="agent-today-tasks">
          <div className="overline">Today's Tasks</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1 mb-3">{dash.today_tasks.length} pending</div>
          {dash.today_tasks.length === 0 ? (
            <div className="py-8 text-center text-sm text-[#5E6C84]">All clear. Log an activity to schedule next touch.</div>
          ) : (
            <ul className="space-y-2">
              {dash.today_tasks.slice(0, 8).map((t) => (
                <li key={t.id} className="p-2.5 border border-[#DFE1E6] rounded hover:border-[#0052CC] transition-colors" data-testid={`task-${t.id}`}>
                  <div className="text-sm font-semibold text-[#091E42]">{t.title}</div>
                  <div className="text-[11px] text-[#5E6C84] mt-1">due {relativeTime(t.due_date)}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Hot leads + Stale leads */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <LeadsCard title="🔥 Hot leads" subtitle="Most recent touchpoints" leads={dash.hot_leads} onLog={openQuickLog} navigate={navigate} testid="hot-leads" />
        <LeadsCard title="⚠️ Stale leads" subtitle="No touch in 7+ days — chase today" leads={dash.stale_leads_list} onLog={openQuickLog} navigate={navigate} testid="stale-leads" />
      </div>

      {/* AI End-of-day digest */}
      <DigestCard />

      {/* Floating mobile FAB */}
      <button
        onClick={() => openQuickLog()}
        data-testid="quick-log-fab-mobile"
        className="sm:hidden fixed bottom-5 right-5 h-14 w-14 rounded-full bg-[#0052CC] hover:bg-[#0747A6] text-white shadow-2xl flex items-center justify-center z-40">
        <Plus className="h-6 w-6" />
      </button>

      {/* Quick log modal */}
      {quickLogOpen && (
        <QuickLogModal
          initialLead={quickLogLead}
          onClose={() => setQuickLogOpen(false)}
          onSaved={() => { setQuickLogOpen(false); load(); }}
        />
      )}
    </div>
  );
}

function KPI({ icon: Icon, label, value, sub, accent, testid }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-3 lg:p-4" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="overline truncate">{label}</div>
        <Icon className="h-4 w-4 shrink-0" style={{ color: accent }} strokeWidth={1.75} />
      </div>
      <div className="font-heading text-2xl lg:text-3xl font-bold text-[#091E42] mt-1 tracking-tight">{value}</div>
      <div className="text-[11px] text-[#5E6C84] mt-1 truncate">{sub}</div>
    </div>
  );
}

function LeadsCard({ title, subtitle, leads, onLog, navigate, testid }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid={testid}>
      <div className="overline">{title}</div>
      <div className="font-heading text-lg font-bold text-[#091E42] mt-1">{subtitle}</div>
      {leads.length === 0 ? (
        <div className="py-6 text-center text-sm text-[#5E6C84]">Nothing here.</div>
      ) : (
        <ul className="mt-3 divide-y divide-[#F1F2F4]">
          {leads.slice(0, 6).map((l) => (
            <li key={l.id} className="py-2.5 flex items-center gap-3" data-testid={`lead-${l.id}`}>
              <Avatar name={l.name} size={32} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-[#091E42] truncate">{l.name}</div>
                <div className="text-[11px] text-[#5E6C84] truncate">{l.city} · {l.specialization || l.type}</div>
              </div>
              <span className="text-[11px] uppercase tracking-wider font-semibold rounded px-1.5 py-0.5"
                    style={{ background: `${STAGE_COLOR[l.pipeline_stage]}15`, color: STAGE_COLOR[l.pipeline_stage] }}>
                {STAGE_LABEL[l.pipeline_stage]}
              </span>
              <button onClick={() => onLog(l)} data-testid={`log-${l.id}`}
                className="flex items-center gap-1 px-2 py-1 text-xs font-semibold text-[#0052CC] hover:bg-[#DEEBFF] rounded">
                <Phone className="h-3.5 w-3.5" /> Log
              </button>
              <button onClick={() => navigate(`/contacts/${l.id}`)} className="text-[#5E6C84] hover:text-[#091E42] text-xs">→</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function DigestCard() {
  const [digest, setDigest] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const generate = async () => {
    setErr(""); setLoading(true);
    try {
      const { data } = await api.post("/agent/digest");
      setDigest(data);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not generate digest");
    }
    setLoading(false);
  };

  return (
    <div
      className="rounded-md p-5 border border-[#6554C0]/30 bg-gradient-to-br from-[#F4F1FD] via-white to-[#EAE6FB]"
      data-testid="agent-digest-card"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="overline flex items-center gap-1.5 text-[#6554C0]">
            <Sparkles className="h-3 w-3" /> AI End-of-day digest
          </div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Your workday wrap-up</div>
          <p className="text-xs text-[#5E6C84] mt-0.5">Claude reads today&apos;s activity and writes a 4-line summary with tomorrow&apos;s #1 action.</p>
        </div>
        <button
          onClick={generate}
          disabled={loading}
          data-testid="digest-generate-btn"
          className="flex items-center gap-2 px-3 py-2 text-sm font-semibold bg-[#6554C0] hover:bg-[#5243AA] text-white rounded-md disabled:opacity-60"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          {digest ? "Regenerate" : "Generate today's digest"}
        </button>
      </div>

      {err && <div className="mt-3 text-sm text-[#FF5630]" data-testid="digest-error">{err}</div>}

      {digest && (
        <div className="mt-4 space-y-3" data-testid="digest-content">
          <pre className="whitespace-pre-wrap font-sans text-sm text-[#091E42] bg-white border border-[#DFE1E6] rounded-md p-3 leading-relaxed">
            {digest.text}
          </pre>
          <div className="flex flex-wrap gap-2">
            <Pill label="Activities" value={digest.stats?.activities ?? 0} />
            <Pill label="Onboarded" value={digest.stats?.onboarded ?? 0} accent="#36B37E" />
            <Pill label="Tasks done" value={digest.stats?.tasks_done ?? 0} accent="#0052CC" />
            {!digest.success && (
              <span className="px-2 py-1 rounded text-[10px] uppercase tracking-wider font-semibold bg-[#FFFAE6] text-[#974F0C] border border-[#FFC400]/40">
                AI offline · raw stats shown
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Pill({ label, value, accent = "#5E6C84" }) {
  return (
    <div className="inline-flex items-baseline gap-1.5 px-2.5 py-1 bg-white border border-[#DFE1E6] rounded">
      <span className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</span>
      <span className="font-heading font-bold text-sm" style={{ color: accent }}>{value}</span>
    </div>
  );
}
