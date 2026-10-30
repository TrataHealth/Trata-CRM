import React, { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bell, Check, X, UserPlus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";

const ROLE = { provider_admin: "Provider admin / owner", provider_staff: "Provider staff" };
const STATUS = { pending: "bg-[#FFFAE6] text-[#974F0C]", approved: "bg-[#E3FCEF] text-[#006644]", declined: "bg-[#FFEBE6] text-[#BF2600]" };

function RequestCard({ r, onDone }) {
  const [busy, setBusy] = useState(false);
  const act = async (action) => {
    const note = action === "decline" ? window.prompt("Reason for declining (optional)") : "";
    if (note === null) return;
    setBusy(true);
    try { await api.post(`/admin/access-requests/${r.id}`, { action, note }); toast.success(action === "approve" ? "Marked approved" : "Declined"); onDone(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
    setBusy(false);
  };
  return (
    <li className="p-4 border-b border-[#F4F5F7] last:border-0" data-testid={`access-request-${r.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <b className="text-[#091E42]">{r.name}</b>
            <span className="text-xs text-[#5E6C84]">+91 {r.phone}</span>
            <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${STATUS[r.status]}`} data-testid={`access-status-${r.id}`}>{r.status}</span>
          </div>
          <div className="text-sm text-[#42526E] mt-1">{ROLE[r.role_wanted]} at <Link to={`/contacts/${r.provider_contact_id}`} className="font-semibold text-[#0052CC] hover:underline">{r.provider_name}</Link>
            <span className="text-xs text-[#5E6C84] capitalize"> · {(r.provider_type || "").replace(/_/g, " ")}</span></div>
          {r.note && <p className="text-sm text-[#5E6C84] mt-1 italic">“{r.note}”</p>}
          <div className="text-[11px] text-[#97A0AF] mt-1">{relativeTime(r.created_at)}{r.decided_at ? ` · ${r.status} by ${r.decided_by} ${relativeTime(r.decided_at)}` : ""}{r.decision_note ? ` — ${r.decision_note}` : ""}</div>
        </div>
        {r.status === "pending" && <div className="flex gap-2 shrink-0">
          {r.provider_user_id && <Link to={`/admin/onboarding/${r.provider_user_id}`} className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-md border border-[#DFE1E6] text-[#42526E] hover:bg-[#F4F5F7]" data-testid={`access-open-provider-${r.id}`}><UserPlus className="h-3.5 w-3.5" /> Open provider</Link>}
          <button onClick={() => act("approve")} disabled={busy} className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#36B37E] text-white hover:bg-[#00875A] disabled:opacity-50" data-testid={`access-approve-${r.id}`}><Check className="h-3.5 w-3.5" /> Approve</button>
          <button onClick={() => act("decline")} disabled={busy} className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-md text-[#BF2600] hover:bg-[#FFEBE6] disabled:opacity-50" data-testid={`access-decline-${r.id}`}><X className="h-3.5 w-3.5" /> Decline</button>
        </div>}
      </div>
    </li>
  );
}

function Feed({ items, onRead }) {
  if (!items.length) return <div className="p-10 text-center text-sm text-[#5E6C84]" data-testid="centre-empty">No notifications yet.</div>;
  return <ul>{items.map((n) => (
    <li key={n.id} className={`px-4 py-3 border-b border-[#F4F5F7] last:border-0 flex items-start gap-3 ${n.is_read ? "" : "bg-[#DEEBFF]/40"}`} data-testid={`centre-item-${n.id}`}>
      <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${n.is_read ? "bg-[#DFE1E6]" : "bg-[#0052CC]"}`} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-[#091E42]">{n.link ? <Link to={n.link} onClick={() => onRead(n.id)} className="hover:underline">{n.title}</Link> : n.title}</div>
        {(n.message || n.body) && <div className="text-sm text-[#42526E]">{n.message || n.body}</div>}
        <div className="text-[11px] text-[#97A0AF] mt-0.5"><span className="capitalize">{(n.kind || "update").replace(/_/g, " ")}</span> · {relativeTime(n.created_at)}</div>
      </div>
      {!n.is_read && <button onClick={() => onRead(n.id)} className="text-[11px] text-[#0052CC] shrink-0" data-testid={`centre-read-${n.id}`}>Mark read</button>}
    </li>))}</ul>;
}

export default function NotificationCentre() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "all";
  const [s, setS] = useState({ loading: true, items: [], unread: 0, pending: 0, reqs: [] });
  const [status, setStatus] = useState("pending");

  const load = useCallback(async () => {
    const [c, r] = await Promise.all([api.get("/admin/notification-centre"), api.get("/admin/access-requests", { params: { status: status || undefined } })]);
    setS({ loading: false, items: c.data.items, unread: c.data.unread, pending: c.data.pending_access, reqs: r.data.items });
  }, [status]);
  useEffect(() => { load().catch(() => setS((p) => ({ ...p, loading: false }))); }, [load]);
  const read = async (id) => { await api.post("/admin/notification-centre/read", id ? { id } : {}); load(); };

  const tabs = [["all", `All${s.unread ? ` · ${s.unread} new` : ""}`], ["access", `Access requests${s.pending ? ` · ${s.pending}` : ""}`]];
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="notification-centre">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1.5"><Bell className="h-3.5 w-3.5" /> Trata Health Admin</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Notification Centre</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Provider access requests, sign-ups, KYC and every other alert meant for you.</p>
        </div>
        {tab === "all" && s.unread > 0 && <button onClick={() => read()} className="text-sm font-semibold text-[#0052CC]" data-testid="centre-read-all">Mark all read</button>}
      </div>
      <div className="flex gap-1.5 border-b border-[#DFE1E6]">{tabs.map(([k, l]) => (
        <button key={k} onClick={() => setSp({ tab: k })} className={`px-3 py-2 text-sm font-semibold border-b-2 -mb-px ${tab === k ? "border-[#0052CC] text-[#0052CC]" : "border-transparent text-[#5E6C84] hover:text-[#091E42]"}`} data-testid={`centre-tab-${k}`}>{l}</button>))}</div>
      {tab === "access" && <div className="flex gap-1.5">{[["pending", "Pending"], ["approved", "Approved"], ["declined", "Declined"], ["", "All"]].map(([k, l]) => (
        <button key={l} onClick={() => setStatus(k)} className={`text-xs px-3 py-1.5 rounded-full border ${status === k ? "bg-[#091E42] text-white border-[#091E42]" : "border-[#DFE1E6] text-[#42526E]"}`} data-testid={`access-filter-${l.toLowerCase()}`}>{l}</button>))}</div>}
      <section className="bg-white border border-[#DFE1E6] rounded-md">
        {s.loading ? <div className="p-6 text-xs text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
          : tab === "access" ? (s.reqs.length ? <ul>{s.reqs.map((r) => <RequestCard key={r.id} r={r} onDone={load} />)}</ul>
            : <div className="p-10 text-center text-sm text-[#5E6C84]" data-testid="access-empty">No {status || ""} access requests.</div>)
          : <Feed items={s.items} onRead={read} />}
      </section>
    </div>
  );
}
