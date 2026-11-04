import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { RecordHistory, DetailTabs } from "../components/history/RecordHistory";
import { ProviderDetailsCard } from "../components/ProviderDetailsCard";
import { ServiceTypesToggle } from "../components/ServiceTypesToggle";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, BadgeCheck, CheckCircle2,
  FileText, Loader2, ShieldCheck, Upload, XCircle, User, Sparkles,
} from "lucide-react";

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  head: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between",
  btn: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-40",
  btnGhost: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] hover:bg-[#F4F5F7] disabled:opacity-40",
  btnSuccess: "inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-md bg-[#006644] text-white hover:bg-[#00875A] disabled:opacity-40 disabled:cursor-not-allowed",
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

async function readFileAsBase64(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      const b64 = dataUrl.split(",")[1] || "";
      resolve({ b64, size: file.size, name: file.name });
    };
    reader.onerror = () => reject(reader.error || new Error("Read failed"));
    reader.readAsDataURL(file);
  });
}

export default function AdminProviderKyc() {
  const { userId } = useParams();
  const nav = useNavigate();
  const [state, setState] = useState({ loading: true, err: "", data: null });
  const [uploadingKey, setUploadingKey] = useState("");
  const [approving, setApproving] = useState(false);
  const fileRefs = useRef({});
  const { user } = useAuth();
  const [tab, setTab] = useState("overview");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/admin/onboarding/providers/${userId}/kyc`);
      setState({ loading: false, err: "", data });
    } catch (e) {
      setState({ loading: false, err: e?.response?.data?.detail || "Could not load KYC", data: null });
    }
  }, [userId]);
  useEffect(() => { load(); }, [load]);

  const pickFile = (key) => fileRefs.current[key]?.click();

  const handleFile = async (key, file, label) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error("File too large (max 4 MB)");
    setUploadingKey(key);
    try {
      const { b64, name } = await readFileAsBase64(file);
      await api.post(`/admin/onboarding/providers/${userId}/kyc/upload`, {
        document_type: key,
        document_name: `${label} — ${name}`,
        file_base64: b64,
      });
      toast.success(`${label} uploaded`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally { setUploadingKey(""); }
  };

  const approveAll = async () => {
    if (!window.confirm(
      "Approve every submitted KYC document and mark this provider as verified?\n" +
      "The mobile Provider App and Trata Admin App will unlock this provider immediately."
    )) return;
    setApproving(true);
    const post = (body) => api.post(`/admin/onboarding/providers/${userId}/approve-all`, body || {});
    try {
      let res;
      try { res = await post(); }
      catch (e) {
        if (e?.response?.data?.detail?.error !== "location_missing") throw e;
        const v = window.prompt("This provider has no location. Enter latitude,longitude (e.g. 19.2352,72.8408):");
        if (!v) { toast.error("Approval cancelled — location required"); return; }
        const [lat, lng] = v.split(",").map(x => parseFloat(x.trim()));
        res = await post({ lat, lng });
      }
      toast.success(`${res.data.docs_approved} docs approved · provider is now VERIFIED`);
      await load();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (typeof detail === "object" && detail?.message && !detail?.missing) {
        toast.error(detail.message);
      } else if (typeof detail === "object" && detail?.missing) {
        toast.error(`${detail.message} (missing: ${detail.missing.join(", ")})`);
      } else {
        toast.error(detail || "Approval failed");
      }
    } finally { setApproving(false); }
  };

  if (state.loading) return (
    <div className="p-8 flex items-center gap-2 text-sm text-[#5E6C84]" data-testid="admin-kyc-loading">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading KYC checklist…
    </div>
  );
  if (state.err) return (
    <div className="p-6 max-w-xl mx-auto mt-10" data-testid="admin-kyc-error">
      <div className="bg-[#FFEBE6] border border-[#FF5630]/40 rounded-md p-4 text-sm text-[#BF2600] flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <div>
          <div className="font-semibold">KYC unavailable</div>
          <div className="text-xs mt-1">{state.err}</div>
          <button className={T.btnGhost + " mt-3"} onClick={() => nav("/admin/onboarding")}><ArrowLeft className="h-3.5 w-3.5" /> Back to onboarding</button>
        </div>
      </div>
    </div>
  );

  const { provider, vertical, checklist = [], all_required_approved } = state.data;
  const requiredItems = checklist.filter(i => i.required);
  const totalRequired = requiredItems.length;
  const requiredUploaded = requiredItems.filter(i => i.upload).length;
  const canApprove = totalRequired > 0 && requiredUploaded === totalRequired && !all_required_approved;
  const alreadyApproved = !!all_required_approved;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="admin-kyc-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/users/providers" className="inline-flex items-center gap-1 text-xs text-[#5E6C84] hover:text-[#091E42]" data-testid="admin-kyc-back">
            <ArrowLeft className="h-3 w-3" /> All providers
          </Link>
          <div className="overline flex items-center gap-1 mt-2"><ShieldCheck className="h-3 w-3" /> KYC onboarding · {vertical}</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
            {provider.name}
          </h1>
          <div className="text-sm text-[#5E6C84] mt-1 flex items-center gap-2">
            <User className="h-3.5 w-3.5" /> {/^\+?\d{10,13}$/.test(provider.phone || "") ? `+91 ${String(provider.phone).replace(/^\+?91(?=\d{10}$)/, "")}` : "No phone"} · <StatusChip status={provider.verification_status} />
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {user?.is_master_admin && <DetailTabs tab={tab} setTab={setTab} />}
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">Required docs uploaded</div>
            <div className="font-heading text-2xl font-black text-[#091E42]">{requiredUploaded} / {totalRequired}</div>
          </div>
          <button
            className={T.btnSuccess}
            disabled={approving || alreadyApproved || !canApprove}
            onClick={approveAll}
            data-testid="admin-kyc-approve-all">
            {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {alreadyApproved ? "Already approved" : "Approve all & activate"}
          </button>
        </div>
      </div>

      {tab === "history" ? <RecordHistory recordId={userId} /> : <>
      <ProviderDetailsCard data={state.data} />
      <ServiceTypesToggle userId={userId} />
      {alreadyApproved && (
        <div className="bg-[#E3FCEF] border border-[#57D9A3] rounded-md p-3 text-xs text-[#006644] flex items-center gap-2" data-testid="admin-kyc-approved-banner">
          <BadgeCheck className="h-4 w-4" /> Every required document is approved — this provider is now live on the mobile Provider App and Trata Admin App.
        </div>
      )}

      {state.data.kyc_enabled === false && (
        <div className="bg-[#F4F5F7] border border-[#DFE1E6] rounded-md p-3 text-xs text-[#42526E]" data-testid="admin-kyc-staff-note">
          This is a staff account ({vertical}) under a provider organisation — KYC is done at the organisation level, so there's no checklist to upload here.
        </div>
      )}
      {state.data.kyc_enabled !== false && <section className={T.card}>
        <div className={T.head}>
          <span>Checklist · {vertical}</span>
          <span className="normal-case text-[10px] text-[#5E6C84] font-normal">
            {canApprove ? "Ready for one-click approval →" : `Upload the remaining ${totalRequired - requiredUploaded} required doc(s) to unlock approve`}
          </span>
        </div>
        <div className="divide-y divide-[#DFE1E6]">
          {checklist.map((item) => {
            const up = item.upload;
            const status = up?.status || "pending";
            const isUploading = uploadingKey === item.key;
            const isAdminUpload = up?.document_name?.startsWith("[Admin]");
            return (
              <div key={item.key} className="p-4 flex items-start gap-3" data-testid={`admin-kyc-row-${item.key}`}>
                <div className="mt-0.5">
                  {up ? <CheckCircle2 className="h-4 w-4 text-[#006644]" /> : <XCircle className="h-4 w-4 text-[#5E6C84]" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="font-semibold text-sm text-[#091E42]">{item.label}</div>
                    {item.required
                      ? <span className={`${T.chip} bg-[#FFEBE6] text-[#BF2600]`}>REQUIRED</span>
                      : <span className={`${T.chip} bg-[#F4F5F7] text-[#5E6C84]`}>OPTIONAL</span>}
                    {up && <StatusChip status={status} />}
                    {isAdminUpload && <span className={`${T.chip} bg-[#EAE6FF] text-[#403294]`}>ADMIN UPLOAD</span>}
                  </div>
                  <div className="text-xs text-[#5E6C84] mt-1">{item.hint}</div>
                  {up && (
                    <div className="text-[11px] text-[#5E6C84] mt-1 flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      <span className="truncate max-w-[420px]">{up.document_name}</span>
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-1">
                  <input
                    type="file"
                    accept="image/*,application/pdf"
                    style={{ display: "none" }}
                    ref={(el) => (fileRefs.current[item.key] = el)}
                    onChange={(e) => handleFile(item.key, e.target.files?.[0], item.label)}
                    data-testid={`admin-kyc-file-${item.key}`}
                  />
                  <button
                    className={T.btn}
                    disabled={isUploading || alreadyApproved}
                    onClick={() => pickFile(item.key)}
                    data-testid={`admin-kyc-upload-${item.key}`}>
                    {isUploading
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <Upload className="h-3.5 w-3.5" />}
                    {up ? "Re-upload" : "Upload"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>}

      <div className="text-[10px] text-[#5E6C84]">
        Writes go directly to shared Supabase — the mobile Provider App and Trata Admin App reflect changes in real time.
      </div>
      </>}
    </div>
  );
}
