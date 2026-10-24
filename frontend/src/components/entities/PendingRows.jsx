import React, { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import api from "../../lib/api";
import { KIND_LABEL, FIELDS, toPayload } from "../../lib/entityFields";

const inp = "w-full px-2 py-1.5 text-xs border border-[#DFE1E6] rounded outline-none focus:border-[#4C9AFF] bg-white";

function PendingItem({ item, kinds, base, params, onChanged }) {
  const [open, setOpen] = useState(false); const [d, setD] = useState(item.data); const [busy, setBusy] = useState(""); const [errs, setErrs] = useState(item.errors || []);
  const set = (k, v) => setD((p) => ({ ...p, [k]: k === "dedicated_phone" ? v.replace(/\D/g, "").slice(0, 10) : v }));
  const act = async (kind) => {
    setBusy(kind);
    try {
      if (kind !== "discard") { const { data } = await api.put(`${base}/pending/${item.id}`, { data: toPayload(d) }, { params }); setErrs(data.errors); if (kind === "save" || data.errors.length) return; }
      if (kind === "import") await api.post(`${base}/pending/${item.id}/import`, null, { params });
      else await api.delete(`${base}/pending/${item.id}`, { params });
      onChanged();
    } catch (e) { setErrs([e?.response?.data?.detail || "Could not import"]); } finally { setBusy(""); }
  };
  return (
    <div className="border border-[#FFE2BD] bg-[#FFFAE6]/50 rounded-md p-3" data-testid={`pending-row-${item.id}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0"><div className="text-sm font-semibold text-[#091E42] truncate">{d.name || "Unnamed row"} <span className="text-xs font-normal text-[#5E6C84]">{KIND_LABEL[d.entity_kind] || d.entity_kind || "no type"} · {d.dedicated_phone || "no phone"}</span></div>
          {errs.length > 0 && <div className="text-xs text-[#974F0C] flex items-start gap-1 mt-0.5" data-testid={`pending-errors-${item.id}`}><AlertTriangle className="h-3.5 w-3.5 mt-px shrink-0" />{errs.join(" · ")}</div>}</div>
        <button onClick={() => setOpen((o) => !o)} className="text-xs font-semibold text-[#0052CC] shrink-0" data-testid={`pending-fix-${item.id}`}>{open ? "Close" : "Fix"}</button>
      </div>
      {open && <div className="mt-3 space-y-3">
        <div className="grid sm:grid-cols-3 gap-2">
          <select className={inp} value={d.entity_kind || ""} onChange={(e) => set("entity_kind", e.target.value)} data-testid={`pending-f-${item.id}-entity_kind`}><option value="">Type…</option>{kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select>
          {FIELDS.map(([k, label, req]) => <input key={k} className={inp} placeholder={`${label}${req ? " *" : ""}`} value={d[k] || ""} onChange={(e) => set(k, e.target.value)} data-testid={`pending-f-${item.id}-${k}`} />)}
        </div>
        <div className="flex justify-end gap-2">
          {[["discard", "Discard", "border border-[#DFE1E6] text-[#BF2600]"], ["save", "Save", "border border-[#DFE1E6]"], ["import", "Save & import", "bg-[#0052CC] text-white font-semibold"]].map(([k, l, c]) =>
            <button key={k} onClick={() => act(k)} disabled={!!busy} className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md disabled:opacity-50 ${c}`} data-testid={`pending-${k}-${item.id}`}>{busy === k && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{l}</button>)}
        </div>
      </div>}
    </div>
  );
}

export default function PendingRows({ items, kinds, base, params, onChanged }) {
  if (!items.length) return null;
  return (
    <div className="mt-4 pt-4 border-t border-[#DFE1E6] space-y-2" data-testid="pending-section">
      <div className="text-[11px] font-bold uppercase tracking-wider text-[#974F0C]">Pending — fix and import <span data-testid="pending-count">({items.length})</span></div>
      {items.map((it) => <PendingItem key={it.id} item={it} kinds={kinds} base={base} params={params} onChanged={onChanged} />)}
    </div>
  );
}
