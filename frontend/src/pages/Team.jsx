import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Avatar } from "./Contacts";
import { Plus, Trash2, Loader2, ShieldCheck, ChevronRight, Users2, MapPin } from "lucide-react";
import { relativeTime } from "../lib/constants";
import { TEAM_ROLES, ROLE_META, roleLabel, roleColor } from "../lib/constants";

const ADDABLE_ROLES = TEAM_ROLES.filter((r) => r.value !== "admin");

export default function Team() {
  const navigate = useNavigate();
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: "", phone: "", email: "", role: "sales_rep", reports_to: "" });
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true);
    const { data } = await api.get("/team");
    setList(data.items);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const validManagerCandidates = useMemo(() => {
    const target = form.role;
    const tier = ROLE_META[target]?.tier;
    if (target === "national_manager") return list.filter((m) => m.is_master_admin);
    if (tier == null) return [];
    return list.filter((m) => ROLE_META[m.role]?.tier === tier - 1);
  }, [form.role, list]);

  const add = async () => {
    setErr("");
    if (!form.name || !form.phone) return setErr("Name and phone are required");
    setAdding(true);
    try {
      const payload = { ...form };
      if (!payload.reports_to) delete payload.reports_to;
      await api.post("/team", payload);
      setForm({ name: "", phone: "", email: "", role: "sales_rep", reports_to: "" });
      load();
    } catch (e) { setErr(e?.response?.data?.detail || "Failed"); }
    setAdding(false);
  };

  const del = async (e, id) => {
    e.stopPropagation();
    if (!window.confirm("Remove this team member? Their reports will be unlinked.")) return;
    await api.delete(`/team/${id}`);
    load();
  };

  // Group by tier
  const byTier = useMemo(() => {
    const groups = {};
    list.forEach((m) => {
      const meta = ROLE_META[m.role] || { tier: 99 };
      (groups[meta.tier] = groups[meta.tier] || []).push(m);
    });
    return Object.entries(groups).sort((a, b) => Number(a[0]) - Number(b[0]));
  }, [list]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6" data-testid="team-page">
      <div>
        <div className="overline">Access Control</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Team & Roles</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Manage internal Trata staff. Click any member card to view their full profile and hierarchy.</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="team-add-form">
        <div className="overline mb-3">Add team member</div>
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2">
          <input data-testid="team-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Full name" className="md:col-span-3 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" />
          <input data-testid="team-phone-input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/[^0-9]/g, "") })} placeholder="Phone (10 digit)" maxLength={10} className="md:col-span-2 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" />
          <input data-testid="team-email-input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="Email" className="md:col-span-3 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" />
          <select data-testid="team-role-select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value, reports_to: "" })} className="md:col-span-2 px-2 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white">
            {ADDABLE_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <select
            data-testid="team-reports-to-select"
            value={form.reports_to}
            onChange={(e) => setForm({ ...form, reports_to: e.target.value })}
            className="md:col-span-1 px-2 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white"
            disabled={validManagerCandidates.length === 0}
            title={validManagerCandidates.length === 0 ? "No valid manager available yet" : "Reports to"}
          >
            <option value="">No manager</option>
            {validManagerCandidates.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <button data-testid="team-add-btn" onClick={add} disabled={adding} className="md:col-span-1 flex items-center justify-center gap-1 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md hover:bg-[#0747A6] disabled:opacity-60">
            {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          </button>
        </div>
        <div className="text-[11px] text-[#5E6C84] mt-2">
          Reporting rule: each role can only report to the role immediately above (e.g., Sales Rep → Area Manager).
        </div>
        {err && <div className="text-xs text-[#FF5630] mt-2" data-testid="team-error">{err}</div>}
      </div>

      {loading ? (
        <div className="text-sm text-[#5E6C84] py-8 text-center"><Loader2 className="h-4 w-4 inline animate-spin mr-2" /> Loading team…</div>
      ) : (
        <div className="space-y-5" data-testid="team-tiers">
          {byTier.map(([tier, members]) => (
            <section key={tier} data-testid={`team-tier-${tier}`}>
              <div className="overline mb-2 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ background: roleColor(members[0]?.role) }} />
                Tier {tier} · {roleLabel(members[0]?.role)}{members.length > 1 ? "s" : ""}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {members.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => navigate(`/team/${m.id}`)}
                    data-testid={`team-card-${m.id}`}
                    className="text-left bg-white border border-[#DFE1E6] rounded-md p-4 flex items-start gap-3 hover:border-[#4C9AFF] hover:shadow-sm transition-colors group"
                  >
                    <Avatar name={m.name} size={44} />
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-[#091E42] flex items-center gap-1.5 truncate">
                        {m.name}
                        {m.is_master_admin && <ShieldCheck className="h-3.5 w-3.5 text-[#0052CC] shrink-0" title="Trata Health Admin" />}
                      </div>
                      <div className="text-xs text-[#5E6C84] truncate">+91 {m.phone}{m.email ? ` · ${m.email}` : ""}</div>
                      <div className="mt-2 flex items-center gap-2 flex-wrap">
                        <span className="inline-flex items-center px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold rounded text-white" style={{ background: roleColor(m.role) }}>
                          {roleLabel(m.role)}
                        </span>
                        {m.reports_count > 0 && (
                          <span className="inline-flex items-center gap-1 text-[10px] text-[#42526E]"><Users2 className="h-3 w-3" /> {m.reports_count} reports</span>
                        )}
                        {(m.territories || []).slice(0, 2).map((t) => (
                          <span key={t} className="inline-flex items-center gap-0.5 text-[10px] text-[#5E6C84]"><MapPin className="h-3 w-3" /> {t}</span>
                        ))}
                      </div>
                      <div className="mt-2 text-[11px] text-[#5E6C84]">
                        {m.manager_name ? (
                          <>Reports to <span className="text-[#091E42] font-medium">{m.manager_name}</span></>
                        ) : (
                          <span className="italic">No manager assigned</span>
                        )}
                        <span className="mx-1.5">·</span>joined {relativeTime(m.created_at)}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1.5">
                      <ChevronRight className="h-4 w-4 text-[#5E6C84] group-hover:text-[#0052CC]" />
                      {!m.is_master_admin && (
                        <button onClick={(e) => del(e, m.id)} data-testid={`team-delete-${m.id}`} className="p-1.5 hover:bg-[#FFEBE6] text-[#5E6C84] hover:text-[#FF5630] rounded">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
