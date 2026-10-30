import React, { useEffect, useState } from "react";
import { DoctorAppointments } from "../components/doctor/DoctorAppointments";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { relativeTime } from "../lib/constants";
import { AssignVehicle, AllocationsPanel } from "../components/AmbulanceDispatch";
import {
  Ambulance, Activity, ShieldCheck, Clock,
  MapPin, Loader2, AlertTriangle, Star,
} from "lucide-react";

const StatusChip = ({ value }) => {
  const tone = {
    pending: "text-[#974F0C] bg-[#FFFAE6]",
    verified: "text-[#006644] bg-[#E3FCEF]",
    approved: "text-[#006644] bg-[#E3FCEF]",
    active: "text-[#006644] bg-[#E3FCEF]",
    available: "text-[#006644] bg-[#E3FCEF]",
    rejected: "text-[#BF2600] bg-[#FFEBE6]",
    cancelled: "text-[#5E6C84] bg-[#F4F5F7]",
    auto_closed: "text-[#974F0C] bg-[#FFFAE6]",
    completed: "text-[#0747A6] bg-[#DEEBFF]",
  }[String(value || "").toLowerCase()] || "text-[#42526E] bg-[#F4F5F7]";
  return <span className={`inline-flex px-2 py-0.5 text-[10px] font-bold rounded-full ${tone}`}>{value || "—"}</span>;
};

const Tile = ({ label, value, sub, icon: Icon, tone = "#0052CC" }) => (
  <div className="bg-white border border-[#DFE1E6] rounded-md p-4" data-testid={`provider-tile-${label.toLowerCase().replace(/[^a-z0-9]+/gi, "-")}`}>
    <div className="flex items-center justify-between">
      <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
      <Icon className="h-4 w-4" style={{ color: tone }} />
    </div>
    <div className="font-heading text-3xl font-black text-[#091E42] mt-1">{value ?? 0}</div>
    {sub && <div className="text-[11px] text-[#5E6C84] mt-1">{sub}</div>}
  </div>
);

