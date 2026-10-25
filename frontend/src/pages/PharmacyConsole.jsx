import React, { useEffect, useState } from "react";
import { Pill } from "lucide-react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import OrdersTab from "../components/pharmacy/OrdersTab";
import PrescriptionsTab from "../components/pharmacy/PrescriptionsTab";
import StockTab from "../components/pharmacy/StockTab";
import SalesTab from "../components/pharmacy/SalesTab";
import { inp } from "../components/pharmacy/ui";

const TABS = [["orders", "Medicine orders", OrdersTab], ["rx", "Prescriptions", PrescriptionsTab], ["stock", "Stock", StockTab], ["sales", "Sales", SalesTab]];
const KIND = { own: "Main store", branch: "Branch", hospital: "Hospital pharmacy", network: "" };

export default function PharmacyConsole() {
  const { user, isProvider } = useAuth();
  const [stores, setStores] = useState(null); const [store, setStore] = useState("all"); const [tab, setTab] = useState("orders"); const [err, setErr] = useState("");
  useEffect(() => { api.get("/pharmacy-console/stores").then((r) => { setStores(r.data.stores); if (r.data.stores.length === 1) setStore(r.data.stores[0].id); }).catch((e) => setErr(e?.response?.data?.detail || "Could not load pharmacies")); }, []);
  const Tab = TABS.find((t) => t[0] === tab)[2];
  const multi = (stores?.length || 0) > 1;
  const title = isProvider ? (user?.provider_type === "hospital" ? `${user?.business_name ? `${user.business_name} · ` : ""}Pharmacy` : user?.business_name || "Pharmacy") : "Pharmacies";
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="pharmacy-console">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><div className="overline flex items-center gap-1.5"><Pill className="h-3.5 w-3.5" /> Pharmacy console</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1" data-testid="pharmacy-title">{title}</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Orders, prescriptions and stock stay in sync with the Trata Provider and Patient apps.</p></div>
        {multi && <select className={`${inp} w-auto min-w-[240px]`} value={store} onChange={(e) => setStore(e.target.value)} data-testid="pharmacy-store-select">
          <option value="all">All stores ({stores.length})</option>
          {stores.map((s) => <option key={s.id} value={s.id}>{s.name}{KIND[s.kind] ? ` — ${KIND[s.kind]}` : ""}{s.city ? `, ${s.city}` : ""}</option>)}</select>}
      </div>
      {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="pharmacy-error">{err}{user?.provider_type === "hospital" && " — add a pharmacy under My Entities to start."}</div>}
      {stores && stores.length === 0 && <div className="text-sm text-[#5E6C84] bg-white border border-[#DFE1E6] rounded-lg p-6" data-testid="pharmacy-no-stores">No pharmacy is linked yet.{user?.provider_type === "hospital" && " Add your hospital pharmacy under My Entities and it will appear here."}</div>}
      {stores && stores.length > 0 && <>
        <div className="flex gap-1 border-b border-[#DFE1E6]">{TABS.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={`px-3 py-2 text-sm font-semibold border-b-2 -mb-px ${tab === k ? "border-[#0052CC] text-[#0052CC]" : "border-transparent text-[#5E6C84] hover:text-[#091E42]"}`} data-testid={`pharmacy-tab-${k}`}>{l}</button>)}</div>
        <Tab key={store} store={store} stores={stores} showStore={multi && store === "all"} />
      </>}
    </div>
  );
}
