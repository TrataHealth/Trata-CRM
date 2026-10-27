import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BellRing, Volume2, VolumeX, X } from "lucide-react";
import api from "../../lib/api";
import { itemLine } from "./ui";

const MUTE_KEY = "trata_order_alert_muted";

function chime(ctxRef) {
  try {
    const ctx = ctxRef.current || (ctxRef.current = new (window.AudioContext || window.webkitAudioContext)());
    if (ctx.state === "suspended") ctx.resume();
    [880, 1175, 1568].forEach((f, i) => {
      const o = ctx.createOscillator(); const g = ctx.createGain(); const t = ctx.currentTime + i * 0.18;
      o.type = "sine"; o.frequency.value = f; g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.35, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + 0.4);
    });
  } catch { /* audio unavailable */ }
}

export function NewOrderAlerts() {
  const [alerts, setAlerts] = useState([]); const [muted, setMuted] = useState(localStorage.getItem(MUTE_KEY) === "1");
  const since = useRef(null); const seen = useRef(new Set()); const ctx = useRef(null); const nav = useNavigate();
  useEffect(() => {
    const unlock = () => { if (!ctx.current) { try { ctx.current = new (window.AudioContext || window.webkitAudioContext)(); } catch { /* none */ } } };
    window.addEventListener("pointerdown", unlock, { once: true });
    return () => window.removeEventListener("pointerdown", unlock);
  }, []);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const { data } = await api.get("/pharmacy-console/orders/new", { params: since.current ? { since: since.current } : {} });
        if (!since.current) { since.current = data.server_time; return; }
        const fresh = data.orders.filter((o) => !seen.current.has(o.id));
        fresh.forEach((o) => seen.current.add(o.id));
        if (data.orders.length) since.current = data.orders[data.orders.length - 1].created_at;
        if (alive && fresh.length) {
          setAlerts((a) => [...fresh.reverse(), ...a].slice(0, 5));
          if (localStorage.getItem(MUTE_KEY) !== "1") chime(ctx);
        }
      } catch { /* offline / not a pharmacy — try again next tick */ }
    };
    const t = setInterval(poll, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const toggleMute = () => { const m = !muted; setMuted(m); localStorage.setItem(MUTE_KEY, m ? "1" : "0"); if (!m) chime(ctx); };
  const dismiss = (id) => setAlerts((a) => a.filter((x) => x.id !== id));
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-2 w-[min(380px,calc(100vw-2rem))]" data-testid="order-alerts">
      {alerts.map((o) => (
        <div key={o.id} className="w-full bg-white border-2 border-[#0052CC] rounded-lg shadow-2xl p-4 animate-in slide-in-from-right" data-testid={`order-alert-${o.id}`}>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 font-heading font-bold text-[#091E42]"><BellRing className="h-4 w-4 text-[#0052CC] animate-bounce" />{o.is_preorder ? "New pre-order" : "New medicine order"}</div>
            <button onClick={() => dismiss(o.id)} className="p-0.5 text-[#5E6C84]" data-testid={`order-alert-dismiss-${o.id}`}><X className="h-4 w-4" /></button>
          </div>
          <div className="text-sm text-[#172B4D] mt-1"><b>{o.patient_name || "A patient"}</b> · #{o.order_number}{o.pharmacy_name ? ` · ${o.pharmacy_name}` : ""}</div>
          <div className="text-xs text-[#5E6C84] mt-0.5 truncate">{(o.items || []).map(itemLine).join(", ")} · {o.delivery_mode || "pickup"}</div>
          <button onClick={() => { dismiss(o.id); nav("/pharmacy/orders"); }} className="mt-3 w-full px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md hover:bg-[#0747A6]" data-testid={`order-alert-view-${o.id}`}>View order</button>
        </div>
      ))}
      <button onClick={toggleMute} title={muted ? "Order sound is off" : "Order sound is on"} className="h-9 w-9 grid place-items-center rounded-full bg-white border border-[#DFE1E6] shadow text-[#42526E] hover:text-[#0052CC]" data-testid="order-alert-mute">
        {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
      </button>
    </div>
  );
}
