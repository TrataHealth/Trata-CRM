import React, { useEffect, useState } from "react";
import { Download } from "lucide-react";
import api from "../../lib/api";
import { inr, errMsg, ghost } from "./ui";

function csv(rows) {
  const head = ["Medicine", "Store", "In stock", "Sold (30 days)", "Reorder level", "Suggested order", "Unit price", "Est. cost"];
  const body = rows.map((r) => [r.medicine_name, r.store_name, r.qty_in_stock, r.sold_30d, r.reorder_threshold, r.suggested_qty, r.unit_price, r.est_cost]);
  const text = [head, ...body].map((l) => l.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" })); a.download = "reorder-list.csv"; a.click();
}

const Th = ({ children }) => <th className="px-3 py-2 font-semibold text-left text-[10px] uppercase tracking-wider text-[#5E6C84]">{children}</th>;

export default function StockActions({ store, view, showStore }) {
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); api.get("/pharmacy-console/stock-actions", { params: { store, days: 60 } }).then((r) => setD(r.data)).catch((e) => { errMsg(e); setD({ expiring: [], reorder: [] }); }); }, [store]);
  if (!d) return <div className="text-sm text-[#5E6C84]">Loading…</div>;
  if (view === "expiring") return (
    <div className="space-y-2" data-testid="expiry-list">
      <div className="text-sm text-[#42526E]">Medicines expiring in the next 60 days — sell, return to the distributor or clear first. Stock value at risk: <b className="text-[#BF2600]" data-testid="expiry-value">{inr(d.value_at_risk)}</b></div>
      {!d.expiring.length ? <div className="text-sm text-[#5E6C84] py-8 text-center" data-testid="expiry-empty">Nothing expires in the next 60 days.</div> : (
        <div className="overflow-x-auto bg-white border border-[#DFE1E6] rounded-lg"><table className="w-full text-sm"><thead className="bg-[#F8F9FA]"><tr><Th>Medicine</Th>{showStore && <Th>Store</Th>}<Th>Batch</Th><Th>Expires</Th><Th>Qty</Th><Th>Value</Th></tr></thead>
          <tbody>{d.expiring.map((it) => (
            <tr key={it.id} className="border-t border-[#F4F5F7]" data-testid={`expiry-row-${it.id}`}>
              <td className="px-3 py-2 font-semibold text-[#091E42]">{it.medicine_name}</td>{showStore && <td className="px-3 py-2 text-xs">{it.store_name}</td>}
              <td className="px-3 py-2 text-xs">{it.batch_no || "—"}</td>
              <td className="px-3 py-2 text-xs whitespace-nowrap">{it.expiry_date.slice(0, 10)} <span className={`ml-1 font-bold ${it.days_left < 0 ? "text-[#BF2600]" : it.days_left <= 15 ? "text-[#DE350B]" : "text-[#974F0C]"}`} data-testid={`expiry-days-${it.id}`}>{it.days_left < 0 ? "EXPIRED" : `${it.days_left} days`}</span></td>
              <td className="px-3 py-2">{it.qty_in_stock}</td><td className="px-3 py-2">{inr(it.value_at_risk)}</td>
            </tr>))}</tbody></table></div>)}
    </div>
  );
  return (
    <div className="space-y-2" data-testid="reorder-list">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-[#42526E]">Suggested order = last 30 days' sales + reorder level, minus what's in stock. Estimated cost: <b data-testid="reorder-cost">{inr(d.reorder_cost)}</b></div>
        {d.reorder.length > 0 && <button className={ghost} onClick={() => csv(d.reorder)} data-testid="reorder-download"><Download className="h-3.5 w-3.5" /> Download list</button>}
      </div>
      {!d.reorder.length ? <div className="text-sm text-[#5E6C84] py-8 text-center" data-testid="reorder-empty">Stock levels look healthy — nothing to reorder.</div> : (
        <div className="overflow-x-auto bg-white border border-[#DFE1E6] rounded-lg"><table className="w-full text-sm"><thead className="bg-[#F8F9FA]"><tr><Th>Medicine</Th>{showStore && <Th>Store</Th>}<Th>In stock</Th><Th>Sold · 30 days</Th><Th>Suggested order</Th><Th>Est. cost</Th></tr></thead>
          <tbody>{d.reorder.map((it) => (
            <tr key={it.id} className="border-t border-[#F4F5F7]" data-testid={`reorder-row-${it.id}`}>
              <td className="px-3 py-2"><div className="font-semibold text-[#091E42]">{it.medicine_name}</div><div className="text-[11px] text-[#5E6C84]">{it.basis}</div></td>
              {showStore && <td className="px-3 py-2 text-xs">{it.store_name}</td>}
              <td className="px-3 py-2">{it.qty_in_stock}</td><td className="px-3 py-2">{it.sold_30d}</td>
              <td className="px-3 py-2"><span className="font-heading font-black text-[#0052CC]" data-testid={`reorder-qty-${it.id}`}>{it.suggested_qty}</span> {it.unit || ""}</td>
              <td className="px-3 py-2">{inr(it.est_cost)}</td>
            </tr>))}</tbody></table></div>)}
    </div>
  );
}
