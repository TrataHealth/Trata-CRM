import React, { useMemo, useRef, useState } from "react";
import * as XLSX from "xlsx";
import { X, Upload, Download, Loader2, CheckCircle2, AlertTriangle, Trash2 } from "lucide-react";
import api from "../../lib/api";
import { KIND_LABEL, COLUMNS, FIELDS, normalizeRow, rowErrors, toPayload } from "../../lib/entityFields";

const LABEL = { entity_kind: "Type", dispatch_radius_km: "Radius (km)", ...Object.fromEntries(FIELDS.map(([k, l]) => [k, l])) };
const cell = "w-full min-w-[120px] px-2 py-1 text-xs border rounded outline-none focus:border-[#4C9AFF]";

function downloadTemplate(kinds) {
  const wb = XLSX.utils.book_new();
  const ex = { entity_kind: kinds[0], name: "Sunrise Branch – Andheri", contact_person: "Dr. A. Mehta", dedicated_phone: "9876543210", email: "andheri@example.com",
    address: "12 Link Road, Andheri West", city: "Mumbai", state: "Maharashtra", pincode: "400053", license_number: "", gst_number: "", dispatch_radius_km: "" };
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([COLUMNS]), "Entities");
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet([ex], { header: COLUMNS }), "Example (not imported)");
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(kinds.map((k) => ({ entity_kind: k, meaning: KIND_LABEL[k] }))), "Allowed types");
  XLSX.writeFile(wb, "trata-entities-template.xlsx");
}

function withChecks(rows, allowed, existing) {
  const seen = {};
  rows.forEach((r) => { if (r.dedicated_phone) seen[r.dedicated_phone] = (seen[r.dedicated_phone] || 0) + 1; });
  return rows.map((r) => {
    const e = rowErrors(r, allowed);
    if (!e.dedicated_phone && r.dedicated_phone && seen[r.dedicated_phone] > 1) e.dedicated_phone = "Same phone used on another row";
    if (!e.dedicated_phone && existing.has(r.dedicated_phone)) e.dedicated_phone = "An entity already uses this phone";
    return { r, e, ok: !Object.keys(e).length };
  });
}

function PreviewRow({ i, row, kinds, onChange, onRemove }) {
  return (
    <tr className={row.ok ? "" : "bg-[#FFF4E5]/60"} data-testid={`bulk-row-${i}`}>
      <td className="px-2 py-1 text-xs whitespace-nowrap">{row.ok ? <CheckCircle2 className="h-4 w-4 text-[#36B37E]" data-testid={`bulk-row-ok-${i}`} />
        : <span title={Object.values(row.e).join("\n")} data-testid={`bulk-row-err-${i}`}><AlertTriangle className="h-4 w-4 text-[#FF8B00]" /></span>}</td>
      <td className="px-2 py-1 text-[11px] text-[#BF2600] min-w-[180px] max-w-[240px]" data-testid={`bulk-row-problems-${i}`}>{Object.values(row.e).join(" · ")}</td>
      {COLUMNS.map((k) => <td key={k} className="px-1 py-1">
        {k === "entity_kind" ? <select className={`${cell} bg-white ${row.e[k] ? "border-[#FF5630]" : "border-[#DFE1E6]"}`} value={row.r[k] || ""} title={row.e[k] || ""}
          onChange={(ev) => onChange(i, k, ev.target.value)} data-testid={`bulk-cell-${i}-${k}`}><option value="">Select…</option>{row.r[k] && !kinds.includes(row.r[k]) && <option value={row.r[k]}>{row.r[k]} (not allowed)</option>}{kinds.map((x) => <option key={x} value={x}>{KIND_LABEL[x]}</option>)}</select>
          : <input className={`${cell} ${row.e[k] ? "border-[#FF5630] bg-white" : "border-[#DFE1E6]"}`} value={row.r[k] || ""} title={row.e[k] || ""}
            onChange={(ev) => onChange(i, k, ev.target.value)} data-testid={`bulk-cell-${i}-${k}`} />}
      </td>)}
      <td className="px-1"><button onClick={() => onRemove(i)} className="p-1 text-[#BF2600] hover:bg-[#FFEBE6] rounded" title="Drop row" data-testid={`bulk-row-remove-${i}`}><Trash2 className="h-3.5 w-3.5" /></button></td>
    </tr>
  );
}

function Progress({ job, onClose }) {
  const finished = job.status === "done";
  return (
    <div className="p-6 space-y-3" data-testid="bulk-progress">
      <div className="flex items-center gap-2 font-semibold text-[#091E42]">{finished ? <CheckCircle2 className="h-5 w-5 text-[#36B37E]" /> : <Loader2 className="h-5 w-5 animate-spin text-[#0052CC]" />}
        {finished ? "Import finished" : `Creating entities… ${job.done} of ${job.total}`}</div>
      <div className="h-2 bg-[#F4F5F7] rounded"><div className="h-2 bg-[#0052CC] rounded transition-[width] duration-500" style={{ width: `${job.total ? (job.done / job.total) * 100 : 100}%` }} /></div>
      <ul className="text-sm text-[#42526E] space-y-1" data-testid="bulk-summary">
        <li><b data-testid="bulk-created">{job.created}</b> created</li>
        <li><b data-testid="bulk-pending-saved">{job.pending_saved + job.failed}</b> saved to Pending to fix later{job.failed ? ` (${job.failed} rejected by the Provider app)` : ""}</li>
      </ul>
      {job.interrupted && <p className="text-sm text-[#974F0C]" data-testid="bulk-interrupted">The import was interrupted. Rows not created yet were not saved; please re-upload them.</p>}
      {finished && <button onClick={onClose} className="px-3 py-2 text-sm bg-[#0052CC] text-white rounded-md" data-testid="bulk-done">Done</button>}
    </div>
  );
}

