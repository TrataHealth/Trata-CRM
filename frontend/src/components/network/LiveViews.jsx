import React, { useEffect, useMemo, useState } from "react";
import api from "../../lib/api";
import { useNavigate } from "react-router-dom";
import {
  Activity, Users as UsersIcon, ShieldCheck, BarChart3, Ambulance, MapPin,
  AlertTriangle, CheckCircle2, XCircle, Clock, ChevronRight, Search, RefreshCw,
  Loader2, Phone, FileText, ExternalLink, Sparkles, Database, Cloud,
} from "lucide-react";
import { relativeTime } from "../../lib/constants";

const TABS = [
  { value: "cases",    label: "Emergency cases", icon: Activity },
  { value: "patients", label: "Patients",        icon: UsersIcon },
  { value: "kyc",      label: "KYC manager",     icon: ShieldCheck },
  { value: "network",  label: "Network stats",   icon: BarChart3 },
];

// Data-source toggle — during the Supabase migration both sources coexist so
// the master admin can flip between them and verify parity before we retire
// the Admin App REST proxy in Phase B.
const SOURCES = {
  supabase: { label: "Supabase (shared DB)", prefix: "/supabase", icon: Database, tone: "text-[#3ECF8E]" },
  restapi:  { label: "Admin App REST",       prefix: "/upstream", icon: Cloud,    tone: "text-[#5E6C84]" },
};

export function useNetworkSource() {
  const [source, setSource] = useState(() => localStorage.getItem("trata.network.source") || "supabase");
  useEffect(() => { localStorage.setItem("trata.network.source", source); }, [source]);
  const [supaStatus, setSupaStatus] = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/supabase/status");
        setSupaStatus(data);
        if (!data.connected) setSource("restapi");
      } catch { setSupaStatus({ connected: false }); }
    })();
  }, []);
  return { source, setSource, supaStatus, prefix: SOURCES[source].prefix };
}

export function SourceToggle({ source, setSource, supaStatus }) {
  return (
    <div className="inline-flex items-center bg-white border border-[#DFE1E6] rounded-full p-0.5 shadow-sm" data-testid="network-source-toggle" title="Switch between the shared Supabase DB and the Admin App REST proxy">
      {Object.entries(SOURCES).map(([k, s]) => {
        const I = s.icon;
        const selected = source === k;
        const disabled = k === "supabase" && supaStatus && !supaStatus.connected;
        return (
          <button key={k} onClick={() => !disabled && setSource(k)} disabled={disabled} data-testid={`network-source-${k}`}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-full transition-colors ${
              selected ? "bg-[#091E42] text-white" : "text-[#42526E] hover:text-[#091E42] hover:bg-[#F4F5F7]"
            } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}>
            <I className={`h-3.5 w-3.5 ${selected ? "text-white" : s.tone}`} /> {s.label}
          </button>
        );
      })}
    </div>
  );
}

export const LIVE_VIEWS = TABS;

