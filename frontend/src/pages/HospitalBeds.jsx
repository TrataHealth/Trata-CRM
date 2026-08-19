import React, { useCallback, useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { toast } from "sonner";
import { AlertTriangle, BedDouble, CheckCircle2, Loader2, Plus, XCircle } from "lucide-react";

// Same visual language as the command centre so the two pages feel like siblings.
const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  sectionHead: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  btnPrimary: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnGhost:   "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
};

const BED_TYPES = ["General", "ICU", "ER", "Ventilator", "Isolation", "Pediatric", "Maternity", "OT"];

const Tile = ({ label, value, sub, icon: Icon, tone = "#0052CC" }) => (
  <div className={`${T.card} p-4`} data-testid={`beds-tile-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
    <div className="flex items-center justify-between">
      <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
      <Icon className="h-4 w-4" style={{ color: tone }} />
    </div>
    <div className="font-heading text-3xl font-black text-[#091E42] mt-1">{value ?? 0}</div>
    {sub && <div className="text-[11px] text-[#5E6C84] mt-1">{sub}</div>}
  </div>
);

export default function HospitalBeds() {
  const { user } = useAuth();
  const [state, setState] = useState({ loading: true, beds: [], err: "" });
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all"); // all | free | occupied
  const [typeFilter, setTypeFilter] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ bed_type: "General", bed_number: "", ward: "", daily_rate: "" });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/hospital/command-center");
      setState({ loading: false, beds: data.beds || [], err: "" });
    } catch (e) {
      setState({ loading: false, beds: [], err: e?.response?.data?.detail || "Could not load beds" });
    }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const toggleBed = async (b) => {
    setBusy(true);
    try {
      await api.post(`/hospital/beds/${b.id}/toggle`, {
        is_available: !b.is_available,
        reason: b.is_available ? "manual_occupy" : "manual_free",
      });
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Toggle failed"); } finally { setBusy(false); }
  };

  const addBed = async () => {
    if (!form.bed_number) { toast.error("Bed number is required"); return; }
    setBusy(true);
    try {
      await api.post("/hospital/beds", {
        bed_type: form.bed_type,
        bed_number: form.bed_number,
        ward: form.ward || null,
        daily_rate: form.daily_rate ? Number(form.daily_rate) : null,
      });
      setForm({ bed_type: "General", bed_number: "", ward: "", daily_rate: "" });
      setShowAdd(false);
      toast.success("Bed added");
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Create failed"); } finally { setBusy(false); }
  };

  const beds = state.beds;
  const totalCount = beds.length;
  const freeCount = beds.filter((b) => b.is_available).length;
  const occCount = totalCount - freeCount;
  const byType = beds.reduce((acc, b) => {
    (acc[b.bed_type] = acc[b.bed_type] || { total: 0, free: 0 });
    acc[b.bed_type].total++;
    if (b.is_available) acc[b.bed_type].free++;
    return acc;
  }, {});
  const availableTypes = Object.keys(byType).sort();

  const filteredBeds = beds.filter((b) => {
    if (filter === "free" && !b.is_available) return false;
    if (filter === "occupied" && b.is_available) return false;
    if (typeFilter !== "all" && b.bed_type !== typeFilter) return false;
    return true;
  });
  const groups = filteredBeds.reduce((acc, b) => { (acc[b.bed_type] = acc[b.bed_type] || []).push(b); return acc; }, {});
  const groupTypes = Object.keys(groups).sort();

  if (state.loading) {
    return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="beds-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading beds…</div>;
  }
  if (state.err) {
    return (
      <div className="p-6 max-w-xl mx-auto mt-10" data-testid="beds-error">
        <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">Beds unavailable</div>
            <div className="text-xs mt-1">{state.err}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="hospital-beds">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><BedDouble className="h-3 w-3" /> Bed Management</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{user?.name || "Hospital"} · Beds</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Live occupancy across every ward. Click any bed to toggle free/occupied — the change is logged to bed_status_logs and instantly reflected in the mobile app.</p>
        </div>
        <button className={T.btnPrimary} onClick={() => setShowAdd((v) => !v)} data-testid="beds-add-toggle"><Plus className="h-3.5 w-3.5" /> Add bed</button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="beds-kpis">
        <Tile label="Total beds"   value={totalCount} sub={`${availableTypes.length} bed type${availableTypes.length === 1 ? "" : "s"}`} icon={BedDouble} tone="#0052CC" />
        <Tile label="Free"         value={freeCount}  sub={totalCount ? `${Math.round(freeCount / totalCount * 100)}% availability` : "—"} icon={CheckCircle2} tone="#006644" />
        <Tile label="Occupied"     value={occCount}   sub={totalCount ? `${Math.round(occCount / totalCount * 100)}% utilisation` : "—"} icon={XCircle} tone="#BF2600" />
        <Tile label="Bed types"    value={availableTypes.length} sub="in your inventory" icon={BedDouble} tone="#5243AA" />
      </div>

      {showAdd && (
        <section className={T.card} data-testid="beds-add-form">
          <div className={T.sectionHead}>Add a bed</div>
          <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
            <label className="text-[11px] text-[#42526E]">Type
              <select className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.bed_type} onChange={(e) => setForm({ ...form, bed_type: e.target.value })} data-testid="beds-add-type">
                {BED_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="text-[11px] text-[#42526E]">Number
              <input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.bed_number} onChange={(e) => setForm({ ...form, bed_number: e.target.value })} placeholder="e.g. 101" data-testid="beds-add-number" />
            </label>
            <label className="text-[11px] text-[#42526E]">Ward
              <input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.ward} onChange={(e) => setForm({ ...form, ward: e.target.value })} placeholder="Optional" data-testid="beds-add-ward" />
            </label>
            <label className="text-[11px] text-[#42526E]">Daily rate (₹)
              <input type="number" className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded" value={form.daily_rate} onChange={(e) => setForm({ ...form, daily_rate: e.target.value })} placeholder="Optional" data-testid="beds-add-rate" />
            </label>
            <div className="flex gap-2">
              <button className={T.btnGhost} onClick={() => setShowAdd(false)}>Cancel</button>
              <button className={T.btnPrimary} disabled={busy || !form.bed_number} onClick={addBed} data-testid="beds-add-submit">Create bed</button>
            </div>
          </div>
        </section>
      )}

      <section className={T.card}>
        <div className={`${T.sectionHead} flex-wrap gap-2`} data-testid="beds-filters">
          <div className="flex items-center gap-1">
            {[
              { k: "all", l: "All" },
              { k: "free", l: `Free · ${freeCount}` },
              { k: "occupied", l: `Occupied · ${occCount}` },
            ].map((o) => (
              <button key={o.k}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold ${filter === o.k ? "bg-[#0052CC] text-white" : "text-[#42526E] hover:bg-[#F4F5F7]"}`}
                onClick={() => setFilter(o.k)}
                data-testid={`beds-filter-${o.k}`}>{o.l}</button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-[#5E6C84]">Type</span>
            <select className="text-xs px-2 py-1 bg-white border border-[#DFE1E6] rounded" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} data-testid="beds-type-filter">
              <option value="all">All</option>
              {availableTypes.map((t) => <option key={t} value={t}>{t} ({byType[t].free}/{byType[t].total})</option>)}
            </select>
          </div>
        </div>

        {filteredBeds.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#5E6C84]" data-testid="beds-empty">
            {beds.length === 0 ? "No beds registered yet. Click Add bed to create your first one." : "No beds match this filter."}
          </div>
        ) : (
          <div className="p-4 space-y-6">
            {groupTypes.map((t) => {
              const list = groups[t];
              const meta = byType[t];
              return (
                <div key={t} data-testid={`beds-group-${t.toLowerCase()}`}>
                  <div className="flex items-baseline justify-between mb-2">
                    <div className="text-[11px] uppercase tracking-wider text-[#5E6C84] font-semibold">{t}</div>
                    <div className="text-[11px] text-[#5E6C84]">{meta.free}/{meta.total} free · {meta.total ? Math.round(meta.free / meta.total * 100) : 0}%</div>
                  </div>
                  <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-7 lg:grid-cols-10 gap-2">
                    {list.map((b) => (
                      <button key={b.id} onClick={() => toggleBed(b)} disabled={busy} data-testid={`beds-bed-${b.id}`}
                        className={`px-2 py-3 text-xs rounded border font-mono text-center transition-colors ${b.is_available ? "bg-[#E3FCEF] border-[#57D9A3] text-[#006644] hover:bg-[#ABF5D1]" : "bg-[#FFEBE6] border-[#FF8F73] text-[#BF2600] hover:bg-[#FFBDAD]"}`}>
                        <div className="font-bold text-sm">{b.bed_number}</div>
                        {b.ward && <div className="text-[9px] mt-0.5 opacity-75">{b.ward}</div>}
                        <div className="text-[9px] mt-1 font-bold">{b.is_available ? "FREE" : "OCCUPIED"}</div>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
