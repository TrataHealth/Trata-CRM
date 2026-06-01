import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../lib/api";
import {
  ArrowLeft, Phone, Mail, MapPin, CheckCircle2, XCircle, Sparkles, Loader2,
  Activity as ActivityIcon, ListChecks, StickyNote, ChevronRight,
} from "lucide-react";
import { Avatar } from "./Contacts";
import {
  PIPELINE_STAGES, ACTIVITY_CATEGORIES, statusColor, typeLabel, fmtCurrency, relativeTime, stageLabel,
} from "../lib/constants";

export default function ContactDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("activity");
  const [aiText, setAiText] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiMode, setAiMode] = useState("summary");
  const [newNote, setNewNote] = useState("");

  const load = async () => {
    const { data } = await api.get(`/contacts/${id}`);
    setData(data);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const updateStage = async (stage) => {
    await api.patch(`/contacts/${id}`, { pipeline_stage: stage });
    load();
  };
  const updateVerified = async (v) => {
    await api.patch(`/contacts/${id}`, { is_verified: v });
    load();
  };

  const runAi = async (mode) => {
    setAiMode(mode); setAiLoading(true); setAiText("");
    try {
      const { data } = await api.post("/ai/insight", { contact_id: id, mode });
      setAiText(data.text);
    } catch (e) { setAiText("AI request failed."); }
    setAiLoading(false);
  };

  const addNote = async () => {
    if (!newNote.trim()) return;
    await api.post("/notes", { contact_id: id, body: newNote });
    setNewNote("");
    load();
  };

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]">Loading…</div>;
  const c = data.contact;
  const stage = PIPELINE_STAGES.find((s) => s.value === c.pipeline_stage);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6 max-w-7xl" data-testid="contact-detail-page">
      <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-xs uppercase tracking-wider font-semibold text-[#5E6C84] hover:text-[#091E42]">
        <ArrowLeft className="h-3.5 w-3.5" /> Back
      </button>

      {/* Header card */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-6">
        <div className="flex flex-wrap items-start gap-6">
          <Avatar name={c.name} src={c.avatar} size={72} />
          <div className="flex-1 min-w-0">
            <div className="overline">{typeLabel(c.type)} · {c.meta?.license_number || "—"}</div>
            <h1 className="font-heading text-3xl font-black tracking-tight text-[#091E42] mt-1">{c.name}</h1>
            <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-[#5E6C84]">
              <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" /> +91 {c.phone}</span>
              {c.email && <span className="inline-flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" /> {c.email}</span>}
              {c.city && <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> {c.city}, {c.state}</span>}
            </div>
            {c.specialization && <div className="mt-1 text-sm text-[#42526E]">{c.specialization}</div>}
          </div>
          <div className="grid grid-cols-2 gap-3 w-full sm:w-auto sm:min-w-[280px]">
            <Metric label="Stage" value={
              <span className="inline-flex px-2 py-0.5 text-xs uppercase tracking-wider font-semibold rounded" style={{ background: `${stage?.color}15`, color: stage?.color }}>
                {stage?.label || "—"}
              </span>
            } />
            <Metric label="Status" value={c.is_verified
              ? <span className="inline-flex items-center gap-1 text-[#36B37E] text-sm font-semibold"><CheckCircle2 className="h-4 w-4" /> Verified</span>
              : <span className="inline-flex items-center gap-1 text-[#FFAB00] text-sm font-semibold"><XCircle className="h-4 w-4" /> Pending</span>
            } />
            <Metric label="Deal Value" value={fmtCurrency(c.deal_value || 0)} />
            <Metric label="Activities" value={data.activities.length} />
          </div>
        </div>

        {/* Quick actions */}
        <div className="mt-5 pt-5 border-t border-[#F1F2F4] flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="overline">Move stage</span>
            <select
              data-testid="stage-select"
              value={c.pipeline_stage || ""}
              onChange={(e) => updateStage(e.target.value)}
              className="px-2 py-1.5 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
            >
              {PIPELINE_STAGES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <button
            data-testid="toggle-verified-btn"
            onClick={() => updateVerified(!c.is_verified)}
            className="px-3 py-1.5 text-sm border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]"
          >
            {c.is_verified ? "Mark as Pending" : "Mark as Verified"}
          </button>
        </div>
      </div>

      {/* AI Insights */}
      <div className="bg-gradient-to-br from-[#091E42] to-[#0747A6] text-white rounded-md p-4 sm:p-6" data-testid="ai-panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-white/70"><Sparkles className="h-3.5 w-3.5 text-[#79E2F2]" /> Claude AI Insights</div>
            <div className="font-heading text-lg sm:text-xl font-bold mt-1">Get instant context on this {typeLabel(c.type).toLowerCase()}</div>
          </div>
          <div className="flex flex-wrap gap-2 w-full sm:w-auto">
            <AiBtn onClick={() => runAi("summary")} active={aiMode === "summary"} testid="ai-summary-btn">Summarize</AiBtn>
            <AiBtn onClick={() => runAi("next_action")} active={aiMode === "next_action"} testid="ai-next-action-btn">Next action</AiBtn>
            <AiBtn onClick={() => runAi("draft_email")} active={aiMode === "draft_email"} testid="ai-draft-email-btn">Draft message</AiBtn>
          </div>
        </div>
        <div className="mt-4 bg-white/10 rounded-md p-4 min-h-[120px] whitespace-pre-wrap text-sm leading-relaxed" data-testid="ai-output">
          {aiLoading ? (
            <div className="flex items-center gap-2 text-white/70"><Loader2 className="h-4 w-4 animate-spin" /> Generating insight…</div>
          ) : aiText ? aiText : (
            <div className="text-white/60">Click any action above. Powered by Claude Sonnet (Anthropic) via Emergent LLM.</div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div>
        <div className="flex overflow-x-auto scrollbar-thin border-b border-[#DFE1E6]" data-testid="detail-tabs">
          <Tab active={tab === "activity"} onClick={() => setTab("activity")} icon={ActivityIcon} label={`Activity (${data.activities.length})`} testid="tab-activity" />
          <Tab active={tab === "tasks"} onClick={() => setTab("tasks")} icon={ListChecks} label={`Tasks (${data.tasks.length})`} testid="tab-tasks" />
          <Tab active={tab === "notes"} onClick={() => setTab("notes")} icon={StickyNote} label={`Notes (${data.notes.length})`} testid="tab-notes" />
        </div>

        <div className="py-4">
          {tab === "activity" && (
            <div className="space-y-2">
              {data.activities.length === 0 && <div className="text-sm text-[#5E6C84] py-8 text-center">No activity yet.</div>}
              {data.activities.map((a) => {
                const cat = ACTIVITY_CATEGORIES.find((x) => x.value === a.category);
                return (
                  <div key={a.id} className="bg-white border border-[#DFE1E6] rounded-md p-3 flex items-start gap-4" data-testid={`activity-${a.id}`}>
                    <div className="h-8 w-8 rounded-md flex items-center justify-center text-[11px] font-bold" style={{ background: `${cat?.color}15`, color: cat?.color }}>
                      {cat?.label.split(" ")[0].slice(0, 3).toUpperCase() || "ACT"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-[#091E42]">{a.title}</div>
                      <div className="text-xs text-[#5E6C84] mt-0.5">{a.description}</div>
                    </div>
                    <div className="text-right shrink-0">
                      <span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded" style={{ background: `${statusColor(a.status)}15`, color: statusColor(a.status) }}>
                        {a.status}
                      </span>
                      <div className="text-[11px] text-[#5E6C84] mt-1">{relativeTime(a.created_at)}</div>
                      {a.amount > 0 && <div className="text-xs text-[#091E42] font-mono mt-1">{fmtCurrency(a.amount)}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {tab === "tasks" && (
            <div className="space-y-2">
              {data.tasks.length === 0 && <div className="text-sm text-[#5E6C84] py-8 text-center">No tasks for this contact.</div>}
              {data.tasks.map((t) => (
                <div key={t.id} className="bg-white border border-[#DFE1E6] rounded-md p-3 flex items-center gap-3">
                  <span className="h-2 w-2 rounded-full" style={{ background: statusColor(t.status) }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-[#091E42]">{t.title}</div>
                    <div className="text-xs text-[#5E6C84]">{t.description}</div>
                  </div>
                  <span className="text-xs uppercase font-semibold text-[#5E6C84]">{t.priority}</span>
                  <span className="text-xs text-[#5E6C84]">{relativeTime(t.due_date)}</span>
                </div>
              ))}
            </div>
          )}
          {tab === "notes" && (
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  data-testid="new-note-input"
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  placeholder="Add a note about this contact…"
                  className="flex-1 px-3 py-2 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
                  onKeyDown={(e) => e.key === "Enter" && addNote()}
                />
                <button
                  data-testid="add-note-btn"
                  onClick={addNote}
                  className="px-4 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md hover:bg-[#0747A6]"
                >Add</button>
              </div>
              {data.notes.length === 0 && <div className="text-sm text-[#5E6C84] py-6 text-center">No notes yet.</div>}
              {data.notes.map((n) => (
                <div key={n.id} className="bg-white border border-[#DFE1E6] rounded-md p-3">
                  <div className="text-sm text-[#091E42]">{n.body}</div>
                  <div className="text-[11px] text-[#5E6C84] mt-1">{n.author_name} · {relativeTime(n.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="bg-[#F8F9FA] rounded-md p-3 border border-[#DFE1E6]">
      <div className="overline">{label}</div>
      <div className="mt-1 text-base font-heading font-bold text-[#091E42]">{value}</div>
    </div>
  );
}

function AiBtn({ children, onClick, active, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
        active ? "bg-[#79E2F2] text-[#091E42]" : "bg-white/10 text-white hover:bg-white/20"
      }`}
    >
      {children}
    </button>
  );
}

function Tab({ active, onClick, icon: Icon, label, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`px-4 py-2.5 text-sm font-semibold flex items-center gap-2 border-b-2 -mb-px transition-colors ${
        active ? "border-[#0052CC] text-[#0052CC]" : "border-transparent text-[#5E6C84] hover:text-[#091E42]"
      }`}
    >
      <Icon className="h-4 w-4" /> {label}
    </button>
  );
}
