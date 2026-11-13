import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";
import { BulkBar, BulkActionDialog, SuspendedTag, RowCheck, useSelection } from "../components/users/BulkActions";
import { DeletedUsers } from "../components/users/DeletedUsers";
import {
  Users, Search, Loader2, AlertTriangle, ChevronRight, HeartPulse,
  Activity, Calendar, Bed, Ambulance, ShieldCheck, Archive, ArrowLeft,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  head: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
  input: "text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded",
};

const STATUS_TONE = {
  admitted:   "bg-[#DEEBFF] text-[#0747A6]",
  active:     "bg-[#DEEBFF] text-[#0747A6]",
  discharged: "bg-[#E3FCEF] text-[#006644]",
  completed:  "bg-[#E3FCEF] text-[#006644]",
  critical:   "bg-[#FFEBE6] text-[#BF2600]",
  pending:    "bg-[#FFFAE6] text-[#974F0C]",
};
function StatusChip({ status }) {
  const v = String(status || "—").toLowerCase();
  const tone = STATUS_TONE[v] || "bg-[#F4F5F7] text-[#5E6C84]";
  return <span className={`${T.chip} ${tone}`}>{v.toUpperCase().replace(/_/g, " ")}</span>;
}

/** Shared roster + detail page. Set `mode="admin"` → uses /admin/patients …
    `mode="provider"` → uses /provider/patients … */
