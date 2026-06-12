import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api from "../lib/api";
import { Avatar } from "./Contacts";
import { useAuth } from "../lib/auth";
import {
  ArrowLeft, ShieldCheck, MapPin, Mail, Phone, Loader2, Trophy, Activity as ActivityIcon,
  Users2, ChevronRight, Pencil, Save, X, MessageSquarePlus, Star, Trash2,
} from "lucide-react";
import { roleLabel, roleColor, ROLE_META, TEAM_ROLES, relativeTime } from "../lib/constants";

const EDITABLE_ROLES = TEAM_ROLES.filter((r) => r.value !== "admin");

export default function TeamMemberDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user: me } = useAuth();
  const [member, setMember] = useState(null);
  const [team, setTeam] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ name: "", email: "", role: "", reports_to: "", territories: "" });
  const [fb, setFb] = useState({ rating: 0, note: "" });
  const [posting, setPosting] = useState(false);

  const canEdit = me?.is_master_admin || me?.role === "admin";

  const load = async () => {
    setLoading(true);
    try {
      const [m, t] = await Promise.all([api.get(`/team/${id}`), api.get("/team")]);
      setMember(m.data);
      setTeam(t.data.items);
      setForm({
        name: m.data.name || "",
        email: m.data.email || "",
        role: m.data.role || "",
        reports_to: m.data.reports_to || "",
        territories: (m.data.territories || []).join(", "),
      });
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not load member");
    }
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const validManagerCandidates = useMemo(() => {
    const target = form.role || member?.role;
    const tier = ROLE_META[target]?.tier;
    if (target === "national_manager") return team.filter((m) => m.is_master_admin);
    if (tier == null) return [];
    return team.filter((m) => ROLE_META[m.role]?.tier === tier - 1 && m.id !== id);
  }, [form.role, team, id, member]);

  const save = async () => {
    setErr("");
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        email: form.email.trim() || null,
        role: form.role,
        reports_to: form.reports_to || null,
        territories: form.territories.split(",").map((t) => t.trim()).filter(Boolean),
      };
      await api.patch(`/team/${id}`, payload);
      setEditing(false);
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not save");
    }
    setSaving(false);
  };

  const postFeedback = async () => {
    if (!fb.note.trim()) return;
    setPosting(true);
    try {
      await api.post(`/team/${id}/feedback`, { rating: fb.rating || null, note: fb.note });
      setFb({ rating: 0, note: "" });
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not post feedback");
    }
    setPosting(false);
  };

  const removeFeedback = async (fbId) => {
    if (!window.confirm("Delete this feedback?")) return;
    await api.delete(`/team/${id}/feedback/${fbId}`);
    load();
  };

  if (loading) return <div className="p-8 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 inline animate-spin mr-2" /> Loading…</div>;
  if (!member) return <div className="p-8 text-sm text-[#FF5630]">Member not found</div>;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6 max-w-6xl" data-testid="team-detail-page">
      <button onClick={() => navigate("/team")} data-testid="back-to-team" className="flex items-center gap-1.5 text-sm text-[#5E6C84] hover:text-[#091E42]">
        <ArrowLeft className="h-4 w-4" /> Back to Team & Roles
      </button>

      {/* Header */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5 flex flex-col sm:flex-row items-start gap-4">
        <Avatar name={member.name} size={64} />
        <div className="flex-1 min-w-0">
          {editing ? (
            <input
              data-testid="tm-name-input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="text-2xl font-heading font-bold text-[#091E42] border-b border-[#DFE1E6] focus:border-[#4C9AFF] outline-none bg-transparent w-full"
            />
          ) : (
            <h1 className="font-heading text-2xl sm:text-3xl font-bold text-[#091E42] flex items-center gap-2">
              {member.name}
              {member.is_master_admin && <ShieldCheck className="h-5 w-5 text-[#0052CC]" />}
            </h1>
          )}
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            {editing ? (
              <select data-testid="tm-role-select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value, reports_to: "" })} className="px-2 py-1 text-xs border border-[#DFE1E6] rounded bg-white">
                {EDITABLE_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            ) : (
              <span className="inline-flex items-center px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold rounded text-white" style={{ background: roleColor(member.role) }} data-testid="tm-role-pill">
                {roleLabel(member.role)}
              </span>
            )}
            <span className="text-xs text-[#5E6C84]">joined {relativeTime(member.created_at)}</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-[#42526E]">
            <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" /> +91 {member.phone}</span>
            {editing ? (
              <input data-testid="tm-email-input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="email@example.com" className="text-sm border-b border-[#DFE1E6] focus:border-[#4C9AFF] outline-none bg-transparent" />
            ) : (
              member.email && <span className="inline-flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" /> {member.email}</span>
            )}
          </div>
        </div>
        {canEdit && !member.is_master_admin && (
          <div className="flex gap-2">
            {editing ? (
              <>
                <button onClick={() => { setEditing(false); load(); }} className="flex items-center gap-1 px-3 py-1.5 text-sm border border-[#DFE1E6] rounded hover:bg-[#F4F5F7]" data-testid="tm-cancel-btn">
                  <X className="h-4 w-4" /> Cancel
                </button>
                <button onClick={save} disabled={saving} data-testid="tm-save-btn" className="flex items-center gap-1 px-3 py-1.5 text-sm font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
                </button>
              </>
            ) : (
              <button onClick={() => setEditing(true)} data-testid="tm-edit-btn" className="flex items-center gap-1 px-3 py-1.5 text-sm border border-[#DFE1E6] rounded hover:bg-[#F4F5F7]">
                <Pencil className="h-4 w-4" /> Edit
              </button>
            )}
          </div>
        )}
      </div>
      {err && <div className="text-sm text-[#FF5630]" data-testid="tm-error">{err}</div>}

      {/* Reporting chain */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="tm-hierarchy">
        <div className="overline mb-3">Reporting chain</div>
        {member.reports_chain && member.reports_chain.length > 0 ? (
          <div className="flex items-center gap-2 flex-wrap text-sm" data-testid="tm-chain">
            {[...member.reports_chain].reverse().map((c, i) => (
              <React.Fragment key={c.id}>
                <button onClick={() => navigate(`/team/${c.id}`)} className="flex items-center gap-1.5 px-2.5 py-1 border border-[#DFE1E6] rounded hover:border-[#4C9AFF]">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-white px-1.5 py-0.5 rounded" style={{ background: roleColor(c.role) }}>{ROLE_META[c.role]?.short || "?"}</span>
                  <span className="text-[#091E42] font-medium">{c.name}</span>
                </button>
                <ChevronRight className="h-4 w-4 text-[#5E6C84]" />
              </React.Fragment>
            ))}
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-[#091E42] text-white rounded font-semibold">
              {member.name}
            </span>
          </div>
        ) : (
          <div className="text-sm text-[#5E6C84]" data-testid="tm-no-manager">No reporting manager assigned.{canEdit && " Click Edit to assign one."}</div>
        )}

        {editing && (
          <div className="mt-3" data-testid="tm-reports-to-section">
            <div className="overline mb-1">Reports to</div>
            <select
              data-testid="tm-reports-to-select"
              value={form.reports_to}
              onChange={(e) => setForm({ ...form, reports_to: e.target.value })}
              className="w-full max-w-md px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white"
            >
              <option value="">— No manager —</option>
              {validManagerCandidates.map((m) => (
                <option key={m.id} value={m.id}>{m.name} · {roleLabel(m.role)}</option>
              ))}
            </select>
            <div className="text-[11px] text-[#5E6C84] mt-1">
              {form.role === "national_manager"
                ? "National Managers can only report to the Master Admin."
                : `Only ${roleLabel(Object.entries(ROLE_META).find(([_, v]) => v.tier === (ROLE_META[form.role]?.tier - 1))?.[0])}s can be selected (strict hierarchy).`}
            </div>
          </div>
        )}
      </div>

      {/* Direct reports */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="tm-direct-reports">
        <div className="flex items-center justify-between mb-3">
          <div className="overline flex items-center gap-1.5"><Users2 className="h-3 w-3" /> Direct reports</div>
          <span className="text-xs text-[#5E6C84]">{member.direct_reports.length} member{member.direct_reports.length === 1 ? "" : "s"}</span>
        </div>
        {member.direct_reports.length === 0 ? (
          <div className="text-sm text-[#5E6C84]">Nobody reports to {member.name} yet.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {member.direct_reports.map((r) => (
              <button
                key={r.id}
                onClick={() => navigate(`/team/${r.id}`)}
                data-testid={`tm-report-card-${r.id}`}
                className="text-left flex items-center gap-3 p-3 border border-[#DFE1E6] rounded-md hover:border-[#4C9AFF] hover:shadow-sm transition-colors"
              >
                <Avatar name={r.name} size={36} />
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-[#091E42] truncate text-sm">{r.name}</div>
                  <div className="text-[11px] text-[#5E6C84] truncate">
                    <span className="inline-block px-1.5 py-0.5 rounded text-white font-semibold text-[9px] uppercase tracking-wider mr-1.5" style={{ background: roleColor(r.role) }}>{ROLE_META[r.role]?.short}</span>
                    {r.reports_count > 0 ? `${r.reports_count} reports below` : "leaf"}
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 text-[#5E6C84]" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <StatCard testid="tm-stat-providers" label="Providers handled" value={member.providers_handled} icon={<Users2 className="h-4 w-4" />} accent="#0052CC" subtitle="contacts assigned" />
        <StatCard testid="tm-stat-activities" label="Activities (MTD)" value={member.performance.activities_total} icon={<ActivityIcon className="h-4 w-4" />} accent="#FFAB00" subtitle={member.performance.scope === "team_rollup" ? `${member.performance.team_size - 1} subordinates rolled up` : "this month"} />
        <StatCard testid="tm-stat-onboarded" label="Onboarded (MTD)" value={member.performance.onboarded_mtd} icon={<Trophy className="h-4 w-4" />} accent="#36B37E" subtitle="reached verified/active" />
      </div>

      {/* Territory chips + edit */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="tm-territories">
        <div className="overline flex items-center gap-1.5 mb-2"><MapPin className="h-3 w-3" /> Assigned territories</div>
        {editing ? (
          <input
            data-testid="tm-territories-input"
            value={form.territories}
            onChange={(e) => setForm({ ...form, territories: e.target.value })}
            placeholder="Delhi, Gurugram, Noida"
            className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md"
          />
        ) : member.territories.length === 0 ? (
          <div className="text-sm text-[#5E6C84]">None assigned.</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {member.territories.map((t) => (
              <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 bg-[#DEEBFF] text-[#0747A6] rounded text-xs font-medium">
                <MapPin className="h-3 w-3" /> {t}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Activity timeline */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="tm-activity-timeline">
        <div className="overline mb-3 flex items-center gap-1.5"><ActivityIcon className="h-3 w-3" /> Recent activities</div>
        {member.recent_activities.length === 0 ? (
          <div className="text-sm text-[#5E6C84]">No recent activity logged.</div>
        ) : (
          <ul className="space-y-2 text-sm">
            {member.recent_activities.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-1.5 border-b border-[#F1F2F4] last:border-0">
                <div className="min-w-0">
                  <div className="text-[#091E42] truncate"><b>{a.title || a.category}</b>{a.contact_name ? ` — ${a.contact_name}` : ""}</div>
                  <div className="text-[11px] text-[#5E6C84]">{a.category}{a.outcome ? ` · ${a.outcome}` : ""}</div>
                </div>
                <span className="text-[11px] text-[#5E6C84] shrink-0">{relativeTime(a.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Manager feedback */}
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="tm-feedback">
        <div className="overline mb-3 flex items-center gap-1.5"><MessageSquarePlus className="h-3 w-3" /> Manager feedback</div>

        {/* Compose */}
        <div className="bg-[#FAFBFC] border border-[#DFE1E6] rounded p-3 mb-4">
          <div className="flex items-center gap-1 mb-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                type="button"
                data-testid={`tm-feedback-rating-${n}`}
                onClick={() => setFb({ ...fb, rating: n })}
                className={`p-0.5 ${fb.rating >= n ? "text-[#FFAB00]" : "text-[#DFE1E6]"}`}
                aria-label={`Rate ${n} stars`}
              >
                <Star className="h-4 w-4 fill-current" />
              </button>
            ))}
            {fb.rating > 0 && <span className="text-xs text-[#5E6C84] ml-1">{fb.rating}/5</span>}
          </div>
          <textarea
            data-testid="tm-feedback-note"
            value={fb.note}
            onChange={(e) => setFb({ ...fb, note: e.target.value })}
            placeholder={`Share feedback for ${member.name}…`}
            rows={2}
            className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white focus:border-[#4C9AFF] outline-none"
          />
          <button
            onClick={postFeedback}
            disabled={posting || !fb.note.trim()}
            data-testid="tm-feedback-submit"
            className="mt-2 flex items-center gap-1 px-3 py-1.5 text-sm font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60"
          >
            {posting ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquarePlus className="h-4 w-4" />}
            Post feedback
          </button>
        </div>

        {/* List */}
        {member.feedback.length === 0 ? (
          <div className="text-sm text-[#5E6C84]">No feedback yet.</div>
        ) : (
          <ul className="space-y-3" data-testid="tm-feedback-list">
            {member.feedback.map((f) => (
              <li key={f.id} className="border border-[#DFE1E6] rounded-md p-3" data-testid={`tm-feedback-item-${f.id}`}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[#091E42] text-sm">{f.author_name}</span>
                    <span className="inline-block px-1.5 py-0.5 rounded text-white text-[9px] uppercase tracking-wider font-semibold" style={{ background: roleColor(f.author_role) }}>{ROLE_META[f.author_role]?.short || f.author_role}</span>
                    {f.rating && (
                      <span className="inline-flex items-center gap-0.5 text-[#FFAB00] text-xs">
                        {Array.from({ length: f.rating }).map((_, i) => <Star key={i} className="h-3 w-3 fill-current" />)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-[#5E6C84]">{relativeTime(f.created_at)}</span>
                    {(me?.id === f.author_id || me?.is_master_admin || me?.role === "admin") && (
                      <button onClick={() => removeFeedback(f.id)} data-testid={`tm-feedback-delete-${f.id}`} className="p-1 hover:bg-[#FFEBE6] text-[#5E6C84] hover:text-[#FF5630] rounded">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
                <p className="text-sm text-[#091E42] mt-1.5 whitespace-pre-wrap">{f.note}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, icon, accent, subtitle, testid }) {
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-4" data-testid={testid}>
      <div className="overline flex items-center gap-1.5" style={{ color: accent }}>
        {icon} {label}
      </div>
      <div className="font-heading text-3xl font-bold text-[#091E42] mt-1">{value?.toLocaleString?.() ?? value}</div>
      {subtitle && <div className="text-[11px] text-[#5E6C84] mt-1">{subtitle}</div>}
    </div>
  );
}
