import React, { useEffect, useState } from "react";
import api from "../lib/api";
import {
  Network, Loader2, ShieldCheck, ShieldAlert, ArrowDownLeft, ArrowUpRight,
  Send, RefreshCw, CheckCircle2, AlertTriangle, Clock, Key, Link as LinkIcon,
} from "lucide-react";
import { relativeTime } from "../lib/constants";

const INBOUND_EVENTS = [
  "provider.signed_up", "provider.first_use",
  "provider.kyc.submitted", "provider.kyc.updated",
  "provider.deactivated", "provider.profile.updated", "payout.processed",
];
const OUTBOUND_EVENTS = [
  { value: "crm.lead.created",    label: "Lead Created"   },
  { value: "crm.lead.assigned",   label: "Lead Assigned"  },
  { value: "crm.kyc.reviewed",    label: "KYC Reviewed"   },
  { value: "crm.activity.logged", label: "Activity Logged"},
  { value: "crm.deal.closed",     label: "Deal Closed"    },
  { value: "crm.note.added",      label: "Note Added"     },
];

const STATUS_COLORS = {
  sent: "#36B37E", pending: "#5E6C84", retrying: "#FFAB00", failed: "#FF5630",
  skipped: "#5E6C84", accepted: "#36B37E", rejected: "#FF5630", errored: "#FF5630",
};

