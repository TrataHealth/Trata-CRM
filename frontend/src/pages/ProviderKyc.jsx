import React, { useCallback, useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { relativeTime } from "../lib/constants";
import { toast } from "sonner";
import {
  AlertTriangle, BadgeCheck, CheckCircle2, ChevronRight,
  FileText, Loader2, ShieldAlert, ShieldCheck, Upload, X,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  sectionHead: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]",
  btnPrimary: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnGhost:   "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full",
};

const STATUS_TONE = {
  submitted: "bg-[#DEEBFF] text-[#0747A6]",
  under_review: "bg-[#FFFAE6] text-[#974F0C]",
  approved: "bg-[#E3FCEF] text-[#006644]",
  verified: "bg-[#E3FCEF] text-[#006644]",
  rejected: "bg-[#FFEBE6] text-[#BF2600]",
};

function StatusChip({ status }) {
  const v = String(status || "pending").toLowerCase();
  const tone = STATUS_TONE[v] || "bg-[#F4F5F7] text-[#5E6C84]";
  return <span className={`${T.chip} ${tone}`}>{v.replace(/_/g, " ").toUpperCase()}</span>;
}

// Read a File object → base64 string. Returns { b64, size, name } or throws.
async function readFileAsBase64(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      const b64 = dataUrl.split(",")[1] || "";
      resolve({ b64, size: file.size, name: file.name });
    };
    reader.onerror = () => reject(new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

// ── Individual checklist row ────────────────────────────────────────────────
function ChecklistRow({ item, onUpload, uploading }) {
  const [expanded, setExpanded] = useState(false);
  const [customName, setCustomName] = useState("");
  const [busy, setBusy] = useState(false);
  const upload = item.upload;
  const isDone = upload && ["approved", "verified", "submitted", "under_review"].includes(String(upload.status || "").toLowerCase());
  const isRejected = upload && String(upload.status || "").toLowerCase() === "rejected";

  const onPick = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) { toast.error("File too big (max 4 MB)"); return; }
    setBusy(true);
    try {
      const { b64 } = await readFileAsBase64(file);
      await onUpload(item, { file_base64: b64, document_name: customName || file.name });
      setExpanded(false); setCustomName("");
    } catch (err) { toast.error(err.message || "Upload failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="border-b border-[#DFE1E6] last:border-0" data-testid={`kyc-row-${item.key}`}>
      <div className="p-4 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-sm font-semibold text-[#091E42]">{item.label}</div>
            {item.required
              ? <span className={`${T.chip} bg-[#FFEBE6] text-[#BF2600]`}>REQUIRED</span>
              : <span className={`${T.chip} bg-[#F4F5F7] text-[#5E6C84]`}>OPTIONAL</span>}
            {upload && <StatusChip status={upload.status} />}
          </div>
          <div className="text-[11px] text-[#5E6C84] mt-1">{item.hint}</div>
          {upload && (
            <div className="mt-2 text-[11px] text-[#42526E]">
              <FileText className="h-3 w-3 inline mr-1" />
              <span className="font-medium">{upload.document_name || upload.document_type}</span>
              {upload.submitted_at && <span className="text-[#5E6C84]"> · submitted {relativeTime(upload.submitted_at)}</span>}
              {upload.reviewed_at && <span className="text-[#5E6C84]"> · reviewed {relativeTime(upload.reviewed_at)}</span>}
            </div>
          )}
          {isRejected && upload?.rejection_reason && (
            <div className="mt-2 p-2 bg-[#FFEBE6] rounded text-[11px] text-[#BF2600]">
              <b>Rejection:</b> {upload.rejection_reason}
              {upload.rejection_comment ? ` — ${upload.rejection_comment}` : ""}
            </div>
          )}
        </div>
        <div className="shrink-0">
          {isDone && !isRejected ? (
            <button className={T.btnGhost} onClick={() => setExpanded((v) => !v)} data-testid={`kyc-reupload-${item.key}`}>
              <Upload className="h-3.5 w-3.5" /> Re-upload
            </button>
          ) : (
            <button className={T.btnPrimary} onClick={() => setExpanded((v) => !v)} data-testid={`kyc-upload-${item.key}`}>
              <Upload className="h-3.5 w-3.5" /> {isRejected ? "Upload again" : "Upload"}
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 pt-1 bg-[#F8F9FA] border-t border-[#DFE1E6]" data-testid={`kyc-form-${item.key}`}>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 items-end">
            <label className="text-[11px] text-[#42526E] md:col-span-2">Display name (optional)
              <input className="w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded"
                value={customName} onChange={(e) => setCustomName(e.target.value)}
                placeholder={`e.g. ${item.label} (${new Date().getFullYear()})`}
                data-testid={`kyc-form-name-${item.key}`} />
            </label>
            <div className="flex items-center gap-2">
              <label className={T.btnPrimary + " cursor-pointer" + (busy || uploading ? " opacity-40" : "")}>
                {busy || uploading
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Uploading…</>
                  : <><Upload className="h-3.5 w-3.5" /> Pick file (≤ 4 MB)</>}
                <input type="file" accept="image/*,application/pdf" className="hidden" onChange={onPick} disabled={busy || uploading} data-testid={`kyc-form-file-${item.key}`} />
              </label>
              <button className={T.btnGhost} onClick={() => { setExpanded(false); setCustomName(""); }}><X className="h-3.5 w-3.5" /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── main page ───────────────────────────────────────────────────────────────
export default function ProviderKyc() {
  const { user } = useAuth();
  const [state, setState] = useState({ loading: true, checklist: [], all_documents: [], err: "" });
  const [uploading, setUploading] = useState(false);
  const supportedByPortal = user?.provider_type && user.provider_type !== "paramedic";

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/provider/kyc/checklist");
      setState({ loading: false, checklist: data.checklist || [], all_documents: data.all_documents || [], err: "" });
    } catch (e) {
      setState({ loading: false, checklist: [], all_documents: [], err: e?.response?.data?.detail || "Could not load KYC checklist" });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const doUpload = async (item, payload) => {
    setUploading(true);
    try {
      await api.post("/provider/kyc/upload", {
        document_type: item.key,
        document_name: payload.document_name || item.label,
        file_base64: payload.file_base64,
      });
      toast.success(`${item.label} submitted for review`);
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Upload failed"); }
    finally { setUploading(false); }
  };

  if (state.loading) {
    return <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="kyc-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading KYC checklist…</div>;
  }
  if (state.err) {
    return (
      <div className="p-6 max-w-xl mx-auto mt-10" data-testid="kyc-error">
        <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">KYC unavailable</div>
            <div className="text-xs mt-1">{state.err}</div>
          </div>
        </div>
      </div>
    );
  }

  if (!supportedByPortal) {
    return (
      <div className="p-8 max-w-xl mx-auto mt-10 text-sm text-[#5E6C84]">
        <ShieldAlert className="h-5 w-5 mb-2" />
        KYC uploads are available only for hospital, ambulance, doctor, pathology and pharmacy providers on the CRM console.
      </div>
    );
  }

  const required = state.checklist.filter((c) => c.required);
  const optional = state.checklist.filter((c) => !c.required);
  const doneOf = (list) => list.filter((c) => c.upload && !["rejected"].includes(String(c.upload.status || "").toLowerCase())).length;
  const requiredDone = doneOf(required);
  const overallPct = state.checklist.length ? Math.round(doneOf(state.checklist) / state.checklist.length * 100) : 0;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-5xl" data-testid="provider-kyc-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1"><ShieldCheck className="h-3 w-3" /> Compliance</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">{user?.name} · KYC</h1>
          <p className="text-sm text-[#5E6C84] mt-1">Same checklist as the Trata Provider mobile app. Uploads land in the shared review queue and reflect on your app within a minute.</p>
        </div>
        <div className={T.card + " p-3 flex items-center gap-3 min-w-[220px]"} data-testid="kyc-progress">
          <div className="relative w-11 h-11 shrink-0">
            <svg viewBox="0 0 36 36" className="w-11 h-11 -rotate-90">
              <circle cx="18" cy="18" r="15" fill="none" stroke="#F1F2F4" strokeWidth="4" />
              <circle cx="18" cy="18" r="15" fill="none" stroke="#0052CC" strokeWidth="4"
                strokeDasharray={`${overallPct * 0.94} 100`} strokeLinecap="round" />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center text-xs font-black text-[#091E42]">{overallPct}%</div>
          </div>
          <div className="text-[11px] leading-tight">
            <div className="font-bold text-[#091E42]">{requiredDone}/{required.length} required · {doneOf(optional)}/{optional.length} optional</div>
            <div className="text-[#5E6C84]">{state.checklist.length - doneOf(state.checklist)} to go</div>
          </div>
        </div>
      </div>

      <section className={T.card} data-testid="kyc-required-section">
        <div className={T.sectionHead}>Required · {requiredDone}/{required.length}</div>
        {required.map((item) => <ChecklistRow key={item.key} item={item} onUpload={doUpload} uploading={uploading} />)}
      </section>

      {optional.length > 0 && (
        <section className={T.card} data-testid="kyc-optional-section">
          <div className={T.sectionHead}>Optional</div>
          {optional.map((item) => <ChecklistRow key={item.key} item={item} onUpload={doUpload} uploading={uploading} />)}
        </section>
      )}

      <section className={T.card} data-testid="kyc-history">
        <div className={T.sectionHead}>Upload history · {state.all_documents.length} document{state.all_documents.length === 1 ? "" : "s"}</div>
        {state.all_documents.length === 0 ? (
          <div className="p-6 text-center text-sm text-[#5E6C84]">Nothing uploaded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
                <tr>
                  <th className="px-3 py-2 text-left">Document</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">Status</th>
                  <th className="px-3 py-2 text-left">Submitted</th>
                  <th className="px-3 py-2 text-left">Reviewed</th>
                  <th className="px-3 py-2 text-left">Comment</th>
                </tr>
              </thead>
              <tbody>
                {state.all_documents.map((d) => (
                  <tr key={d.id} className="border-t border-[#DFE1E6]" data-testid={`kyc-doc-${d.id}`}>
                    <td className="px-3 py-2 text-[#091E42] max-w-[280px] truncate">{d.document_name || "—"}</td>
                    <td className="px-3 py-2">{(d.document_type || "").replace(/_/g, " ")}</td>
                    <td className="px-3 py-2"><StatusChip status={d.status} /></td>
                    <td className="px-3 py-2">{d.submitted_at ? relativeTime(d.submitted_at) : "—"}</td>
                    <td className="px-3 py-2">{d.reviewed_at ? relativeTime(d.reviewed_at) : "—"}</td>
                    <td className="px-3 py-2 max-w-[300px] truncate">{d.rejection_reason ? `${d.rejection_reason} · ${d.rejection_comment || ""}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
