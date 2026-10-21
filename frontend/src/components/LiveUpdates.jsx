import React, { useEffect, useRef, useState } from "react";
import { Bell, Wallet } from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";

// Broadcast for pages (dashboard/earnings) that want to refetch on live events.
const emit = (type, data) => window.dispatchEvent(new CustomEvent("trata:live", { detail: { type, data } }));

function useLiveStream(onCounters) {
  const cb = useRef(onCounters);
  cb.current = onCounters;
  useEffect(() => {
    const token = localStorage.getItem("trata_token");
    if (!token) return undefined;
    let es, retry;
    const open = () => {
      es = new EventSource(`${process.env.REACT_APP_BACKEND_URL}/api/live/stream?token=${encodeURIComponent(token)}`);
      es.addEventListener("counters", (ev) => cb.current(JSON.parse(ev.data)));
      es.addEventListener("notification", (ev) => {
        const n = JSON.parse(ev.data);
        toast(n.title || "New notification", { description: n.message, icon: <Bell className="h-4 w-4" /> });
        emit("notification", n);
      });
      es.addEventListener("payout", (ev) => {
        const p = JSON.parse(ev.data);
        const amt = `₹${Number(p.net || 0).toLocaleString("en-IN")}`;
        toast.success(p.change === "new" ? `New payout ${amt}` : `Payout ${amt} is now ${p.status}`, { icon: <Wallet className="h-4 w-4" /> });
        emit("payout", p);
      });
      es.onerror = () => { es.close(); retry = setTimeout(open, 8000); };
    };
    open();
    return () => { clearTimeout(retry); if (es) es.close(); };
  }, []);
}

export const LiveBell = () => {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  useLiveStream((c) => setUnread(c.unread || 0));

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      try { const { data } = await api.get("/live/notifications"); setItems(data.items || []); setUnread(data.unread || 0); } catch { setItems([]); }
    }
  };
  const readAll = async () => {
    await api.post("/live/notifications/read-all");
    setUnread(0);
    setItems((xs) => xs.map((x) => ({ ...x, is_read: true })));
  };

  return (
    <div className="relative hidden md:block">
      <button onClick={toggle} className="flex items-center gap-2 px-3 py-2 text-sm text-[#42526E] hover:bg-[#F1F2F4] rounded-md" data-testid="topbar-notifications-btn">
        <Bell className="h-4 w-4" /> Notifications
        {unread > 0 && <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-[#DE350B] text-white text-[10px] font-bold flex items-center justify-center" data-testid="notifications-unread-badge">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-80 bg-white border border-[#DFE1E6] rounded-md shadow-lg z-50" data-testid="notifications-panel">
          <div className="px-3 py-2 border-b border-[#DFE1E6] flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">Live · shared with your mobile app</span>
            <button onClick={readAll} disabled={!unread} className="text-[11px] text-[#0052CC] disabled:text-[#A5ADBA]" data-testid="notifications-read-all">Mark all read</button>
          </div>
          <div className="max-h-96 overflow-auto">
            {items.length === 0 ? <div className="p-4 text-sm text-[#5E6C84]" data-testid="notifications-empty">No notifications yet.</div> : items.map((n) => (
              <div key={n.id} className={`px-3 py-2 border-b border-[#F4F5F7] last:border-0 ${n.is_read ? "" : "bg-[#DEEBFF]/40"}`} data-testid={`notification-${n.id}`}>
                <div className="text-xs font-semibold text-[#091E42]">{n.title || (n.notification_type || "").replace(/_/g, " ")}</div>
                {n.message && <div className="text-[11px] text-[#42526E] line-clamp-2">{n.message}</div>}
                <div className="text-[10px] text-[#5E6C84] mt-0.5">{n.created_at ? relativeTime(n.created_at) : ""}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
