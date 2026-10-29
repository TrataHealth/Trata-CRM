import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { AbhaBadge, useAbhaLookup } from "../components/abdm/AbhaBadge";
import { AbhaQrScanner } from "../components/abdm/AbhaQrScanner";
import { HealthRecordsPanel } from "../components/abdm/HealthRecordsPanel";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { RecordHistory, DetailTabs } from "../components/history/RecordHistory";
import { relativeTime } from "../lib/constants";
import {
  ArrowLeft, User, Phone, Mail, Calendar, HeartPulse, AlertTriangle,
  Bed, Ambulance, Activity, Loader2, ShieldCheck, FileText, MapPin,
  Clock, LogOut, FlaskConical,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  head: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
};

const STATUS_TONE = {
  admitted:   "bg-[#DEEBFF] text-[#0747A6]",
  active:     "bg-[#DEEBFF] text-[#0747A6]",
  discharged: "bg-[#E3FCEF] text-[#006644]",
  completed:  "bg-[#E3FCEF] text-[#006644]",
  critical:   "bg-[#FFEBE6] text-[#BF2600]",
  pending:    "bg-[#FFFAE6] text-[#974F0C]",
  scheduled:  "bg-[#DEEBFF] text-[#0747A6]",
  in_progress: "bg-[#EAE6FF] text-[#403294]",
};
function StatusChip({ status }) {
  const v = String(status || "—").toLowerCase();
  const tone = STATUS_TONE[v] || "bg-[#F4F5F7] text-[#5E6C84]";
  return <span className={`${T.chip} ${tone}`}>{v.toUpperCase().replace(/_/g, " ")}</span>;
}

function LabelValue({ icon: Icon, label, value, mono = false }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold flex items-center gap-1">
        {Icon && <Icon className="h-3 w-3" />} {label}
      </div>
      <div className={`text-sm text-[#091E42] mt-0.5 ${mono ? "font-mono" : "font-semibold"}`}>{value || "—"}</div>
    </div>
  );
}

