import React, { useEffect, useState } from "react";
import { BellRing, Loader2, Volume2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { ALERT_KINDS, currentSubscription, disablePush, enablePush, playChime, pushSupported, setSound, soundOn } from "../../lib/push";

const ALL_ON = Object.fromEntries(ALERT_KINDS.map((k) => [k.key, true]));

export function AlertSettingsCard() {
  const [st, setSt] = useState({ loading: true, on: false, devices: 0, prefs: ALL_ON });
  const [busy, setBusy] = useState(false);
  const [sound, setSnd] = useState(soundOn());

  const load = async () => {
    const sub = await currentSubscription().catch(() => null);
    const { data } = await api.get("/admin/alerts/devices", { params: { endpoint: sub?.endpoint } });
    setSt({ loading: false, on: !!sub && data.this_device, devices: data.devices, prefs: data.prefs });
  };
  useEffect(() => { load().catch(() => setSt((s) => ({ ...s, loading: false }))); }, []);

  const run = async (fn, ok) => { setBusy(true); try { await fn(); if (ok) toast.success(ok); await load(); } catch (e) { toast.error(e?.response?.data?.detail || e.message || "Failed"); } setBusy(false); };
  const toggle = (key) => {
    const prefs = { ...st.prefs, [key]: !st.prefs[key] };
    setSt((s) => ({ ...s, prefs }));
    if (st.on) run(async () => { const sub = await currentSubscription(); await api.put("/admin/alerts/prefs", { endpoint: sub.endpoint, prefs }); });
  };
  const test = () => run(async () => { const { data } = await api.post("/admin/alerts/test"); if (!data.sent) throw new Error("No device received it — try turning alerts off and on again"); }, "Test alert sent");

  return (
    <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="settings-alerts-card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-heading font-bold text-[#091E42] flex items-center gap-2"><BellRing className="h-4 w-4 text-[#0052CC]" /> Push alerts on this device</div>
          <p className="text-xs text-[#5E6C84] mt-1 max-w-md">Get a notification with sound on this phone or computer, even when the console is closed. Turn it on separately on each device.</p>
          <div className="text-[11px] text-[#5E6C84] mt-1" data-testid="alerts-device-count">{st.loading ? "Checking…" : `${st.on ? "On for this device" : "Off for this device"} · ${st.devices} device(s) receiving alerts`}</div>
        </div>
        {st.on ? (
          <div className="flex gap-2">
            <button onClick={test} disabled={busy} className="px-3 py-1.5 text-xs font-semibold rounded-md border border-[#DFE1E6] text-[#42526E] hover:bg-[#F4F5F7]" data-testid="alerts-test-btn">Send test</button>
            <button onClick={() => run(disablePush, "Alerts turned off for this device")} disabled={busy} className="px-3 py-1.5 text-xs font-semibold rounded-md text-[#BF2600] hover:bg-[#FFEBE6]" data-testid="alerts-disable-btn">Turn off</button>
          </div>
        ) : (
          <button onClick={() => run(() => enablePush(st.prefs), "Alerts turned on for this device")} disabled={busy || st.loading || !pushSupported()}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] disabled:opacity-50" data-testid="alerts-enable-btn">
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Turn on alerts
          </button>
        )}
      </div>
      {!pushSupported() && <div className="text-[11px] text-[#974F0C] bg-[#FFFAE6] rounded px-2 py-1 mt-3" data-testid="alerts-unsupported">This browser can&apos;t receive push alerts. On iPhone, open the console from your Home Screen.</div>}
      <div className="mt-4 grid sm:grid-cols-2 gap-2">
        {ALERT_KINDS.map((k) => (
          <label key={k.key} className="flex items-center gap-2 text-sm text-[#091E42] cursor-pointer" data-testid={`alerts-pref-${k.key}`}>
            <input type="checkbox" checked={st.prefs[k.key] !== false} onChange={() => toggle(k.key)} disabled={busy} className="h-4 w-4 accent-[#0052CC]" />{k.label}
          </label>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-3 text-sm">
        <label className="flex items-center gap-2 cursor-pointer" data-testid="alerts-sound-toggle">
          <input type="checkbox" checked={sound} onChange={() => { setSound(!sound); setSnd(!sound); }} className="h-4 w-4 accent-[#0052CC]" />
          Play a chime when the console is open
        </label>
        <button onClick={() => playChime()} className="inline-flex items-center gap-1 text-xs text-[#0052CC] font-semibold" data-testid="alerts-sound-preview"><Volume2 className="h-3.5 w-3.5" /> Preview</button>
      </div>
      <p className="text-[11px] text-[#5E6C84] mt-2">When the console is closed, your device plays its normal notification sound.</p>
    </div>
  );
}
