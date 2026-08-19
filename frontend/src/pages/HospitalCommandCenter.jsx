import React, { useEffect, useRef, useState, useCallback } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { relativeTime } from "../lib/constants";
import { toast } from "sonner";
import {
  Activity, Ambulance, AlertTriangle, BedDouble, CheckCircle2, ChevronDown,
  Clock, Loader2, MapPin, MessageSquare, Plus, Radio, Send, ShieldCheck,
  Siren, SquareX, User, X,
} from "lucide-react";

// ── design tokens (matches ambulance PC console) ────────────────────────────
const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  sectionHead: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
  btnPrimary: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnDanger:  "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#FFEBE6] text-[#BF2600] hover:bg-[#FFBDAD] disabled:opacity-40",
  btnGhost:   "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
  btnSecondary: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#E4E6EA] text-[#091E42] hover:bg-[#DFE1E6] disabled:opacity-40",
};

const PRIORITY_TONE = {
  critical: "bg-[#FFEBE6] text-[#BF2600]",
  high:     "bg-[#FFF0B3] text-[#974F0C]",
  medium:   "bg-[#DEEBFF] text-[#0747A6]",
  low:      "bg-[#E3FCEF] text-[#006644]",
};

const StatusChip = ({ value }) => {
  const v = String(value || "").toUpperCase();
  const tone =
    v.includes("CRITICAL") || v.includes("FAILED") ? "text-[#BF2600] bg-[#FFEBE6]" :
    v.includes("EN_ROUTE") || v.includes("DISPATCHED") ? "text-[#0747A6] bg-[#DEEBFF]" :
    v.includes("ARRIVED") || v.includes("ADMITTED")    ? "text-[#006644] bg-[#E3FCEF]" :
    v.includes("HOSPITAL_ASSIGNED") || v.includes("AMBULANCE_ASSIGNED") ? "text-[#974F0C] bg-[#FFFAE6]" :
    "text-[#42526E] bg-[#F4F5F7]";
  return <span className={`${T.chip} ${tone}`}>{value || "—"}</span>;
};

const PriorityChip = ({ value }) => {
  const tone = PRIORITY_TONE[String(value || "").toLowerCase()] || "bg-[#F4F5F7] text-[#42526E]";
  return <span className={`${T.chip} ${tone}`}>{(value || "—").toUpperCase()}</span>;
};

// ── KPI tile ────────────────────────────────────────────────────────────────
const Tile = ({ label, value, sub, icon: Icon, tone = "#0052CC", accent }) => (
  <div className={`${T.card} p-4 relative overflow-hidden`} data-testid={`hcc-tile-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
    {accent && <div className="absolute inset-y-0 left-0 w-1" style={{ background: tone }} />}
    <div className="flex items-center justify-between">
      <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
      <Icon className="h-4 w-4" style={{ color: tone }} />
    </div>
    <div className="font-heading text-3xl font-black text-[#091E42] mt-1">{value ?? 0}</div>
    {sub && <div className="text-[11px] text-[#5E6C84] mt-1">{sub}</div>}
  </div>
);

// ── Incoming card ───────────────────────────────────────────────────────────
function IncomingCard({ c, onAccept, onDecline, busy }) {
  const patientName = c.patient_profile?.basicInfo?.fullName || c.customer_phone || "Unknown";
  return (
    <div className="p-4 border-b border-[#DFE1E6] last:border-0" data-testid={`hcc-incoming-${c.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <PriorityChip value={c.priority} />
            <span className="text-[11px] text-[#5E6C84]">{(c.case_type || "").replace(/_/g, " ")}</span>
            {c.distance != null && <span className="text-[11px] text-[#5E6C84]">· {Number(c.distance).toFixed(1)} km</span>}
            {c.estimated_response_time && <span className="text-[11px] text-[#5E6C84]">· ETA {c.estimated_response_time} min</span>}
          </div>
          <div className="mt-1 text-sm font-semibold text-[#091E42] truncate">{patientName}</div>
          <div className="text-[11px] text-[#5E6C84] flex items-center gap-1">
            <MapPin className="h-3 w-3" /> {c.location?.address || c.location?.formatted || "Location pending"}
          </div>
          {c.reason && <div className="mt-1 text-xs text-[#42526E] line-clamp-2">{c.reason}</div>}
          {c.vital_signs && Object.keys(c.vital_signs).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
              {Object.entries(c.vital_signs).slice(0, 4).map(([k, v]) => (
                <span key={k} className="px-1.5 py-0.5 bg-[#F4F5F7] rounded text-[#42526E]">{k}: <b>{String(v)}</b></span>
              ))}
            </div>
          )}
        </div>
        <div className="text-right shrink-0 text-[10px] text-[#5E6C84]">{c.created_at ? relativeTime(c.created_at) : ""}</div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button className={T.btnPrimary} disabled={busy} onClick={() => onAccept(c.id)} data-testid={`hcc-accept-${c.id}`}>
          <CheckCircle2 className="h-3.5 w-3.5" /> Accept case
        </button>
        <button className={T.btnDanger} disabled={busy} onClick={() => onDecline(c.id)} data-testid={`hcc-decline-${c.id}`}>
          <SquareX className="h-3.5 w-3.5" /> Decline
        </button>
      </div>
    </div>
  );
}