export default function Patients({ mode = "admin" }) {
  const nav = useNavigate();
  const basePath = mode === "provider" ? "/provider/patients" : "/admin/patients";
  const [state, setState] = useState({ loading: true, patients: [], err: "", scope: "", message: "" });
  const [q, setQ] = useState("");
  const [sp, setSp] = useSearchParams();
  const deletedView = mode === "admin" && sp.get("view") === "deleted";

  const load = useCallback(async (searchQ) => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const { data } = await api.get(basePath, { params: searchQ ? { q: searchQ } : {} });
      setState({ loading: false, patients: data.patients || [], err: "",
                 scope: data.scope || "", message: data.message || "" });
    } catch (e) {
      setState({ loading: false, patients: [], err: e?.response?.data?.detail || "Could not load patients", scope: "", message: "" });
    }
  }, [basePath]);

  useEffect(() => { load(""); }, [load]);

  const submitSearch = (e) => { e?.preventDefault(); load(q.trim()); };

  const isProviderView = mode === "provider";
  const [status, setStatus] = useState("");
  const [action, setAction] = useState(null);
  const rows = state.patients.filter((p) => isProviderView || !status || (status === "suspended") === !!p.is_suspended);
  const pick = useSelection(isProviderView ? [] : rows);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="patients-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1">
            {isProviderView ? <HeartPulse className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
            {isProviderView ? "Patient roster" : "Trata Health Admin · Patients"}
          </div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
            {isProviderView ? "My patients" : deletedView ? "Deleted patients" : "Trata Patient Users"}
          </h1>
          <p className="text-sm text-[#5E6C84] mt-1 max-w-2xl">
            {isProviderView
              ? "Same list your mobile Provider App shows — click a patient to see their clinical profile, admissions, appointments, and ambulance rides."
              : deletedView ? "Patient accounts deleted here or in the app. Restore within 30 days — after that they're erased permanently."
              : "Every account on the Trata Patient app — one row per person. Search by name or phone. Click a row for their full profile and history."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
        {!isProviderView && <button type="button" onClick={() => setSp(deletedView ? {} : { view: "deleted" })} data-testid="patients-deleted-toggle"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded border border-[#DFE1E6] bg-white text-[#42526E] hover:bg-[#F4F5F7]">
          {deletedView ? <><ArrowLeft className="h-3.5 w-3.5" /> Back to patients</> : <><Archive className="h-3.5 w-3.5" /> Deleted users</>}</button>}
        {!deletedView && <form onSubmit={submitSearch} className="flex items-center gap-2">
          <div className="relative">
            <Search className="h-3.5 w-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-[#5E6C84]" />
            <input
              className={T.input + " pl-7 w-64"}
              placeholder="Search name or phone…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              data-testid="patients-search"
            />
          </div>
          {!isProviderView && (
            <select value={status} onChange={(e) => setStatus(e.target.value)} data-testid="patients-status-filter"
                    className={T.input + " py-[7px]"}>
              <option value="">Any access</option><option value="active">Active</option><option value="suspended">Suspended</option>
            </select>
          )}
        </form>}
        </div>
      </div>
      {deletedView ? <DeletedUsers app="patient" /> : <>

      {!isProviderView && <>
        <BulkBar count={pick.selected.length} onAction={setAction} onClear={pick.clear} />
        <BulkActionDialog action={action} ids={pick.selected} field="user_ids" app="patient" onClose={() => setAction(null)}
                          onDone={() => { setAction(null); pick.clear(); load(q.trim()); }} />
      </>}

      {state.message && (
        <div className="bg-[#DEEBFF] border border-[#B3D4FF] rounded-md px-4 py-2 text-xs text-[#0747A6]" data-testid="patients-scope-message">
          {state.message}
        </div>
      )}

      <section className={T.card} data-testid="patients-list">
        <div className={T.head}>
          <span>{rows.length} patient{rows.length === 1 ? "" : "s"}</span>
          <span className="normal-case text-[10px] text-[#5E6C84] font-normal">
            Live from shared Trata Supabase
          </span>
        </div>
        {state.loading ? (
          <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="patients-loading">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading patients…
          </div>
        ) : state.err ? (
          <div className="p-6 text-sm text-[#BF2600] flex items-start gap-2" data-testid="patients-error">
            <AlertTriangle className="h-4 w-4 mt-0.5" /> {state.err}
          </div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-[#5E6C84]" data-testid="patients-empty">
            <Users className="h-6 w-6 mx-auto mb-2 text-[#5E6C84]" />
            No patients yet. When the mobile Provider App admits a patient or accepts a case, they will appear here instantly.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
                <tr>
                  {!isProviderView && <th className="pl-3 py-2 w-8"><RowCheck checked={pick.all} onChange={pick.toggleAll} testId="patients-select-all" /></th>}
                  <th className="px-3 py-2 text-left">Patient</th>
                  <th className="px-3 py-2 text-left">Phone</th>
                  {isProviderView ? (
                    <>
                      <th className="px-3 py-2 text-left">Age / Sex</th>
                      <th className="px-3 py-2 text-left">Blood</th>
                      <th className="px-3 py-2 text-left">Diagnosis</th>
                      <th className="px-3 py-2 text-center">Status</th>
                      <th className="px-3 py-2 text-left">Admitted</th>
                    </>
                  ) : (
                    <>
                      <th className="px-3 py-2 text-center">Cases</th>
                      <th className="px-3 py-2 text-center">Appointments</th>
                      <th className="px-3 py-2 text-center">Admissions</th>
                      <th className="px-3 py-2 text-left">Joined</th>
                    </>
                  )}
                  <th className="px-3 py-2 text-right"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  // For provider view we key on the patient_id (link to user), fall back to hp row id
                  const uid = isProviderView ? (p.patient_id || p.trata_patient_id || p.id) : p.id;
                  return (
                    <tr key={p.id} className={`border-t border-[#DFE1E6] hover:bg-[#F8F9FA] cursor-pointer ${pick.sel.has(p.id) ? "bg-[#DEEBFF]/40" : ""}`}
                        onClick={() => nav(`${basePath}/${uid}`)}
                        data-testid={`patient-row-${uid}`}>
                      {!isProviderView && <td className="pl-3 py-2"><RowCheck checked={pick.sel.has(p.id)} onChange={() => pick.toggle(p.id)} testId={`patient-select-${p.id}`} /></td>}
                      <td className="px-3 py-2">
                        <div className={`font-semibold ${p.name ? "text-[#091E42]" : "text-[#97A0AF] italic font-normal"}`}>{p.name || "Name not added yet"}{p.is_suspended && <SuspendedTag reason={p.suspended_reason} testId={`patient-suspended-${p.id}`} />}</div>
                        <div className="text-[10px] text-[#5E6C84] font-mono">{String(uid).slice(0, 8)}…</div>
                      </td>
                      <td className="px-3 py-2 font-mono">{p.phone ? `+91 ${p.phone}` : "—"}</td>
                      {isProviderView ? (
                        <>
                          <td className="px-3 py-2">{p.age ? `${p.age}` : "—"}{p.sex ? ` · ${p.sex}` : ""}</td>
                          <td className="px-3 py-2">{p.blood_group || "—"}</td>
                          <td className="px-3 py-2 max-w-[200px] truncate">{p.diagnosis || "—"}</td>
                          <td className="px-3 py-2 text-center"><StatusChip status={p.status} /></td>
                          <td className="px-3 py-2 text-[11px] text-[#5E6C84]">{p.admission_date ? relativeTime(p.admission_date) : "—"}</td>
                        </>
                      ) : (
                        <>
                          <td className="px-3 py-2 text-center">{p.cases || 0}</td>
                          <td className="px-3 py-2 text-center">{p.appts || 0}</td>
                          <td className="px-3 py-2 text-center">{p.admits || 0}</td>
                          <td className="px-3 py-2 text-[11px] text-[#5E6C84]">{p.created_at ? relativeTime(p.created_at) : "—"}</td>
                        </>
                      )}
                      <td className="px-3 py-2 text-right"><ChevronRight className="h-3.5 w-3.5 text-[#5E6C84]" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {!isProviderView && rows.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Tile label="Total patients"    value={rows.length}                                               icon={Users}      />
          <Tile label="With cases"        value={rows.filter(r => r.cases > 0).length}                       icon={Activity}   />
          <Tile label="With appointments" value={rows.filter(r => r.appts > 0).length}                       icon={Calendar}   />
          <Tile label="With admissions"   value={rows.filter(r => r.admits > 0).length}                      icon={Bed}        />
        </div>
      )}
      </>}
    </div>
  );
}

function Tile({ label, value, icon: Icon }) {
  return (
    <div className={T.card + " p-4"} data-testid={`patients-tile-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
        <Icon className="h-4 w-4 text-[#5E6C84]" />
      </div>
      <div className="font-heading text-2xl font-black text-[#091E42] mt-1">{value}</div>
    </div>
  );
}
