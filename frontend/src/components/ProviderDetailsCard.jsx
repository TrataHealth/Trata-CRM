import React, { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";

const HIDE = new Set(["id", "user_id", "tenant_id", "phone_key"]);
const label = (k) => k.replace(/_/g, " ");
const show = (v) => {
  if (v == null || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : x)).join(", ") : "—";
  if (typeof v === "object") return Object.entries(v).map(([a, b]) => `${label(a)}: ${typeof b === "object" ? JSON.stringify(b) : b}`).join(" · ") || "—";
  if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return new Date(v).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  return String(v);
};

function Grid({ obj, testid }) {
  const rows = Object.entries(obj || {}).filter(([k, v]) => !HIDE.has(k) && v !== null && v !== "" && !(Array.isArray(v) && !v.length));
  if (!rows.length) return <div className="text-xs text-[#5E6C84]">Nothing filled in yet.</div>;
  return (
    <dl className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3" data-testid={testid}>
      {rows.map(([k, v]) => (
        <div key={k} className="min-w-0"><dt className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label(k)}</dt>
          <dd className="text-sm text-[#091E42] break-words">{show(v)}</dd></div>))}
    </dl>
  );
}

function Section({ title, sub, children, open: initial = true, testid }) {
  const [open, setOpen] = useState(initial);
  return (
    <div className="border-t border-[#DFE1E6] first:border-0">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 py-3 text-left" data-testid={`${testid}-toggle`}>
        {open ? <ChevronDown className="h-4 w-4 text-[#5E6C84]" /> : <ChevronRight className="h-4 w-4 text-[#5E6C84]" />}
        <span className="font-heading font-bold text-[#091E42]">{title}</span>{sub && <span className="text-xs text-[#5E6C84]">{sub}</span>}
      </button>
      {open && <div className="pb-4 pl-6">{children}</div>}
    </div>
  );
}

/** Everything the Provider app holds about this provider: account, vertical profile, TrataX KYC application and every uploaded document. */
export function ProviderDetailsCard({ data }) {
  if (!data) return null;
  const app = data.kyc_application;
  const docs = data.all_documents || [];
  return (
    <section className="bg-white border border-[#DFE1E6] rounded-md px-5" data-testid="provider-details-card">
      <Section title="Account" sub="Provider app login" testid="pd-account"><Grid obj={data.provider} testid="pd-account-grid" /></Section>
      <Section title="Profile" sub={data.profile_table ? `as filled in the Provider app` : "no profile table for this role"} testid="pd-profile">
        {data.profile ? <Grid obj={data.profile} testid="pd-profile-grid" /> : <div className="text-xs text-[#5E6C84]">No profile created yet.</div>}
      </Section>
      <Section title="KYC application" sub={app ? `status: ${app.status || "—"}` : "not started"} testid="pd-kyc-app">
        {app ? <div className="space-y-4">
          <Grid obj={{ status: app.status, org_type: app.org_type, email: app.email, submitted_by: app.submitted_by, reviewed_by: app.reviewed_by, reviewed_at: app.reviewed_at, approved_at: app.approved_at, rejected_at: app.rejected_at, rejection_reason: app.rejection_reason, created_at: app.created_at, updated_at: app.updated_at }} testid="pd-kyc-app-grid" />
          {app.fields && Object.keys(app.fields).length > 0 && <div><div className="text-xs font-semibold text-[#42526E] mb-2">Submitted details</div><Grid obj={app.fields} testid="pd-kyc-fields" /></div>}
          {Array.isArray(app.timeline) && app.timeline.length > 0 && <div><div className="text-xs font-semibold text-[#42526E] mb-1">Timeline</div>
            <ul className="text-xs text-[#42526E] space-y-0.5">{app.timeline.map((t, i) => <li key={i}>{show(t.at || t.created_at)} — {t.status || t.action || t.event} {t.by ? `· ${t.by}` : ""} {t.note || t.reason || ""}</li>)}</ul></div>}
        </div> : <div className="text-xs text-[#5E6C84]">This provider hasn&apos;t started a KYC application in the Provider app.</div>}
      </Section>
      <Section title="KYC documents" sub={`${docs.length} uploaded`} testid="pd-kyc-docs">
        {docs.length ? <ul className="divide-y divide-[#F4F5F7]" data-testid="pd-kyc-doc-list">{docs.map((d) => (
          <li key={d.id} className="py-2 flex flex-wrap items-center gap-3 text-sm">
            <FileText className="h-4 w-4 text-[#5E6C84]" />
            <span className="font-semibold text-[#091E42] capitalize">{label(d.document_type || "document")}</span>
            <span className="text-xs text-[#5E6C84]">{d.document_name}</span>
            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-[#F4F5F7] text-[#42526E]">{d.status || "pending"}</span>
            {d.rejection_reason && <span className="text-xs text-[#BF2600]">{d.rejection_reason}</span>}
            <span className="text-xs text-[#97A0AF] ml-auto">{show(d.created_at || d.uploaded_at)}</span>
            {(d.document_url || d.file_url) && <a href={d.document_url || d.file_url} target="_blank" rel="noreferrer" className="text-xs font-semibold text-[#0052CC]">Open</a>}
          </li>))}</ul> : <div className="text-xs text-[#5E6C84]">No documents uploaded yet.</div>}
      </Section>
    </section>
  );
}
