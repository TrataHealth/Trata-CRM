import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Webhook, Loader2, ShieldCheck, ShieldAlert, Send, CheckCircle2, AlertTriangle, Plus } from "lucide-react";
import { relativeTime } from "../lib/constants";

const EVENTS = [
  { value: "provider.signed_up", label: "Provider signed up", stage: "verified", color: "#36B37E" },
  { value: "provider.first_use", label: "Provider first use", stage: "active", color: "#0052CC" },
];

export default function WebhookBridgePanel() {
  const [events, setEvents] = useState(null);
  const [secretOk, setSecretOk] = useState(false);
  const [form, setForm] = useState({ event: "provider.signed_up", phone: "", name: "", city: "", state: "" });
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const load = async () => {
    const { data } = await api.get("/admin/webhooks/events", { params: { limit: 20 } });
    setEvents(data.items);
    setSecretOk(data.secret_configured);
  };

  useEffect(() => { load(); }, []);

  const send = async () => {
    setErr(""); setResult(null);
    if (!form.phone.trim()) { setErr("Phone is required"); return; }
    setSending(true);
    try {
      const { data } = await api.post("/admin/webhooks/test-send", form);
      setResult(data);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not send webhook");
    }
    setSending(false);
  };

  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden" data-testid="webhook-bridge-panel">
      <div className="px-5 py-4 border-b border-[#DFE1E6] flex items-start justify-between flex-wrap gap-3">
        <div>
          <div className="overline flex items-center gap-1.5"><Webhook className="h-3 w-3" /> Provider App Bridge</div>
          <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Inbound webhook · auto-advance pipeline</div>
          <p className="text-xs text-[#5E6C84] mt-1">
            Trata Provider App pings <code className="font-mono text-[11px] bg-[#F1F2F4] px-1 py-0.5 rounded">POST /api/webhooks/provider-app</code> with an <code className="font-mono text-[11px] bg-[#F1F2F4] px-1 py-0.5 rounded">X-Trata-Signature</code> header.
            The matching lead is moved to <b className="text-[#36B37E]">verified</b> on signup and <b className="text-[#0052CC]">active</b> on first use.
          </p>
        </div>
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-semibold border ${
            secretOk
              ? "bg-[#E3FCEF] text-[#006644] border-[#36B37E]/30"
              : "bg-[#FFEBE6] text-[#BF2600] border-[#FF5630]/30"
          }`}
          data-testid="webhook-secret-status"
        >
          {secretOk ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
          {secretOk ? "HMAC secret configured" : "PROVIDER_WEBHOOK_SECRET missing"}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-[#DFE1E6]">
        {/* Test sender */}
        <div className="p-5 space-y-3" data-testid="webhook-test-sender">
          <div className="overline">Send a test event</div>
          <div className="flex flex-wrap gap-2">
            {EVENTS.map((ev) => (
              <button
                key={ev.value}
                onClick={() => setForm((f) => ({ ...f, event: ev.value }))}
                data-testid={`wh-event-${ev.value}`}
                className={`px-2.5 py-1 rounded text-xs font-semibold border transition-colors ${
                  form.event === ev.value
                    ? "text-white border-transparent"
                    : "bg-white text-[#42526E] border-[#DFE1E6] hover:border-[#0052CC]"
                }`}
                style={form.event === ev.value ? { background: ev.color } : {}}
              >
                {ev.label} <span className="opacity-70">→ {ev.stage}</span>
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Field testid="wh-phone" label="Provider phone *" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} placeholder="9000020003" />
            <Field testid="wh-name" label="Provider name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="Speedway Ambulance" />
            <Field testid="wh-city" label="City (territory)" value={form.city} onChange={(v) => setForm({ ...form, city: v })} placeholder="Delhi" />
            <Field testid="wh-state" label="State" value={form.state} onChange={(v) => setForm({ ...form, state: v })} placeholder="Delhi" />
          </div>

          <button
            onClick={send}
            disabled={sending || !secretOk}
            data-testid="wh-send-btn"
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold bg-[#0052CC] hover:bg-[#0747A6] text-white rounded-md disabled:opacity-60"
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Send signed webhook
          </button>

          {err && <div className="text-sm text-[#FF5630]" data-testid="wh-error">{err}</div>}
          {result && (
            <div className="bg-[#E3FCEF] border border-[#36B37E]/30 rounded p-3 text-xs" data-testid="wh-result">
              <div className="flex items-center gap-1.5 font-semibold text-[#006644]"><CheckCircle2 className="h-4 w-4" /> {result.action}</div>
              <div className="mt-1 text-[#42526E]">Stage: <b className="text-[#091E42]">{result.pipeline_stage}</b> · {result.created_new_lead ? <span className="inline-flex items-center gap-0.5"><Plus className="h-3 w-3" /> new lead</span> : "matched existing lead"}</div>
              <div className="mt-1 text-[10px] font-mono text-[#5E6C84] truncate">{result.signature}</div>
            </div>
          )}
        </div>

        {/* Recent events */}
        <div className="p-5" data-testid="webhook-recent-events">
          <div className="overline">Recent events</div>
          <div className="mt-2 space-y-2 max-h-[340px] overflow-y-auto scrollbar-thin">
            {events === null && <div className="text-sm text-[#5E6C84] py-6 text-center"><Loader2 className="h-4 w-4 animate-spin inline mr-2" /> Loading…</div>}
            {events?.length === 0 && <div className="text-sm text-[#5E6C84] py-6 text-center">No webhook events yet.</div>}
            {events?.map((e) => (
              <div key={e.id} className="border border-[#DFE1E6] rounded p-2.5 text-xs" data-testid={`wh-event-row-${e.id}`}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-1.5 font-semibold text-[#091E42]">
                    {e.status === "accepted" ? <CheckCircle2 className="h-3.5 w-3.5 text-[#36B37E]" /> : <AlertTriangle className="h-3.5 w-3.5 text-[#FF5630]" />}
                    {e.event}
                    {e.test_send && <span className="text-[9px] uppercase tracking-wider px-1 py-0.5 bg-[#FFFAE6] text-[#974F0C] rounded">test</span>}
                  </div>
                  <span className="text-[10px] text-[#5E6C84]">{relativeTime(e.created_at)}</span>
                </div>
                {e.status === "accepted" ? (
                  <div className="mt-1 text-[#42526E] truncate">
                    <b className="text-[#091E42]">{e.contact_name}</b> · {e.action?.replace(/_/g, " ")} {e.assigned_agent_name ? `· ${e.assigned_agent_name}` : ""}
                  </div>
                ) : (
                  <div className="mt-1 text-[#FF5630] truncate">{e.error}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, testid }) {
  return (
    <label className="text-xs space-y-1 block">
      <span className="text-[10px] uppercase tracking-wider font-semibold text-[#5E6C84]">{label}</span>
      <input
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-2.5 py-1.5 text-sm border border-[#DFE1E6] rounded focus:border-[#4C9AFF] outline-none"
      />
    </label>
  );
}
