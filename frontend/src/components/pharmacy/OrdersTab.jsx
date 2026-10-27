import React, { useEffect, useState } from "react";
import { Image as ImageIcon, MapPin, Phone } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { ORDER_STATUS, Chip, inr, when, itemLine, errMsg, inp, primary, ghost, danger } from "./ui";

const FILTERS = [["", "All"], ["PENDING_PHARMACY", "New"], ["PREORDER_PENDING", "Pre-orders"], ["ACCEPTED", "Accepted"], ["FULFILLED", "Fulfilled"], ["REJECTED", "Rejected"], ["CANCELLED", "Cancelled"]];

function Actions({ o, onDone }) {
  const [mode, setMode] = useState(null); const [amount, setAmount] = useState(o.total_amount ?? ""); const [text, setText] = useState(""); const [busy, setBusy] = useState(false);
  const run = async (action) => {
    setBusy(true);
    try {
      const body = { action, ...(amount !== "" && action !== "reject" ? { total_amount: Number(amount) } : {}), ...(action === "reject" ? { reason: text } : text ? { note: text } : {}) };
      const { data } = await api.post(`/pharmacy-console/orders/${o.id}/action`, body);
      toast.success(`Order ${data.order.status.toLowerCase().replace("_", " ")}`); setMode(null); onDone(data.order);
    } catch (e) { errMsg(e); } finally { setBusy(false); }
  };
  const open = ["PENDING_PHARMACY", "PREORDER_PENDING"].includes(o.status);
  const start = (m) => { setText(""); setAmount(o.total_amount ?? ""); setMode(m); };
  if (mode) return (
    <div className="mt-3 p-3 bg-[#F8F9FA] rounded-md space-y-2" data-testid={`order-form-${o.id}`}>
      {mode !== "reject" && <input className={inp} inputMode="decimal" placeholder="Bill amount ₹" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} data-testid={`order-amount-${o.id}`} />}
      <input className={inp} placeholder={mode === "reject" ? "Reason (shown to the patient) *" : "Note for the patient (optional)"} value={text} onChange={(e) => setText(e.target.value)} data-testid={`order-text-${o.id}`} />
      <div className="flex gap-2 justify-end"><button className={ghost} onClick={() => setMode(null)}>Cancel</button>
        <button className={mode === "reject" ? danger : primary} disabled={busy || (mode === "reject" ? !text.trim() : mode === "fulfil" && amount === "")} onClick={() => run(mode)} data-testid={`order-confirm-${o.id}`}>
          {{ accept: "Accept order", reject: "Reject order", fulfil: "Mark fulfilled" }[mode]}</button></div>
    </div>
  );
  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {open && <button className={primary} onClick={() => start("accept")} data-testid={`order-accept-${o.id}`}>Accept</button>}
      {o.status === "ACCEPTED" && <button className={primary} onClick={() => start("fulfil")} data-testid={`order-fulfil-${o.id}`}>Mark fulfilled</button>}
      {["ACCEPTED", "FULFILLED"].includes(o.status) && !o.is_paid && <button className={ghost} disabled={busy} onClick={() => run("mark_paid")} data-testid={`order-paid-${o.id}`}>Mark paid</button>}
      {(open || o.status === "ACCEPTED") && <button className={danger} onClick={() => start("reject")} data-testid={`order-reject-${o.id}`}>Reject</button>}
    </div>
  );
}

function OrderCard({ o, showStore, onDone }) {
  const [img, setImg] = useState(null);
  const viewRx = () => api.get(`/pharmacy-console/orders/${o.id}/rx-image`).then((r) => setImg(r.data.image)).catch((e) => errMsg(e));
  return (
    <div className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid={`order-${o.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><div className="flex items-center gap-2"><span className="font-semibold text-[#091E42]">{o.patient_name || "Patient"}</span><Chip map={ORDER_STATUS} s={o.status} testid={`order-status-${o.id}`} />{o.is_paid && <span className="text-[10px] font-bold text-[#006644]">PAID</span>}</div>
          <div className="text-xs text-[#5E6C84] mt-0.5">#{o.order_number} · {when(o.created_at)}{showStore && ` · ${o.pharmacy_name}`}</div></div>
        <div className="text-right"><div className="font-heading font-black text-[#091E42]" data-testid={`order-total-${o.id}`}>{inr(o.total_amount)}</div><div className="text-[11px] text-[#5E6C84]">{o.payment_method || "cash"} · {o.delivery_mode || "pickup"}</div></div>
      </div>
      <ul className="mt-2 text-sm text-[#172B4D] list-disc pl-5">{o.items.map((it, i) => <li key={i}>{itemLine(it)}</li>)}</ul>
      {o.notes && <p className="text-xs text-[#42526E] mt-1">Patient note: {o.notes}</p>}
      <div className="flex flex-wrap gap-3 text-xs text-[#5E6C84] mt-2">
        {o.patient_phone && <span className="flex items-center gap-1"><Phone className="h-3 w-3" />{o.patient_phone}</span>}
        {o.delivery_mode === "delivery" && o.delivery_address && <span className="flex items-center gap-1"><MapPin className="h-3 w-3" />{o.delivery_address}</span>}
        {o.has_rx_image && <button onClick={viewRx} className="flex items-center gap-1 text-[#0052CC] font-semibold" data-testid={`order-rx-${o.id}`}><ImageIcon className="h-3 w-3" />View prescription</button>}
      </div>
      {img && <img src={img.startsWith("data:") ? img : `data:image/jpeg;base64,${img}`} alt="Prescription" className="mt-2 max-h-72 rounded border" />}
      {o.rejection_reason && <p className="text-xs text-[#BF2600] mt-1">Rejected: {o.rejection_reason}</p>}
      <Actions o={o} onDone={onDone} />
    </div>
  );
}

export default function OrdersTab({ store, showStore }) {
  const [status, setStatus] = useState(""); const [data, setData] = useState(null);
  const load = () => api.get("/pharmacy-console/orders", { params: { store, status: status || undefined } }).then((r) => setData(r.data)).catch((e) => { errMsg(e); setData({ orders: [], counts: {} }); });
  useEffect(() => { load(); const t = setInterval(load, 20000); window.addEventListener("trata:new-order", load); return () => { clearInterval(t); window.removeEventListener("trata:new-order", load); }; /* eslint-disable-next-line */ }, [store, status]);
  const replace = (o) => setData((d) => ({ ...d, orders: d.orders.map((x) => (x.id === o.id ? o : x)).filter((x) => !status || x.status === status) }));
  return (
    <div className="space-y-3" data-testid="orders-tab">
      <div className="flex flex-wrap gap-1.5">{FILTERS.map(([v, l]) => <button key={v} onClick={() => setStatus(v)} className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${status === v ? "bg-[#0052CC] text-white border-[#0052CC]" : "border-[#DFE1E6] text-[#42526E] hover:bg-[#F4F5F7]"}`} data-testid={`orders-filter-${v || "all"}`}>{l}{!status && v && data?.counts?.[v] ? ` · ${data.counts[v]}` : ""}</button>)}</div>
      {!data ? <div className="text-sm text-[#5E6C84]">Loading orders…</div> : data.orders.length === 0 ? <div className="text-sm text-[#5E6C84] py-8 text-center" data-testid="orders-empty">No medicine orders here yet. Orders patients place in the Trata app appear instantly.</div>
        : <div className="grid lg:grid-cols-2 gap-3">{data.orders.map((o) => <OrderCard key={o.id} o={o} showStore={showStore} onDone={replace} />)}</div>}
    </div>
  );
}
