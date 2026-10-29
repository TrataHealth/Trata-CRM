import React, { useEffect, useRef, useState } from "react";
import { Activity, ShieldCheck, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";

const OPS = { INSERT: ["Created", "bg-[#E3FCEF] text-[#006644]"], UPDATE: ["Changed", "bg-[#DEEBFF] text-[#0747A6]"], DELETE: ["Deleted", "bg-[#FFEBE6] text-[#BF2600]"] };
const label = (t) => t.replace(/_/g, " ");
const show = (v) => (v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

function Health({ h, onTrack }) {
  return (
    <section className="bg-white border border-[#DFE1E6] rounded-lg p-5" data-testid="audit-health">
      <div className="font-heading font-bold text-[#091E42] flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-[#36B37E]" /> Sync health</div>
      <p className="text-xs text-[#5E6C84] mt-0.5">Tracked tables record every change from every app in the same step as the change — nothing can be skipped.</p>
      <div className="text-xs mt-2 flex flex-wrap gap-x-4 gap-y-1" data-testid="audit-summary">
        <span><b className="text-[#006644]">{h.covered.length}</b> tables tracked</span>
        <span className={h.auto_attach ? "text-[#006644]" : "text-[#BF2600]"} data-testid="audit-auto-attach">{h.auto_attach ? "New tables are tracked automatically" : "Auto-tracking of new tables is off"}</span>
        {h.skipped_noisy.length > 0 && <span className="text-[#5E6C84]" title={h.skipped_noisy.map((u) => u.table).join(", ")} data-testid="audit-skipped">{h.skipped_noisy.length} noisy tables skipped (chats, OTPs, caches, queues)</span>}
      </div>
      <div className="flex flex-wrap gap-2 mt-3 max-h-40 overflow-y-auto">{h.covered.filter((c) => c.last_24h > 0).map((c) => (
        <span key={c.table} className="text-xs px-2 py-1 rounded bg-[#E3FCEF] text-[#006644]" data-testid={`audit-covered-${c.table}`}>{label(c.table)} · <b>{c.last_24h}</b> today</span>))}</div>
      {h.uncovered_with_data.length > 0 && <>
        <div className="text-[11px] font-bold uppercase tracking-wider text-[#974F0C] mt-4">Not tracked yet ({h.uncovered_with_data.length} tables with data)</div>
        <div className="flex flex-wrap gap-2 mt-2">{h.uncovered_with_data.slice(0, 24).map((u) => (
          <button key={u.table} onClick={() => onTrack(u.table)} className="text-xs px-2 py-1 rounded border border-[#FFE380] bg-[#FFFAE6] text-[#974F0C] hover:bg-[#FFF0B3] inline-flex items-center gap-1" data-testid={`audit-track-${u.table}`}>
            <Plus className="h-3 w-3" />{label(u.table)} <span className="opacity-70">({u.rows})</span></button>))}</div>
      </>}
      {h.apps_7d.length > 0 && <div className="text-xs text-[#5E6C84] mt-3">Changes by source · 7 days: {h.apps_7d.map((a) => `${a.app} ${a.n}`).join(" · ")}</div>}
    </section>
  );
}

function Row({ e }) {
  const [open, setOpen] = useState(false); const [l, c] = OPS[e.op] || [e.op, ""];
  const keys = e.op === "UPDATE" ? e.changed || [] : Object.keys(e.new_data || e.old_data || {}).slice(0, 14);
  return (
    <div className="border-b border-[#F4F5F7] last:border-0" data-testid={`audit-row-${e.id}`}>
      <button onClick={() => setOpen(!open)} className="w-full text-left flex items-center gap-2 sm:gap-3 py-2.5 hover:bg-[#F8F9FA] px-1 sm:px-2 min-w-0">
        {open ? <ChevronDown className="h-3.5 w-3.5 text-[#5E6C84] shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-[#5E6C84] shrink-0" />}
        <span className="text-xs text-[#5E6C84] w-24 sm:w-36 shrink-0">{new Date(e.at).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${c}`}>{l}</span>
        <span className="text-sm font-semibold text-[#091E42] capitalize">{label(e.table_name)}</span>
        <span className="text-xs text-[#5E6C84] truncate flex-1">{e.op === "UPDATE" ? (e.changed || []).join(", ") : e.row_id}</span>
        <span className="text-[11px] text-[#5E6C84] shrink-0 hidden md:inline">{e.app || "app server (direct DB)"}</span>
      </button>
      {open && <div className="px-9 pb-3 text-xs" data-testid={`audit-detail-${e.id}`}>
        <div className="text-[#5E6C84] mb-1">Record {e.row_id} · source {e.app || "app server (direct DB)"} · db role {e.db_role}</div>
        <table className="w-full"><tbody>{keys.map((k) => (
          <tr key={k} className="align-top"><td className="py-0.5 pr-3 font-semibold text-[#42526E] w-48">{k}</td>
            {e.op === "UPDATE" && <td className="py-0.5 pr-3 text-[#BF2600] break-all line-through">{show(e.old_data?.[k])}</td>}
            <td className="py-0.5 text-[#006644] break-all">{show((e.new_data || e.old_data)?.[k])}</td></tr>))}</tbody></table>
      </div>}
    </div>
  );
}

const SCOPES = {
  patient: ["Patient app", "Patient App Activity", "Every change patients make in the Patient app — sign-ups, bookings, orders, consents, health records — live."],
  provider: ["Provider app", "Provider App Activity", "Every change providers make in the Provider app and TrataX — profiles, KYC, beds, labs, pharmacy, staff — live."],
};

export default function AuditLog({ scope }) {
  const [h, setH] = useState(null); const [items, setItems] = useState([]); const [f, setF] = useState({ table: "", op: "" }); const [err, setErr] = useState(""); const [more, setMore] = useState(true);
  const cursor = useRef(null);
  const params = () => ({ table: f.table || undefined, op: f.op || undefined, scope });
  const [kicker, title, blurb] = SCOPES[scope] || ["All apps", "Live Audit", "Every change made by the Patient app, Provider app, TrataX and this console — live."];
  const tables = h ? h.covered.filter((c) => !scope || c.scope.includes(scope)) : [];
  const loadHealth = () => api.get("/admin/activity-log/health").then((r) => setH(r.data)).catch((e) => setErr(e?.response?.data?.detail || "Could not load"));
  useEffect(() => { loadHealth(); }, []);
  useEffect(() => {
    let alive = true;
    api.get("/admin/activity-log", { params: { ...params(), limit: 50 } }).then((r) => { setItems(r.data.items); setMore(r.data.items.length === 50); cursor.current = r.data.cursor_txid; });
    const t = setInterval(async () => {
      if (cursor.current == null) return;
      try {
        const { data } = await api.get("/admin/activity-log", { params: { ...params(), after_txid: cursor.current, limit: 200 } });
        cursor.current = data.cursor_txid;
        if (alive && data.items.length) setItems((x) => { const have = new Set(x.map((i) => i.id)); return [...data.items.filter((i) => !have.has(i.id)).reverse(), ...x].slice(0, 500); });
      } catch { /* retry next tick */ }
    }, 10000);
    return () => { alive = false; clearInterval(t); };
    // eslint-disable-next-line
  }, [f.table, f.op, scope]);
  useEffect(() => { setF({ table: "", op: "" }); }, [scope]);
  const older = () => api.get("/admin/activity-log", { params: { ...params(), before_id: items[items.length - 1]?.id, limit: 50 } }).then((r) => { setItems((x) => [...x, ...r.data.items]); setMore(r.data.items.length === 50); });
  const track = async (t) => { try { await api.post("/admin/activity-log/install", { tables: [t] }); toast.success(`Now tracking ${label(t)}`); loadHealth(); } catch (e) { toast.error(e?.response?.data?.detail || "Could not start tracking"); } };
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="audit-log-page">
      <div><div className="overline flex items-center gap-1.5"><Activity className="h-3.5 w-3.5" /> {kicker}</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="audit-title">{title}</h1>
        <p className="text-sm text-[#5E6C84] mt-1">{blurb}</p></div>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="audit-error">{err}</div>}
      {h && !scope && <Health h={h} onTrack={track} />}
      {h && <section className="bg-white border border-[#DFE1E6] rounded-lg p-4">
        <div className="flex flex-wrap gap-2 mb-3">
          <select className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" value={f.table} onChange={(e) => setF({ ...f, table: e.target.value })} data-testid="audit-filter-table">
            <option value="">{`All tracked tables (${tables.length})`}</option>{tables.map((c) => <option key={c.table} value={c.table}>{label(c.table)}</option>)}</select>
          <select className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" value={f.op} onChange={(e) => setF({ ...f, op: e.target.value })} data-testid="audit-filter-op">
            <option value="">All actions</option><option value="INSERT">Created</option><option value="UPDATE">Changed</option><option value="DELETE">Deleted</option></select>
        </div>
        {items.length === 0 ? <div className="text-sm text-[#5E6C84] py-8 text-center" data-testid="audit-empty">No changes recorded yet. New activity in any app shows up here within seconds.</div>
          : <div data-testid="audit-feed">{items.map((e) => <Row key={e.id} e={e} />)}</div>}
        {more && items.length > 0 && <button onClick={older} className="mt-3 text-sm font-semibold text-[#0052CC]" data-testid="audit-older">Load older</button>}
      </section>}
    </div>
  );
}