/** Shared patient detail. mode="admin" → /admin/patients/:id · mode="provider" → /provider/patients/:id */
export default function PatientDetail({ mode = "admin" }) {
  const { userId } = useParams();
  const [abha, refreshAbha] = useAbhaLookup([userId]);
  const nav = useNavigate();
  const basePath = mode === "provider" ? "/provider/patients" : "/admin/patients";
  const listPath = mode === "provider" ? "/provider/patients" : "/admin/patients";
  const [state, setState] = useState({ loading: true, err: "", data: null });
  const { user } = useAuth();
  const canHistory = mode === "admin" && !!user?.is_master_admin;
  const [tab, setTab] = useState("overview");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`${basePath}/${userId}`);
      setState({ loading: false, err: "", data });
    } catch (e) {
      setState({ loading: false, err: e?.response?.data?.detail || "Could not load patient", data: null });
    }
  }, [basePath, userId]);
  useEffect(() => { load(); }, [load]);

  if (state.loading) return (
    <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="patient-detail-loading">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading patient…
    </div>
  );
  if (state.err) return (
    <div className="p-6 max-w-xl mx-auto mt-10" data-testid="patient-detail-error">
      <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <div>
          <div className="font-semibold">Patient unavailable</div>
          <div className="text-xs mt-1">{state.err}</div>
          <button className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7]"
                  onClick={() => nav(listPath)}><ArrowLeft className="h-3.5 w-3.5" /> Back</button>
        </div>
      </div>
    </div>
  );

  const { patient, clinical_profile, emergency_cases = [], appointments = [], admissions = [], ambulance_rides = [], lab_bookings = [] } = state.data || {};
  const cp = clinical_profile || {};

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="patient-detail-page">
      <Link to={listPath} className="inline-flex items-center gap-1 text-xs text-[#5E6C84] hover:text-[#091E42]" data-testid="patient-detail-back">
        <ArrowLeft className="h-3 w-3" /> All patients
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><HeartPulse className="h-3 w-3" /> Patient</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
            {patient?.name || cp.name || "Unnamed patient"}
          </h1>
          <div className="text-sm text-[#5E6C84] mt-1 flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-1"><Phone className="h-3.5 w-3.5" /> +91 {patient?.phone || cp.phone || "—"}</span>
            {patient?.email && <span className="flex items-center gap-1"><Mail className="h-3.5 w-3.5" /> {patient.email}</span>}
            {patient?.patient_id && <span className="font-mono text-[10px] bg-[#F4F5F7] px-2 py-0.5 rounded">{patient.patient_id}</span>}
          </div>
          <div className="mt-2 flex items-center gap-2" data-testid="patient-abha">
            {abha[userId] ? <AbhaBadge abha={abha[userId]} testid="patient-abha-badge" /> : <span className="text-[11px] text-[#97A0AF]">No ABHA linked</span>}
            {abha[userId]?.abha_address && <span className="text-[11px] text-[#42526E]">{abha[userId].abha_address}</span>}
            {!abha[userId] && <AbhaQrScanner patientUserId={userId} patientPhone={patient?.phone || cp.phone} onResult={refreshAbha} label="Scan ABHA" testid="patient-abha-scan" />}
          </div>
        </div>
        {canHistory && <DetailTabs tab={tab} setTab={setTab} />}
      </div>

      {tab === "history" ? <RecordHistory recordId={userId} /> : <>
      {abha[userId] && <HealthRecordsPanel patientUserId={userId} showConsents={false} />}

      <section className={T.card} data-testid="patient-clinical">
        <div className={T.head}><span>Clinical profile</span><span className="normal-case text-[10px] text-[#5E6C84] font-normal">Same data as mobile Provider App</span></div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          <LabelValue icon={Calendar} label="Age" value={cp.age ? `${cp.age} yrs` : (patient?.dob ? patient.dob : "—")} />
          <LabelValue label="Sex" value={cp.sex} />
          <LabelValue label="Blood group" value={cp.blood_group} />
          <LabelValue label="Status" value={cp.status ? <StatusChip status={cp.status} /> : "—"} />
          <LabelValue icon={MapPin} label="Address" value={cp.address} />
          <LabelValue label="Emergency contact" value={cp.emergency_contact} mono />
          <LabelValue label="Allergies" value={cp.allergies} />
          <LabelValue label="Chronic conditions" value={cp.chronic_conditions} />
          <LabelValue label="Current diagnosis" value={cp.diagnosis} />
          <LabelValue label="Admission date" value={cp.admission_date ? relativeTime(cp.admission_date) : "—"} />
          <LabelValue label="Discharge date" value={cp.discharge_date ? relativeTime(cp.discharge_date) : "—"} />
          <LabelValue label="Bed" value={cp.bed_id} mono />
        </div>
        {!clinical_profile && (
          <div className="p-4 text-[11px] text-[#5E6C84] border-t border-[#DFE1E6]">
            No hospital clinical record yet — this patient hasn&apos;t been admitted or triaged on a Trata hospital.
          </div>
        )}
      </section>

      <TimelineFeed
        admissions={admissions}
        appointments={appointments}
        emergencyCases={emergency_cases}
        ambulanceRides={ambulance_rides}
        labBookings={lab_bookings}
      />

      <ActivityList
        title="Admissions" icon={Bed} rows={admissions}
        empty="No hospital admissions on record."
        renderRow={(a) => (
          <>
            <div className="font-semibold text-[#091E42]">{a.admission_number || a.id.slice(0, 8)}</div>
            <div className="text-[11px] text-[#5E6C84]">{a.chief_complaint || a.case_type || "—"}</div>
            <div className="text-[10px] text-[#5E6C84]">Ward {a.ward_type || "—"} · Bed {a.bed_number || "—"} · Triage {a.triage_priority || "—"}</div>
          </>
        )}
        renderRight={(a) => (
          <div className="flex flex-col items-end gap-1 text-[11px] text-[#5E6C84]">
            <StatusChip status={a.status} />
            <span>{a.triage_time ? relativeTime(a.triage_time) : "—"}</span>
          </div>
        )}
      />

      <ActivityList
        title="Appointments" icon={Calendar} rows={appointments}
        empty="No doctor appointments yet."
        renderRow={(a) => (
          <>
            <div className="font-semibold text-[#091E42]">{a.reason || "Consultation"}</div>
            <div className="text-[11px] text-[#5E6C84]">{a.doctor_name || "—"}{a.hospital_name ? ` · ${a.hospital_name}` : ""}</div>
            <div className="text-[11px] text-[#5E6C84]">{a.appointment_date || "—"} · {a.time_slot || "—"}</div>
          </>
        )}
        renderRight={(a) => <StatusChip status={a.status} />}
      />

      <ActivityList
        title="Lab tests" icon={FlaskConical} rows={lab_bookings}
        empty="No lab / diagnostic bookings yet."
        renderRow={(b) => (
          <>
            <div className="font-semibold text-[#091E42]">{b.booking_id || b.id.slice(0, 8)} · {b.pathologist_name || "Lab"}</div>
            <div className="text-[11px] text-[#5E6C84]">{(b.tests || []).map(t => t.testName || t.name).filter(Boolean).join(", ") || "—"}</div>
            <div className="text-[10px] text-[#5E6C84]">{b.scheduled_date || "—"} · {b.scheduled_time || "—"} · {(b.service_type || "").replace(/_/g, " ")}</div>
          </>
        )}
        renderRight={(b) => (
          <div className="flex flex-col items-end gap-1 text-[11px] text-[#5E6C84]">
            <StatusChip status={b.status} />
            <span>₹ {b.total_amount ?? "—"}</span>
          </div>
        )}
      />

      <ActivityList
        title="Emergency cases" icon={Activity} rows={emergency_cases}
        empty="No emergency SOS on record."
        renderRow={(c) => (
          <>
            <div className="font-semibold text-[#091E42]">{c.case_type || "Emergency"}</div>
            <div className="text-[11px] text-[#5E6C84]">{c.reason || "—"}</div>
          </>
        )}
        renderRight={(c) => (
          <div className="flex flex-col items-end gap-1 text-[11px] text-[#5E6C84]">
            <StatusChip status={c.status} />
            <span className="text-[10px] uppercase">Priority: {c.priority || "—"}</span>
            <span>{c.created_at ? relativeTime(c.created_at) : "—"}</span>
          </div>
        )}
      />

      <ActivityList
        title="Ambulance rides" icon={Ambulance} rows={ambulance_rides}
        empty="No ambulance bookings yet."
        renderRow={(r) => (
          <>
            <div className="font-semibold text-[#091E42]">{r.booking_id || r.id.slice(0, 8)}</div>
            <div className="text-[11px] text-[#5E6C84]">{r.pickup_address || "—"} → {r.drop_address || "—"}</div>
            {r.is_emergency && <div className={T.chip + " bg-[#FFEBE6] text-[#BF2600] mt-1"}>SOS</div>}
          </>
        )}
        renderRight={(r) => (
          <div className="flex flex-col items-end gap-1 text-[11px] text-[#5E6C84]">
            <StatusChip status={r.status} />
            <span>₹ {r.total_fare ?? "—"}</span>
          </div>
        )}
      />
      </>}
    </div>
  );
}