// ─────────────────────────────────────────────────────────────────────────────
// Emergency Cases
// ─────────────────────────────────────────────────────────────────────────────
export function CasesTab({ prefix }) {
  const [state, setState] = useState({ loading: true, items: [], counts: {}, total: 0, upstream: true });
  const [filter, setFilter] = useState({ status: "", case_type: "" });
  const [detail, setDetail] = useState(null);

  const load = async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const { data } = await api.get(`${prefix}/cases`, {
        params: { status: filter.status || undefined, case_type: filter.case_type || undefined },
      });
      setState({ loading: false, items: data.items, counts: data.counts, total: data.total, upstream: data.upstream_available });
    } catch {
      setState((s) => ({ ...s, loading: false, upstream: false }));
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter.status, filter.case_type, prefix]);

  if (!state.upstream && !state.loading) return <UpstreamDown />;

  return (
    <div className="space-y-4" data-testid="network-cases">
      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-2" data-testid="cases-filter">
        <Pill label="All statuses" active={!filter.status} onClick={() => setFilter((f) => ({ ...f, status: "" }))} count={state.total} />
        {Object.entries(state.counts.by_status || {}).map(([s, n]) => (
          <Pill key={s} label={s} count={n} active={filter.status.toUpperCase() === s} onClick={() => setFilter((f) => ({ ...f, status: s }))} />
        ))}
        <span className="text-[#DFE1E6] mx-1">·</span>
        <Pill label="All types" active={!filter.case_type} onClick={() => setFilter((f) => ({ ...f, case_type: "" }))} />
        {Object.entries(state.counts.by_type || {}).map(([t, n]) => (
          <Pill key={t} label={t.replace(/_/g, " ")} count={n} active={filter.case_type === t} onClick={() => setFilter((f) => ({ ...f, case_type: t }))} />
        ))}
        <button onClick={load} className="ml-auto inline-flex items-center gap-1 text-xs text-[#5E6C84] hover:text-[#091E42]" data-testid="cases-refresh-btn">
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </div>

      {/* Cases table */}
      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="hidden md:grid grid-cols-12 gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]">
          <div className="col-span-3">Patient / Caller</div>
          <div className="col-span-2">Type</div>
          <div className="col-span-2">Priority</div>
          <div className="col-span-2">Status</div>
          <div className="col-span-2">Created</div>
          <div className="col-span-1"></div>
        </div>
        {state.loading ? (
          <SkeletonRows />
        ) : state.items.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="cases-empty">No cases match this filter.</div>
        ) : (
          state.items.map((c) => (
            <button
              key={c.id}
              onClick={() => setDetail(c)}
              data-testid={`case-row-${c.id}`}
              className="w-full text-left grid grid-cols-1 md:grid-cols-12 gap-1 md:gap-2 px-4 py-3 border-b border-[#DFE1E6] last:border-0 hover:bg-[#F8F9FA]"
            >
              <div className="col-span-3 min-w-0">
                <div className="text-sm font-semibold text-[#091E42] truncate">
                  {c.patient_profile?.basicInfo?.fullName || c.customer_phone || "—"}
                </div>
                <div className="text-[11px] text-[#5E6C84] truncate">{c.patient_id || c.customer_phone || ""}</div>
              </div>
              <div className="col-span-2 text-xs text-[#42526E]">{(c.case_type || "—").replace(/_/g, " ")}</div>
              <div className="col-span-2"><PriorityChip value={c.priority} /></div>
              <div className="col-span-2"><StatusChip value={c.status} /></div>
              <div className="col-span-2 text-xs text-[#42526E]">{c.created_at ? relativeTime(c.created_at) : "—"}</div>
              <div className="col-span-1 text-right text-[#5E6C84]"><ChevronRight className="inline h-4 w-4" /></div>
            </button>
          ))
        )}
      </div>

      {detail && <CaseDetailDrawer caseObj={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function CaseDetailDrawer({ caseObj, onClose }) {
  const c = caseObj;
  const ts = (c.timeline || []).slice().sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || ""));
  return (
    <div className="fixed inset-0 z-50 bg-[#091E42]/40 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose} data-testid="case-detail-drawer">
      <div className="bg-white border border-[#DFE1E6] rounded-t-md sm:rounded-md w-full max-w-3xl max-h-[92vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-[#DFE1E6] flex items-start justify-between sticky top-0 bg-white z-10">
          <div>
            <div className="text-xs text-[#5E6C84]">Case · {c.id.slice(0, 8)}</div>
            <div className="font-heading text-base font-bold text-[#091E42] mt-0.5">{c.patient_profile?.basicInfo?.fullName || c.customer_phone || "—"} <span className="text-[#5E6C84] font-normal">({(c.case_type || "—").replace(/_/g, " ")})</span></div>
            <div className="mt-1 flex items-center gap-2"><PriorityChip value={c.priority} /><StatusChip value={c.status} /><span className="text-xs text-[#5E6C84]">{c.created_at ? new Date(c.created_at).toLocaleString() : "—"}</span></div>
          </div>
          <button onClick={onClose} className="text-[#5E6C84] hover:text-[#091E42] text-2xl leading-none" data-testid="case-detail-close" aria-label="Close">×</button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          {c.reason && <Card title="Reason"><p className="text-[#42526E]">{c.reason}</p></Card>}
          {c.location && (c.location.lat || c.location.latitude) && (
            <Card title="Location">
              <p className="text-[#42526E]"><MapPin className="inline h-3.5 w-3.5 mr-1 text-[#FF5630]" />{(c.location.address || `${c.location.lat || c.location.latitude}, ${c.location.lng || c.location.longitude}`)}</p>
              {c.distance && <p className="text-[#5E6C84] text-xs mt-1">Distance: {c.distance}</p>}
            </Card>
          )}
          {c.patient_profile?.basicInfo && Object.keys(c.patient_profile.basicInfo).length > 0 && (
            <Card title="Patient profile">
              <dl className="grid grid-cols-2 gap-2 text-xs">
                {Object.entries(c.patient_profile.basicInfo).map(([k, v]) => (
                  <div key={k}><dt className="text-[#5E6C84] uppercase tracking-wider text-[10px]">{k}</dt><dd className="text-[#091E42]">{String(v ?? "—")}</dd></div>
                ))}
              </dl>
            </Card>
          )}
          {c.vital_signs && Object.keys(c.vital_signs).length > 0 && (
            <Card title="Vitals">
              <dl className="grid grid-cols-2 gap-2 text-xs">
                {Object.entries(c.vital_signs).map(([k, v]) => (
                  <div key={k}><dt className="text-[#5E6C84] uppercase tracking-wider text-[10px]">{k}</dt><dd className="text-[#091E42] font-mono">{String(v ?? "—")}</dd></div>
                ))}
              </dl>
            </Card>
          )}
          {ts.length > 0 && (
            <Card title="Timeline">
              <ol className="space-y-2">
                {ts.map((t, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    <div className="w-1.5 h-1.5 rounded-full bg-[#0052CC] mt-1.5 shrink-0" />
                    <div className="flex-1">
                      <div className="text-[#091E42] font-semibold">{t.event || t.status || t.type || "Event"}</div>
                      {t.note && <div className="text-[#42526E] mt-0.5">{t.note}</div>}
                      <div className="text-[10px] text-[#5E6C84]">{t.timestamp ? new Date(t.timestamp).toLocaleString() : ""}</div>
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Patients
// ─────────────────────────────────────────────────────────────────────────────
export function PatientsTab({ prefix }) {
  const [state, setState] = useState({ loading: true, items: [], total: 0, upstream: true });
  const [q, setQ] = useState("");
  const load = async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const { data } = await api.get(`${prefix}/patients`, { params: { q: q || undefined } });
      setState({ loading: false, items: data.items, total: data.total, upstream: data.upstream_available });
    } catch {
      setState((s) => ({ ...s, loading: false, upstream: false }));
    }
  };
  useEffect(() => { const id = setTimeout(load, q ? 250 : 0); return () => clearTimeout(id); /* eslint-disable-next-line */ }, [q, prefix]);
  if (!state.upstream && !state.loading) return <UpstreamDown />;
  return (
    <div className="space-y-4" data-testid="network-patients">
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-[#5E6C84]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name or phone" className="w-full pl-8 pr-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="patients-search" />
        </div>
        <div className="text-xs text-[#5E6C84]" data-testid="patients-total">{state.total} patient{state.total === 1 ? "" : "s"}</div>
      </div>
      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="hidden md:grid grid-cols-12 gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]">
          <div className="col-span-4">Patient</div>
          <div className="col-span-3">Phone</div>
          <div className="col-span-2">Cases</div>
          <div className="col-span-3">Latest</div>
        </div>
        {state.loading ? <SkeletonRows /> : state.items.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="patients-empty">No patients on the upstream platform yet.</div>
        ) : state.items.map((p, idx) => (
          <div key={`${p.patient_id || p.phone}-${idx}`} className="grid grid-cols-1 md:grid-cols-12 gap-1 md:gap-2 px-4 py-3 border-b border-[#DFE1E6] last:border-0 hover:bg-[#F8F9FA]" data-testid={`patient-row-${p.patient_id || p.phone}`}>
            <div className="col-span-4 min-w-0">
              <div className="text-sm font-semibold text-[#091E42] truncate">{p.name || <span className="text-[#5E6C84] italic">No name on file</span>}</div>
              <div className="text-[11px] text-[#5E6C84] truncate">{p.patient_id || "—"}{p.gender ? ` · ${p.gender}` : ""}{p.age ? ` · ${p.age} yrs` : ""}</div>
            </div>
            <div className="col-span-3 text-xs text-[#42526E] flex items-center gap-1"><Phone className="h-3 w-3 text-[#5E6C84]" />{p.phone || "—"}</div>
            <div className="col-span-2 text-xs"><span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[#DEEBFF] text-[#0747A6] font-semibold">{p.cases_count}</span></div>
            <div className="col-span-3 text-xs text-[#42526E]">
              <div>{(p.latest_case_type || "—").replace(/_/g, " ")}</div>
              <div className="text-[10px] text-[#5E6C84]">{p.latest_case_at ? relativeTime(p.latest_case_at) : ""}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// KYC manager
// ─────────────────────────────────────────────────────────────────────────────
export function KycTab({ prefix }) {
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, items: [], total: 0, upstream: true });
  const load = async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const { data } = await api.get(`${prefix}/kyc-overview`);
      setState({ loading: false, items: data.items, total: data.total, upstream: data.upstream_available });
    } catch {
      setState((s) => ({ ...s, loading: false, upstream: false }));
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [prefix]);
  if (!state.upstream && !state.loading) return <UpstreamDown />;
  return (
    <div className="space-y-4" data-testid="network-kyc">
      <div className="flex items-center gap-2">
        <div className="text-xs text-[#5E6C84]" data-testid="kyc-total">{state.total} provider{state.total === 1 ? "" : "s"} across the network</div>
        <button onClick={load} className="ml-auto inline-flex items-center gap-1 text-xs text-[#5E6C84] hover:text-[#091E42]" data-testid="kyc-refresh-btn">
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </div>
      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="hidden md:grid grid-cols-12 gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]">
          <div className="col-span-3">Provider</div>
          <div className="col-span-2">Role</div>
          <div className="col-span-2">Upstream KYC</div>
          <div className="col-span-2">CRM review</div>
          <div className="col-span-2">Assigned to</div>
          <div className="col-span-1"></div>
        </div>
        {state.loading ? <SkeletonRows /> : state.items.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="kyc-empty">No providers on the network.</div>
        ) : state.items.map((p) => (
          <div key={p.upstream_user_id} className="grid grid-cols-1 md:grid-cols-12 gap-1 md:gap-2 px-4 py-3 border-b border-[#DFE1E6] last:border-0 hover:bg-[#F8F9FA] items-center" data-testid={`kyc-row-${p.upstream_user_id}`}>
            <div className="col-span-3 min-w-0">
              <div className="text-sm font-semibold text-[#091E42] truncate">{p.name}</div>
              <div className="text-[11px] text-[#5E6C84] truncate">{p.phone}{p.city ? ` · ${p.city}` : ""}</div>
            </div>
            <div className="col-span-2 text-xs text-[#42526E]">{(p.role || "").replace(/_/g, " ")}</div>
            <div className="col-span-2"><KycStatusChip value={p.verification_status} verified={p.verified} /></div>
            <div className="col-span-2 text-xs">
              {p.doc_reviews?.approved || p.doc_reviews?.rejected ? (
                <span className="inline-flex items-center gap-1">
                  <span className="text-[#006644] font-semibold">✓{p.doc_reviews.approved}</span>
                  <span className="text-[#BF2600] font-semibold">✗{p.doc_reviews.rejected}</span>
                  {p.ai_prescreen && <Sparkles className="h-3 w-3 text-[#6554C0]" />}
                </span>
              ) : <span className="text-[#5E6C84]">—</span>}
            </div>
            <div className="col-span-2 text-xs text-[#42526E] truncate">{p.assigned_agent_name || <span className="text-[#5E6C84]">—</span>}</div>
            <div className="col-span-1 text-right">
              {p.crm_contact_id ? (
                <button onClick={() => navigate(`/contacts/${p.crm_contact_id}`)} data-testid={`kyc-open-${p.upstream_user_id}`} className="text-[#0052CC] text-xs font-semibold hover:underline inline-flex items-center gap-0.5">
                  Open <ChevronRight className="h-3 w-3" />
                </button>
              ) : <span className="text-[10px] text-[#5E6C84]">(no CRM contact)</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Network stats
// ─────────────────────────────────────────────────────────────────────────────
export function NetworkStatsTab({ prefix }) {
  const [state, setState] = useState({ loading: true, stats: null, upstream: true });
  useEffect(() => {
    (async () => {
      setState((s) => ({ ...s, loading: true }));
      try {
        const { data } = await api.get(`${prefix}/network-stats`);
        setState({ loading: false, stats: data.stats, upstream: data.upstream_available });
      } catch {
        setState({ loading: false, stats: null, upstream: false });
      }
    })();
  }, [prefix]);
  if (state.loading) return <SkeletonRows />;
  if (!state.upstream || !state.stats) return <UpstreamDown />;
  const s = state.stats;
  // Field names differ between REST (camelCase) and Supabase (snake_case) — normalise
  const ehrTotal    = s.ehr?.total_records ?? s.ehr?.totalRecords ?? 0;
  const hgZones     = s.health_guard?.zones ?? s.healthGuard?.totalZones ?? 0;
  const hgAnomalies = s.health_guard?.anomalies_active ?? s.healthGuard?.activeAnomalies ?? 0;
  const ambVerified = s.verification?.ambulanceProviders?.verified ?? 0;
  const hospVerified = s.verification?.hospitals?.verified ?? 0;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="network-stats">
      <Tile label="Total users"           value={s.users?.total} sub={`${s.users?.newToday || 0} today`} icon={UsersIcon} />
      <Tile label="Patients"              value={s.users?.patients} sub="on the Provider App" icon={UsersIcon} />
      <Tile label="Ambulance providers"   value={s.users?.ambulance_providers ?? s.users?.ambulanceProviders} sub={`${ambVerified} verified`} icon={Ambulance} />
      <Tile label="Hospitals"             value={s.users?.hospitals} sub={`${hospVerified} verified`} icon={ShieldCheck} />
      <Tile label="Cases total"           value={s.cases?.total} sub={`${s.cases?.active || 0} active`} icon={Activity} />
      <Tile label="Cases today"           value={s.cases?.today} sub={`${s.cases?.week ?? s.cases?.thisWeek ?? 0} this week`} icon={Clock} />
      <Tile label="EHR records"           value={ehrTotal} sub="patient health records" icon={FileText} />
      <Tile label="HealthGuard zones"     value={hgZones} sub={`${hgAnomalies} anomalies`} icon={AlertTriangle} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared
// ─────────────────────────────────────────────────────────────────────────────
function Pill({ label, count, active, onClick }) {
  return (
    <button onClick={onClick} className={`px-2.5 py-1 text-[11px] font-semibold rounded-full border transition-colors ${active ? "bg-[#0052CC] text-white border-[#0052CC]" : "bg-white text-[#42526E] border-[#DFE1E6] hover:border-[#42526E]"}`}>
      {label}{typeof count === "number" && <span className="ml-1 opacity-70">·{count}</span>}
    </button>
  );
}
function PriorityChip({ value }) {
  const map = { CRITICAL: ["#BF2600", "#FFEBE6"], HIGH: ["#974F0C", "#FFFAE6"], MEDIUM: ["#0747A6", "#DEEBFF"], LOW: ["#006644", "#E3FCEF"] };
  const [fg, bg] = map[value] || ["#42526E", "#F4F5F7"];
  return <span className="inline-flex px-2 py-0.5 text-[10px] font-bold rounded-full" style={{ color: fg, background: bg }}>{value || "—"}</span>;
}
function StatusChip({ value }) {
  const map = { ACTIVE: ["#006644", "#E3FCEF"], COMPLETED: ["#0747A6", "#DEEBFF"], CANCELLED: ["#5E6C84", "#F4F5F7"], AUTO_CLOSED: ["#974F0C", "#FFFAE6"], CLOSED: ["#5E6C84", "#F4F5F7"] };
  const [fg, bg] = map[value] || ["#42526E", "#F4F5F7"];
  return <span className="inline-flex px-2 py-0.5 text-[10px] font-bold rounded-full" style={{ color: fg, background: bg }}>{value || "—"}</span>;
}
function KycStatusChip({ value, verified }) {
  const isVerified = verified || value === "verified";
  if (isVerified) return <span className="inline-flex items-center gap-0.5 px-2 py-0.5 text-[10px] font-bold rounded-full text-[#006644] bg-[#E3FCEF]"><CheckCircle2 className="h-3 w-3" /> verified</span>;
  return <span className="inline-flex items-center gap-0.5 px-2 py-0.5 text-[10px] font-bold rounded-full text-[#974F0C] bg-[#FFFAE6]"><Clock className="h-3 w-3" /> {value || "pending"}</span>;
}
function Card({ title, children }) {
  return (
    <div className="border border-[#DFE1E6] rounded-md overflow-hidden">
      <div className="px-3 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold bg-[#F8F9FA] border-b border-[#DFE1E6]">{title}</div>
      <div className="p-3">{children}</div>
    </div>
  );
}
function Tile({ label, value, sub, icon: Icon }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-4" data-testid={`network-tile-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
        <Icon className="h-4 w-4 text-[#5E6C84]" />
      </div>
      <div className="font-heading text-3xl font-black text-[#091E42] mt-1">{value ?? 0}</div>
      {sub && <div className="text-[11px] text-[#5E6C84] mt-1">{sub}</div>}
    </div>
  );
}
function SkeletonRows() {
  return (
    <div className="p-4 space-y-2">
      {[1, 2, 3].map((i) => <div key={i} className="h-12 bg-[#F4F5F7] rounded animate-pulse" />)}
    </div>
  );
}
function UpstreamDown() {
  return (
    <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2" data-testid="network-upstream-down">
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
      <div>
        <div className="font-semibold">Trata Admin App is unreachable right now.</div>
        <div className="text-xs mt-1">Couldn't fetch data from the upstream backend. The CRM will keep retrying via the 5-minute background sync — try again in a moment.</div>
      </div>
    </div>
  );
}