export default function BulkImportDialog({ base, params, kinds, existingPhones, onClose, onFinished }) {
  const [rows, setRows] = useState(null); const [onlyBad, setOnlyBad] = useState(false); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false); const [job, setJob] = useState(null);
  const fileRef = useRef();
  const checked = useMemo(() => (rows ? withChecks(rows, kinds, existingPhones) : []), [rows, kinds, existingPhones]);
  const good = checked.filter((x) => x.ok); const bad = checked.filter((x) => !x.ok);
  const onFile = async (f) => {
    setErr("");
    try {
      const wb = XLSX.read(await f.arrayBuffer());
      const data = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: "", raw: false }).map(normalizeRow).filter((r) => Object.keys(r).length);
      if (!data.length) return setErr("No rows found. Use the template's column names in the first row.");
      if (data.length > 500) return setErr("Up to 500 rows per file. Please split the file.");
      setRows(data);
    } catch { setErr("Could not read this file. Upload an .xlsx, .xls or .csv file."); }
  };
  const change = (i, k, v) => setRows((p) => p.map((r, j) => (j === i ? { ...r, [k]: k === "dedicated_phone" ? v.replace(/\D/g, "").slice(0, 10) : v } : r)));
  const start = async () => {
    setBusy(true); setErr("");
    try {
      const { data } = await api.post(`${base}/bulk`, { rows: good.map((x) => toPayload(x.r)), pending: bad.map((x) => toPayload(x.r)) }, { params });
      let j = { status: "running", total: data.total, done: 0, created: 0, failed: 0, pending_saved: data.pending_saved }; setJob(j);
      for (let n = 0; j.status !== "done" && n < 1500; n++) { await new Promise((res) => setTimeout(res, 1500)); j = (await api.get(`${base}/bulk/${data.job_id}`, { params })).data; setJob(j); }
      onFinished();
    } catch (e) { setErr(e?.response?.data?.detail || "Import failed"); setJob(null); } finally { setBusy(false); }
  };
  const shown = checked.map((x, i) => [x, i]).filter(([x]) => !onlyBad || !x.ok);
  return (
    <div className="fixed inset-0 z-50 bg-[#091E42]/50 grid place-items-center p-4" data-testid="bulk-import-dialog">
      <div className="bg-white rounded-lg w-full max-w-6xl max-h-[92vh] flex flex-col shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#DFE1E6]"><div className="font-heading font-bold flex items-center gap-2"><Upload className="h-4 w-4 text-[#0052CC]" /> Bulk import entities</div>
          <button onClick={onClose} disabled={busy} data-testid="bulk-close"><X className="h-4 w-4" /></button></div>
        {job ? <Progress job={job} onClose={onClose} /> : <>
          <div className="p-5 overflow-auto space-y-4 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => e.target.files[0] && onFile(e.target.files[0])} data-testid="bulk-file-input" />
              <button onClick={() => fileRef.current.click()} className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-md text-white bg-[#0052CC] hover:bg-[#0747A6]" data-testid="bulk-choose-file"><Upload className="h-4 w-4" />{rows ? "Choose another file" : "Choose Excel or CSV file"}</button>
              <button onClick={() => downloadTemplate(kinds)} className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]" data-testid="bulk-template"><Download className="h-4 w-4" /> Download template</button>
            </div>
            {!rows && <p className="text-sm text-[#5E6C84]">One row per entity. Required: type, entity name, admin / owner name, dedicated login phone, address and city. You'll see a preview before anything is created.</p>}
            {err && <div className="text-sm text-[#BF2600] bg-[#FFEBE6] rounded px-3 py-2" data-testid="bulk-error">{err}</div>}
            {rows && <>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="px-2 py-1 rounded bg-[#E3FCEF] text-[#006644] font-semibold" data-testid="bulk-ready-count">{good.length} ready</span>
                <span className="px-2 py-1 rounded bg-[#FFF4E5] text-[#974F0C] font-semibold" data-testid="bulk-bad-count">{bad.length} need fixing</span>
                <label className="flex items-center gap-1.5 text-[#42526E]"><input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} data-testid="bulk-only-bad" /> Show only rows with problems</label>
                <span className="text-xs text-[#5E6C84]">Fix highlighted cells here, or import now and fix them later from Pending.</span>
              </div>
              <div className="overflow-auto border border-[#DFE1E6] rounded-md max-h-[50vh]">
                <table className="text-left"><thead className="bg-[#F4F5F7] sticky top-0"><tr><th className="px-2 py-2" /><th className="px-2 py-2 text-[10px] font-bold uppercase tracking-wider text-[#5E6C84]">Problems</th>{COLUMNS.map((k) => <th key={k} className="px-2 py-2 text-[10px] font-bold uppercase tracking-wider text-[#5E6C84] whitespace-nowrap">{LABEL[k]}</th>)}<th /></tr></thead>
                  <tbody>{shown.map(([x, i]) => <PreviewRow key={i} i={i} row={x} kinds={kinds} onChange={change} onRemove={(n) => setRows((p) => p.filter((_, j) => j !== n))} />)}</tbody></table>
              </div>
            </>}
          </div>
          <div className="flex flex-wrap justify-end gap-2 px-5 py-3 border-t border-[#DFE1E6]">
            <button onClick={onClose} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="bulk-cancel">Cancel</button>
            <button onClick={start} disabled={busy || !rows || !checked.length} className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md disabled:opacity-50" data-testid="bulk-start">
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}{bad.length ? `Import ${good.length} ready, save ${bad.length} to Pending` : `Import ${good.length} entities`}</button>
          </div></>}
      </div>
    </div>
  );
}
