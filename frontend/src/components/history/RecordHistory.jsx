import React, { useEffect, useState } from "react";
import { History, Loader2, ChevronDown, ChevronRight } from "lucide-react";
import api from "../../lib/api";

const OPS = { INSERT: ["Created", "bg-[#E3FCEF] text-[#006644]"], UPDATE: ["Changed", "bg-[#DEEBFF] text-[#0747A6]"], DELETE: ["Deleted", "bg-[#FFEBE6] text-[#BF2600]"] };
const show = (v) => (v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
const when = (iso) => new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Entry({ e }) {
  const [open, setOpen] = useState(false); const [l, c] = OPS[e.op] || [e.op, ""];
  const keys = e.op === "UPDATE" ? e.changed || [] : Object.keys(e.new_data || e.old_data || {}).slice(0, 20);
  return (
    <li className="relative pl-8 py-2" data-testid={`history-entry-${e.id}`}>
      <span className="absolute left-[9px] top-4 h-2.5 w-2.5 rounded-full bg-white border-2 border-[#0052CC]" />
      <button onClick={() => setOpen(!open)} className="w-full text-left flex flex-wrap items-center gap-2">
        {open ? <ChevronDown className="h-3.5 w-3.5 text-[#5E6C84]" /> : <ChevronRight className="h-3.5 w-3.5 text-[#5E6C84]" />}
        <span className="text-xs text-[#5E6C84]">{when(e.at)}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${c}`}>{l}</span>
        <span className="text-sm font-semibold text-[#091E42] capitalize">{e.table_name.replace(/_/g, " ")}</span>
        {e.op === "UPDATE" && <span className="text-xs text-[#5E6C84] truncate">{(e.changed || []).join(", ")}</span>}
        <span className="text-[11px] text-[#97A0AF] ml-auto">{e.app || "app server (direct DB)"}</span>
      </button>
      {open && <table className="mt-2 ml-5 text-xs w-[calc(100%-1.25rem)]" data-testid={`history-detail-${e.id}`}><tbody>{keys.map((k) => (
        <tr key={k} className="align-top"><td className="py-0.5 pr-3 font-semibold text-[#42526E] w-40">{k}</td>
          {e.op === "UPDATE" && <td className="py-0.5 pr-3 text-[#BF2600] line-through break-all">{show(e.old_data?.[k])}</td>}
          <td className="py-0.5 text-[#006644] break-all">{show((e.new_data || e.old_data)?.[k])}</td></tr>))}</tbody></table>}
    </li>
  );
}

/** Every recorded change to this person/organisation and anything linked to them, oldest first. Master admin only. */
export function RecordHistory({ recordId }) {
  const [s, setS] = useState({ loading: true, items: [], more: false, since: null, err: "" });
  const load = (after = 0) => api.get(`/admin/activity-log/record/${recordId}`, { params: { after_id: after } })
    .then(({ data }) => setS((p) => ({ loading: false, err: "", items: after ? [...p.items, ...data.items] : data.items, more: data.more, since: data.recording_since })))
    .catch((e) => setS((p) => ({ ...p, loading: false, err: e?.response?.data?.detail || "Could not load history" })));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [recordId]);

  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md" data-testid="record-history">
      <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between">
        <span className="flex items-center gap-1"><History className="h-3 w-3" /> Change history · {s.items.length}{s.more ? "+" : ""}</span>
        <span className="normal-case font-normal">Oldest first{s.since ? ` · recorded since ${when(s.since)}` : ""}</span>
      </div>
      {s.loading ? <div className="p-6 text-xs text-[#5E6C84] flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading history…</div>
        : s.err ? <div className="p-4 text-xs text-[#BF2600]" data-testid="record-history-error">{s.err}</div>
        : s.items.length === 0 ? <div className="p-8 text-center text-xs text-[#5E6C84]" data-testid="record-history-empty">No changes recorded for this record yet. Every change from now on will appear here.</div>
        : <ol className="relative px-4 py-2"><div className="absolute left-[29px] top-4 bottom-4 w-px bg-[#DFE1E6]" />{s.items.map((e) => <Entry key={e.id} e={e} />)}</ol>}
      {s.more && <button onClick={() => load(s.items[s.items.length - 1].id)} className="m-4 text-sm font-semibold text-[#0052CC]" data-testid="record-history-more">Load later changes</button>}
    </section>
  );
}

export function DetailTabs({ tab, setTab }) {
  return (
    <div className="inline-flex bg-[#F4F5F7] rounded-md p-0.5" data-testid="detail-tabs">
      {[["overview", "Overview"], ["history", "History"]].map(([k, l]) => (
        <button key={k} onClick={() => setTab(k)} data-testid={`detail-tab-${k}`}
                className={`px-3 py-1.5 text-xs font-semibold rounded ${tab === k ? "bg-white text-[#091E42] shadow-sm" : "text-[#5E6C84] hover:text-[#091E42]"}`}>{l}</button>
      ))}
    </div>
  );
}
