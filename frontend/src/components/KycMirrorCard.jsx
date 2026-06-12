import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  ShieldCheck, ShieldAlert, ShieldQuestion, Loader2, RefreshCw, ExternalLink,
  CheckCircle2, XCircle, FileText, FileQuestion, AlertCircle, MessagesSquare, Send, Sparkles, Crown, Wand2,
} from "lucide-react";
import { relativeTime } from "../lib/constants";
import SlaChip from "./SlaChip";

const DOC_STATUS_STYLE = {
  approved: { color: "#36B37E", icon: CheckCircle2, label: "Approved" },
  pending:  { color: "#FFAB00", icon: FileQuestion, label: "Pending" },
  rejected: { color: "#FF5630", icon: XCircle,      label: "Rejected" },
};

const STATUS_STYLE = {
  pending:        { color: "#FFAB00", icon: ShieldQuestion, label: "Pending" },
  in_review:      { color: "#0052CC", icon: ShieldQuestion, label: "In Review" },
  approved:       { color: "#36B37E", icon: ShieldCheck,    label: "Approved" },
  rejected:       { color: "#FF5630", icon: ShieldAlert,    label: "Rejected" },
  needs_more_info:{ color: "#974F0C", icon: AlertCircle,    label: "Needs more info" },
};

export default function KycMirrorCard({ contactId }) {
  const { user: me } = useAuth();
  const [state, setState] = useState({ loading: true, data: null, contact: null, err: "" });
  const [docReviewing, setDocReviewing] = useState({ docId: null, decision: "approved", notes: "" });
  const [submitting, setSubmitting] = useState(false);
  const [adminForm, setAdminForm] = useState({ open: false, decision: "verified", notes: "" });
  const [aiScanning, setAiScanning] = useState(false);

  const isAdmin = me?.is_master_admin || me?.role === "admin";

  const load = async (refresh = false) => {
    setState((s) => ({ ...s, loading: true, err: "" }));
    try {
      const [{ data }, contactResp] = await Promise.all([
        api.get(`/contacts/${contactId}/kyc`, { params: refresh ? { refresh: true } : {} }),
        api.get(`/contacts/${contactId}`),
      ]);
      setState({ loading: false, data, contact: contactResp.data?.contact, err: "" });
    } catch (e) {
      setState({ loading: false, data: null, contact: null, err: e?.response?.data?.detail || "Could not fetch KYC" });
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [contactId]);

  const reviewDoc = async (docId, decision) => {
    const ai = (state.contact?.ai_doc_prescreens || {})[docId];
    const aiDecision = ai?.recommendation === "approve" ? "approved" : ai?.recommendation === "reject" ? "rejected" : null;
    const aiHint = ai && aiDecision === decision && ai.reason ? `AI: ${ai.reason}` : "";
    setDocReviewing({ docId, decision, notes: aiHint });
  };

  const runAiPrescreen = async () => {
    if (aiScanning) return;
    setAiScanning(true);
    setState((s) => ({ ...s, err: "" }));
    try {
      const { data } = await api.post(`/contacts/${contactId}/kyc-ai-prescreen`);
      // Optimistic merge so the docs section doesn't flicker back to its loading skeleton
      setState((s) => ({
        ...s,
        contact: {
          ...(s.contact || {}),
          ai_doc_prescreens: data.ai_doc_prescreens || {},
          ai_prescreen_summary: data.ai_prescreen_summary || null,
        },
      }));
    } catch (e) {
      setState((s) => ({ ...s, err: e?.response?.data?.detail || "AI pre-screen failed" }));
    }
    setAiScanning(false);
  };

  const submitDocReview = async () => {
    setSubmitting(true);
    try {
      await api.post(`/contacts/${contactId}/kyc-doc-review`, {
        doc_id: docReviewing.docId, decision: docReviewing.decision, notes: docReviewing.notes,
      });
      setDocReviewing({ docId: null, decision: "approved", notes: "" });
      await load(true);
    } catch (e) {
      setState((s) => ({ ...s, err: e?.response?.data?.detail || "Could not save doc review" }));
    }
    setSubmitting(false);
  };

  const submitForAdmin = async () => {
    if (!window.confirm("Submit all doc reviews to Master Admin for final approval?")) return;
    setSubmitting(true);
    try {
      await api.post(`/contacts/${contactId}/kyc-submit-for-admin`);
      await load(true);
    } catch (e) {
      setState((s) => ({ ...s, err: e?.response?.data?.detail || "Submit failed" }));
    }
    setSubmitting(false);
  };

  const adminFinalDecide = async () => {
    setSubmitting(true);
    try {
      await api.post(`/contacts/${contactId}/kyc-admin-final`, adminForm);
      setAdminForm({ open: false, decision: "verified", notes: "" });
      await load(true);
    } catch (e) {
      setState((s) => ({ ...s, err: e?.response?.data?.detail || "Final decision failed" }));
    }
    setSubmitting(false);
  };

  if (state.loading) {
    return (
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="kyc-card">
        <div className="overline flex items-center gap-1.5"><ShieldQuestion className="h-3 w-3" /> KYC Mirror</div>
        <div className="mt-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 inline animate-spin mr-1" /> Loading KYC from Trata Admin App…</div>
      </div>
    );
  }

  if (!state.data?.available) {
    return (
      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="kyc-card">
        <div className="overline flex items-center gap-1.5"><ShieldQuestion className="h-3 w-3" /> KYC Mirror</div>
        <div className="mt-2 text-sm text-[#974F0C] bg-[#FFFAE6] border border-[#FFC400]/40 rounded p-3">
          <AlertCircle className="h-4 w-4 inline mr-1" />
          {state.data?.message || state.err || "KYC data not available."}
        </div>
        <button onClick={() => load(true)} data-testid="kyc-refresh-btn" className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-[#0052CC] hover:underline">
          <RefreshCw className="h-3.5 w-3.5" /> Try again
        </button>
      </div>
    );
  }

  const { kyc, synced_at, local_decision } = state.data;
  const statusMeta = STATUS_STYLE[kyc.status] || STATUS_STYLE.pending;
  const completedCount = (kyc.checklist || []).filter((x) => x.completed).length;
  const totalCount = (kyc.checklist || []).length;
  const StatusIcon = statusMeta.icon;

  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="kyc-card">
      {/* Header */}
      <div className="px-5 py-4 border-b border-[#DFE1E6] flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="overline flex items-center gap-1.5"><ShieldCheck className="h-3 w-3" /> KYC Mirror</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1 flex items-center gap-2">
            From Trata Admin App
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded text-white" style={{ background: statusMeta.color }} data-testid="kyc-status-pill">
              <StatusIcon className="h-3 w-3" /> {statusMeta.label}
            </span>
          </div>
          <div className="text-xs text-[#5E6C84] mt-1 flex flex-wrap gap-3">
            <span>Synced {relativeTime(synced_at)}</span>
            {kyc.kyc_id && <span className="font-mono">kyc_id: {kyc.kyc_id.slice(0, 8)}…</span>}
            {kyc.last_review_by && <span>last reviewed by <b className="text-[#091E42]">{kyc.last_review_by}</b></span>}
          </div>
        </div>
        <button onClick={() => load(true)} data-testid="kyc-refresh-btn" className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold border border-[#DFE1E6] rounded hover:bg-[#F4F5F7]">
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {/* Checklist + Docs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-[#DFE1E6]">
        <div className="p-5" data-testid="kyc-checklist">
          <div className="overline mb-3 flex items-center justify-between">
            <span>Checklist</span>
            <span className="text-[#5E6C84] normal-case tracking-normal text-[11px]">{completedCount} of {totalCount} complete</span>
          </div>
          {/* Progress bar */}
          <div className="h-1.5 bg-[#F1F2F4] rounded-full overflow-hidden mb-3" data-testid="kyc-progress">
            <div className="h-full bg-[#36B37E] transition-all" style={{ width: `${totalCount ? (completedCount / totalCount) * 100 : 0}%` }} />
          </div>
          <ul className="space-y-1.5">
            {(kyc.checklist || []).map((item) => (
              <li key={item.item} className="flex items-center justify-between gap-2 text-sm" data-testid={`kyc-item-${item.item}`}>
                <span className="flex items-center gap-2 min-w-0">
                  {item.completed
                    ? <CheckCircle2 className="h-4 w-4 text-[#36B37E] shrink-0" />
                    : <span className="h-4 w-4 rounded border border-[#DFE1E6] shrink-0" />}
                  <span className={item.completed ? "text-[#091E42]" : "text-[#42526E]"}>{item.label || item.item}</span>
                </span>
                {item.required && <span className="text-[10px] uppercase tracking-wider text-[#5E6C84]">Required</span>}
              </li>
            ))}
            {totalCount === 0 && <div className="text-sm text-[#5E6C84]">No checklist items yet.</div>}
          </ul>
        </div>

        <div className="p-5" data-testid="kyc-docs">
          <div className="overline mb-3 flex items-center justify-between gap-2 flex-wrap">
            <span>Uploaded documents ({(kyc.docs || []).length})</span>
            {(kyc.docs || []).length > 0 && (
              <button
                onClick={runAiPrescreen}
                disabled={aiScanning}
                data-testid="kyc-ai-prescreen-btn"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold rounded text-white bg-gradient-to-r from-[#6554C0] to-[#403294] hover:opacity-95 disabled:opacity-60 normal-case tracking-normal"
                title="Use Gemini Vision to suggest approve/reject for every document"
              >
                {aiScanning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />}
                {aiScanning ? "AI scanning…" : (state.contact?.ai_prescreen_summary ? "Re-scan with AI" : "AI pre-screen")}
              </button>
            )}
          </div>
          {state.contact?.ai_prescreen_summary && (
            <div className="mb-3 text-[11px] text-[#42526E] bg-[#EAE6FF] border border-[#6554C0]/30 rounded p-2 flex items-center gap-1.5 flex-wrap" data-testid="kyc-ai-summary">
              <Sparkles className="h-3 w-3 text-[#6554C0]" />
              <b className="text-[#403294]">AI suggests:</b>
              <span className="text-[#006644]">{state.contact.ai_prescreen_summary.approve} approve</span>
              <span>·</span>
              <span className="text-[#BF2600]">{state.contact.ai_prescreen_summary.reject} reject</span>
              <span>·</span>
              <span className="text-[#974F0C]">{state.contact.ai_prescreen_summary.unclear} unclear</span>
              <span className="text-[#5E6C84]">(model: {state.contact.ai_prescreen_summary.model})</span>
              <span className="text-[#5E6C84]">— final call is yours.</span>
            </div>
          )}
          {(kyc.docs || []).length === 0 ? (
            <div className="text-sm text-[#5E6C84]">No documents uploaded yet.</div>
          ) : (
            <ul className="space-y-2 max-h-[340px] overflow-y-auto scrollbar-thin">
              {kyc.docs.map((d) => {
                const s = DOC_STATUS_STYLE[d.status] || DOC_STATUS_STYLE.pending;
                const Icon = s.icon;
                const myReview = (state.contact?.agent_doc_reviews || {})[d.id];
                const aiRec = (state.contact?.ai_doc_prescreens || {})[d.id];
                const isReviewing = docReviewing.docId === d.id;
                const aiStyle = aiRec
                  ? (aiRec.recommendation === "approve"
                      ? { bg: "#E3FCEF", fg: "#006644", border: "#36B37E", icon: CheckCircle2, label: "AI: Approve" }
                      : aiRec.recommendation === "reject"
                      ? { bg: "#FFEBE6", fg: "#BF2600", border: "#FF5630", icon: XCircle, label: "AI: Reject" }
                      : { bg: "#FFFAE6", fg: "#974F0C", border: "#FFAB00", icon: AlertCircle, label: "AI: Unclear" })
                  : null;
                const AiIcon = aiStyle?.icon;
                return (
                  <li key={d.id} className="border border-[#DFE1E6] rounded p-2.5" data-testid={`kyc-doc-${d.id}`}>
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="flex items-start gap-2 min-w-0">
                        <FileText className="h-4 w-4 text-[#5E6C84] mt-0.5 shrink-0" />
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-[#091E42] truncate">{d.name || d.kind}</div>
                          <div className="text-[11px] text-[#5E6C84]">{d.kind} · uploaded {relativeTime(d.uploaded_at)}</div>
                        </div>
                      </div>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-semibold rounded text-white whitespace-nowrap" style={{ background: s.color }}>
                        <Icon className="h-3 w-3" /> Admin: {s.label}
                      </span>
                    </div>
                    {d.url && (
                      <a href={d.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-[11px] text-[#0052CC] font-semibold hover:underline" data-testid={`kyc-doc-link-${d.id}`}>
                        <ExternalLink className="h-3 w-3" /> View document
                      </a>
                    )}
                    {/* AI pre-screen recommendation */}
                    {aiStyle && (
                      <div
                        className="mt-2 px-2 py-1 rounded border text-[11px] flex items-start gap-1.5"
                        style={{ background: aiStyle.bg, borderColor: aiStyle.border + "55", color: aiStyle.fg }}
                        data-testid={`kyc-doc-ai-${d.id}`}
                      >
                        <Sparkles className="h-3 w-3 mt-0.5 shrink-0 text-[#6554C0]" />
                        <span className="flex-1">
                          <b>{aiStyle.label}</b>
                          {typeof aiRec.confidence === "number" && (
                            <span className="ml-1 text-[10px] opacity-80">({Math.round(aiRec.confidence * 100)}% conf)</span>
                          )}
                          {aiRec.reason && <span className="block text-[11px] opacity-90 mt-0.5">{aiRec.reason}</span>}
                        </span>
                        {!myReview && aiRec.recommendation !== "unclear" && (
                          <button
                            onClick={() => reviewDoc(d.id, aiRec.recommendation === "approve" ? "approved" : "rejected")}
                            data-testid={`kyc-doc-ai-accept-${d.id}`}
                            className="text-[10px] font-semibold underline whitespace-nowrap"
                            title="Open review with AI reasoning pre-filled"
                          >
                            Use suggestion
                          </button>
                        )}
                      </div>
                    )}
                    {/* My agent-side review */}
                    {myReview ? (
                      <div className="mt-2 flex items-center justify-between text-[11px]" data-testid={`kyc-doc-myreview-${d.id}`}>
                        <span className="flex items-center gap-1">
                          {myReview.decision === "approved" ? <CheckCircle2 className="h-3.5 w-3.5 text-[#36B37E]" /> : <XCircle className="h-3.5 w-3.5 text-[#FF5630]" />}
                          <b className="text-[#091E42]">Sales rep: {myReview.decision.toUpperCase()}</b>
                          {myReview.notes && <span className="text-[#5E6C84]">— {myReview.notes}</span>}
                        </span>
                        <button onClick={() => reviewDoc(d.id, "approved")} data-testid={`kyc-doc-redo-${d.id}`} className="text-[#0052CC] hover:underline">Change</button>
                      </div>
                    ) : (
                      <div className="mt-2 flex gap-2">
                        <button onClick={() => reviewDoc(d.id, "approved")} data-testid={`kyc-doc-approve-${d.id}`} className="flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold bg-[#E3FCEF] text-[#006644] border border-[#36B37E]/30 rounded hover:bg-[#ABF5D1]">
                          <CheckCircle2 className="h-3 w-3" /> Approve
                        </button>
                        <button onClick={() => reviewDoc(d.id, "rejected")} data-testid={`kyc-doc-reject-${d.id}`} className="flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold bg-[#FFEBE6] text-[#BF2600] border border-[#FF5630]/30 rounded hover:bg-[#FFBDAD]">
                          <XCircle className="h-3 w-3" /> Reject
                        </button>
                      </div>
                    )}
                    {/* Notes textarea (inline) */}
                    {isReviewing && (
                      <div className="mt-2 space-y-2 bg-[#FAFBFC] p-2 rounded border border-[#DFE1E6]" data-testid={`kyc-doc-review-form-${d.id}`}>
                        <input
                          value={docReviewing.notes}
                          onChange={(e) => setDocReviewing({ ...docReviewing, notes: e.target.value })}
                          placeholder={docReviewing.decision === "approved" ? "Optional note…" : "Why are you rejecting? (e.g. blurry scan)"}
                          className="w-full px-2 py-1 text-xs border border-[#DFE1E6] rounded"
                        />
                        <div className="flex gap-1.5">
                          <button onClick={submitDocReview} disabled={submitting} data-testid={`kyc-doc-save-${d.id}`} className="px-2 py-1 text-[11px] font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60">
                            {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : `Save ${docReviewing.decision}`}
                          </button>
                          <button onClick={() => setDocReviewing({ docId: null, decision: "approved", notes: "" })} className="px-2 py-1 text-[11px] border border-[#DFE1E6] rounded hover:bg-[#F4F5F7]">Cancel</button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* Notes */}
      {(kyc.notes || []).length > 0 && (
        <div className="px-5 py-4 border-t border-[#DFE1E6]" data-testid="kyc-notes">
          <div className="overline mb-2 flex items-center gap-1.5"><MessagesSquare className="h-3 w-3" /> Review history from Admin App</div>
          <ul className="space-y-1.5">
            {kyc.notes.map((n, i) => (
              <li key={i} className="text-xs text-[#42526E] border-l-2 border-[#0052CC]/30 pl-2 py-0.5">
                <b className="text-[#091E42]">{n.decision || n.author_role || "Note"}</b>
                {n.text ? ` — ${n.text}` : ""}
                {n.created_at && <span className="text-[#5E6C84] ml-1">· {relativeTime(n.created_at)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Two-tier decision panel */}
      <div className="px-5 py-4 border-t border-[#DFE1E6] bg-[#FAFBFC]" data-testid="kyc-decision">
        {(() => {
          const c = state.contact || {};
          const docReviews = c.agent_doc_reviews || {};
          const docsTotal = (kyc.docs || []).length;
          const docsReviewed = Object.keys(docReviews).length;
          const allReviewed = docsTotal > 0 && docsReviewed >= docsTotal;
          const kycStatus = c.kyc_status;

          if (kycStatus === "verified") {
            return (
              <div className="flex items-center gap-2 text-sm font-semibold text-[#006644]" data-testid="kyc-state-verified">
                <ShieldCheck className="h-5 w-5" /> Master Admin VERIFIED on {relativeTime(c.kyc_admin_decision_at)} by {c.kyc_admin_decision_by || "admin"}
                {c.kyc_admin_decision_notes && <span className="text-[#5E6C84] font-normal">— {c.kyc_admin_decision_notes}</span>}
              </div>
            );
          }
          if (kycStatus === "rejected" && c.kyc_admin_decision_at) {
            return (
              <div className="flex items-center gap-2 text-sm font-semibold text-[#BF2600]" data-testid="kyc-state-rejected">
                <ShieldAlert className="h-5 w-5" /> Master Admin REJECTED on {relativeTime(c.kyc_admin_decision_at)}
                {c.kyc_admin_decision_notes && <span className="text-[#5E6C84] font-normal">— {c.kyc_admin_decision_notes}</span>}
              </div>
            );
          }
          if (kycStatus === "agent_reviewed") {
            // Awaiting master admin
            if (isAdmin) {
              return (
                <div className="space-y-2" data-testid="kyc-admin-final">
                  <div className="flex items-center gap-2 text-sm text-[#091E42] flex-wrap">
                    <Crown className="h-4 w-4 text-[#FFAB00]" />
                    <b>Master Admin: final approval</b>
                    <SlaChip since={c.kyc_agent_completed_at} threshold={24} prefix="Awaiting" testid="kyc-sla-admin" />
                    <span className="text-[#5E6C84] text-xs">— sales rep finished: {c.kyc_agent_summary?.approved || 0} approved, {c.kyc_agent_summary?.rejected || 0} rejected</span>
                  </div>
                  {!adminForm.open ? (
                    <div className="flex gap-2 flex-wrap">
                      <button data-testid="kyc-admin-verify" onClick={() => setAdminForm({ open: true, decision: "verified", notes: "" })} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#36B37E] text-white rounded hover:bg-[#006644]">
                        <ShieldCheck className="h-4 w-4" /> Verify (final)
                      </button>
                      <button data-testid="kyc-admin-reject" onClick={() => setAdminForm({ open: true, decision: "rejected", notes: "" })} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#FF5630] text-white rounded hover:bg-[#BF2600]">
                        <ShieldAlert className="h-4 w-4" /> Reject
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <textarea data-testid="kyc-admin-notes" value={adminForm.notes} onChange={(e) => setAdminForm({ ...adminForm, notes: e.target.value })} placeholder="Admin notes (optional)…" rows={2} className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white" />
                      <div className="flex gap-2">
                        <button onClick={adminFinalDecide} disabled={submitting} data-testid="kyc-admin-submit" className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60">
                          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} {adminForm.decision === "verified" ? "Verify" : "Reject"} as Master Admin
                        </button>
                        <button onClick={() => setAdminForm({ open: false, decision: "verified", notes: "" })} className="px-3 py-1.5 text-sm border border-[#DFE1E6] rounded hover:bg-[#F4F5F7]">Cancel</button>
                      </div>
                    </div>
                  )}
                </div>
              );
            } else {
              return (
                <div className="flex items-center gap-2 text-sm text-[#0747A6]" data-testid="kyc-state-awaiting-admin">
                  <Crown className="h-4 w-4" /> <b>Awaiting Master Admin final approval</b>
                  <span className="text-[#5E6C84]">— you submitted {relativeTime(c.kyc_agent_completed_at)} ({c.kyc_agent_summary?.approved || 0} ✓ / {c.kyc_agent_summary?.rejected || 0} ✗)</span>
                </div>
              );
            }
          }
          // Default: sales rep reviewing
          return (
            <div className="space-y-2" data-testid="kyc-state-agent-reviewing">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="text-sm text-[#091E42] flex items-center gap-2 flex-wrap">
                  <b>Sales rep review:</b>
                  <span className="text-[#5E6C84]">{docsReviewed} of {docsTotal} documents decided</span>
                  <SlaChip since={c.created_at || c.updated_at} threshold={24} prefix="Pending" testid="kyc-sla-agent" />
                </div>
                <button
                  onClick={submitForAdmin}
                  disabled={!allReviewed || submitting}
                  data-testid="kyc-submit-for-admin"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60 disabled:cursor-not-allowed"
                  title={allReviewed ? "Submit to Master Admin for final approval" : `Review all ${docsTotal} documents first`}
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crown className="h-4 w-4" />}
                  Submit to Master Admin
                </button>
              </div>
              {!allReviewed && docsTotal > 0 && (
                <div className="text-[11px] text-[#5E6C84]">Approve or reject each document above. Once all {docsTotal} are decided, you can submit for final approval.</div>
              )}
            </div>
          );
        })()}
        {state.err && <div className="mt-2 text-xs text-[#FF5630]" data-testid="kyc-err">{state.err}</div>}
      </div>
    </div>
  );
}