export default function AdminBridgePanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ event: "crm.lead.assigned", phone: "", new_agent_phone: "" });
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    const { data } = await api.get("/admin/bridge/events", { params: { limit: 20 } });
    setData(data);
    setLoading(false);
  };
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []);

  const send = async () => {
    setErr("");
    if (!form.phone.trim()) return setErr("Phone is required");
    setSending(true);
    try {
      const payload = { event: form.event, data: { phone: form.phone, new_agent_phone: form.new_agent_phone || null, source: "manual_test" } };
      await api.post("/admin/bridge/test-send", payload);
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Send failed");
    }
    setSending(false);
  };

  const syncUsers = async () => {
    setErr("");
    setSending(true);
    try {
      const { data } = await api.post("/admin/bridge/sync-users");
      setErr(`Synced: ${data.fetched} fetched · ${data.created} created · ${data.updated} updated · ${data.skipped} skipped`);
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Sync failed");
    }
    setSending(false);
  };

  const retry = async (id) => {
    try { await api.post(`/admin/bridge/retry/${id}`); load(); } catch {}
  };

  const cfg = data?.config || {};
  const ready = cfg.secret_configured && cfg.admin_webhook_url;

  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="admin-bridge-panel">
      <div className="px-5 py-4 border-b border-[#DFE1E6] flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="overline flex items-center gap-1.5"><Network className="h-3 w-3" /> Trata Admin App ⇄ CRM Bridge</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Two-way event integration</div>
          <p className="text-xs text-[#5E6C84] mt-1">
            Receives 7 inbound events at <code className="font-mono text-[11px] bg-[#F1F2F4] px-1 rounded">POST /api/webhooks/admin-app</code> and emits 6 outbound CRM events to the admin app. Same shared HMAC secret both ways. Idempotency via <code className="font-mono text-[11px] bg-[#F1F2F4] px-1 rounded">id</code> field.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={syncUsers} disabled={sending || !cfg.admin_api_key_configured} data-testid="bridge-sync-users-btn" className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold bg-white border border-[#DFE1E6] rounded hover:border-[#0052CC] disabled:opacity-60">
            <RefreshCw className="h-3 w-3" /> Sync users now
          </button>
          <Badge ok={cfg.secret_configured} testid="bridge-secret-badge">{cfg.secret_configured ? "Shared secret OK" : "Secret missing"}</Badge>
          <Badge ok={!!cfg.admin_webhook_url} testid="bridge-url-badge">{cfg.admin_webhook_url ? "Upstream URL set" : "Upstream URL missing"}</Badge>
          <Badge ok={cfg.admin_api_key_configured} kind="info" testid="bridge-key-badge">{cfg.admin_api_key_configured ? "Bearer token set" : "Bearer pending"}</Badge>
        </div>
      </div>

      {/* Counts */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 border-b border-[#DFE1E6] bg-[#FAFBFC]" data-testid="bridge-counts">
        <Stat label="Inbound (total)" value={data?.counts?.inbound_total ?? "—"} icon={<ArrowDownLeft className="h-3.5 w-3.5" />} accent="#0052CC" />
        <Stat label="Outbound queued" value={data?.counts?.outbound_pending ?? "—"} icon={<Clock className="h-3.5 w-3.5" />} accent="#FFAB00" />
        <Stat label="Outbound sent" value={data?.counts?.outbound_sent ?? "—"} icon={<CheckCircle2 className="h-3.5 w-3.5" />} accent="#36B37E" />
        <Stat label="Outbound failed" value={data?.counts?.outbound_failed ?? "—"} icon={<AlertTriangle className="h-3.5 w-3.5" />} accent="#FF5630" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-[#DFE1E6]">
        {/* Outbound — Test sender + queue */}
        <div className="p-5 space-y-3" data-testid="bridge-outbound">
          <div className="overline flex items-center gap-1.5"><ArrowUpRight className="h-3 w-3" /> Outbound (CRM → Trata Admin)</div>

          <div className="bg-[#FAFBFC] border border-[#DFE1E6] rounded p-3 space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {OUTBOUND_EVENTS.map((ev) => (
                <button
                  key={ev.value}
                  onClick={() => setForm((f) => ({ ...f, event: ev.value }))}
                  data-testid={`bridge-out-event-${ev.value}`}
                  className={`px-2 py-1 rounded text-[11px] font-semibold border ${
                    form.event === ev.value ? "bg-[#0052CC] text-white border-transparent" : "bg-white text-[#42526E] border-[#DFE1E6] hover:border-[#0052CC]"
                  }`}
                >
                  {ev.label}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input data-testid="bridge-phone-input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="Provider phone (10-digit)" className="px-2.5 py-1.5 text-sm border border-[#DFE1E6] rounded" />
              <input data-testid="bridge-agent-input" value={form.new_agent_phone} onChange={(e) => setForm({ ...form, new_agent_phone: e.target.value })} placeholder="Agent phone (optional)" className="px-2.5 py-1.5 text-sm border border-[#DFE1E6] rounded" />
            </div>
            <button
              onClick={send}
              disabled={sending || !ready}
              data-testid="bridge-send-btn"
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded hover:bg-[#0747A6] disabled:opacity-60"
            >
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Queue + send test event
            </button>
            {err && <div className="text-xs text-[#FF5630]" data-testid="bridge-err">{err}</div>}
            {!ready && (
              <div className="text-[11px] text-[#974F0C] bg-[#FFFAE6] border border-[#FFC400]/40 rounded p-2">
                <Key className="h-3 w-3 inline mr-1" /> Outbound URL or secret missing — set TRATA_ADMIN_WEBHOOK_URL and ADMIN_CRM_WEBHOOK_SECRET in backend/.env.
              </div>
            )}
          </div>

          <div className="overline mt-3">Recent outbound</div>
          <div className="space-y-1.5 max-h-[260px] overflow-y-auto scrollbar-thin">
            {loading && <div className="text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 inline animate-spin mr-1" /> Loading…</div>}
            {data?.outbound?.length === 0 && <div className="text-sm text-[#5E6C84]">No outbound events yet.</div>}
            {data?.outbound?.map((o) => (
              <div key={o.id} className="border border-[#DFE1E6] rounded p-2 text-[11px]" data-testid={`bridge-out-row-${o.id}`}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="font-semibold text-[#091E42] flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLORS[o.status] || "#5E6C84" }} />
                    {o.event}
                  </span>
                  <span className="text-[#5E6C84]">{relativeTime(o.created_at)}</span>
                </div>
                <div className="mt-0.5 text-[#42526E] truncate">
                  status=<b style={{ color: STATUS_COLORS[o.status] }}>{o.status}</b> · attempts={o.attempts}
                  {o.last_error && <span className="text-[#FF5630]"> · {o.last_error.slice(0, 60)}</span>}
                </div>
                {(o.status === "retrying" || o.status === "failed") && (
                  <button onClick={() => retry(o.id)} data-testid={`bridge-retry-${o.id}`} className="mt-1 inline-flex items-center gap-1 text-[10px] text-[#0052CC] font-semibold hover:underline">
                    <RefreshCw className="h-3 w-3" /> Retry now
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Inbound */}
        <div className="p-5" data-testid="bridge-inbound">
          <div className="overline flex items-center gap-1.5 mb-2"><ArrowDownLeft className="h-3 w-3" /> Inbound (Trata Admin → CRM)</div>

          <div className="bg-[#FAFBFC] border border-[#DFE1E6] rounded p-3 mb-3 text-[11px]">
            <div className="font-semibold text-[#091E42] mb-1">Endpoint configured:</div>
            <code className="font-mono text-[10px] block text-[#0747A6] break-all">POST /api/webhooks/admin-app</code>
            <div className="mt-2 text-[#5E6C84]">Supports events:</div>
            <div className="flex flex-wrap gap-1 mt-1">
              {INBOUND_EVENTS.map((e) => (
                <span key={e} className="px-1.5 py-0.5 bg-white border border-[#DFE1E6] rounded text-[10px] text-[#42526E] font-mono">{e}</span>
              ))}
            </div>
          </div>

          <div className="space-y-1.5 max-h-[280px] overflow-y-auto scrollbar-thin">
            {data?.inbound?.length === 0 && <div className="text-sm text-[#5E6C84]">No inbound events yet.</div>}
            {data?.inbound?.map((i) => (
              <div key={i.id} className="border border-[#DFE1E6] rounded p-2 text-[11px]" data-testid={`bridge-in-row-${i.id}`}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="font-semibold text-[#091E42] flex items-center gap-1.5">
                    {i.status === "accepted" ? <CheckCircle2 className="h-3 w-3 text-[#36B37E]" /> : <AlertTriangle className="h-3 w-3 text-[#FF5630]" />}
                    {i.event || "(rejected)"}
                  </span>
                  <span className="text-[#5E6C84]">{relativeTime(i.created_at)}</span>
                </div>
                {i.status === "accepted" ? (
                  <div className="mt-0.5 text-[#42526E] truncate">{i.result?.action} {i.result?.contact_id ? `· ${i.result.contact_id.slice(0, 8)}` : ""}</div>
                ) : (
                  <div className="mt-0.5 text-[#FF5630] truncate">{i.reason || "rejected"}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Badge({ ok, children, testid, kind = "ok" }) {
  const cls = ok
    ? "bg-[#E3FCEF] text-[#006644] border-[#36B37E]/30"
    : kind === "info"
      ? "bg-[#DEEBFF] text-[#0747A6] border-[#0052CC]/20"
      : "bg-[#FFEBE6] text-[#BF2600] border-[#FF5630]/30";
  return (
    <span data-testid={testid} className={`flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-semibold border ${cls}`}>
      {ok ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
      {children}
    </span>
  );
}

function Stat({ label, value, icon, accent }) {
  return (
    <div className="px-5 py-3 text-center sm:text-left border-b sm:border-b-0 sm:border-r last:border-r-0 border-[#DFE1E6]">
      <div className="overline flex items-center justify-center sm:justify-start gap-1" style={{ color: accent }}>
        {icon} {label}
      </div>
      <div className="font-heading text-2xl font-bold text-[#091E42] mt-0.5">{value}</div>
    </div>
  );
}