// ── Active card + inline chat + admit ───────────────────────────────────────
function ActiveCard({ c, beds, onAdmit, onOpenChat, chatOpenFor, chatMessages, onSendChat, sending, onCloseChat }) {
  const [chief, setChief] = useState("");
  const [bedId, setBedId] = useState("");
  const [priority, setPriority] = useState("medium");
  const [admitting, setAdmitting] = useState(false);
  const [showAdmit, setShowAdmit] = useState(false);
  const patientName = c.patient_profile?.basicInfo?.fullName || c.customer_phone || "Unknown";
  const chatOpen = chatOpenFor === c.id;
  const chatBoxRef = useRef(null);
  const [draft, setDraft] = useState("");
  useEffect(() => { if (chatOpen && chatBoxRef.current) chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight; }, [chatOpen, chatMessages]);

  const free = beds.filter((b) => b.is_available);
  return (
    <div className="p-4 border-b border-[#DFE1E6] last:border-0" data-testid={`hcc-active-${c.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusChip value={c.status} />
            <PriorityChip value={c.priority} />
            <span className="text-[11px] text-[#5E6C84]">{(c.case_type || "").replace(/_/g, " ")}</span>
          </div>
          <div className="mt-1 text-sm font-semibold text-[#091E42] truncate">{patientName}</div>
          <div className="text-[11px] text-[#5E6C84]">
            {c.customer_phone && <>Phone {c.customer_phone} · </>}
            {c.ambulance_id && <>Ambulance {c.ambulance_id.slice(0, 8)}…</>}
          </div>
        </div>
        <div className="text-right shrink-0 text-[10px] text-[#5E6C84]">{c.assigned_hospital_at ? relativeTime(c.assigned_hospital_at) : (c.created_at ? relativeTime(c.created_at) : "")}</div>
      </div>
      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <button className={T.btnPrimary} onClick={() => setShowAdmit((v) => !v)} data-testid={`hcc-admit-toggle-${c.id}`}>
          <User className="h-3.5 w-3.5" /> Admit patient
        </button>
        <button className={T.btnSecondary} onClick={() => onOpenChat(c.id)} data-testid={`hcc-chat-open-${c.id}`}>
          <MessageSquare className="h-3.5 w-3.5" /> Chat with ambulance
        </button>
      </div>

      {showAdmit && (
        <div className="mt-3 p-3 bg-[#F4F5F7] border border-[#DFE1E6] rounded-md space-y-2" data-testid={`hcc-admit-form-${c.id}`}>
          <div className="text-[11px] uppercase tracking-wider text-[#5E6C84] font-semibold">Admission details</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <label className="text-xs text-[#42526E]">Bed
              <select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={bedId} onChange={(e) => setBedId(e.target.value)}>
                <option value="">— No bed yet —</option>
                {free.map((b) => <option key={b.id} value={b.id}>{b.bed_type} · {b.bed_number}{b.ward ? ` (${b.ward})` : ""}</option>)}
              </select>
            </label>
            <label className="text-xs text-[#42526E]">Triage priority
              <select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={priority} onChange={(e) => setPriority(e.target.value)}>
                <option value="critical">Critical</option><option value="high">High</option>
                <option value="medium">Medium</option><option value="low">Low</option>
              </select>
            </label>
          </div>
          <label className="text-xs text-[#42526E] block">Chief complaint
            <textarea rows={2} className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={chief} onChange={(e) => setChief(e.target.value)} placeholder="e.g. chest pain, road traffic accident, breathlessness…" />
          </label>
          <div className="flex justify-end gap-2">
            <button className={T.btnGhost} onClick={() => setShowAdmit(false)}>Cancel</button>
            <button className={T.btnPrimary} disabled={admitting} onClick={async () => {
              setAdmitting(true);
              try {
                await onAdmit(c.id, { bed_id: bedId || null, chief_complaint: chief || null, triage_priority: priority });
                setShowAdmit(false); setChief(""); setBedId("");
              } finally { setAdmitting(false); }
            }} data-testid={`hcc-admit-submit-${c.id}`}>
              {admitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} Confirm admit
            </button>
          </div>
        </div>
      )}

      {chatOpen && (
        <div className="mt-3 border border-[#DFE1E6] rounded-md overflow-hidden" data-testid={`hcc-chat-${c.id}`}>
          <div className="px-3 py-2 flex items-center justify-between bg-[#F8F9FA] border-b border-[#DFE1E6]">
            <div className="text-[11px] uppercase tracking-wider text-[#5E6C84] font-semibold">Case chat · #{c.id.slice(0, 6)}</div>
            <button className="text-[#5E6C84] hover:text-[#091E42]" onClick={onCloseChat} data-testid={`hcc-chat-close-${c.id}`}><X className="h-4 w-4" /></button>
          </div>
          <div ref={chatBoxRef} className="max-h-56 overflow-y-auto p-3 space-y-2 bg-white">
            {(chatMessages || []).length === 0 ? (
              <div className="text-xs text-[#5E6C84] text-center py-4">No messages yet. Start the conversation.</div>
            ) : (chatMessages || []).map((m) => (
              <div key={m.id} className={`flex ${m.sender_type === "hospital" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] px-3 py-1.5 rounded-lg text-xs ${m.sender_type === "hospital" ? "bg-[#0052CC] text-white" : "bg-[#F4F5F7] text-[#091E42]"}`}>
                  <div className="text-[10px] opacity-70 mb-0.5">{m.sender_type || "them"}</div>
                  <div className="break-words">{m.content}</div>
                  <div className="text-[9px] opacity-60 mt-0.5">{m.created_at ? relativeTime(m.created_at) : ""}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="p-2 border-t border-[#DFE1E6] flex items-center gap-2 bg-[#F8F9FA]">
            <input className="flex-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" placeholder="Message the paramedic…" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && draft.trim()) { onSendChat(c.id, draft); setDraft(""); } }} data-testid={`hcc-chat-input-${c.id}`} />
            <button className={T.btnPrimary} disabled={sending || !draft.trim()} onClick={() => { onSendChat(c.id, draft); setDraft(""); }} data-testid={`hcc-chat-send-${c.id}`}>
              {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Bed grid ────────────────────────────────────────────────────────────────
function BedGrid({ beds, onToggle, onAddBed, addBusy }) {
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ bed_type: "General", bed_number: "", ward: "", daily_rate: "" });
  const groups = beds.reduce((acc, b) => { (acc[b.bed_type] = acc[b.bed_type] || []).push(b); return acc; }, {});
  const types = Object.keys(groups).sort();
  return (
    <section className={T.card} data-testid="hcc-beds">
      <div className={T.sectionHead}>
        <span className="flex items-center gap-1.5"><BedDouble className="h-3 w-3" /> Beds · {beds.filter((b) => b.is_available).length}/{beds.length} free</span>
        <button className={T.btnGhost} onClick={() => setShowAdd((v) => !v)} data-testid="hcc-add-bed-toggle"><Plus className="h-3 w-3" /> Add bed</button>
      </div>
      {showAdd && (
        <div className="p-3 bg-[#F4F5F7] border-b border-[#DFE1E6] grid grid-cols-2 md:grid-cols-5 gap-2 items-end" data-testid="hcc-add-bed-form">
          <label className="text-[11px] text-[#42526E]">Type
            <select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.bed_type} onChange={(e) => setForm({ ...form, bed_type: e.target.value })}>
              {["General", "ICU", "ER", "Ventilator", "Isolation", "Pediatric", "Maternity", "OT"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-[#42526E]">Number
            <input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.bed_number} onChange={(e) => setForm({ ...form, bed_number: e.target.value })} placeholder="e.g. 101" />
          </label>
          <label className="text-[11px] text-[#42526E]">Ward
            <input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.ward} onChange={(e) => setForm({ ...form, ward: e.target.value })} placeholder="Optional" />
          </label>
          <label className="text-[11px] text-[#42526E]">Daily rate
            <input type="number" className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.daily_rate} onChange={(e) => setForm({ ...form, daily_rate: e.target.value })} placeholder="₹" />
          </label>
          <button className={T.btnPrimary} disabled={addBusy || !form.bed_number} onClick={async () => {
            await onAddBed({ ...form, daily_rate: form.daily_rate ? Number(form.daily_rate) : null });
            setForm({ bed_type: "General", bed_number: "", ward: "", daily_rate: "" });
            setShowAdd(false);
          }} data-testid="hcc-add-bed-submit">Create bed</button>
        </div>
      )}
      {beds.length === 0 ? (
        <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="hcc-beds-empty">No beds yet. Click Add bed to register one.</div>
      ) : (
        <div className="p-4 space-y-4">
          {types.map((t) => {
            const list = groups[t];
            const free = list.filter((b) => b.is_available).length;
            return (
              <div key={t} data-testid={`hcc-bedgroup-${t.toLowerCase()}`}>
                <div className="text-[11px] uppercase tracking-wider text-[#5E6C84] font-semibold mb-2">{t} · {free}/{list.length} free</div>
                <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2">
                  {list.map((b) => (
                    <button key={b.id} onClick={() => onToggle(b)} data-testid={`hcc-bed-${b.id}`}
                      className={`px-2 py-2 text-xs rounded border font-mono text-center transition-colors ${b.is_available ? "bg-[#E3FCEF] border-[#57D9A3] text-[#006644] hover:bg-[#ABF5D1]" : "bg-[#FFEBE6] border-[#FF8F73] text-[#BF2600] hover:bg-[#FFBDAD]"}`}>
                      <div className="font-bold">{b.bed_number}</div>
                      <div className="text-[9px] mt-0.5">{b.is_available ? "FREE" : "OCC"}</div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Admissions table with discharge ─────────────────────────────────────────
function AdmissionsTable({ admissions, onDischarge, dischargeBusy }) {
  const [openDischarge, setOpenDischarge] = useState(null);
  const [notes, setNotes] = useState("");
  return (
    <section className={T.card} data-testid="hcc-admissions">
      <div className={T.sectionHead}>
        <span>In-facility · {admissions.length} patient{admissions.length === 1 ? "" : "s"}</span>
      </div>
      {admissions.length === 0 ? (
        <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="hcc-admissions-empty">No active admissions.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
              <tr>
                <th className="px-3 py-2 text-left">Adm #</th>
                <th className="px-3 py-2 text-left">Bed</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-left">Priority</th>
                <th className="px-3 py-2 text-left">Chief complaint</th>
                <th className="px-3 py-2 text-left">Admitted</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {admissions.map((a) => (
                <React.Fragment key={a.id}>
                  <tr className="border-t border-[#DFE1E6]" data-testid={`hcc-admission-${a.id}`}>
                    <td className="px-3 py-2 font-mono text-[#091E42]">{a.admission_number}</td>
                    <td className="px-3 py-2">{a.bed_number || "—"}{a.ward_type ? ` · ${a.ward_type}` : ""}</td>
                    <td className="px-3 py-2">{(a.case_type || a.admission_type || "").replace(/_/g, " ")}</td>
                    <td className="px-3 py-2"><PriorityChip value={a.triage_priority} /></td>
                    <td className="px-3 py-2 max-w-[280px] truncate">{a.chief_complaint || "—"}</td>
                    <td className="px-3 py-2">{a.admission_time ? relativeTime(a.admission_time) : "—"}</td>
                    <td className="px-3 py-2 text-right">
                      <button className={T.btnDanger} onClick={() => { setOpenDischarge(openDischarge === a.id ? null : a.id); setNotes(""); }} data-testid={`hcc-discharge-toggle-${a.id}`}>
                        Discharge
                      </button>
                    </td>
                  </tr>
                  {openDischarge === a.id && (
                    <tr className="bg-[#F4F5F7]"><td colSpan={7} className="p-3">
                      <div className="flex flex-col gap-2">
                        <textarea rows={2} className="text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" placeholder="Discharge notes (added to admission_notes as note_type=discharge)" value={notes} onChange={(e) => setNotes(e.target.value)} data-testid={`hcc-discharge-notes-${a.id}`} />
                        <div className="flex justify-end gap-2">
                          <button className={T.btnGhost} onClick={() => setOpenDischarge(null)}>Cancel</button>
                          <button className={T.btnDanger} disabled={dischargeBusy} onClick={async () => {
                            await onDischarge(a.id, notes);
                            setOpenDischarge(null); setNotes("");
                          }} data-testid={`hcc-discharge-confirm-${a.id}`}>Confirm discharge</button>
                        </div>
                      </div>
                    </td></tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── main page ───────────────────────────────────────────────────────────────
export default function HospitalCommandCenter() {
  const { user } = useAuth();
  const [state, setState] = useState({ loading: true, data: null, err: "" });
  const [busy, setBusy] = useState(false);
  const [chatOpenFor, setChatOpenFor] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatSending, setChatSending] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/hospital/command-center");
      setState({ loading: false, data, err: "" });
      setLastUpdated(Date.now());
    } catch (e) {
      setState({ loading: false, data: null, err: e?.response?.data?.detail || "Could not load command centre" });
    }
  }, []);

  // Initial fetch + SSE realtime stream (fallback to polling if SSE fails)
  useEffect(() => {
    let es = null;
    let fallbackTimer = null;
    let cancelled = false;

    const startFallback = () => {
      if (fallbackTimer) return;
      fallbackTimer = setInterval(load, 3000);
    };

    (async () => {
      await load();
      if (cancelled) return;
      const token = localStorage.getItem("trata_token");
      if (!token) { startFallback(); return; }
      try {
        const base = process.env.REACT_APP_BACKEND_URL || "";
        es = new EventSource(`${base}/api/hospital/command-center/stream?token=${encodeURIComponent(token)}`);
        es.addEventListener("snapshot", (ev) => {
          try {
            const data = JSON.parse(ev.data);
            setState({ loading: false, data, err: "" });
            setLastUpdated(Date.now());
          } catch {
            // malformed frame — ignore
          }
        });
        es.addEventListener("error", () => {
          // Falls through to onerror below if the connection actually drops.
        });
        es.onerror = () => {
          if (es) { es.close(); es = null; }
          // Fall back to polling if SSE is unavailable (proxy stripped it, network blip, etc.)
          startFallback();
        };
      } catch {
        startFallback();
      }
    })();

    return () => {
      cancelled = true;
      if (es) es.close();
      if (fallbackTimer) clearInterval(fallbackTimer);
    };
  }, [load]);

  useEffect(() => {
    if (!chatOpenFor) { setChatMessages([]); return; }
    let cancelled = false;
    const pullChat = async () => {
      try {
        const { data } = await api.get(`/hospital/case-chat/${chatOpenFor}`);
        if (!cancelled) setChatMessages(data.messages || []);
      } catch {
        // swallow: chat polling errors are non-blocking
      }
    };
    pullChat();
    const t = setInterval(pullChat, 3000);
    return () => { cancelled = true; clearInterval(t); };
  }, [chatOpenFor]);

  const doAccept = async (caseId) => {
    setBusy(true);
    try {
      await api.post(`/hospital/emergencies/${caseId}/accept`);
      toast.success("Case accepted");
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Accept failed"); } finally { setBusy(false); }
  };
  const doDecline = async (caseId) => {
    setBusy(true);
    try {
      await api.post(`/hospital/emergencies/${caseId}/decline`, { reason: null });
      toast("Case declined");
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Decline failed"); } finally { setBusy(false); }
  };
  const doAdmit = async (caseId, body) => {
    try {
      const { data } = await api.post(`/hospital/emergencies/${caseId}/admit`, body);
      toast.success(`Admitted · ${data.admission_number}`);
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Admit failed"); throw e; }
  };
  const doDischarge = async (admissionId, notes) => {
    setBusy(true);
    try {
      await api.post(`/hospital/admissions/${admissionId}/discharge`, { outcome: "discharged", notes });
      toast.success("Patient discharged");
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Discharge failed"); } finally { setBusy(false); }
  };
  const doToggleBed = async (bed) => {
    try {
      await api.post(`/hospital/beds/${bed.id}/toggle`, { is_available: !bed.is_available, reason: bed.is_available ? "manual_occupy" : "manual_free" });
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Toggle failed"); }
  };
  const doAddBed = async (body) => {
    try {
      await api.post(`/hospital/beds`, body);
      toast.success("Bed added");
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Create failed"); }
  };
  const doSendChat = async (caseId, content) => {
    setChatSending(true);
    try {
      await api.post(`/hospital/case-chat/${caseId}`, { content, message_type: "text" });
      const { data } = await api.get(`/hospital/case-chat/${caseId}`);
      setChatMessages(data.messages || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Send failed"); } finally { setChatSending(false); }
  };

  if (state.loading) {
    return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="hcc-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading command centre…</div>;
  }
  if (state.err || !state.data) {
    return (
      <div className="p-6 max-w-xl mx-auto mt-10" data-testid="hcc-error">
        <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">Command centre unavailable</div>
            <div className="text-xs mt-1">{state.err || "Unknown error"}</div>
          </div>
        </div>
      </div>
    );
  }

  const { incoming, active, beds, admissions, stats } = state.data;
  const lastUpdatedLabel = lastUpdated ? relativeTime(new Date(lastUpdated).toISOString()) : "just now";

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="hospital-command-center">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><Siren className="h-3 w-3" /> Emergency Command Centre</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{user?.name || "Hospital"}</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Accept incoming SOS, track patients from ambulance → bed → discharge — same data as your mobile Hospital Provider App.</p>
        </div>
        <div className="text-[11px] text-[#5E6C84] flex items-center gap-1" data-testid="hcc-live-badge">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#3ECF8E] animate-pulse" />
          Live push · updated {lastUpdatedLabel}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4" data-testid="hcc-kpis">
        <Tile label="Incoming SOS"    value={incoming.length}      sub="awaiting your response" icon={Radio}       tone="#DE350B" accent />
        <Tile label="Active in-house" value={stats.cases_active}   sub="on the way or admitted" icon={Ambulance}   tone="#0747A6" />
        <Tile label="Beds free"       value={`${stats.beds_free}/${stats.beds_total}`} sub="across all wards" icon={BedDouble} tone="#006644" />
        <Tile label="Admitted today"  value={stats.admissions_today} sub="past 24 hours" icon={Activity} tone="#5243AA" />
        <Tile label="Discharged today" value={stats.discharges_today} sub="past 24 hours" icon={CheckCircle2} tone="#00B8D9" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className={T.card} data-testid="hcc-incoming-section">
          <div className={T.sectionHead}>
            <span className="flex items-center gap-1.5"><Radio className="h-3 w-3" /> Incoming emergencies · {incoming.length}</span>
          </div>
          {incoming.length === 0 ? (
            <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="hcc-incoming-empty">No new SOS broadcasted to you right now.</div>
          ) : incoming.map((c) => (
            <IncomingCard key={c.id} c={c} onAccept={doAccept} onDecline={doDecline} busy={busy} />
          ))}
        </section>

        <section className={T.card} data-testid="hcc-active-section">
          <div className={T.sectionHead}>
            <span className="flex items-center gap-1.5"><Ambulance className="h-3 w-3" /> Active cases · {active.length}</span>
          </div>
          {active.length === 0 ? (
            <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="hcc-active-empty">No active cases assigned to you.</div>
          ) : active.map((c) => (
            <ActiveCard key={c.id} c={c} beds={beds} onAdmit={doAdmit} onOpenChat={setChatOpenFor}
              chatOpenFor={chatOpenFor} chatMessages={chatMessages} onSendChat={doSendChat} sending={chatSending}
              onCloseChat={() => setChatOpenFor(null)} />
          ))}
        </section>
      </div>

      <BedGrid beds={beds} onToggle={doToggleBed} onAddBed={doAddBed} addBusy={busy} />
      <AdmissionsTable admissions={admissions} onDischarge={doDischarge} dischargeBusy={busy} />
      <KycUploader />
    </div>
  );
}


// ── KYC uploader ────────────────────────────────────────────────────────────
function KycUploader() {
  const [docs, setDocs] = useState([]);
  const [docTypes, setDocTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [form, setForm] = useState({ document_type: "hospital_license", document_name: "", file_base64: "", size: 0, filename: "" });

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get("/hospital/kyc/documents");
      setDocs(data.documents || []);
      setDocTypes(data.document_types || []);
    } catch (e) {
      // KYC endpoints require hospital vertical — ignore for others
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const pickFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast.error("File too big (>4 MB)"); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = String(reader.result || "").split(",")[1] || "";
      setForm((prev) => ({ ...prev, file_base64: b64, size: f.size, filename: f.name, document_name: prev.document_name || f.name }));
    };
    reader.readAsDataURL(f);
  };

  const submit = async () => {
    if (!form.file_base64) { toast.error("Choose a file first"); return; }
    setUploading(true);
    try {
      await api.post("/hospital/kyc/upload", {
        document_type: form.document_type,
        document_name: form.document_name || form.filename || form.document_type,
        file_base64: form.file_base64,
      });
      toast.success("Document uploaded to Trata KYC queue");
      setForm({ document_type: "hospital_license", document_name: "", file_base64: "", size: 0, filename: "" });
      await refresh();
    } catch (e) { toast.error(e?.response?.data?.detail || "Upload failed"); } finally { setUploading(false); }
  };

  const statusChip = (s) => {
    const v = String(s || "submitted").toLowerCase();
    const tone =
      v === "approved" || v === "verified" ? "bg-[#E3FCEF] text-[#006644]" :
      v === "rejected" ? "bg-[#FFEBE6] text-[#BF2600]" :
      "bg-[#FFFAE6] text-[#974F0C]";
    return <span className={`${T.chip} ${tone}`}>{v.toUpperCase()}</span>;
  };

  return (
    <section className={T.card} data-testid="hcc-kyc">
      <div className={T.sectionHead}>
        <span>Provider KYC · {docs.length} document{docs.length === 1 ? "" : "s"}</span>
      </div>

      <div className="p-4 bg-[#F4F5F7] border-b border-[#DFE1E6]" data-testid="hcc-kyc-form">
        <div className="text-[11px] uppercase tracking-wider text-[#5E6C84] font-semibold mb-2">Upload a document to Trata KYC</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
          <label className="text-xs text-[#42526E]">Type
            <select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.document_type} onChange={(e) => setForm({ ...form, document_type: e.target.value })} data-testid="hcc-kyc-doc-type">
              {docTypes.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
            </select>
          </label>
          <label className="text-xs text-[#42526E]">Display name
            <input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" placeholder="e.g. Karnataka operating licence 2026" value={form.document_name} onChange={(e) => setForm({ ...form, document_name: e.target.value })} data-testid="hcc-kyc-doc-name" />
          </label>
          <label className="text-xs text-[#42526E]">File (image / PDF, ≤ 4 MB)
            <input type="file" accept="image/*,application/pdf" className="w-full mt-1 text-xs" onChange={pickFile} data-testid="hcc-kyc-file" />
            {form.filename && <div className="text-[10px] text-[#5E6C84] mt-1">{form.filename} · {(form.size / 1024).toFixed(1)} KB</div>}
          </label>
          <button className={T.btnPrimary} disabled={uploading || !form.file_base64} onClick={submit} data-testid="hcc-kyc-upload-submit">
            {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />} Upload
          </button>
        </div>
      </div>

      {loading ? (
        <div className="p-6 text-center text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin inline" /> Loading documents…</div>
      ) : docs.length === 0 ? (
        <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="hcc-kyc-empty">No documents uploaded yet.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
              <tr>
                <th className="px-3 py-2 text-left">Document</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Submitted</th>
                <th className="px-3 py-2 text-left">Reviewed</th>
                <th className="px-3 py-2 text-left">Comment</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-t border-[#DFE1E6]" data-testid={`hcc-kyc-doc-${d.id}`}>
                  <td className="px-3 py-2 text-[#091E42] max-w-[280px] truncate">{d.document_name || "—"}</td>
                  <td className="px-3 py-2">{(d.document_type || "").replace(/_/g, " ")}</td>
                  <td className="px-3 py-2">{statusChip(d.status)}</td>
                  <td className="px-3 py-2">{d.submitted_at ? relativeTime(d.submitted_at) : "—"}</td>
                  <td className="px-3 py-2">{d.reviewed_at ? relativeTime(d.reviewed_at) : "—"}</td>
                  <td className="px-3 py-2 max-w-[300px] truncate">{d.rejection_reason ? `${d.rejection_reason} · ${d.rejection_comment || ""}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
