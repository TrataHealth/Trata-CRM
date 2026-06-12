import React, { useEffect, useState } from "react";
import api from "../lib/api";
import {
  ShieldCheck, ShieldAlert, ShieldQuestion, Loader2, RefreshCw, ExternalLink,
  CheckCircle2, XCircle, FileText, FileQuestion, AlertCircle, MessagesSquare, Send,
} from "lucide-react";
import { relativeTime } from "../lib/constants";

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
  const [state, setState] = useState({ loading: true, data: null, err: "" });
  const [decisionForm, setDecisionForm] = useState({ open: false, decision: "approved", notes: "" });
  const [submitting, setSubmitting] = useState(false);

  const load = async (refresh = false) => {
    setState((s) => ({ ...s, loading: true, err: "" }));
    try {
      const { data } = await api.get(`/contacts/${contactId}/kyc`, { params: refresh ? { refresh: true } : {} });
      setState({ loading: false, data, err: "" });
    } catch (e) {
      setState({ loading: false, data: null, err: e?.response?.data?.detail || "Could not fetch KYC" });
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [contactId]);

  const submitDecision = async () => {
    setSubmitting(true);
    try {
      await api.post(`/contacts/${contactId}/kyc-review`, decisionForm);
      setDecisionForm({ open: false, decision: "approved", notes: "" });
      await load(true);
    } catch (e) {
      setState((s) => ({ ...s, err: e?.response?.data?.detail || "Could not submit decision" }));
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
          <div className="overline mb-3">Uploaded documents ({(kyc.docs || []).length})</div>
          {(kyc.docs || []).length === 0 ? (
            <div className="text-sm text-[#5E6C84]">No documents uploaded yet.</div>
          ) : (
            <ul className="space-y-2 max-h-[260px] overflow-y-auto scrollbar-thin">
              {kyc.docs.map((d) => {
                const s = DOC_STATUS_STYLE[d.status] || DOC_STATUS_STYLE.pending;
                const Icon = s.icon;
                return (
                  <li key={d.id} className="border border-[#DFE1E6] rounded p-2.5" data-testid={`kyc-doc-${d.id}`}>
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="flex items-start gap-2 min-w-0">
                        <FileText className="h-4 w-4 text-[#5E6C84] mt-0.5 shrink-0" />
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-[#091E42] truncate">{d.name || d.kind}</div>
                          <div className="text-[11px] text-[#5E6C84]">{d.kind} · {d.mime} · uploaded {relativeTime(d.uploaded_at)}</div>
                        </div>
                      </div>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-semibold rounded text-white whitespace-nowrap" style={{ background: s.color }}>
                        <Icon className="h-3 w-3" /> {s.label}
                      </span>
                    </div>
                    {d.rejection_comment && <div className="mt-1 text-[11px] text-[#FF5630]">{d.rejection_comment}</div>}
                    {d.url && (
                      <a href={d.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-[11px] text-[#0052CC] font-semibold hover:underline" data-testid={`kyc-doc-link-${d.id}`}>
                        <ExternalLink className="h-3 w-3" /> View document
                      </a>
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

      {/* Decision panel */}
      <div className="px-5 py-4 border-t border-[#DFE1E6] bg-[#FAFBFC]" data-testid="kyc-decision">
        {local_decision && (
          <div className="mb-3 text-[11px] text-[#5E6C84]">
            Last CRM decision: <b className="text-[#091E42] uppercase">{local_decision}</b>
            {state.data.local_decision_at && <> · {relativeTime(state.data.local_decision_at)}</>}
          </div>
        )}
        {!decisionForm.open ? (
          <div className="flex flex-wrap gap-2">
            <button data-testid="kyc-decide-approved" onClick={() => setDecisionForm({ open: true, decision: "approved", notes: "" })} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#36B37E] text-white rounded hover:bg-[#006644]">
              <CheckCircle2 className="h-4 w-4" /> Approve KYC
            </button>
            <button data-testid="kyc-decide-needs_more_info" onClick={() => setDecisionForm({ open: true, decision: "needs_more_info", notes: "" })} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#FFAB00] text-white rounded hover:bg-[#974F0C]">
              <AlertCircle className="h-4 w-4" /> Needs more info
            </button>
            <button data-testid="kyc-decide-rejected" onClick={() => setDecisionForm({ open: true, decision: "rejected", notes: "" })} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#FF5630] text-white rounded hover:bg-[#BF2600]">
              <XCircle className="h-4 w-4" /> Reject
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="text-xs text-[#091E42] font-semibold">
              {decisionForm.decision === "approved" && "Approving KYC. This advances the pipeline to verified and notifies the admin app."}
              {decisionForm.decision === "needs_more_info" && "Marking as 'needs more info'. The admin app records your note as a review."}
              {decisionForm.decision === "rejected" && "Rejecting KYC. The provider will be notified via the admin app."}
            </div>
            <textarea
              data-testid="kyc-decision-notes"
              value={decisionForm.notes}
              onChange={(e) => setDecisionForm({ ...decisionForm, notes: e.target.value })}
              placeholder="Reviewer notes (visible in the admin app)…"
              rows={3}
              className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white focus:border-[#4C9AFF] outline-none"
            />
            <div className="flex gap-2">
              <button data-testid="kyc-decision-submit" onClick={submitDecision} disabled={submitting} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Submit decision
              </button>
              <button onClick={() => setDecisionForm({ open: false, decision: "approved", notes: "" })} className="px-3 py-1.5 text-sm border border-[#DFE1E6] rounded hover:bg-[#F4F5F7]">
                Cancel
              </button>
            </div>
          </div>
        )}
        {state.err && <div className="mt-2 text-xs text-[#FF5630]" data-testid="kyc-err">{state.err}</div>}
      </div>
    </div>
  );
}
