import React, { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { inr, errMsg, inp, primary, ghost } from "./ui";

const FIELDS = [["medicine_name", "Medicine name *"], ["manufacturer", "Manufacturer"], ["sku", "SKU"], ["unit", "Unit (strip, bottle…)"],
  ["qty_in_stock", "Qty in stock", "num"], ["reorder_threshold", "Reorder at", "num"], ["unit_price", "Unit price ₹", "num"], ["batch_no", "Batch no."], ["expiry_date", "Expiry", "date"]];

function ItemDialog({ item, stores, defaultStore, onClose, onSaved }) {
  const [f, setF] = useState(item ? { ...item, expiry_date: (item.expiry_date || "").slice(0, 10) } : { qty_in_stock: 0, reorder_threshold: 10, unit_price: 0 });
  const [store, setStore] = useState(item?.store_id || defaultStore || stores[0]?.id); const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const body = Object.fromEntries(FIELDS.map(([k, , t]) => [k, t === "num" ? (f[k] === "" || f[k] == null ? undefined : Number(f[k])) : f[k] || undefined]));
    try {
      if (item) await api.patch(`/pharmacy-console/inventory/${item.id}`, body); else await api.post("/pharmacy-console/inventory", body, { params: { store } });
      toast.success(item ? "Stock updated" : "Medicine added"); onSaved();
    } catch (e) { errMsg(e); } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 bg-[#091E42]/50 grid place-items-center p-4" data-testid="stock-dialog">
      <div className="bg-white rounded-lg w-full max-w-xl p-5 space-y-3">
        <div className="flex justify-between items-center"><div className="font-heading font-bold">{item ? "Edit medicine" : "Add medicine"}</div><button onClick={onClose} data-testid="stock-dialog-close"><X className="h-4 w-4" /></button></div>
        {!item && stores.length > 1 && <select className={inp} value={store} onChange={(e) => setStore(e.target.value)} data-testid="stock-store-select">{stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
        <div className="grid sm:grid-cols-2 gap-2">{FIELDS.map(([k, l, t]) => <label key={k} className="text-[11px] font-semibold text-[#5E6C84]">{l}
          <input className={`${inp} mt-1`} type={t === "date" ? "date" : "text"} inputMode={t === "num" ? "decimal" : undefined} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`stock-f-${k}`} /></label>)}</div>
        <div className="flex justify-end gap-2"><button className={ghost} onClick={onClose}>Cancel</button><button className={primary} disabled={busy || !String(f.medicine_name || "").trim()} onClick={save} data-testid="stock-save">Save</button></div>
      </div>
    </div>
  );
}

export default function StockTab({ store, stores, showStore }) {
  const [data, setData] = useState(null); const [q, setQ] = useState(""); const [low, setLow] = useState(false); const [edit, setEdit] = useState(undefined);
  const load = () => api.get("/pharmacy-console/inventory", { params: { store, low_stock_only: low, search: q || undefined } }).then((r) => setData(r.data)).catch((e) => { errMsg(e); setData({ items: [] }); });
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); /* eslint-disable-next-line */ }, [store, low, q]);
  const remove = async (it) => { if (!window.confirm(`Remove ${it.medicine_name} from stock?`)) return; try { await api.delete(`/pharmacy-console/inventory/${it.id}`); toast.success("Removed"); load(); } catch (e) { errMsg(e); } };
  return (
    <div className="space-y-3" data-testid="stock-tab">
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${inp} max-w-xs`} placeholder="Search medicine…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="stock-search" />
        <label className="flex items-center gap-1.5 text-sm text-[#42526E]"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} data-testid="stock-low-only" /> Low stock only</label>
        {data && <span className="text-xs text-[#5E6C84]" data-testid="stock-alerts"><b className="text-[#BF2600]">{data.low_stock}</b> low · <b className="text-[#974F0C]">{data.expiring_soon}</b> expiring within 60 days</span>}
        <button className={`${primary} ml-auto`} onClick={() => setEdit(null)} data-testid="stock-add"><Plus className="h-3.5 w-3.5" /> Add medicine</button>
      </div>
      {!data ? <div className="text-sm text-[#5E6C84]">Loading stock…</div> : data.items.length === 0 ? <div className="text-sm text-[#5E6C84] py-8 text-center" data-testid="stock-empty">No medicines in stock yet.</div> : (
        <div className="overflow-x-auto bg-white border border-[#DFE1E6] rounded-lg"><table className="w-full text-sm" data-testid="stock-table">
          <thead><tr className="text-left text-[10px] uppercase tracking-wider text-[#5E6C84] bg-[#F8F9FA]">{["Medicine", ...(showStore ? ["Store"] : []), "Qty", "Price", "Batch", "Expiry", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{data.items.map((it) => (
            <tr key={it.id} className="border-t border-[#F4F5F7]" data-testid={`stock-row-${it.id}`}>
              <td className="px-3 py-2"><div className="font-semibold text-[#091E42]">{it.medicine_name}</div><div className="text-xs text-[#5E6C84]">{[it.manufacturer, it.unit].filter(Boolean).join(" · ")}</div></td>
              {showStore && <td className="px-3 py-2 text-xs">{it.store_name}</td>}
              <td className="px-3 py-2 whitespace-nowrap"><b>{it.qty_in_stock}</b>{it.low_stock && <span className="ml-1.5 text-[10px] font-bold text-[#BF2600]" data-testid={`stock-low-${it.id}`}>LOW</span>}</td>
              <td className="px-3 py-2">{inr(it.unit_price)}</td>
              <td className="px-3 py-2 text-xs">{it.batch_no || "—"}</td>
              <td className="px-3 py-2 text-xs whitespace-nowrap">{(it.expiry_date || "—").slice(0, 10)}{it.expired ? <span className="ml-1.5 font-bold text-[#BF2600]">EXPIRED</span> : it.expiring_soon && <span className="ml-1.5 font-bold text-[#974F0C]" data-testid={`stock-exp-${it.id}`}>SOON</span>}</td>
              <td className="px-3 py-2 whitespace-nowrap text-right"><button onClick={() => setEdit(it)} className="p-1 hover:bg-[#F4F5F7] rounded" data-testid={`stock-edit-${it.id}`}><Pencil className="h-3.5 w-3.5" /></button>
                <button onClick={() => remove(it)} className="p-1 hover:bg-[#FFEBE6] rounded text-[#BF2600]" data-testid={`stock-delete-${it.id}`}><Trash2 className="h-3.5 w-3.5" /></button></td>
            </tr>))}</tbody>
        </table></div>)}
      {edit !== undefined && <ItemDialog item={edit} stores={stores} defaultStore={store !== "all" ? store : undefined} onClose={() => setEdit(undefined)} onSaved={() => { setEdit(undefined); load(); }} />}
    </div>
  );
}
