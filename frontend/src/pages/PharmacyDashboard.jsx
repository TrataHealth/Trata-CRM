import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShoppingBag, FileText, Pill, IndianRupee } from "lucide-react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { useStores, StorePicker } from "./PharmacyConsole";
import { inr, when, ORDER_STATUS, Chip } from "../components/pharmacy/ui";

function Tile({ to, icon: Icon, label, value, sub, testid, tone = "#0052CC" }) {
  return (
    <Link to={to} className="bg-white border border-[#DFE1E6] rounded-lg p-4 hover:border-[#4C9AFF] transition-colors" data-testid={testid}>
      <div className="flex items-center justify-between"><span className="text-[10px] font-bold uppercase tracking-wider text-[#5E6C84]">{label}</span><Icon className="h-4 w-4" style={{ color: tone }} /></div>
      <div className="font-heading text-3xl font-black text-[#091E42] mt-1">{value}</div><div className="text-xs text-[#5E6C84]">{sub}</div>
    </Link>
  );
}

export default function PharmacyDashboard() {
  const { user } = useAuth();
  const { stores, err } = useStores();
  const [store, setStore] = useState("all"); const [d, setD] = useState(null); const [tick, setTick] = useState(0);
  const multi = (stores?.length || 0) > 1;
  const sel = multi ? store : stores?.[0]?.id;
  useEffect(() => { const f = () => setTick((t) => t + 1); window.addEventListener("trata:new-order", f); return () => window.removeEventListener("trata:new-order", f); }, []);
  useEffect(() => {
    if (!sel) return;
    const p = { store: sel };
    Promise.all([api.get("/pharmacy-console/orders", { params: p }), api.get("/pharmacy-console/prescriptions", { params: p }),
      api.get("/pharmacy-console/inventory", { params: p }), api.get("/pharmacy-console/sales", { params: { ...p, days: 7 } })])
      .then(([o, rx, inv, s]) => setD({ orders: o.data, rx: rx.data.prescriptions, inv: inv.data, sales: s.data })).catch(() => setD(false));
  }, [sel, tick]);
  const newOrders = d ? (d.orders.counts.PENDING_PHARMACY || 0) + (d.orders.counts.PREORDER_PENDING || 0) : 0;
  const newRx = d ? d.rx.filter((x) => ["submitted", "issued", "pending"].includes(x.status)).length : 0;
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="pharmacy-dashboard">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><div className="overline">My Dashboard</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="pharmacy-dashboard-title">{user?.business_name || "My Pharmacy"}</h1></div>
        <StorePicker stores={stores} store={store} setStore={setStore} />
      </div>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2">{err}</div>}
      {d === null && !err && <div className="text-sm text-[#5E6C84]">Loading…</div>}
      {d && <>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile to="/pharmacy/orders" icon={ShoppingBag} label="New orders" value={newOrders} sub={`${d.orders.counts.ACCEPTED || 0} accepted, waiting to fulfil`} testid="pd-new-orders" />
          <Tile to="/pharmacy/prescriptions" icon={FileText} label="New prescriptions" value={newRx} sub={`${d.rx.length} in inbox`} testid="pd-new-rx" />
          <Tile to="/pharmacy/stock" icon={Pill} label="Low stock" value={d.inv.low_stock} sub={`${d.inv.expiring_soon} expiring within 60 days`} testid="pd-low-stock" tone="#BF2600" />
          <Tile to="/pharmacy/sales" icon={IndianRupee} label="Sales · 7 days" value={inr(d.sales.revenue)} sub={`${d.sales.fulfilled} fulfilled`} testid="pd-sales" tone="#006644" />
        </div>
        <div className="bg-white border border-[#DFE1E6] rounded-lg p-4" data-testid="pd-recent-orders">
          <div className="flex justify-between mb-2"><span className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84]">Latest orders</span><Link to="/pharmacy/orders" className="text-xs font-semibold text-[#0052CC]">See all</Link></div>
          {d.orders.orders.length === 0 ? <div className="text-sm text-[#5E6C84]">No orders yet.</div> : d.orders.orders.slice(0, 6).map((o) => (
            <div key={o.id} className="flex items-center justify-between py-2 border-b border-[#F4F5F7] last:border-0 text-sm">
              <span><b>{o.patient_name}</b> <span className="text-xs text-[#5E6C84]">#{o.order_number} · {when(o.created_at)}{multi && store === "all" ? ` · ${o.pharmacy_name}` : ""}</span></span>
              <span className="flex items-center gap-2"><Chip map={ORDER_STATUS} s={o.status} />{inr(o.total_amount)}</span>
            </div>))}
        </div>
      </>}
    </div>
  );
}