function ActivityList({ title, icon: Icon, rows, empty, renderRow, renderRight }) {
  return (
    <section className={T.card} data-testid={`patient-section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
      <div className={T.head}>
        <span className="flex items-center gap-1"><Icon className="h-3 w-3" /> {title} · {rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="p-6 text-center text-xs text-[#5E6C84]">{empty}</div>
      ) : (
        <div className="divide-y divide-[#DFE1E6]">
          {rows.map((r) => (
            <div key={r.id} className="p-4 flex items-start justify-between gap-4">
              <div className="min-w-0">{renderRow(r)}</div>
              <div className="shrink-0">{renderRight(r)}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}


// ── Unified Patient Timeline ───────────────────────────────────────────────
const TL_KIND = {
  admission: { icon: Bed,       tone: "bg-[#DEEBFF] text-[#0747A6]", ring: "ring-[#0052CC]", label: "Admission" },
  discharge: { icon: LogOut,    tone: "bg-[#E3FCEF] text-[#006644]", ring: "ring-[#006644]", label: "Discharge" },
  appointment: { icon: Calendar,tone: "bg-[#EAE6FF] text-[#403294]", ring: "ring-[#5243AA]", label: "Appointment" },
  emergency: { icon: Activity,  tone: "bg-[#FFEBE6] text-[#BF2600]", ring: "ring-[#BF2600]", label: "SOS · Emergency" },
  ride:      { icon: Ambulance, tone: "bg-[#FFFAE6] text-[#974F0C]", ring: "ring-[#FF991F]", label: "Ambulance ride" },
  lab:       { icon: FlaskConical, tone: "bg-[#E6FCFF] text-[#008DA6]", ring: "ring-[#00A3BF]", label: "Lab test" },
};

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return String(iso); }
}

function TimelineFeed({ admissions = [], appointments = [], emergencyCases = [], ambulanceRides = [], labBookings = [] }) {
  const [activeFilter, setActiveFilter] = React.useState(() => {
    try { return sessionStorage.getItem("patient-timeline-filter") || "all"; }
    catch { return "all"; }
  });
  const setFilter = (k) => {
    setActiveFilter(k);
    try { sessionStorage.setItem("patient-timeline-filter", k); } catch {}
  };

  // Flatten all events into one array with a normalised { at, kind, title, subtitle, status }
  const events = [];
  admissions.forEach((a) => {
    if (a.triage_time) {
      events.push({
        id: `adm-${a.id}`,
        at: a.triage_time,
        kind: "admission",
        title: a.admission_number ? `Admitted · ${a.admission_number}` : "Admitted",
        subtitle: a.chief_complaint || a.case_type || `Ward ${a.ward_type || "—"} · Bed ${a.bed_number || "—"}`,
        status: a.status,
        priority: a.triage_priority,
      });
    }
    // Discharges get their own event when the status is discharged (best-effort — no discharge_time in schema)
    if ((a.status || "").toLowerCase() === "discharged") {
      events.push({
        id: `dis-${a.id}`,
        at: a.triage_time,   // best available signal
        kind: "discharge",
        title: `Discharged from ward ${a.ward_type || "—"}`,
        subtitle: a.chief_complaint || a.admission_number,
        status: "completed",
      });
    }
  });
  appointments.forEach((a) => events.push({
    id: `apt-${a.id}`,
    at: a.appointment_date || a.created_at,
    kind: "appointment",
    title: a.reason || "Doctor appointment",
    subtitle: `${a.time_slot || "—"}`,
    status: a.status,
  }));
  emergencyCases.forEach((c) => events.push({
    id: `sos-${c.id}`,
    at: c.created_at,
    kind: "emergency",
    title: c.case_type || "Emergency case",
    subtitle: c.reason || "—",
    status: c.status,
    priority: c.priority,
  }));
  ambulanceRides.forEach((r) => events.push({
    id: `ride-${r.id}`,
    at: r.scheduled_time || r.created_at,
    kind: "ride",
    title: r.booking_id ? `Ride · ${r.booking_id}` : "Ambulance ride",
    subtitle: `${r.pickup_address || "—"} → ${r.drop_address || "—"}`,
    status: r.status,
    isSos: r.is_emergency,
    fare: r.total_fare,
  }));

  labBookings.forEach((b) => events.push({
    id: `lab-${b.id}`,
    at: b.created_at,
    kind: "lab",
    title: b.booking_id ? `Lab test · ${b.booking_id}` : "Lab test",
    subtitle: (b.tests || []).map(t => t.testName || t.name).filter(Boolean).join(", ") || b.pathologist_name || "—",
    status: b.status,
  }));

  // Sort newest first
  events.sort((a, b) => {
    const ta = a.at ? new Date(a.at).getTime() : 0;
    const tb = b.at ? new Date(b.at).getTime() : 0;
    return tb - ta;
  });

  // Per-kind counts drive the pill filter labels
  const counts = { all: events.length, admission: 0, discharge: 0, appointment: 0, emergency: 0, ride: 0, lab: 0 };
  events.forEach((e) => { counts[e.kind] = (counts[e.kind] || 0) + 1; });

  const FILTER_PILLS = [
    { key: "all",         label: "All",           tone: "bg-[#F4F5F7] text-[#42526E]" },
    { key: "admission",   label: "Admissions",    tone: "bg-[#DEEBFF] text-[#0747A6]" },
    { key: "appointment", label: "Appointments",  tone: "bg-[#EAE6FF] text-[#403294]" },
    { key: "emergency",   label: "SOS",           tone: "bg-[#FFEBE6] text-[#BF2600]" },
    { key: "ride",        label: "Rides",         tone: "bg-[#FFFAE6] text-[#974F0C]" },
    { key: "lab",         label: "Lab tests",     tone: "bg-[#E6FCFF] text-[#008DA6]" },
  ];

  const filtered = activeFilter === "all"
    ? events
    : events.filter((e) => e.kind === activeFilter || (activeFilter === "admission" && e.kind === "discharge"));

  return (
    <section className={T.card} data-testid="patient-timeline">
      <div className={T.head}>
        <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> Timeline · {events.length}</span>
        <span className="normal-case text-[10px] text-[#5E6C84] font-normal">Everything, newest first</span>
      </div>
      {/* Filter pills */}
      <div className="px-4 py-3 border-b border-[#DFE1E6] flex flex-wrap items-center gap-2 bg-[#FAFBFC]" data-testid="patient-timeline-filters">
        {FILTER_PILLS.map((p) => {
          const isActive = activeFilter === p.key;
          const n = counts[p.key] ?? 0;
          const disabled = p.key !== "all" && n === 0;
          return (
            <button
              key={p.key}
              type="button"
              disabled={disabled}
              onClick={() => setFilter(p.key)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold transition
                ${isActive ? `${p.tone} ring-1 ring-inset ring-[#0747A6]/20 shadow-sm` : "bg-white text-[#42526E] border border-[#DFE1E6] hover:bg-[#F4F5F7]"}
                ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
              data-testid={`patient-timeline-filter-${p.key}`}>
              {p.label}
              <span className={`ml-0.5 inline-flex items-center justify-center min-w-[18px] px-1 h-[16px] rounded-full text-[10px] font-black
                ${isActive ? "bg-white/70" : "bg-[#F4F5F7] text-[#5E6C84]"}`}>
                {n}
              </span>
            </button>
          );
        })}
      </div>
      {filtered.length === 0 ? (
        <div className="p-8 text-center text-xs text-[#5E6C84]" data-testid="patient-timeline-empty">
          {events.length === 0
            ? "No activity yet. Admissions, appointments, SOS, and ambulance rides will appear here as they happen."
            : "No events match this filter — try another pill above."}
        </div>
      ) : (
        <ol className="relative py-3">
          {/* vertical rail */}
          <div className="absolute left-[26px] top-3 bottom-3 w-px bg-[#DFE1E6]" aria-hidden />
          {filtered.map((e) => {
            const meta = TL_KIND[e.kind] || TL_KIND.appointment;
            const Icon = meta.icon;
            return (
              <li key={e.id} className="relative flex gap-3 px-4 py-3" data-testid={`patient-timeline-event-${e.kind}`}>
                <div className={`relative z-10 h-[26px] w-[26px] rounded-full grid place-items-center ring-2 ring-white ${meta.tone} shrink-0`}>
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`${T.chip} ${meta.tone}`}>{meta.label}</span>
                    <span className="text-sm font-semibold text-[#091E42]">{e.title}</span>
                    {e.isSos && <span className={`${T.chip} bg-[#FFEBE6] text-[#BF2600]`}>SOS</span>}
                    {e.priority && <span className={`${T.chip} bg-[#F4F5F7] text-[#42526E]`}>{String(e.priority).toUpperCase()}</span>}
                  </div>
                  {e.subtitle && <div className="text-[11px] text-[#5E6C84] mt-0.5 line-clamp-2">{e.subtitle}</div>}
                  <div className="flex items-center gap-3 mt-1 text-[10px] text-[#5E6C84]">
                    <span>{fmtDate(e.at)}</span>
                    <span>·</span>
                    <span>{e.at ? relativeTime(e.at) : "—"}</span>
                    {e.fare != null && <><span>·</span><span>₹ {e.fare}</span></>}
                  </div>
                </div>
                <div className="shrink-0">
                  {e.status && <StatusChip status={e.status} />}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
