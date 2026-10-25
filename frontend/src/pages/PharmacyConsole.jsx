import React, { useEffect, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { Pill } from "lucide-react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import OrdersTab from "../components/pharmacy/OrdersTab";
import PrescriptionsTab from "../components/pharmacy/PrescriptionsTab";
import StockTab from "../components/pharmacy/StockTab";
import SalesTab from "../components/pharmacy/SalesTab";
import { inp } from "../components/pharmacy/ui";

const PAGES = { orders: ["Medicine Orders", OrdersTab], prescriptions: ["Prescriptions", PrescriptionsTab], stock: ["Stock", StockTab], sales: ["Sales", SalesTab] };
const KIND = { own: "Main store", branch: "Branch" };

export function useStores() {
  const [stores, setStores] = useState(null); const [err, setErr] = useState("");
  useEffect(() => { api.get("/pharmacy-console/stores").then((r) => setStores(r.data.stores)).catch((e) => setErr(e?.response?.data?.detail || "Could not load your pharmacy")); }, []);
  return { stores, err };
}

export function StorePicker({ stores, store, setStore }) {
  if (!stores || stores.length < 2) return null;
  return (
    <select className={`${inp} w-auto min-w-[240px]`} value={store} onChange={(e) => setStore(e.target.value)} data-testid="pharmacy-store-select">
      <option value="all">All stores ({stores.length})</option>
      {stores.map((s) => <option key={s.id} value={s.id}>{s.name}{KIND[s.kind] ? ` — ${KIND[s.kind]}` : ""}{s.city ? `, ${s.city}` : ""}</option>)}
    </select>
  );
}

export default function PharmacyConsole() {
  const { tab } = useParams();
  const { user } = useAuth();
  const { stores, err } = useStores();
  const [store, setStore] = useState("all");
  if (!PAGES[tab]) return <Navigate to="/pharmacy/orders" replace />;
  const [label, Tab] = PAGES[tab];
  const multi = (stores?.length || 0) > 1;
  const sel = multi ? store : stores?.[0]?.id;
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="pharmacy-console">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><div className="overline flex items-center gap-1.5"><Pill className="h-3.5 w-3.5" /> Pharmacy</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="pharmacy-title">{user?.business_name ? `${user.business_name} · ${label}` : label}</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Stays in sync with the Trata Provider and Patient apps.</p></div>
        <StorePicker stores={stores} store={store} setStore={setStore} />
      </div>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="pharmacy-error">{err}</div>}
      {stores && sel && <Tab key={`${tab}-${sel}`} store={sel} stores={stores} showStore={multi && store === "all"} />}
    </div>
  );
}