export default function ProviderDashboard() {
  const { user } = useAuth();
  const [state, setState] = useState({ loading: true, data: null, err: "" });

  const load = React.useCallback(async () => {
    try {
      const { data } = await api.get("/provider/pc-dashboard");
      setState({ loading: false, data, err: "" });
    } catch (e) {
      setState({ loading: false, data: null, err: e?.response?.data?.detail || "Could not load dashboard" });
    }
  }, []);

  useEffect(() => {
    load();
    window.addEventListener("trata:live", load);
    return () => window.removeEventListener("trata:live", load);
  }, [load]);

  if (state.loading) {
    return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="provider-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading your dashboard from the shared TrataHealth backend…</div>;
  }
  if (state.err || !state.data) {
    return (
      <div className="p-6 max-w-xl mx-auto mt-10" data-testid="provider-error">
        <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">Could not load your PC dashboard</div>
            <div className="text-xs mt-1">{state.err || "Unknown error"}</div>
            <div className="text-[11px] text-[#5E6C84] mt-2">If your profile isn't set up yet, complete provider onboarding on the mobile Provider App first — this PC console reads from the same data.</div>
          </div>
        </div>
      </div>
    );
  }
  const { provider, kpis, recent_cases, fleet, allocations } = state.data;
  const fleetById = Object.fromEntries((fleet || []).map((v) => [v.id, v]));

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="provider-dashboard">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><Ambulance className="h-3 w-3" /> Provider PC Console</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{provider.business_name || user?.business_name || "My Dashboard"}</h1>
          <p className="text-sm text-[#5E6C84] mt-1 flex items-center gap-2 flex-wrap">
            <MapPin className="h-3 w-3" /> {[provider.city, provider.state].filter(Boolean).join(", ") || "Location not set"}
            <span className="text-[#DFE1E6]">·</span>
            <StatusChip value={provider.status} />
            {provider.average_rating != null && (
              <>
                <span className="text-[#DFE1E6]">·</span>
                <span className="inline-flex items-center gap-0.5 text-[#974F0C]"><Star className="h-3 w-3 fill-[#FFAB00] text-[#FFAB00]" />{Number(provider.average_rating).toFixed(1)}</span>
              </>
            )}
          </p>
        </div>
        <div className="text-[11px] text-[#5E6C84] flex items-center gap-1" data-testid="provider-shared-db-badge">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#3ECF8E] animate-pulse" /> Live from shared Supabase DB — same data as your mobile app.
        </div>
      </div>

      {state.data.profile_incomplete && (
        <div className="bg-[#FFFAE6] border border-[#FFE380] rounded-md p-4 text-sm text-[#974F0C] flex items-start gap-2" data-testid="provider-profile-incomplete">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>Your {state.data.vertical || "provider"} profile isn&apos;t complete yet, so some details are missing here. Finish it under <a href="/provider/profile" className="font-semibold underline">Profile</a> or on the Trata Provider mobile app.</div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="provider-kpis">
        {state.data.vertical === "ambulance" ? (
          <>
            <Tile label="Active trips" value={kpis.active_trips} sub="dispatched or en route" icon={Activity} tone="#DE350B" />
            <Tile label="Trips today"  value={kpis.trips_today}  sub={`${kpis.trips_week ?? 0} in last 7 days`} icon={Clock} tone="#0052CC" />
            <Tile label="Fleet"        value={`${kpis.fleet_available ?? 0}/${kpis.fleet_total ?? 0}`} sub="available / total" icon={Ambulance} tone="#006644" />
          </>
        ) : (
          <>
            {state.data.vertical !== "doctor" && <>
            <Tile label={state.data.vertical === "hospital" ? "Active cases" : "Cases assigned"} value={kpis.active_trips ?? 0} sub="in progress" icon={Activity} tone="#DE350B" />
            <Tile label="Today" value={kpis.trips_today ?? 0} sub="new today" icon={Clock} tone="#0052CC" />
            </>}
            <Tile label="Status" value={provider.status || provider.verification_status || (provider.is_verified ? "verified" : "pending")} sub="on the network" icon={ShieldCheck} tone="#006644" />
          </>
        )}
        <Tile label="KYC docs"     value={kpis.kyc_approved} sub={`${kpis.kyc_pending ?? 0} pending`} icon={ShieldCheck} tone="#5243AA" />
      </div>

      {state.data.vertical === "hospital" && (
        <a href="/provider/command-center" data-testid="provider-open-command-center"
          className="block bg-gradient-to-r from-[#0052CC] to-[#0747A6] text-white rounded-md p-4 hover:shadow-lg transition-shadow">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-white/70 font-semibold">Live Ops</div>
              <div className="font-heading text-lg font-black mt-0.5">Open Emergency Command Centre →</div>
              <div className="text-xs text-white/80 mt-1">Accept incoming SOS, chat with the ambulance, admit patients, manage beds and discharge — all live from the shared TrataHealth backend.</div>
            </div>
            <div className="hidden sm:flex items-center gap-1 text-[11px] text-white/80 whitespace-nowrap">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-white animate-pulse" /> Live · updates every 3s
            </div>
          </div>
        </a>
      )}

      {state.data.vertical === "ambulance" && (
        <div className="bg-white border border-[#DFE1E6] rounded-md p-4 grid grid-cols-2 sm:grid-cols-4 gap-4" data-testid="provider-lifetime-strip">
          <div><div className="text-[10px] uppercase text-[#5E6C84] font-semibold">Total bookings</div><div className="text-lg font-bold text-[#091E42] mt-0.5">{provider.total_bookings || 0}</div></div>
          <div><div className="text-[10px] uppercase text-[#5E6C84] font-semibold">Completed</div><div className="text-lg font-bold text-[#091E42] mt-0.5">{provider.completed_bookings || 0}</div></div>
          <div><div className="text-[10px] uppercase text-[#5E6C84] font-semibold">Lifetime earnings</div><div className="text-lg font-bold text-[#091E42] mt-0.5">₹{Number(provider.total_earnings || 0).toLocaleString("en-IN")}</div></div>
          <div><div className="text-[10px] uppercase text-[#5E6C84] font-semibold">Onboarded</div><div className="text-lg font-bold text-[#091E42] mt-0.5">{provider.created_at ? relativeTime(provider.created_at) : "—"}</div></div>
        </div>
      )}

      {state.data.vertical === "doctor" ? <DoctorAppointments compact /> : (
      <div className={`grid grid-cols-1 ${state.data.vertical === "ambulance" ? "lg:grid-cols-2" : ""} gap-4`}>
        <section className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="provider-recent-cases">
          <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]">Recent cases · last 10</div>
          {(!recent_cases || recent_cases.length === 0) ? (
            <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="provider-cases-empty">No cases assigned yet.</div>
          ) : recent_cases.map((c) => (
            <div key={c.id} className="px-4 py-3 border-b border-[#DFE1E6] last:border-0 flex items-start justify-between gap-3" data-testid={`provider-case-${c.id}`}>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-[#091E42] truncate">{c.patient_profile?.basicInfo?.fullName || c.customer_phone || "—"}</div>
                <div className="text-[11px] text-[#5E6C84]">{(c.case_type || "").replace(/_/g, " ")}{c.distance ? ` · ${c.distance}` : ""}</div>
                {c.ambulance_id && <div className="text-[11px] text-[#0747A6] font-mono flex items-center gap-1" data-testid={`provider-case-vehicle-${c.id}`}><Ambulance className="h-3 w-3" /> {fleetById[c.ambulance_id]?.vehicle_number || "Vehicle assigned"}</div>}
                {state.data.vertical === "ambulance" && <AssignVehicle caseRow={c} fleet={fleet} onDone={load} />}
              </div>
              <div className="text-right shrink-0 space-y-1">
                <StatusChip value={c.status} />
                <div className="text-[10px] text-[#5E6C84]">{c.created_at ? relativeTime(c.created_at) : ""}</div>
              </div>
            </div>
          ))}
        </section>

        {state.data.vertical === "ambulance" && (
          <section className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="provider-fleet">
            <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]">Fleet</div>
            {(!fleet || fleet.length === 0) ? (
              <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="provider-fleet-empty">No ambulances registered yet. Add them on the mobile Provider App.</div>
            ) : fleet.map((v) => (
              <div key={v.id} className="px-4 py-3 border-b border-[#DFE1E6] last:border-0 flex items-start justify-between gap-3" data-testid={`provider-fleet-${v.id}`}>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-[#091E42] font-mono truncate">{v.vehicle_number || "—"}</div>
                  <div className="text-[11px] text-[#5E6C84] truncate">{[v.ambulance_type, v.model].filter(Boolean).join(" · ") || "—"}</div>
                  {v.assigned_driver_name && <div className="text-[11px] text-[#42526E]">Driver: {v.assigned_driver_name}{v.assigned_driver_phone ? ` · ${v.assigned_driver_phone}` : ""}</div>}
                </div>
                <div className="text-right shrink-0"><StatusChip value={v.status} /></div>
              </div>
            ))}
          </section>
        )}
        {state.data.vertical === "ambulance" && <AllocationsPanel allocations={allocations} onDone={load} />}
      </div>
      )}
    </div>
  );
}
