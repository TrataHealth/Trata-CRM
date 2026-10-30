import React, { useCallback, useEffect, useState } from "react";
import { CalendarDays, Loader2, Phone, Video, Building2, Stethoscope, Check, UserX, X, NotebookPen } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../ui/sheet";
import { ConsultEditor } from "./ConsultEditor";

const MODE_ICON = { video: Video, hospital: Building2 };
const STATUS_TONE = {
  completed: "bg-[#E3FCEF] text-[#006644]", confirmed: "bg-[#DEEBFF] text-[#0747A6]", no_show: "bg-[#FFF0B3] text-[#974F0C]",
  cancelled: "bg-[#FFEBE6] text-[#BF2600]", canceled: "bg-[#FFEBE6] text-[#BF2600]",
};
const SRC = { clinic: "Clinic visit", hospital: "Hospital consult", video: "Video consult", general: "Appointment" };
const when = (a) => {
  const d = a.date ? new Date(`${String(a.date).slice(0, 10)}T00:00:00`) : null;
  return `${d && !isNaN(d) ? d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }) : "Date not set"}${a.time ? ` · ${a.time}` : ""}`;
};
const Status = ({ s }) => <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${STATUS_TONE[String(s || "").toLowerCase()] || "bg-[#F4F5F7] text-[#42526E]"}`}>{String(s || "pending").replace(/_/g, " ")}</span>;

function Actions({ a, onDone }) {
  const [busy, setBusy] = useState("");
  const set = async (status) => {
    if (status === "cancelled" && !window.confirm(`Cancel ${a.patient_name || "this patient"}'s appointment? The patient will see it as cancelled.`)) return;
    setBusy(status);
    try { await api.post(`/provider/doctor/appointments/${a.source}/${a.id}/status`, { status }); toast.success(`Marked ${status.replace("_", " ")}`); onDone(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Update failed"); }
    setBusy("");
  };
  const B = ({ s, icon: I, label, cls }) => (
    <button onClick={(e) => { e.stopPropagation(); set(s); }} disabled={!!busy} className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-md disabled:opacity-50 ${cls}`} data-testid={`appt-${s}-${a.id}`}>
      {busy === s ? <Loader2 className="h-3 w-3 animate-spin" /> : <I className="h-3 w-3" />} {label}
    </button>
  );
  return (
    <div className="flex gap-1.5 flex-wrap">
      <B s="completed" icon={Check} label="Completed" cls="bg-[#36B37E] text-white hover:bg-[#00875A]" />
      <B s="no_show" icon={UserX} label="No-show" cls="border border-[#DFE1E6] text-[#974F0C] hover:bg-[#FFFAE6]" />
      <B s="cancelled" icon={X} label="Cancel" cls="text-[#BF2600] hover:bg-[#FFEBE6]" />
    </div>
  );
}

function Row({ a, upcoming, onOpen, onDone, onConsult }) {
  const Icon = MODE_ICON[a.source] || (a.mode === "video" ? Video : Stethoscope);
  return (
    <li onClick={() => onOpen(a)} className="px-4 py-3 border-b border-[#F4F5F7] last:border-0 flex flex-wrap items-center gap-3 cursor-pointer hover:bg-[#F8F9FA]" data-testid={`appt-row-${a.id}`}>
      <div className="w-36 shrink-0 text-xs font-semibold text-[#091E42]">{when(a)}</div>
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-[#091E42] truncate">{a.patient_name || "Patient"}{(a.age || a.gender) && <span className="text-xs font-normal text-[#5E6C84]"> · {[a.age, a.gender].filter(Boolean).join(" / ")}</span>}</div>
        <div className="text-xs text-[#5E6C84] truncate flex items-center gap-1"><Icon className="h-3 w-3 shrink-0" /> {SRC[a.source]}{a.reason ? ` — ${a.reason}` : ""}</div>
      </div>
      <Status s={a.status} />
      <button onClick={(e) => { e.stopPropagation(); onConsult(a); }} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-md border border-[#4C9AFF] text-[#0052CC] hover:bg-[#DEEBFF]" data-testid={`appt-consult-${a.id}`}><NotebookPen className="h-3 w-3" /> Notes &amp; Rx</button>
      {upcoming && <Actions a={a} onDone={onDone} />}
    </li>
  );
}

function PatientSheet({ a, onClose, onConsult }) {
  const [visits, setVisits] = useState(null);
  useEffect(() => {
    if (!a) return;
    setVisits(null);
    api.get(`/provider/doctor/patients/${a.patient_id || "none"}/visits`, { params: { phone: a.patient_phone || "" } }).then((r) => setVisits(r.data.items)).catch(() => setVisits([]));
  }, [a]);
  const F = ({ l, v }) => v ? <div><div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{l}</div><div className="text-sm text-[#091E42] break-words">{v}</div></div> : null;
  return (
    <Sheet open={!!a} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto" data-testid="appt-patient-sheet">
        {a && <>
          <SheetHeader><SheetTitle className="font-heading text-xl">{a.patient_name || "Patient"}</SheetTitle></SheetHeader>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <F l="Phone" v={a.patient_phone && <a href={`tel:${a.patient_phone}`} className="text-[#0052CC] inline-flex items-center gap-1"><Phone className="h-3 w-3" />{a.patient_phone}</a>} />
            <F l="Age / gender" v={[a.age, a.gender].filter(Boolean).join(" / ")} />
            <F l="When" v={when(a)} />
            <F l="Type" v={`${SRC[a.source]} · ${a.mode}`} />
            <F l="Fee" v={a.fee != null ? `₹${a.fee}` : null} />
            <F l="Payment" v={a.payment_status} />
            <F l="Visit" v={a.visit_type} />
            <F l="Ref / token" v={a.token} />
          </div>
          <div className="mt-3 space-y-3"><F l="Reason" v={a.reason} /><F l="Booking notes" v={a.notes} /></div>
          <button onClick={() => onConsult(a)} className="mt-4 w-full inline-flex justify-center items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6]" data-testid="appt-sheet-consult-btn"><NotebookPen className="h-4 w-4" /> Notes &amp; prescription</button>
          <div className="mt-6 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">Visits with you</div>
          {visits === null ? <div className="text-xs text-[#5E6C84] mt-2 flex items-center gap-2"><Loader2 className="h-3 w-3 animate-spin" /> Loading…</div>
            : <ul className="mt-2 space-y-2" data-testid="appt-visit-history">{visits.map((v) => (
              <li key={`${v.source}-${v.id}`} className={`rounded-md border px-3 py-2 ${v.id === a.id ? "border-[#4C9AFF] bg-[#DEEBFF]/40" : "border-[#DFE1E6]"}`}>
                <div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold text-[#091E42]">{when(v)}</span><Status s={v.status} /></div>
                <div className="text-xs text-[#5E6C84] mt-0.5">{SRC[v.source]}{v.reason ? ` — ${v.reason}` : ""}</div>
                {v.notes && <div className="text-xs text-[#42526E] mt-1 italic">{v.notes}</div>}
              </li>))}</ul>}
        </>}
      </SheetContent>
    </Sheet>
  );
}

/** Doctor's appointments from every Patient-app booking type, with status actions and per-patient history. */
export function DoctorAppointments({ compact = false }) {
  const [s, setS] = useState({ loading: true, upcoming: [], past: [], counts: {} });
  const [tab, setTab] = useState("upcoming");
  const [open, setOpen] = useState(null);
  const [consult, setConsult] = useState(null);
  const load = useCallback(() => api.get("/provider/doctor/appointments").then(({ data }) => setS({ loading: false, ...data }))
    .catch((e) => setS({ loading: false, upcoming: [], past: [], counts: {}, err: e?.response?.data?.detail || "Could not load appointments" })), []);
  useEffect(() => { load(); window.addEventListener("trata:live", load); return () => window.removeEventListener("trata:live", load); }, [load]);
  const list = (tab === "upcoming" ? s.upcoming : s.past).slice(0, compact ? 8 : 500);

  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md" data-testid="doctor-appointments">
      <div className="px-4 pt-3 flex flex-wrap items-center justify-between gap-2 border-b border-[#DFE1E6]">
        <div className="flex items-center gap-2 text-sm font-heading font-bold text-[#091E42] pb-3"><CalendarDays className="h-4 w-4 text-[#0052CC]" /> Appointments
          {s.counts.today > 0 && <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[#DEEBFF] text-[#0747A6]" data-testid="appt-today-count">{s.counts.today} today</span>}</div>
        <div className="flex gap-1">{[["upcoming", `Upcoming · ${s.counts.upcoming ?? 0}`], ["past", `Past · ${s.counts.past ?? 0}`]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${tab === k ? "border-[#0052CC] text-[#0052CC]" : "border-transparent text-[#5E6C84]"}`} data-testid={`appt-tab-${k}`}>{l}</button>))}</div>
      </div>
      {s.loading ? <div className="p-6 text-xs text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading appointments…</div>
        : s.err ? <div className="p-4 text-sm text-[#BF2600]" data-testid="appt-error">{s.err}</div>
        : list.length === 0 ? <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="appt-empty">{tab === "upcoming" ? "No upcoming appointments." : "No past appointments yet."}</div>
        : <ul>{list.map((a) => <Row key={`${a.source}-${a.id}`} a={a} upcoming={tab === "upcoming"} onOpen={setOpen} onDone={load} onConsult={setConsult} />)}</ul>}
      <PatientSheet a={open} onClose={() => setOpen(null)} onConsult={(a) => { setOpen(null); setConsult(a); }} />
      <ConsultEditor appt={consult} onClose={() => setConsult(null)} onChanged={load} />
    </section>
  );
}
